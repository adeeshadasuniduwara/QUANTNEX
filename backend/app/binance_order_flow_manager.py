"""Bounded on-demand lifecycle manager for Binance Spot order-flow streams.

The manager starts a sequence-validated stream only after a candle setup has
qualified for order-flow confirmation. It deliberately limits concurrent
symbols; it never opens one connection for every exchangeInfo pair.
"""
from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

import httpx

from .binance_order_flow_stream import BinanceSpotOrderFlowStream
from .database import SessionLocal
from .order_flow_recorder import (
    DEFAULT_RETENTION_DAYS,
    SAMPLE_INTERVAL_SECONDS,
    is_recordable_order_flow_snapshot,
    record_order_flow_observation,
)
from .order_flow_raw_recorder import (
    DEFAULT_RAW_EVENT_RETENTION_DAYS,
    record_order_flow_market_events,
)


MAX_PENDING_CAPTURE_TASKS = 16
REPLAY_CAPTURE_ALIGNMENT_WINDOW_SECONDS = 2.0


def _seconds_until_next_utc_minute(captured_at: datetime) -> float | None:
    """Return time to the next UTC minute only inside its final two seconds."""
    if (
        not isinstance(captured_at, datetime)
        or captured_at.tzinfo is None
        or captured_at.utcoffset() is None
    ):
        return None
    stamp = captured_at.astimezone(timezone.utc)
    elapsed = stamp.second + stamp.microsecond / 1_000_000
    remaining = 60.0 - elapsed
    if remaining <= 0 or remaining > REPLAY_CAPTURE_ALIGNMENT_WINDOW_SECONDS:
        return None
    return remaining


