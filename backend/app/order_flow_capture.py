"""Bounded, asynchronous persistence for minute-sampled Binance Spot order flow.

This stores the latest quality/provenance snapshot per symbol per UTC minute.
It is not a raw aggregate-trade or diff-depth event archive.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import math
import re
import threading
from typing import Any, Callable

from .database import SessionLocal
from .models import OrderFlowCapture


def _utc_datetime(value: Any, fallback: datetime | None = None) -> datetime | None:
    if isinstance(value, datetime):
        stamp = value
    else:
        try:
            stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError, OverflowError):
            stamp = fallback
    if stamp is None or stamp.tzinfo is None:
        return None
    return stamp.astimezone(timezone.utc)


def _finite_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number >= 0 and str(number) == str(value).strip() else None


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        return str(value) if value.is_finite() else None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return str(value)


def _compact_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    order_flow = snapshot.get("order_flow")
    if not isinstance(order_flow, dict):
        order_flow = {}
    trade_state = snapshot.get("trade_state")
    if not isinstance(trade_state, dict):
        trade_state = {}
    depth_book = snapshot.get("depth_book")
    if not isinstance(depth_book, dict):
        depth_book = {}
    order_book = order_flow.get("order_book")
    if not isinstance(order_book, dict):
        order_book = {}

    footprint = order_flow.get("footprint")
    if not isinstance(footprint, list):
        footprint = []
    microprice = _finite_or_none(order_book.get("microprice"))
    best_bid = _finite_or_none(order_book.get("best_bid"))
    best_ask = _finite_or_none(order_book.get("best_ask"))
    anchor = microprice or (
        (best_bid + best_ask) / 2 if best_bid is not None and best_ask is not None else None
    )
    valid_footprint = [row for row in footprint if isinstance(row, dict)]
    if len(valid_footprint) > 64 and anchor is not None:
        valid_footprint = sorted(
            valid_footprint,
            key=lambda row: abs((_finite_or_none(row.get("price")) or anchor) - anchor),
        )[:64]
        valid_footprint.sort(key=lambda row: _finite_or_none(row.get("price")) or 0.0)
    elif len(valid_footprint) > 64:
        valid_footprint = valid_footprint[-64:]

    order_flow_payload = {
        key: order_flow.get(key)
        for key in (
            "trade_count", "unique_aggregate_trade_ids", "first_trade_at",
            "last_trade_at", "trade_data_age_seconds", "buy_volume",
            "sell_volume", "delta", "delta_ratio", "window_cumulative_delta",
            "window_delta_scope", "quote_delta", "cvd_value", "cvd_status",
            "cvd_scope", "session_timezone", "session_date_utc", "session_delta",
            "session_delta_sample", "session_delta_coverage_complete",
            "session_delta_scope", "session_start_trade_id", "feed_mode",
            "quality", "data_provenance", "data_sources",
        )
        if key in order_flow
    }
    order_flow_payload["footprint"] = _json_safe(valid_footprint)
    order_flow_payload["footprint_truncated"] = len(footprint) > len(valid_footprint)
    order_flow_payload["order_book"] = {
        key: order_book.get(key)
        for key in (
            "best_bid", "best_ask", "spread", "spread_bps",
            "bid_depth_quote", "ask_depth_quote", "depth_imbalance",
            "microprice", "microprice_displacement",
        )
        if key in order_book
    }
    return _json_safe({
        "sample_kind": "LATEST_VALIDATED_STATE_PER_UTC_MINUTE_NOT_RAW_EVENT_TAPE",
        "signal_ready": bool(snapshot.get("signal_ready")),
        "status": snapshot.get("status"),
        "order_flow": order_flow_payload if order_flow else None,
        "trade_state": {
            key: trade_state.get(key)
            for key in (
                "last_agg_trade_id", "cvd_value", "cvd_status", "cvd_scope",
                "coverage_complete", "gap_detected", "gap_expected_id",
                "gap_observed_id", "session_date_utc", "session_delta",
                "session_delta_coverage_complete", "session_start_trade_id",
                "applied_trade_count", "duplicate_count", "out_of_order_count",
                "last_trade_time_ms",
            )
            if key in trade_state
        },
        "depth_book": {
            key: depth_book.get(key)
            for key in (
                "last_update_id", "valid", "sequence_validated",
                "best_bid", "best_ask", "spread_bps", "depth_imbalance",
            )
            if key in depth_book
        },
        "data_provenance": snapshot.get("data_provenance"),
    })


class OrderFlowCaptureStore:
    """Coalesce snapshots in memory and persist them with a bounded async writer."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Any] = SessionLocal,
        retention_days: int = 7,
        max_pending: int = 256,
    ) -> None:
        if isinstance(retention_days, bool) or not isinstance(retention_days, int) or retention_days < 1:
            raise ValueError("retention_days must be a positive integer.")
        if isinstance(max_pending, bool) or not isinstance(max_pending, int) or max_pending < 1:
            raise ValueError("max_pending must be a positive integer.")
        self.session_factory = session_factory
        self.retention_days = retention_days
        self.max_pending = max_pending
        self._pending: OrderedDict[tuple[str, str, int], dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self.dropped_pending = 0
        self.rows_written = 0
        self.last_error: str | None = None
        self.last_flush_at: str | None = None
        self._last_cleanup_at: datetime | None = None

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def record_snapshot(self, snapshot: dict[str, Any]) -> bool:
        if not isinstance(snapshot, dict):
            return False
        symbol = str(snapshot.get("symbol") or "").strip().upper()
        market_type = str(snapshot.get("market_type") or "").upper()
        if market_type != "BINANCE_SPOT" or not re.fullmatch(r"[A-Z0-9]{5,25}", symbol):
            return False
        captured_at = _utc_datetime(snapshot.get("captured_at"), datetime.now(timezone.utc))
        if captured_at is None:
            return False
        minute_bucket = int(captured_at.timestamp() // 60)

        order_flow = snapshot.get("order_flow")
        if not isinstance(order_flow, dict):
            order_flow = {}
        trade_state = snapshot.get("trade_state")
        if not isinstance(trade_state, dict):
            trade_state = {}
        depth_book = snapshot.get("depth_book")
        if not isinstance(depth_book, dict):
            depth_book = {}
        order_book = order_flow.get("order_book")
        if not isinstance(order_book, dict):
            order_book = {}

        cvd_status = str(
            trade_state.get("cvd_status")
            or order_flow.get("cvd_status")
            or "UNKNOWN"
        )[:40]
        session_scope = str(
            order_flow.get("session_delta_scope")
            or (
                "FULL_UTC_SESSION"
                if trade_state.get("session_delta_coverage_complete") is True
                else "INCOMPLETE_UTC_SESSION_SAMPLE"
            )
        )[:40]
        quality_status = "READY" if snapshot.get("signal_ready") is True else str(
            snapshot.get("status") or "NOT_READY"
        )[:40]
        payload_json = json.dumps(
            _compact_payload(snapshot),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        record = {
            "symbol": symbol,
            "market_type": "BINANCE_SPOT",
            "minute_bucket": minute_bucket,
            "captured_at": captured_at,
            "signal_ready": snapshot.get("signal_ready") is True,
            "quality_status": quality_status,
            "cvd_status": cvd_status,
            "session_delta_scope": session_scope,
            "depth_sequence_validated": depth_book.get("sequence_validated") is True,
            "trade_delta": _finite_or_none(order_flow.get("delta")),
            "buy_volume": _finite_or_none(order_flow.get("buy_volume")),
            "sell_volume": _finite_or_none(order_flow.get("sell_volume")),
            "quote_delta": _finite_or_none(order_flow.get("quote_delta")),
            "cvd_value": _finite_or_none(
                trade_state.get("cvd_value", order_flow.get("cvd_value"))
            ),
            "session_delta": _finite_or_none(
                trade_state.get("session_delta", order_flow.get("session_delta"))
            ),
            "spread_bps": _finite_or_none(order_book.get("spread_bps")),
            "depth_imbalance": _finite_or_none(order_book.get("depth_imbalance")),
            "microprice": _finite_or_none(order_book.get("microprice")),
            "depth_update_id": _int_or_none(
                depth_book.get("last_update_id", order_flow.get("depth_snapshot_update_id"))
            ),
            "payload_json": payload_json,
        }
        key = (symbol, "BINANCE_SPOT", minute_bucket)
        with self._lock:
            if key not in self._pending and len(self._pending) >= self.max_pending:
                self._pending.popitem(last=False)
                self.dropped_pending += 1
            self._pending[key] = record
            self._pending.move_to_end(key)
        return True

    def flush(self, *, now: datetime | None = None) -> int:
        clock = _utc_datetime(now, datetime.now(timezone.utc))
        if clock is None:
            raise ValueError("Capture flush clock must be timezone-aware.")
        with self._lock:
            pending = list(self._pending.items())
            self._pending.clear()
        if not pending:
            self.last_flush_at = clock.isoformat()
            return 0

        db = self.session_factory()
        try:
            for _key, record in pending:
                row = db.query(OrderFlowCapture).filter(
                    OrderFlowCapture.symbol == record["symbol"],
                    OrderFlowCapture.market_type == record["market_type"],
                    OrderFlowCapture.minute_bucket == record["minute_bucket"],
                ).first()
                if row is None:
                    row = OrderFlowCapture(**record)
                    db.add(row)
                else:
                    for field_name, value in record.items():
                        if field_name not in {"symbol", "market_type", "minute_bucket"}:
                            setattr(row, field_name, value)
            cutoff = clock - timedelta(days=self.retention_days)
            if self._last_cleanup_at is None or (clock - self._last_cleanup_at).total_seconds() >= 3600:
                db.query(OrderFlowCapture).filter(
                    OrderFlowCapture.captured_at < cutoff
                ).delete(synchronize_session=False)
                self._last_cleanup_at = clock
            db.commit()
            self.rows_written += len(pending)
            self.last_error = None
            self.last_flush_at = clock.isoformat()
            return len(pending)
        except Exception as exc:
            db.rollback()
            with self._lock:
                for key, record in pending:
                    current = self._pending.get(key)
                    if current is None or current["captured_at"] < record["captured_at"]:
                        self._pending[key] = record
                        self._pending.move_to_end(key)
                while len(self._pending) > self.max_pending:
                    self._pending.popitem(last=False)
                    self.dropped_pending += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            db.close()

    async def run(self, stop_event: asyncio.Event, *, flush_interval_seconds: float = 5.0) -> None:
        if not math.isfinite(flush_interval_seconds) or flush_interval_seconds <= 0:
            raise ValueError("flush_interval_seconds must be finite and positive.")
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=flush_interval_seconds)
            except asyncio.TimeoutError:
                pass
            try:
                await asyncio.to_thread(self.flush)
            except Exception:
                # Keep the worker alive; last_error is exposed in status and
                # pending records are re-queued for the next bounded flush.
                pass
        try:
            await asyncio.to_thread(self.flush)
        except Exception:
            pass

    def status(self) -> dict[str, Any]:
        return {
            "retention_days": self.retention_days,
            "max_pending": self.max_pending,
            "pending_count": self.pending_count,
            "dropped_pending": self.dropped_pending,
            "rows_written": self.rows_written,
            "last_flush_at": self.last_flush_at,
            "last_error": self.last_error,
        }


_STORE = OrderFlowCaptureStore()
_WORKER_TASK: asyncio.Task | None = None
_STOP_EVENT: asyncio.Event | None = None


def get_order_flow_capture_store() -> OrderFlowCaptureStore:
    return _STORE


def record_order_flow_snapshot(snapshot: dict[str, Any]) -> bool:
    return _STORE.record_snapshot(snapshot)


async def start_order_flow_capture_worker() -> None:
    global _WORKER_TASK, _STOP_EVENT
    if _WORKER_TASK is not None and not _WORKER_TASK.done():
        return
    _STOP_EVENT = asyncio.Event()
    _WORKER_TASK = asyncio.create_task(
        _STORE.run(_STOP_EVENT),
        name="quantnex-orderflow-capture-writer",
    )


async def stop_order_flow_capture_worker() -> None:
    global _WORKER_TASK, _STOP_EVENT
    if _STOP_EVENT is not None:
        _STOP_EVENT.set()
    if _WORKER_TASK is not None:
        await asyncio.gather(_WORKER_TASK, return_exceptions=True)
    _WORKER_TASK = None
    _STOP_EVENT = None
