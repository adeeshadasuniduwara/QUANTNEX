"""Read-only Binance Spot WebSocket order-flow adapter.

One symbol per connection is intentional. A higher-level bounded subscription
manager must decide which eligible pairs deserve streams; do not instantiate
this class for every exchangeInfo symbol at once.

CVD is complete only since the bounded REST bootstrap seed, with reconnect gaps
recovered by aggregate-trade ID backfill. UTC session delta remains unavailable
unless a separate session-start anchor proves full-session coverage. L2 depth
is exposed to the signal layer only after the REST snapshot/diff sequence bridge
has validated at least one post-snapshot update.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import math
import random
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable

import httpx
from websockets.asyncio.client import connect

from .binance_order_flow_state import (
    AggTradeCvdState,
    BinanceSpotDepthBook,
    OrderFlowStateError,
)
from .binance_public import BinancePublicDataError, get_binance_public_json
from .order_flow import OrderFlowDataError, calculate_order_flow

BINANCE_SPOT_STREAM_BASE = "wss://data-stream.binance.vision/stream"
DEFAULT_TRADE_LIMIT = 1000
DEFAULT_DEPTH_LIMIT = 100
DEFAULT_MAX_BUFFERED_EVENTS = 4096


class BinanceSpotOrderFlowStreamError(RuntimeError):
    """Raised when the stream cannot safely maintain contiguous market state."""


def _decode_combined_event(raw: str | bytes, expected_symbol: str) -> tuple[str, dict[str, Any]]:
    """Decode one Binance combined-stream message and validate its symbol."""
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise BinanceSpotOrderFlowStreamError("Binance WebSocket sent invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise BinanceSpotOrderFlowStreamError("Binance WebSocket message must be an object.")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise BinanceSpotOrderFlowStreamError("Binance combined-stream message is missing data.")
    stream_name = str(payload.get("stream") or "").lower()
    symbol = str(data.get("s") or "").upper()
    if symbol != expected_symbol:
        raise BinanceSpotOrderFlowStreamError("Binance WebSocket event symbol does not match subscription.")
    if stream_name and not stream_name.startswith(expected_symbol.lower() + "@"):
        raise BinanceSpotOrderFlowStreamError("Binance combined-stream name does not match subscription.")

    event_type = str(data.get("e") or "")
    if event_type == "aggTrade":
        return "aggTrade", data
    if event_type == "depthUpdate":
        return "depthUpdate", data
    if event_type == "serverShutdown":
        raise BinanceSpotOrderFlowStreamError("Binance requested WebSocket server shutdown.")
    return "UNKNOWN", data


class BinanceSpotOrderFlowStream:
    """Maintain one Binance Spot symbol's aggTrade CVD and sequence-valid L2 book.

    The caller owns the HTTP client and lifecycle. No API key is used. A
    callback receives a snapshot with signal_ready=False until trade
    continuity and depth sequence validation are both sound and fresh.
    """

    def __init__(
        self,
        symbol: str,
        tick_size: str,
        *,
        websocket_factory: Callable[..., Any] = connect,
        max_trade_age_seconds: float = 15.0,
        max_depth_age_seconds: float = 5.0,
        max_recent_trades: int = DEFAULT_TRADE_LIMIT,
        max_buffered_events: int = DEFAULT_MAX_BUFFERED_EVENTS,
        max_backfill_pages: int = 50,
        reconnect_initial_seconds: float = 1.0,
        reconnect_max_seconds: float = 30.0,
        random_uniform: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self.symbol = str(symbol or "").strip().upper()
        if not self.symbol.isalnum() or not 5 <= len(self.symbol) <= 25:
            raise BinanceSpotOrderFlowStreamError("Invalid Binance Spot symbol.")
        try:
            tick = float(tick_size)
            trade_age = float(max_trade_age_seconds)
            depth_age = float(max_depth_age_seconds)
        except (TypeError, ValueError, OverflowError):
            raise BinanceSpotOrderFlowStreamError("Tick size and freshness limits must be numeric.") from None
        if not all(math.isfinite(value) and value > 0 for value in (tick, trade_age, depth_age)):
            raise BinanceSpotOrderFlowStreamError("Tick size and freshness limits must be finite and positive.")
        if not all(
            isinstance(value, int) and not isinstance(value, bool) and value > 0
            for value in (max_recent_trades, max_buffered_events, max_backfill_pages)
        ):
            raise BinanceSpotOrderFlowStreamError("Stream buffer and backfill limits must be positive integers.")
        if (
            reconnect_initial_seconds <= 0
            or reconnect_max_seconds < reconnect_initial_seconds
        ):
            raise BinanceSpotOrderFlowStreamError("Reconnect delay bounds are invalid.")

        self.tick_size = str(tick_size)
        self.max_trade_age_seconds = trade_age
        self.max_depth_age_seconds = depth_age
        self.max_recent_trades = max_recent_trades
        self.max_buffered_events = max_buffered_events
        self.max_backfill_pages = max_backfill_pages
        self.reconnect_initial_seconds = reconnect_initial_seconds
        self.reconnect_max_seconds = reconnect_max_seconds
        self.random_uniform = random_uniform
        self.websocket_factory = websocket_factory

        self.trade_state = AggTradeCvdState(self.symbol)
        self.depth_book = BinanceSpotDepthBook()
        self.recent_trades: deque[dict[str, Any]] = deque(maxlen=max_recent_trades)
        self.capture_events: deque[dict[str, Any]] = deque()
        self.stream_session_id = uuid.uuid4().hex
        self.capture_rejected_events = 0
        self._recent_trade_ids: set[int] = set()
        self.trade_source: str | None = None
        self.depth_source: str | None = None
        self.depth_observed_at: datetime | None = None
        self.last_message_at: datetime | None = None
        self.status = "STOPPED"
        self.last_error: str | None = None
        self.callback_error: str | None = None
        self.stream_url = (
            f"{BINANCE_SPOT_STREAM_BASE}?streams="
            f"{self.symbol.lower()}@aggTrade/{self.symbol.lower()}@depth@100ms"
        )

    def _remember_trade(self, row: dict[str, Any]) -> None:
        trade_id = int(row["a"])
        if trade_id in self._recent_trade_ids:
            return
        if len(self.recent_trades) == self.max_recent_trades:
            oldest = self.recent_trades[0]
            self._recent_trade_ids.discard(int(oldest["a"]))
        self.recent_trades.append(dict(row))
        self._recent_trade_ids.add(trade_id)

    def _queue_capture_event(self, event_type: str, payload: dict[str, Any], source: str) -> None:
        if len(self.capture_events) >= self.max_buffered_events:
            raise BinanceSpotOrderFlowStreamError("Raw Order Flow capture queue overflowed; event continuity cannot be guaranteed.")
        stamp = payload.get("T") if event_type == "aggTrade" else payload.get("E") if event_type == "depthUpdate" else int(datetime.now(timezone.utc).timestamp() * 1000)
        try:
            event_time_ms = int(stamp)
        except (TypeError, ValueError, OverflowError):
            self.capture_rejected_events += 1
            return
        if event_time_ms <= 0:
            self.capture_rejected_events += 1
            return
        self.capture_events.append({
            "symbol": self.symbol, "event_type": event_type,
            "event_time_ms": event_time_ms,
            "received_at_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
            "source": source, "stream_session_id": self.stream_session_id,
            "payload": dict(payload),
        })

    def drain_capture_events(self, limit: int = 256) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 2048:
            raise ValueError("Capture drain limit must be between 1 and 2048.")
        batch = []
        while self.capture_events and len(batch) < limit:
            batch.append(self.capture_events.popleft())
        return batch

    async def _fetch_public(
        self,
        client: httpx.AsyncClient,
        path: str,
        params: dict[str, Any],
    ) -> tuple[Any, str]:
        try:
            return await get_binance_public_json(client, path, params)
        except (BinancePublicDataError, httpx.HTTPError, ValueError, TypeError) as exc:
            raise BinanceSpotOrderFlowStreamError(
                f"Binance public REST bootstrap/backfill failed for {path}: {exc}"
            ) from exc

    async def _recover_trade_gap(self, client: httpx.AsyncClient) -> None:
        """Backfill every missing aggTrade ID or leave CVD explicitly unusable."""
        for _ in range(self.max_backfill_pages):
            if not self.trade_state.gap_detected:
                return
            last_id = self.trade_state.last_agg_trade_id
            if last_id is None:
                raise BinanceSpotOrderFlowStreamError("Trade gap has no last contiguous aggregate-trade ID.")
            # apply_backfill may have advanced partway through a multi-page gap;
            # continue from the next contiguous ID, not the original gap marker.
            expected = last_id + 1
            rows, source = await self._fetch_public(
                client,
                "/api/v3/aggTrades",
                {"symbol": self.symbol, "fromId": expected, "limit": DEFAULT_TRADE_LIMIT},
            )
            if not isinstance(rows, list) or not rows:
                raise BinanceSpotOrderFlowStreamError("Aggregate-trade backfill returned no rows.")
            before = self.trade_state.last_agg_trade_id
            try:
                result = self.trade_state.apply_backfill(rows)
            except OrderFlowStateError as exc:
                raise BinanceSpotOrderFlowStreamError(f"Aggregate-trade backfill rejected: {exc}") from exc
            after = self.trade_state.last_agg_trade_id
            for row in rows:
                try:
                    row_id = int(row["a"])
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
                if before is not None and before < row_id <= (after if after is not None else before):
                    self._remember_trade(row)
                    self._queue_capture_event("aggTrade", row, "REST_GAP_BACKFILL")
            self.trade_source = source
            if result == "RECOVERED":
                return
            if after == before:
                raise BinanceSpotOrderFlowStreamError("Aggregate-trade backfill made no progress.")
        raise BinanceSpotOrderFlowStreamError(
            f"Aggregate-trade gap remains after {self.max_backfill_pages} bounded backfill pages."
        )

    async def _apply_trade_row(self, client: httpx.AsyncClient, row: dict[str, Any], *, source: str = "WEBSOCKET") -> str:
        if not isinstance(row, dict):
            raise BinanceSpotOrderFlowStreamError("Aggregate-trade event is not an object.")
        if row.get("s") is not None and str(row.get("s")).upper() != self.symbol:
            raise BinanceSpotOrderFlowStreamError("Aggregate-trade event symbol does not match subscription.")
        if self.trade_state.gap_detected:
            await self._recover_trade_gap(client)
        try:
            result = self.trade_state.ingest(row)
        except OrderFlowStateError as exc:
            if self.trade_state.gap_detected:
                await self._recover_trade_gap(client)
                return "RECOVERED_AFTER_INVALID_EVENT"
            raise BinanceSpotOrderFlowStreamError(f"Aggregate-trade event rejected: {exc}") from exc
        if result == "GAP_DETECTED":
            await self._recover_trade_gap(client)
            return "RECOVERED_GAP"
        if result == "APPLIED":
            self._remember_trade(row)
            self._queue_capture_event("aggTrade", row, source)
        return result

    def _apply_depth_event(self, event: dict[str, Any]) -> str:
        result = self.depth_book.apply_diff(event)
        if result == "APPLIED":
            self.depth_observed_at = datetime.now(timezone.utc)
            self._queue_capture_event("depthUpdate", event, "WEBSOCKET")
            return result
        if result == "DUPLICATE":
            return result
        raise BinanceSpotOrderFlowStreamError(
            f"Depth sequence became invalid ({result}); a fresh REST snapshot is required."
        )

    async def _bootstrap(
        self,
        websocket: Any,
        client: httpx.AsyncClient,
    ) -> asyncio.Task:
        """Buffer live events while obtaining REST seeds, then bridge the book."""
        trade_task = asyncio.create_task(self._fetch_public(
            client, "/api/v3/aggTrades", {"symbol": self.symbol, "limit": DEFAULT_TRADE_LIMIT}
        ))
        depth_task = asyncio.create_task(self._fetch_public(
            client, "/api/v3/depth", {"symbol": self.symbol, "limit": DEFAULT_DEPTH_LIMIT}
        ))
        recv_task = asyncio.create_task(websocket.recv())
        buffered_trades: list[dict[str, Any]] = []
        buffered_depth: list[dict[str, Any]] = []
        try:
            while not (trade_task.done() and depth_task.done()):
                done, _ = await asyncio.wait(
                    {trade_task, depth_task, recv_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if recv_task in done:
                    raw = recv_task.result()
                    kind, event = _decode_combined_event(raw, self.symbol)
                    self.last_message_at = datetime.now(timezone.utc)
                    if kind == "aggTrade":
                        buffered_trades.append(event)
                    elif kind == "depthUpdate":
                        buffered_depth.append(event)
                    if len(buffered_trades) + len(buffered_depth) > self.max_buffered_events:
                        raise BinanceSpotOrderFlowStreamError(
                            "Initial WebSocket event buffer overflowed while REST snapshots were loading."
                        )
                    recv_task = asyncio.create_task(websocket.recv())

            trades, trade_source = trade_task.result()
            depth, depth_source = depth_task.result()
            if not isinstance(trades, list) or not trades:
                raise BinanceSpotOrderFlowStreamError("Binance returned no aggregate trades for stream seeding.")
            if not isinstance(depth, dict) or not isinstance(depth.get("bids"), list) or not isinstance(depth.get("asks"), list):
                raise BinanceSpotOrderFlowStreamError("Binance returned an invalid depth snapshot.")
            if self.trade_state.last_agg_trade_id is None:
                first = trades[0]
                self.trade_state.begin_stream_seed(first.get("a"), first.get("T"))
            for row in trades:
                await self._apply_trade_row(client, row, source="REST_BOOTSTRAP")
            for row in buffered_trades:
                await self._apply_trade_row(client, row, source="WEBSOCKET_BUFFER")

            try:
                bridge_result = self.depth_book.load_snapshot(
                    depth.get("lastUpdateId"),
                    depth["bids"],
                    depth["asks"],
                    buffered_events=buffered_depth,
                )
            except OrderFlowStateError as exc:
                raise BinanceSpotOrderFlowStreamError(f"Depth snapshot rejected: {exc}") from exc
            if bridge_result in {"GAP_DETECTED", "INVALID_BOOK", "INVALID_EVENT", "RESYNC_REQUIRED"}:
                raise BinanceSpotOrderFlowStreamError(
                    f"Depth snapshot could not bridge buffered updates ({bridge_result})."
                )
            self.trade_source = trade_source
            self.depth_source = depth_source
            self.depth_observed_at = datetime.now(timezone.utc)
            self._queue_capture_event("depthSnapshot", {
                "lastUpdateId": depth["lastUpdateId"],
                "bids": depth["bids"], "asks": depth["asks"],
            }, "REST_BOOTSTRAP")
            for depth_event in buffered_depth:
                self._queue_capture_event("depthUpdate", depth_event, "WEBSOCKET_BUFFER")
            return recv_task
        except Exception:
            for task in (trade_task, depth_task, recv_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(trade_task, depth_task, recv_task, return_exceptions=True)
            raise

    def snapshot(self, *, now: datetime | None = None) -> dict[str, Any]:
        clock = now or datetime.now(timezone.utc)
        if clock.tzinfo is None:
            raise BinanceSpotOrderFlowStreamError("Snapshot clock must be timezone-aware.")
        trade_state = self.trade_state.snapshot()
        book_state = self.depth_book.snapshot(limit=100)
        depth_age = (
            max(0.0, (clock - self.depth_observed_at).total_seconds())
            if self.depth_observed_at is not None else None
        )
        metrics: dict[str, Any] | None = None
        metrics_error: str | None = None
        signal_ready = bool(
            trade_state["coverage_complete"]
            and not trade_state["gap_detected"]
            and book_state["valid"]
            and book_state["sequence_validated"]
            and depth_age is not None
            and depth_age <= self.max_depth_age_seconds
            and self.recent_trades
        )
        if signal_ready:
            try:
                metrics = calculate_order_flow(
                    list(self.recent_trades),
                    book_state["bids"],
                    book_state["asks"],
                    now=clock,
                    max_trade_age_seconds=self.max_trade_age_seconds,
                    tick_size=self.tick_size,
                )
                metrics["symbol"] = self.symbol
                metrics["cvd_value"] = trade_state["cvd_value"]
                metrics["cvd_status"] = trade_state["cvd_status"]
                metrics["cvd_scope"] = trade_state["cvd_scope"]
                metrics["session_delta"] = trade_state["session_delta"]
                metrics["session_delta_sample"] = float(self.trade_state.session_delta)
                metrics["session_delta_coverage_complete"] = trade_state["session_delta_coverage_complete"]
                metrics["session_delta_scope"] = (
                    "FULL_UTC_SESSION" if trade_state["session_delta_coverage_complete"]
                    else "INCOMPLETE_UTC_SESSION_SAMPLE"
                )
                metrics["order_book"]["source"] = "BINANCE_SPOT_SEQUENCE_VALIDATED_DEPTH_STREAM"
                metrics["data_provenance"]["book_source"] = "Binance Spot sequence-validated diff-depth stream"
                metrics["depth_is_continuous"] = True
                metrics["depth_snapshot_update_id"] = book_state["last_update_id"]
                metrics["depth_observed_at"] = self.depth_observed_at.isoformat()
                metrics["data_sources"] = {
                    "trades": self.trade_source,
                    "depth_snapshot": self.depth_source,
                    "stream": "wss://data-stream.binance.vision",
                }
                metrics["feed_mode"] = "PUBLIC_WEBSOCKET_STREAM"
                metrics["quality"] = "OBSERVED_AGGRESSOR_DELTA_AND_SEQUENCE_VALIDATED_L2"
            except (OrderFlowDataError, OrderFlowStateError, TypeError, ValueError, KeyError, OverflowError) as exc:
                metrics_error = f"{type(exc).__name__}: {exc}"
                signal_ready = False

        return {
            "symbol": self.symbol,
            "market_type": "BINANCE_SPOT",
            "status": self.status,
            "signal_ready": signal_ready,
            "trade_state": trade_state,
            "depth_book": book_state,
            "order_flow": metrics,
            "order_flow_error": metrics_error,
            "depth_age_seconds": round(depth_age, 3) if depth_age is not None else None,
            "last_message_at": self.last_message_at.isoformat() if self.last_message_at else None,
            "last_error": self.last_error,
            "callback_error": self.callback_error,
            "data_provenance": {
                "trade_side": "Binance Spot aggregate-trade buyer-is-maker flag; inferred aggressor side",
                "depth": "REST snapshot bridged to diff-depth update IDs; sequence-valid only after first bridge event",
                "cvd": "Complete only since bounded stream bootstrap seed; not a full historical or UTC-session CVD",
                "session_delta": "Unavailable as full-session value unless session coverage is independently anchored",
                "candle_volume_used": False,
            },
        }

    async def _notify(self, callback: Callable[[dict[str, Any]], Any] | None) -> None:
        if callback is None:
            return
        try:
            result = callback(self.snapshot())
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            self.callback_error = f"{type(exc).__name__}: {exc}"

    def _backoff(self, attempt: int) -> float:
        base = min(
            self.reconnect_max_seconds,
            self.reconnect_initial_seconds * (2 ** min(max(attempt, 0), 10)),
        )
        factor = self.random_uniform(0.8, 1.2)
        return min(self.reconnect_max_seconds, max(0.1, base * factor))

    async def run(
        self,
        client: httpx.AsyncClient,
        stop_event: asyncio.Event,
        on_update: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        """Run until stopped; reconnect with bounded jitter and fail closed."""
        attempt = 0
        while not stop_event.is_set():
            try:
                self.status = "CONNECTING"
                self.depth_book = BinanceSpotDepthBook()
                await self._notify(on_update)
                async with self.websocket_factory(
                    self.stream_url,
                    ping_interval=20,
                    ping_timeout=60,
                    close_timeout=10,
                    open_timeout=10,
                    max_size=1_048_576,
                    max_queue=256,
                ) as websocket:
                    self.stream_session_id = uuid.uuid4().hex
                    self.status = "BOOTSTRAPPING"
                    recv_task = await self._bootstrap(websocket, client)
                    self.last_error = None
                    attempt = 0
                    self.status = "LIVE" if self.snapshot()["signal_ready"] else "DEPTH_BRIDGING"
                    await self._notify(on_update)
                    stop_task = asyncio.create_task(stop_event.wait())
                    try:
                        while not stop_event.is_set():
                            done, _ = await asyncio.wait(
                                {recv_task, stop_task},
                                return_when=asyncio.FIRST_COMPLETED,
                            )
                            if stop_task in done:
                                break
                            raw = recv_task.result()
                            recv_task = asyncio.create_task(websocket.recv())
                            kind, event = _decode_combined_event(raw, self.symbol)
                            self.last_message_at = datetime.now(timezone.utc)
                            if kind == "aggTrade":
                                await self._apply_trade_row(client, event)
                            elif kind == "depthUpdate":
                                self._apply_depth_event(event)
                            self.status = "LIVE" if self.snapshot()["signal_ready"] else "DEPTH_BRIDGING"
                            await self._notify(on_update)
                    finally:
                        if not recv_task.done():
                            recv_task.cancel()
                        if not stop_task.done():
                            stop_task.cancel()
                        await asyncio.gather(recv_task, stop_task, return_exceptions=True)
                if stop_event.is_set():
                    break
                raise BinanceSpotOrderFlowStreamError("Binance WebSocket connection closed.")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                self.depth_book = BinanceSpotDepthBook()
                self.depth_observed_at = None
                self.status = "RECONNECTING"
                await self._notify(on_update)
                delay = self._backoff(attempt)
                attempt += 1
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=delay)
                except TimeoutError:
                    pass
        self.status = "STOPPED"
        await self._notify(on_update)
