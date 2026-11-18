"""Bounded on-demand lifecycle manager for Binance Spot order-flow streams.

The manager starts a sequence-validated stream only after a candle setup has
qualified for order-flow confirmation. It deliberately limits concurrent
symbols; it never opens one connection for every exchangeInfo pair.
"""
from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

import httpx

from .binance_order_flow_stream import BinanceSpotOrderFlowStream


class BinanceSpotOrderFlowManagerError(RuntimeError):
    """Raised when a safe Spot order-flow stream cannot be managed."""


@dataclass
class _ManagedStream:
    stream: BinanceSpotOrderFlowStream
    stop_event: asyncio.Event
    changed_event: asyncio.Event
    task: asyncio.Task
    tick_size: str
    max_trade_age_seconds: float
    max_depth_age_seconds: float
    last_requested_monotonic: float


class BinanceSpotOrderFlowManager:
    """Own a bounded LRU set of read-only per-symbol Spot stream tasks."""

    def __init__(
        self,
        *,
        max_streams: int = 8,
        request_timeout_seconds: float = 8.0,
        connect_timeout_seconds: float = 3.0,
        stream_factory: Callable[..., BinanceSpotOrderFlowStream] = BinanceSpotOrderFlowStream,
    ) -> None:
        if isinstance(max_streams, bool) or not isinstance(max_streams, int) or max_streams < 1:
            raise ValueError("max_streams must be a positive integer.")
        if not all(
            math.isfinite(value) and value > 0
            for value in (request_timeout_seconds, connect_timeout_seconds)
        ):
            raise ValueError("HTTP timeout values must be finite and positive.")
        self.max_streams = max_streams
        self.request_timeout_seconds = float(request_timeout_seconds)
        self.connect_timeout_seconds = float(connect_timeout_seconds)
        self.stream_factory = stream_factory
        self._slots: dict[str, _ManagedStream] = {}
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()
        self._closed = False

    @property
    def active_stream_count(self) -> int:
        return sum(not slot.task.done() for slot in self._slots.values())

    async def start(self) -> None:
        async with self._lock:
            self._closed = False
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(
                    timeout=httpx.Timeout(
                        self.request_timeout_seconds,
                        connect=self.connect_timeout_seconds,
                    ),
                    limits=httpx.Limits(
                        max_connections=self.max_streams * 2,
                        max_keepalive_connections=self.max_streams,
                    ),
                )

    async def _stop_slot(self, slot: _ManagedStream) -> None:
        slot.stop_event.set()
        if slot.task.done():
            await asyncio.gather(slot.task, return_exceptions=True)
            return
        try:
            await asyncio.wait_for(slot.task, timeout=3.0)
        except asyncio.TimeoutError:
            slot.task.cancel()
            await asyncio.gather(slot.task, return_exceptions=True)

    async def stop(self) -> None:
        async with self._lock:
            self._closed = True
            slots = list(self._slots.values())
            self._slots.clear()
            client = self._client
            self._client = None
            for slot in slots:
                slot.stop_event.set()
        if slots:
            await asyncio.gather(*(self._stop_slot(slot) for slot in slots), return_exceptions=True)
        if client is not None and not client.is_closed:
            await client.aclose()

    def _validate_request(
        self,
        symbol: str,
        tick_size: str,
        wait_seconds: float,
        max_trade_age_seconds: float,
        max_depth_age_seconds: float,
    ) -> tuple[str, str, float, float, float]:
        normalized = str(symbol or "").strip().upper()
        if not normalized.isalnum() or not 5 <= len(normalized) <= 25:
            raise BinanceSpotOrderFlowManagerError("Invalid Binance Spot symbol.")
        try:
            tick = Decimal(str(tick_size))
            wait = float(wait_seconds)
            trade_age = float(max_trade_age_seconds)
            depth_age = float(max_depth_age_seconds)
        except (InvalidOperation, TypeError, ValueError, OverflowError):
            raise BinanceSpotOrderFlowManagerError("Tick size and stream freshness settings must be numeric.") from None
        if not tick.is_finite() or tick <= 0:
            raise BinanceSpotOrderFlowManagerError("Binance Spot symbol tick size must be finite and positive.")
        if not math.isfinite(wait) or wait < 0:
            raise BinanceSpotOrderFlowManagerError("Stream warm-up wait must be finite and non-negative.")
        if not all(math.isfinite(value) and value > 0 for value in (trade_age, depth_age)):
            raise BinanceSpotOrderFlowManagerError("Stream freshness limits must be finite and positive.")
        return normalized, str(tick_size), wait, trade_age, depth_age

    async def _create_slot(
        self,
        symbol: str,
        tick_size: str,
        max_trade_age_seconds: float,
        max_depth_age_seconds: float,
    ) -> _ManagedStream:
        if self._client is None or self._client.is_closed:
            raise BinanceSpotOrderFlowManagerError("Order-flow manager HTTP client is not running.")
        stream = self.stream_factory(
            symbol,
            tick_size,
            max_trade_age_seconds=max_trade_age_seconds,
            max_depth_age_seconds=max_depth_age_seconds,
        )
        stop_event = asyncio.Event()
        changed_event = asyncio.Event()

        async def on_update(_snapshot: dict[str, Any]) -> None:
            changed_event.set()

        task = asyncio.create_task(
            stream.run(self._client, stop_event, on_update),
            name=f"quantnex-orderflow-{symbol.lower()}",
        )
        return _ManagedStream(
            stream=stream,
            stop_event=stop_event,
            changed_event=changed_event,
            task=task,
            tick_size=tick_size,
            max_trade_age_seconds=max_trade_age_seconds,
            max_depth_age_seconds=max_depth_age_seconds,
            last_requested_monotonic=time.monotonic(),
        )

    async def _slot_for(
        self,
        symbol: str,
        tick_size: str,
        max_trade_age_seconds: float,
        max_depth_age_seconds: float,
    ) -> _ManagedStream:
        async with self._lock:
            if self._closed or self._client is None or self._client.is_closed:
                raise BinanceSpotOrderFlowManagerError("Order-flow manager is stopped.")
            existing = self._slots.get(symbol)
            if existing is not None and (
                existing.task.done()
                or existing.tick_size != tick_size
                or existing.max_trade_age_seconds != max_trade_age_seconds
                or existing.max_depth_age_seconds != max_depth_age_seconds
            ):
                self._slots.pop(symbol, None)
                await self._stop_slot(existing)
                existing = None

            if existing is None:
                if len(self._slots) >= self.max_streams:
                    # Least-recently requested streams yield their slot to a new
                    # qualified setup, so any eligible symbol can be considered.
                    oldest_symbol, oldest = min(
                        self._slots.items(),
                        key=lambda item: item[1].last_requested_monotonic,
                    )
                    self._slots.pop(oldest_symbol, None)
                    await self._stop_slot(oldest)
                existing = await self._create_slot(
                    symbol,
                    tick_size,
                    max_trade_age_seconds,
                    max_depth_age_seconds,
                )
                self._slots[symbol] = existing

            existing.last_requested_monotonic = time.monotonic()
            return existing

    def _result(self, slot: _ManagedStream) -> dict[str, Any]:
        try:
            snapshot = slot.stream.snapshot()
        except Exception as exc:
            snapshot = {
                "symbol": slot.stream.symbol,
                "market_type": "BINANCE_SPOT",
                "status": "SNAPSHOT_ERROR",
                "signal_ready": False,
                "order_flow": None,
                "last_error": f"{type(exc).__name__}: {exc}",
            }
        snapshot["manager"] = {
            "active_streams": self.active_stream_count,
            "max_streams": self.max_streams,
            "eviction_policy": "LEAST_RECENTLY_REQUESTED",
        }
        return snapshot

    async def get_snapshot(
        self,
        symbol: str,
        tick_size: str,
        *,
        wait_seconds: float = 0.75,
        max_trade_age_seconds: float = 15.0,
        max_depth_age_seconds: float = 5.0,
    ) -> dict[str, Any]:
        """Start/reuse a symbol stream and wait briefly for a ready snapshot.

        A not-ready result is explicit and must be treated as WAIT by the signal
        engine. No REST-only or candle-volume fallback is returned here.
        """
        normalized, tick, wait, trade_age, depth_age = self._validate_request(
            symbol,
            tick_size,
            wait_seconds,
            max_trade_age_seconds,
            max_depth_age_seconds,
        )
        await self.start()
        slot = await self._slot_for(normalized, tick, trade_age, depth_age)
        result = self._result(slot)
        if result.get("signal_ready") or wait <= 0:
            return result

        deadline = asyncio.get_running_loop().time() + wait
        while not result.get("signal_ready"):
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0 or slot.task.done():
                break
            slot.changed_event.clear()
            try:
                await asyncio.wait_for(slot.changed_event.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            result = self._result(slot)
        return self._result(slot)


_MANAGER = BinanceSpotOrderFlowManager()


def get_binance_spot_order_flow_manager() -> BinanceSpotOrderFlowManager:
    return _MANAGER


async def start_binance_spot_order_flow_manager() -> None:
    await _MANAGER.start()


async def stop_binance_spot_order_flow_manager() -> None:
    await _MANAGER.stop()