def _snapshot_stays_fresh_until_next_minute(
    snapshot: dict[str, Any],
    seconds_until_boundary: float,
    *,
    max_trade_age_seconds: float,
    max_depth_age_seconds: float,
) -> bool:
    """Ensure source ages still pass the replay gate at the next candle boundary."""
    if not isinstance(snapshot, dict) or not math.isfinite(seconds_until_boundary) or seconds_until_boundary < 0:
        return False
    order_flow = snapshot.get("order_flow")
    if not isinstance(order_flow, dict):
        return False
    try:
        trade_age_value = order_flow.get("trade_data_age_seconds")
        depth_age_value = snapshot.get("depth_age_seconds")
        if isinstance(trade_age_value, bool) or isinstance(depth_age_value, bool):
            return False
        trade_age = float(trade_age_value)
        depth_age = float(depth_age_value)
    except (TypeError, ValueError, OverflowError):
        return False
    if not all(math.isfinite(value) and value >= 0 for value in (trade_age, depth_age)):
        return False
    return (
        trade_age + seconds_until_boundary <= max_trade_age_seconds + 1e-9
        and depth_age + seconds_until_boundary <= max_depth_age_seconds + 1e-9
    )


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
        capture_interval_seconds: float = SAMPLE_INTERVAL_SECONDS,
        capture_retention_days: int = DEFAULT_RETENTION_DAYS,
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
        if not math.isfinite(capture_interval_seconds) or capture_interval_seconds <= 0:
            raise ValueError("capture_interval_seconds must be finite and positive.")
        if isinstance(capture_retention_days, bool) or not isinstance(capture_retention_days, int) or capture_retention_days < 1:
            raise ValueError("capture_retention_days must be a positive integer.")
        self.stream_factory = stream_factory
        self.capture_interval_seconds = float(capture_interval_seconds)
        self.capture_retention_days = capture_retention_days
        self.last_capture_at: str | None = None
        self.last_capture_error: str | None = None
        self.last_raw_event_capture_at: str | None = None
        self.last_raw_event_count = 0
        self.last_raw_event_error: str | None = None
        self._last_prune_monotonic: float | None = None
        self._capture_tasks: set[asyncio.Task] = set()
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
        if self._capture_tasks:
            await asyncio.gather(*list(self._capture_tasks), return_exceptions=True)
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
            raise BinanceSpotOrderFlowManagerError("tick size and stream freshness settings must be numeric.") from None
        if not tick.is_finite() or tick <= 0:
            raise BinanceSpotOrderFlowManagerError("Binance Spot symbol tick size must be finite and positive.")
        if not math.isfinite(wait) or wait < 0:
            raise BinanceSpotOrderFlowManagerError("Stream warm-up wait must be finite and non-negative.")
        if not all(math.isfinite(value) and value > 0 for value in (trade_age, depth_age)):
            raise BinanceSpotOrderFlowManagerError("Stream freshness limits must be finite and positive.")
        return normalized, str(tick_size), wait, trade_age, depth_age

    def _persist_market_events(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        db = SessionLocal()
        try:
            return record_order_flow_market_events(
                db, events, retention_days=DEFAULT_RAW_EVENT_RETENTION_DAYS
            )
        finally:
            db.close()

    def _raw_events_capture_finished(self, task: asyncio.Task, stream=None, events=None) -> None:
        self._capture_tasks.discard(task)
        if task.cancelled():
            return
        try:
            result = task.result()
        except Exception as exc:
            self.last_raw_event_error = f"{type(exc).__name__}: {exc}"
            restore = getattr(stream, "restore_capture_events", None)
            if callable(restore) and events:
                try:
                    restore(events)
                except Exception as restore_error:
                    self.last_raw_event_error += f"; retry queue: {type(restore_error).__name__}"
            return
        if isinstance(result, dict):
            self.last_raw_event_count += int(result.get("stored", 0))
            self.last_raw_event_capture_at = datetime.now(timezone.utc).isoformat()
            self.last_raw_event_error = None

    def _persist_snapshot(
        self,
        snapshot: dict[str, Any],
        captured_at: datetime,
        prune_before: datetime | None,
    ) -> dict[str, Any]:
        db = SessionLocal()
        try:
            return record_order_flow_observation(
                db, snapshot, captured_at=captured_at, prune_before=prune_before
            )
        finally:
            db.close()

    def _capture_finished(self, task: asyncio.Task) -> None:
        self._capture_tasks.discard(task)
        if task.cancelled():
            return
        try:
            result = task.result()
        except Exception as exc:
            self.last_capture_error = f"{type(exc).__name__}: {exc}"
            return
        if isinstance(result, dict) and result.get("recorded"):
            self.last_capture_at = result.get("captured_at")
            self.last_capture_error = None
        elif isinstance(result, dict) and result.get("reason") not in {
            "DUPLICATE_UTC_MINUTE_BUCKET",
        }:
            self.last_capture_error = str(result.get("reason") or "Order-flow snapshot was not stored.")

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

        last_capture_monotonic: float | None = None

        async def on_update(snapshot: dict[str, Any]) -> None:
            nonlocal last_capture_monotonic
            changed_event.set()
            if snapshot.get("capture_gap_detected") is True:
                self.last_raw_event_error = "CAPTURE_GAP_DETECTED: raw event queue overflow was recorded."
            # Drain every validated raw trade/depth event independently of the
            # once-per-minute feature snapshot alignment window.
            if len(self._capture_tasks) < MAX_PENDING_CAPTURE_TASKS:
                drain_events = getattr(stream, "drain_capture_events", None)
                raw_events = drain_events(limit=256) if callable(drain_events) else []
                if raw_events:
                    raw_task = asyncio.create_task(
                        asyncio.to_thread(self._persist_market_events, raw_events),
                        name=f"quantnex-orderflow-raw-{symbol.lower()}",
                    )
                    self._capture_tasks.add(raw_task)
                    raw_task.add_done_callback(
                        lambda task, active_stream=stream, batch=raw_events:
                            self._raw_events_capture_finished(task, active_stream, batch)
                    )
            else:
                self.last_raw_event_error = "RAW_EVENT_BACKPRESSURE: pending database writes reached the safety limit."
            captured_at = datetime.now(timezone.utc)
            seconds_until_boundary = _seconds_until_next_utc_minute(captured_at)
            if seconds_until_boundary is None:
                return
            if len(self._capture_tasks) >= MAX_PENDING_CAPTURE_TASKS:
                self.last_capture_error = "CAPTURE_BACKPRESSURE: pending snapshot writes reached the safety limit."
                return
            if not is_recordable_order_flow_snapshot(snapshot):
                return
            # The replay decision timestamp is the next UTC minute boundary.
            # Reject a sample if either source would be stale by that decision.
            if not _snapshot_stays_fresh_until_next_minute(
                snapshot,
                seconds_until_boundary,
                max_trade_age_seconds=max_trade_age_seconds,
                max_depth_age_seconds=max_depth_age_seconds,
            ):
                return
            now = time.monotonic()
            if last_capture_monotonic is not None and now - last_capture_monotonic < self.capture_interval_seconds:
                return
            last_capture_monotonic = now
            prune_before = None
            if self._last_prune_monotonic is None or now - self._last_prune_monotonic >= 3600:
                prune_before = captured_at - timedelta(days=self.capture_retention_days)
                self._last_prune_monotonic = now
            task = asyncio.create_task(
                asyncio.to_thread(self._persist_snapshot, snapshot, captured_at, prune_before),
                name=f"quantnex-orderflow-capture-{symbol.lower()}",
            )
            self._capture_tasks.add(task)
            task.add_done_callback(self._capture_finished)

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
            "capture": {
                "enabled": True,
                "sample_interval_seconds": self.capture_interval_seconds,
                "retention_days": self.capture_retention_days,
                "alignment": "FINAL_TWO_SECONDS_BEFORE_UTC_MINUTE_BOUNDARY",
                "alignment_window_seconds": REPLAY_CAPTURE_ALIGNMENT_WINDOW_SECONDS,
                "last_captured_at": self.last_capture_at,
                "last_error": self.last_capture_error,
                "raw_event_archive": True,
                "raw_event_retention_days": DEFAULT_RAW_EVENT_RETENTION_DAYS,
                "last_raw_event_capture_at": self.last_raw_event_capture_at,
                "raw_events_persisted": self.last_raw_event_count,
                "raw_event_error": self.last_raw_event_error,
                "pending_raw_events": len(getattr(slot.stream, "capture_events", ())),
                "raw_capture_rejected_events": getattr(slot.stream, "capture_rejected_events", 0),
                "capture_gap_detected": snapshot.get("capture_gap_detected") is True,
            },
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
