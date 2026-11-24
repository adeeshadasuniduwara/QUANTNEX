"""Causal replay of archived Binance Spot aggregate-trade and diff-depth events.

Replay decisions use receive time: an event cannot influence a checkpoint before
it was recorded. Aggressor delta is inferred from Binance's buyer-is-maker flag;
it is not consolidated quoted bid/ask volume. Capture completeness and full UTC
session coverage are never inferred from a contiguous bounded archive.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .binance_order_flow_state import (
    AggTradeCvdState,
    BinanceSpotDepthBook,
    OrderFlowStateError,
)
from .order_flow import OrderFlowDataError, calculate_order_book_metrics


MARKET_TYPE = "BINANCE_SPOT"
MAX_REPLAY_EVENTS = 5000
_ALLOWED_EVENT_TYPES = {"aggTrade", "depthUpdate", "depthSnapshot", "captureGap"}
_ALLOWED_SOURCES = {"WEBSOCKET", "WEBSOCKET_BUFFER", "REST_BOOTSTRAP", "REST_GAP_BACKFILL"}


class OrderFlowReplayError(ValueError):
    """Raised when an archived event window cannot be replayed deterministically."""


def _strict_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise OrderFlowReplayError(f"{label} must be an integer.")
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        raise OrderFlowReplayError(f"{label} must be an integer.") from None
    if str(parsed) != str(value).strip():
        raise OrderFlowReplayError(f"{label} must be an exact integer.")
    return parsed


def _positive_decimal(value: Any, label: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise OrderFlowReplayError(f"{label} must be a decimal number.") from None
    if not parsed.is_finite() or parsed <= 0:
        raise OrderFlowReplayError(f"{label} must be finite and positive.")
    return parsed


def _utc_iso(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_events(
    events: list[dict[str, Any]],
    symbol: str,
    *,
    now_ms: int,
) -> list[dict[str, Any]]:
    if not isinstance(events, list) or not events or len(events) > MAX_REPLAY_EVENTS:
        raise OrderFlowReplayError(
            f"Replay requires between 1 and {MAX_REPLAY_EVENTS} archived events."
        )
    normalized_symbol = str(symbol or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,25}", normalized_symbol):
        raise OrderFlowReplayError("A valid Binance Spot symbol is required.")

    seen: dict[tuple[str, str], tuple[int, str]] = {}
    normalized: list[dict[str, Any]] = []
    for index, source_event in enumerate(events):
        if not isinstance(source_event, dict):
            raise OrderFlowReplayError(f"Archived event {index} must be an object.")
        if source_event.get("market_type") != MARKET_TYPE:
            raise OrderFlowReplayError("Raw-event replay supports Binance Spot only.")
        event_symbol = str(source_event.get("symbol") or "").strip().upper()
        if event_symbol != normalized_symbol:
            raise OrderFlowReplayError("Every replay event must match the requested symbol.")

        event_type = str(source_event.get("event_type") or "")
        source = str(source_event.get("source") or "")
        session = str(source_event.get("stream_session_id") or "")
        if event_type not in _ALLOWED_EVENT_TYPES:
            raise OrderFlowReplayError("Archived event type is unsupported.")
        if source not in _ALLOWED_SOURCES:
            raise OrderFlowReplayError("Archived event source is unsupported.")
        if not re.fullmatch(r"[0-9a-f]{32}", session):
            raise OrderFlowReplayError("Archived stream-session identifier is invalid.")

        event_id = _strict_int(source_event.get("id", index + 1), "event row ID")
        event_time_ms = _strict_int(source_event.get("event_time_ms"), "event timestamp")
        received_at_ms = _strict_int(source_event.get("received_at_ms"), "receive timestamp")
        if event_id < 0 or event_time_ms <= 0 or received_at_ms <= 0:
            raise OrderFlowReplayError("Archived event identifiers and timestamps must be positive.")
        if event_time_ms > received_at_ms + 2_000:
            raise OrderFlowReplayError("Archived event timestamp is ahead of its receive time.")
        if received_at_ms > now_ms + 2_000:
            raise OrderFlowReplayError("Replay archive contains a future receive timestamp.")

        payload = source_event.get("payload")
        if not isinstance(payload, dict):
            raise OrderFlowReplayError("Archived event payload must be an object.")

        if event_type == "aggTrade":
            trade_id = _strict_int(payload.get("a"), "aggregate trade ID")
            trade_time = _strict_int(payload.get("T"), "aggregate trade timestamp")
            price = _positive_decimal(payload.get("p"), "aggregate trade price")
            quantity = _positive_decimal(payload.get("q"), "aggregate trade quantity")
            if trade_id < 0 or trade_time != event_time_ms or not isinstance(payload.get("m"), bool):
                raise OrderFlowReplayError("Aggregate trade identity, timestamp or maker flag is invalid.")
            event_key = str(trade_id)
            normalized_payload = {
                "a": trade_id, "p": str(price), "q": str(quantity),
                "T": trade_time, "m": payload["m"],
            }
        elif event_type == "depthUpdate":
            first = _strict_int(payload.get("U"), "depth first update ID")
            last = _strict_int(payload.get("u"), "depth last update ID")
            event_time = _strict_int(payload.get("E"), "depth event timestamp")
            if first <= 0 or last < first or event_time != event_time_ms:
                raise OrderFlowReplayError("Depth update sequence or timestamp is invalid.")
            if not isinstance(payload.get("b"), list) or not isinstance(payload.get("a"), list):
                raise OrderFlowReplayError("Depth update sides must be arrays.")
            event_key = str(last)
            normalized_payload = {
                "U": first, "u": last, "E": event_time,
                "b": payload["b"], "a": payload["a"],
            }
        elif event_type == "depthSnapshot":
            last = _strict_int(payload.get("lastUpdateId"), "depth snapshot update ID")
            if last <= 0 or not isinstance(payload.get("bids"), list) or not isinstance(payload.get("asks"), list):
                raise OrderFlowReplayError("Depth snapshot update ID or sides are invalid.")
            event_key = str(last)
            normalized_payload = {
                "lastUpdateId": last, "bids": payload["bids"], "asks": payload["asks"],
            }
        else:
            gap_id = str(payload.get("gap_id") or "")
            if not re.fullmatch(r"[0-9a-f]{32}", gap_id) or payload.get("reason") != "RAW_CAPTURE_QUEUE_OVERFLOW":
                raise OrderFlowReplayError("Raw capture-gap marker is invalid.")
            event_key = gap_id
            normalized_payload = {"gap_id": gap_id, "reason": "RAW_CAPTURE_QUEUE_OVERFLOW"}

        identity = (event_type, event_key)
        payload_fingerprint = repr(normalized_payload)
        previous = seen.get(identity)
        if previous is not None:
            if previous != (event_time_ms, payload_fingerprint):
                raise OrderFlowReplayError("One archived event ID has conflicting payloads.")
            continue
        seen[identity] = (event_time_ms, payload_fingerprint)

        normalized.append({
            "id": event_id,
            "symbol": normalized_symbol,
            "event_type": event_type,
            "event_key": event_key,
            "event_time_ms": event_time_ms,
            "received_at_ms": received_at_ms,
            "source": source,
            "stream_session_id": session,
            "payload": normalized_payload,
        })

    normalized.sort(key=lambda item: (item["received_at_ms"], item["id"]))
    if not normalized:
        raise OrderFlowReplayError("No unique raw events remain after de-duplication.")
    return normalized


def replay_spot_order_flow_events(
    events: list[dict[str, Any]],
    symbol: str,
    *,
    now: datetime | None = None,
    interval_ms: int = 60_000,
    max_trade_age_seconds: float = 15.0,
    max_depth_age_seconds: float = 5.0,
    depth_levels: int = 10,
) -> list[dict[str, Any]]:
    """Reconstruct receive-time-bucketed Spot flow snapshots from archived raw events.

    Only completed receive-time buckets are returned. A bounded archive may
    establish continuity since its first captured trade, but it cannot prove
    that capture began at UTC session start or that no event was lost before
    the archive's first row. A capture-gap marker permanently vetoes replay
    eligibility for this archive window.
    """
    if isinstance(interval_ms, bool) or not isinstance(interval_ms, int) or not 1_000 <= interval_ms <= 3_600_000:
        raise OrderFlowReplayError("Replay interval must be an integer from 1 second to 1 hour.")
    if isinstance(depth_levels, bool) or not isinstance(depth_levels, int) or not 1 <= depth_levels <= 100:
        raise OrderFlowReplayError("Depth levels must be an integer from 1 to 100.")
    if isinstance(max_trade_age_seconds, bool) or isinstance(max_depth_age_seconds, bool):
        raise OrderFlowReplayError("Replay freshness limits must be numeric.")
    try:
        max_trade_age_seconds = float(max_trade_age_seconds)
        max_depth_age_seconds = float(max_depth_age_seconds)
    except (TypeError, ValueError, OverflowError):
        raise OrderFlowReplayError("Replay freshness limits must be finite positive numbers.") from None
    if not math.isfinite(max_trade_age_seconds) or max_trade_age_seconds <= 0:
        raise OrderFlowReplayError("Trade freshness limit must be finite and positive.")
    if not math.isfinite(max_depth_age_seconds) or max_depth_age_seconds <= 0:
        raise OrderFlowReplayError("Depth freshness limit must be finite and positive.")
    clock = now or datetime.now(timezone.utc)
    if not isinstance(clock, datetime) or clock.tzinfo is None or clock.utcoffset() is None:
        raise OrderFlowReplayError("Replay clock must be timezone-aware.")
    now_ms = int(clock.astimezone(timezone.utc).timestamp() * 1000)
    rows = _normalize_events(events, symbol, now_ms=now_ms)

    trade_state: AggTradeCvdState | None = None
    pending_trade_rows: dict[int, dict[str, Any]] = {}
    trade_integrity_failed = False
    trade_event_order_invalid = False
    capture_gap_detected = False
    depth_book = BinanceSpotDepthBook()
    current_stream_session_id: str | None = None
    last_depth_event_time_ms: int | None = None
    stream_sessions: set[str] = set()
    snapshots: list[dict[str, Any]] = []

    bucket_start: int | None = None
    bucket_live = _new_trade_bucket()
    bucket_backfill = _new_trade_bucket()
    bucket_bootstrap = _new_trade_bucket()
    bucket_counts = defaultdict(int)
    bucket_source_counts = defaultdict(int)
    bucket_backfill_used = False
    bucket_capture_gap = False

    def add_trade_to_bucket(target: dict[str, Decimal | int], payload: dict[str, Any]) -> None:
        quantity = Decimal(str(payload["q"]))
        price = Decimal(str(payload["p"]))
        buyer_is_maker = payload["m"]
        if buyer_is_maker:
            target["sell_volume"] += quantity
            target["sell_quote_volume"] += price * quantity
        else:
            target["buy_volume"] += quantity
            target["buy_quote_volume"] += price * quantity
        target["trade_count"] += 1

    def finalize_bucket(start_ms: int) -> None:
        nonlocal snapshots
        decision_at_ms = start_ms + interval_ms
        trade_snapshot = trade_state.snapshot() if trade_state is not None else None
        last_trade_ms = trade_snapshot.get("last_trade_time_ms") if trade_snapshot else None
        trade_age = (
            (decision_at_ms - int(last_trade_ms)) / 1000.0
            if last_trade_ms is not None else None
        )
        depth_age = (
            (decision_at_ms - last_depth_event_time_ms) / 1000.0
            if last_depth_event_time_ms is not None else None
        )

        book_snapshot = depth_book.snapshot(limit=max(20, depth_levels))
        book_metrics = None
        book_error = None
        if depth_book.valid and depth_book.sequence_validated:
            try:
                book_metrics = calculate_order_book_metrics(
                    book_snapshot["bids"], book_snapshot["asks"],
                    depth_levels=depth_levels,
                )
                book_metrics["source"] = "BINANCE_SPOT_SEQUENCE_VALIDATED_DEPTH_REPLAY"
            except OrderFlowDataError as exc:
                book_error = str(exc)

        trade_covered = bool(
            trade_snapshot
            and trade_snapshot.get("coverage_complete") is True
            and trade_snapshot.get("gap_detected") is False
            and not trade_integrity_failed
            and not trade_event_order_invalid
            and not capture_gap_detected
        )
        trade_fresh = bool(
            trade_age is not None and math.isfinite(trade_age)
            and 0 <= trade_age <= max_trade_age_seconds
        )
        depth_valid = bool(
            depth_book.valid and depth_book.sequence_validated and book_metrics is not None
        )
        depth_fresh = bool(
            depth_age is not None and math.isfinite(depth_age)
            and 0 <= depth_age <= max_depth_age_seconds
        )
        eligible = trade_covered and trade_fresh and depth_valid and depth_fresh

        live_buy = float(bucket_live["buy_volume"])
        live_sell = float(bucket_live["sell_volume"])
        live_total = live_buy + live_sell
        live_delta = live_buy - live_sell
        delta_ratio = live_delta / live_total if live_total > 0 else None
        backfill_delta = float(bucket_backfill["buy_volume"] - bucket_backfill["sell_volume"])
        bootstrap_delta = float(bucket_bootstrap["buy_volume"] - bucket_bootstrap["sell_volume"])
        cvd_value = (
            float(trade_snapshot["cumulative_delta_observed"])
            if trade_covered and trade_snapshot is not None else None
        )
        if capture_gap_detected:
            cvd_status = "INCOMPLETE_RAW_CAPTURE_GAP"
        elif trade_event_order_invalid:
            cvd_status = "INCOMPLETE_EVENT_ORDER"
        elif trade_integrity_failed:
            cvd_status = "INCOMPLETE_RAW_CAPTURE_GAP"
        elif trade_snapshot is None:
            cvd_status = "NOT_AVAILABLE_NO_TRADE_SEED"
        else:
            cvd_status = trade_snapshot["cvd_status"]

        if bucket_capture_gap or capture_gap_detected:
            coverage_status = "CAPTURE_GAP_DETECTED"
        elif trade_event_order_invalid:
            coverage_status = "TRADE_EVENT_ORDER_INVALID"
        elif trade_integrity_failed or (trade_snapshot and trade_snapshot.get("gap_detected")):
            coverage_status = "TRADE_SEQUENCE_GAP"
        elif not trade_covered:
            coverage_status = "TRADE_COVERAGE_UNPROVEN"
        elif not trade_fresh:
            coverage_status = "TRADE_STALE"
        elif not depth_valid:
            coverage_status = "DEPTH_SEQUENCE_UNVALIDATED"
        elif not depth_fresh:
            coverage_status = "DEPTH_STALE"
        else:
            coverage_status = "OBSERVED_CONTIGUOUS_CAPTURE_NOT_FULL_SESSION"

        snapshots.append({
            "market_type": MARKET_TYPE,
            "symbol": str(symbol).strip().upper(),
            "capture_bucket_ms": start_ms,
            "decision_at_ms": decision_at_ms,
            "decision_at": _utc_iso(decision_at_ms),
            "capture_clock": "RECEIVED_AT_MS",
            "capture_scope": "RECEIVE_TIME_BUCKET",
            "event_count": int(bucket_counts["events"]),
            "live_trade_count": int(bucket_live["trade_count"]),
            "backfill_trade_count": int(bucket_backfill["trade_count"]),
            "bootstrap_trade_count": int(bucket_bootstrap["trade_count"]),
            "source_counts": dict(sorted(bucket_source_counts.items())),
            "stream_sessions": sorted(stream_sessions),
            "stream_session_count": len(stream_sessions),
            "buy_volume": live_buy,
            "sell_volume": live_sell,
            "buy_quote_volume": float(bucket_live["buy_quote_volume"]),
            "sell_quote_volume": float(bucket_live["sell_quote_volume"]),
            "delta": live_delta,
            "delta_scope": "WEBSOCKET_AND_BUFFER_AGGTRADES_RECEIVED_DURING_CAPTURE_BUCKET",
            "quote_delta": float(bucket_live["buy_quote_volume"] - bucket_live["sell_quote_volume"]),
            "delta_ratio": delta_ratio,
            "backfill_delta": backfill_delta,
            "backfill_delta_scope": "REST_GAP_BACKFILL_EVENTS_RECEIVED_DURING_CAPTURE_BUCKET",
            "bootstrap_delta": bootstrap_delta,
            "bootstrap_delta_scope": "REST_BOOTSTRAP_EVENTS_RECEIVED_DURING_CAPTURE_BUCKET",
            "backfill_used": bucket_backfill_used,
            "cvd_value": cvd_value,
            "cvd_scope": "SINCE_CAPTURE_SEED" if cvd_value is not None else None,
            "cvd_status": cvd_status,
            "session_delta": (
                float(trade_snapshot["session_delta"])
                if trade_covered and trade_snapshot and trade_snapshot.get("session_delta") is not None
                else None
            ),
            "session_delta_coverage_complete": bool(
                trade_snapshot and trade_snapshot.get("session_delta_coverage_complete") is True
                and trade_covered
            ),
            "session_delta_scope": "UTC_SESSION_START_ANCHOR_REQUIRED",
            "last_trade_at_ms": last_trade_ms,
            "trade_age_seconds": round(trade_age, 3) if trade_age is not None else None,
            "last_depth_event_at_ms": last_depth_event_time_ms,
            "depth_age_seconds": round(depth_age, 3) if depth_age is not None else None,
            "trade_state": trade_snapshot,
            "depth_book": book_snapshot,
            "order_book": book_metrics,
            "depth_error": book_error,
            "depth_is_continuous": depth_valid,
            "depth_snapshot_update_id": depth_book.last_update_id,
            "capture_gap_detected": capture_gap_detected,
            "coverage_status": coverage_status,
            "coverage_is_complete": False,
            "eligible_for_order_flow_replay": bool(eligible),
            "data_provenance": {
                "trade_source": "Binance Spot aggregate trades; buyer-is-maker flag infers aggressor side",
                "book_source": "Binance Spot REST bootstrap snapshot plus sequence-applied diff-depth events",
                "bid_ask_semantics": "Aggressor-side inferred trade volume; not quoted bid/ask volume or a consolidated footprint",
                "candle_volume_used": False,
                "decision_clock": "received_at_ms; later-arriving events cannot alter earlier checkpoints",
                "capture_scope": "bounded raw archive; continuity is only established since the first captured trade",
            },
            "feed_mode": "RAW_EVENT_REPLAY",
            "session_timezone": "UTC",
            "session_delta_is_full_session": False,
        })

    for event in rows:
        receive_bucket = (event["received_at_ms"] // interval_ms) * interval_ms
        if bucket_start is None:
            bucket_start = receive_bucket
        elif receive_bucket != bucket_start:
            if bucket_start + interval_ms <= now_ms:
                finalize_bucket(bucket_start)
            bucket_start = receive_bucket
            bucket_live = _new_trade_bucket()
            bucket_backfill = _new_trade_bucket()
            bucket_bootstrap = _new_trade_bucket()
            bucket_counts = defaultdict(int)
            bucket_source_counts = defaultdict(int)
            bucket_backfill_used = False
            bucket_capture_gap = False

        bucket_counts["events"] += 1
        bucket_source_counts[event["source"]] += 1
        stream_sessions.add(event["stream_session_id"])
        if current_stream_session_id != event["stream_session_id"]:
            current_stream_session_id = event["stream_session_id"]
            depth_book = BinanceSpotDepthBook()
            last_depth_event_time_ms = None

        event_type = event["event_type"]
        source = event["source"]
        payload = event["payload"]

        if event_type == "captureGap":
            capture_gap_detected = True
            bucket_capture_gap = True
            depth_book = BinanceSpotDepthBook()
            last_depth_event_time_ms = None
            trade_integrity_failed = True
            continue

        if event_type == "aggTrade":
            trade_id = int(payload["a"])
            if trade_state is None:
                trade_state = AggTradeCvdState(str(symbol).strip().upper())
                trade_state.begin_stream_seed(trade_id, int(payload["T"]))

            if source == "REST_GAP_BACKFILL":
                bucket_backfill_used = True
                add_trade_to_bucket(bucket_backfill, payload)
            elif source == "REST_BOOTSTRAP":
                add_trade_to_bucket(bucket_bootstrap, payload)
            else:
                add_trade_to_bucket(bucket_live, payload)

            if trade_state.gap_detected:
                pending_trade_rows[trade_id] = payload
                if source == "REST_GAP_BACKFILL":
                    try:
                        result = trade_state.apply_backfill(
                            [pending_trade_rows[key] for key in sorted(pending_trade_rows)]
                        )
                    except OrderFlowStateError as exc:
                        raise OrderFlowReplayError(str(exc)) from None
                    if result == "RECOVERED":
                        pending_trade_rows.clear()
                continue

            try:
                status = trade_state.ingest(payload)
            except OrderFlowStateError as exc:
                trade_integrity_failed = True
                raise OrderFlowReplayError(str(exc)) from None
            if status == "GAP_DETECTED":
                pending_trade_rows[trade_id] = payload
            elif status == "GAP_PENDING":
                pending_trade_rows[trade_id] = payload
            elif status == "OUT_OF_ORDER":
                trade_event_order_invalid = True

        if event_type in {"depthSnapshot", "depthUpdate"}:
            try:
                if event_type == "depthSnapshot":
                    depth_book.load_snapshot(
                        int(payload["lastUpdateId"]), payload["bids"], payload["asks"]
                    )
                    last_depth_event_time_ms = event["event_time_ms"]
                else:
                    status = depth_book.apply_diff(payload)
                    if status == "APPLIED":
                        last_depth_event_time_ms = event["event_time_ms"]
            except OrderFlowStateError as exc:
                raise OrderFlowReplayError(str(exc)) from None

    if bucket_start is not None and bucket_start + interval_ms <= now_ms:
        finalize_bucket(bucket_start)
    return snapshots


def _new_trade_bucket() -> dict[str, Decimal | int]:
    return {
        "trade_count": 0,
        "buy_volume": Decimal("0"),
        "sell_volume": Decimal("0"),
        "buy_quote_volume": Decimal("0"),
        "sell_quote_volume": Decimal("0"),
    }
