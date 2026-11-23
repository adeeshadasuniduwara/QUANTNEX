"""Append-only raw-event recorder for validated Binance Spot Order Flow.

Each aggTrade and successfully sequence-applied diff-depth event is stored with
its exchange timestamp, receive timestamp, UTC one-minute bucket, stream
session, source and exchange event/sequence identifiers. This is an observed
event archive, not a claim that an entire candle has complete market coverage.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy import func

from .models import OrderFlowMarketEvent

MARKET_TYPE = "BINANCE_SPOT"
DEFAULT_RAW_EVENT_RETENTION_DAYS = 7
MAX_RAW_EVENT_BATCH = 2048
MAX_RAW_EVENT_PAYLOAD_BYTES = 262_144


class OrderFlowRawEventError(ValueError):
    """Raised when a raw market event is malformed or unsupported."""


def _event_identity(event: dict[str, Any]) -> tuple[str, str, int, int, str, int | None, int | None, str, dict[str, Any]]:
    if not isinstance(event, dict):
        raise OrderFlowRawEventError("Raw market event must be an object.")
    symbol = str(event.get("symbol") or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,25}", symbol):
        raise OrderFlowRawEventError("Raw market event symbol is invalid.")
    event_type = str(event.get("event_type") or "")
    if event_type not in {"aggTrade", "depthUpdate", "depthSnapshot", "captureGap"}:
        raise OrderFlowRawEventError("Raw market event type is unsupported.")
    source = str(event.get("source") or "")
    if source not in {"WEBSOCKET", "WEBSOCKET_BUFFER", "REST_BOOTSTRAP", "REST_GAP_BACKFILL"}:
        raise OrderFlowRawEventError("Raw market event source is unsupported.")
    session_id = str(event.get("stream_session_id") or "")
    if not re.fullmatch(r"[0-9a-f]{32}", session_id):
        raise OrderFlowRawEventError("Raw market event session identifier is invalid.")
    try:
        event_time_ms = int(event.get("event_time_ms"))
        received_at_ms = int(event.get("received_at_ms"))
    except (TypeError, ValueError, OverflowError):
        raise OrderFlowRawEventError("Raw market event timestamps must be integer milliseconds.") from None
    if event_time_ms <= 0 or received_at_ms <= 0 or event_time_ms > received_at_ms + 2_000:
        raise OrderFlowRawEventError("Raw market event timestamps are invalid or future-dated.")
    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise OrderFlowRawEventError("Raw market event payload must be an object.")
    first = last = None
    if event_type == "aggTrade":
        try:
            trade_id = int(payload["a"])
            price = float(payload["p"])
            quantity = float(payload["q"])
            trade_time = int(payload["T"])
            maker = payload["m"]
        except (KeyError, TypeError, ValueError, OverflowError):
            raise OrderFlowRawEventError("Aggregate trade is missing required Binance fields.") from None
        if trade_id < 0 or trade_time != event_time_ms or not math.isfinite(price) or not math.isfinite(quantity) or price <= 0 or quantity <= 0 or not isinstance(maker, bool):
            raise OrderFlowRawEventError("Aggregate trade failed price, quantity, timestamp or side validation.")
        key = str(trade_id)
        normalized_payload = {"a": trade_id, "p": str(payload["p"]), "q": str(payload["q"]), "T": trade_time, "m": maker}
    elif event_type == "depthUpdate":
        try:
            first, last = int(payload["U"]), int(payload["u"])
            event_time = int(payload["E"])
            bids, asks = payload["b"], payload["a"]
        except (KeyError, TypeError, ValueError, OverflowError):
            raise OrderFlowRawEventError("Depth update is missing sequence, timestamp or side arrays.") from None
        if first <= 0 or last < first or event_time != event_time_ms or not isinstance(bids, list) or not isinstance(asks, list):
            raise OrderFlowRawEventError("Depth update failed sequence or payload validation.")
        key = str(last)
        normalized_payload = {"U": first, "u": last, "E": event_time, "b": bids, "a": asks}
    elif event_type == "depthSnapshot":
        try:
            last = int(payload["lastUpdateId"])
            bids, asks = payload["bids"], payload["asks"]
        except (KeyError, TypeError, ValueError, OverflowError):
            raise OrderFlowRawEventError("Depth snapshot is missing its update ID or levels.") from None
        if last <= 0 or not isinstance(bids, list) or not isinstance(asks, list):
            raise OrderFlowRawEventError("Depth snapshot failed validation.")
        key = str(last)
        normalized_payload = {"lastUpdateId": last, "bids": bids, "asks": asks}
    else:
        gap_id = str(payload.get("gap_id") or "")
        reason = str(payload.get("reason") or "")
        if not re.fullmatch(r"[0-9a-f]{32}", gap_id) or reason != "RAW_CAPTURE_QUEUE_OVERFLOW":
            raise OrderFlowRawEventError("Capture-gap marker is invalid.")
        key = gap_id
        normalized_payload = {"gap_id": gap_id, "reason": reason}
    try:
        encoded = json.dumps(normalized_payload, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, OverflowError):
        raise OrderFlowRawEventError("Raw market event payload is not strict JSON.") from None
    if len(encoded.encode("utf-8")) > MAX_RAW_EVENT_PAYLOAD_BYTES:
        raise OrderFlowRawEventError("Raw market event payload exceeds the storage safety limit.")
    return symbol, event_type, event_time_ms, received_at_ms, source, first, last, session_id, {"key": key, "payload": normalized_payload}


def record_order_flow_market_events(db, events: list[dict[str, Any]], *, now: datetime | None = None, retention_days: int = DEFAULT_RAW_EVENT_RETENTION_DAYS, prune_before: datetime | None = None) -> dict[str, Any]:
    """Persist a bounded batch of validated events idempotently."""
    if not isinstance(events, list) or not events or len(events) > MAX_RAW_EVENT_BATCH:
        raise OrderFlowRawEventError(f"Event batch must contain between 1 and {MAX_RAW_EVENT_BATCH} rows.")
    if isinstance(retention_days, bool) or not isinstance(retention_days, int) or not 1 <= retention_days <= 30:
        raise OrderFlowRawEventError("Raw event retention must be between 1 and 30 days.")
    clock = now or datetime.now(timezone.utc)
    if not isinstance(clock, datetime) or clock.tzinfo is None or clock.utcoffset() is None:
        raise OrderFlowRawEventError("Recorder clock must be timezone-aware.")
    now_ms = int(clock.astimezone(timezone.utc).timestamp() * 1000)
    cutoff_ms = None
    if prune_before is not None:
        if not isinstance(prune_before, datetime) or prune_before.tzinfo is None or prune_before.utcoffset() is None:
            raise OrderFlowRawEventError("Raw event retention cutoff must be timezone-aware.")
        cutoff_ms = int(prune_before.astimezone(timezone.utc).timestamp() * 1000)
        db.query(OrderFlowMarketEvent).filter(OrderFlowMarketEvent.received_at_ms < cutoff_ms).delete(synchronize_session=False)
    seen: dict[tuple[str, str, str], tuple[int, str]] = {}
    rows = []
    duplicates = 0
    for event in events:
        symbol, event_type, event_ms, received_ms, source, first, last, session, extra = _event_identity(event)
        if received_ms > now_ms + 2_000:
            raise OrderFlowRawEventError("Receive timestamp is ahead of recorder clock.")
        key = (symbol, event_type, extra["key"])
        payload_json = json.dumps(extra["payload"], separators=(",", ":"), allow_nan=False)
        prior = seen.get(key)
        if prior is not None:
            if prior != (event_ms, payload_json):
                raise OrderFlowRawEventError("One exchange event identifier has conflicting duplicate payloads.")
            duplicates += 1
            continue
        seen[key] = (event_ms, payload_json)
        rows.append(OrderFlowMarketEvent(
            market_type=MARKET_TYPE,
            symbol=symbol,
            event_type=event_type,
            event_key=extra["key"],
            event_time_ms=event_ms,
            received_at_ms=received_ms,
            candle_bucket_ms=(event_ms // 60_000) * 60_000,
            source=source,
            stream_session_id=session,
            sequence_first=first,
            sequence_last=last,
            payload_json=json.dumps(extra["payload"], separators=(",", ":"), allow_nan=False),
        ))
    stored = 0
    try:
        for row in rows:
            exists = db.query(OrderFlowMarketEvent).filter(
                OrderFlowMarketEvent.market_type == MARKET_TYPE,
                OrderFlowMarketEvent.symbol == row.symbol,
                OrderFlowMarketEvent.event_type == row.event_type,
                OrderFlowMarketEvent.event_key == row.event_key,
            ).first()
            if exists:
                if exists.event_time_ms != row.event_time_ms or exists.payload_json != row.payload_json:
                    raise OrderFlowRawEventError("A stored exchange event ID was replayed with conflicting payload data.")
                duplicates += 1
                continue
            try:
                with db.begin_nested():
                    db.add(row)
                    db.flush()
                stored += 1
            except IntegrityError:
                duplicates += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"stored": stored, "duplicates": duplicates, "received": len(events), "retention_days": retention_days}


def load_order_flow_market_events(db, symbol: str, start_ms: int, end_ms: int, *, limit: int = 1000) -> list[dict[str, Any]]:
    normalized = str(symbol or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,25}", normalized):
        raise ValueError("A valid Binance Spot symbol is required.")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (start_ms, end_ms, limit)):
        raise ValueError("Time range and limit must be integers.")
    if start_ms <= 0 or end_ms <= start_ms or not 1 <= limit <= 5000:
        raise ValueError("Use a valid millisecond range and a limit from 1 to 5000.")
    rows = db.query(OrderFlowMarketEvent).filter(
        OrderFlowMarketEvent.market_type == MARKET_TYPE,
        OrderFlowMarketEvent.symbol == normalized,
        OrderFlowMarketEvent.event_time_ms >= start_ms,
        OrderFlowMarketEvent.event_time_ms < end_ms,
    ).order_by(OrderFlowMarketEvent.event_time_ms.asc(), OrderFlowMarketEvent.id.asc()).limit(limit).all()
    return [{
        "id": row.id, "market_type": row.market_type, "symbol": row.symbol,
        "event_type": row.event_type, "event_key": row.event_key,
        "event_time_ms": row.event_time_ms, "received_at_ms": row.received_at_ms,
        "candle_bucket_ms": row.candle_bucket_ms, "source": row.source,
        "stream_session_id": row.stream_session_id,
        "sequence_first": row.sequence_first, "sequence_last": row.sequence_last,
        "payload": json.loads(row.payload_json),
    } for row in rows]


def summarize_order_flow_candles(db, symbol: str, start_ms: int, end_ms: int, *, limit: int = 1000) -> list[dict[str, Any]]:
    """Return conservative UTC 1m raw-event coverage diagnostics.

    The event window is bounded. Every row explicitly reports truncation,
    trade-ID gaps, depth sequence bridges/gaps, stream-session changes,
    source counts and capture-gap markers. No result is ever labelled complete.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 5000:
        raise ValueError("Candle summary limit must be an integer from 1 to 5000.")
    event_limit = min(5000, limit * 200)
    events = load_order_flow_market_events(
        db, symbol, start_ms, end_ms, limit=event_limit
    )
    normalized = str(symbol or "").strip().upper()
    total_events = db.query(func.count(OrderFlowMarketEvent.id)).filter(
        OrderFlowMarketEvent.market_type == MARKET_TYPE,
        OrderFlowMarketEvent.symbol == normalized,
        OrderFlowMarketEvent.event_time_ms >= start_ms,
        OrderFlowMarketEvent.event_time_ms < end_ms,
    ).scalar() or 0
    truncated = total_events > len(events)
    buckets: dict[int, dict[str, Any]] = {}
    for event in events:
        bucket = event["candle_bucket_ms"]
        row = buckets.setdefault(bucket, {
            "candle_open_time_ms": bucket,
            "event_count": 0,
            "trade_count": 0,
            "depth_update_count": 0,
            "depth_snapshot_count": 0,
            "capture_gap_count": 0,
            "gap_detected": False,
            "first_event_time_ms": event["event_time_ms"],
            "last_event_time_ms": event["event_time_ms"],
            "sources": set(),
            "source_counts": {},
            "stream_sessions": set(),
            "session_event_counts": {},
            "backfill_used": False,
            "first_depth_update_id": None,
            "last_depth_update_id": None,
            "trade_ids": [],
            "depth_updates": [],
            "depth_snapshots": [],
        })
        row["event_count"] += 1
        row["first_event_time_ms"] = min(row["first_event_time_ms"], event["event_time_ms"])
        row["last_event_time_ms"] = max(row["last_event_time_ms"], event["event_time_ms"])
        source = event["source"]
        session = event["stream_session_id"]
        row["sources"].add(source)
        row["source_counts"][source] = row["source_counts"].get(source, 0) + 1
        row["stream_sessions"].add(session)
        row["session_event_counts"][session] = row["session_event_counts"].get(session, 0) + 1
        row["backfill_used"] = row["backfill_used"] or source == "REST_GAP_BACKFILL"
        if event["event_type"] == "aggTrade":
            row["trade_count"] += 1
            row["trade_ids"].append(int(event["event_key"]))
        elif event["event_type"] == "depthUpdate":
            row["depth_update_count"] += 1
            row["first_depth_update_id"] = (
                event["sequence_first"] if row["first_depth_update_id"] is None
                else min(row["first_depth_update_id"], event["sequence_first"])
            )
            row["last_depth_update_id"] = max(
                row["last_depth_update_id"] or 0, event["sequence_last"] or 0
            )
            row["depth_updates"].append({
                "session": session,
                "first": event["sequence_first"],
                "last": event["sequence_last"],
                "received_at_ms": event["received_at_ms"],
            })
        elif event["event_type"] == "depthSnapshot":
            row["depth_snapshot_count"] += 1
            row["depth_snapshots"].append({
                "session": session,
                "last_update_id": int(event["payload"]["lastUpdateId"]),
                "received_at_ms": event["received_at_ms"],
            })
        elif event["event_type"] == "captureGap":
            row["capture_gap_count"] += 1
            row["gap_detected"] = True

    result = []
    for bucket in sorted(buckets):
        row = buckets[bucket]
        trade_ids = sorted(set(row.pop("trade_ids")))
        trade_id_gap_count = sum(
            max(0, current - previous - 1)
            for previous, current in zip(trade_ids, trade_ids[1:])
        )
        depth_updates = row.pop("depth_updates")
        depth_snapshots = row.pop("depth_snapshots")
        depth_sessions = sorted({item["session"] for item in depth_updates})
        depth_sequence_gap_count = 0
        depth_baseline_validated = True if depth_sessions else None
        depth_unanchored_sessions = 0
        gap_reasons: set[str] = set()
        if trade_id_gap_count:
            gap_reasons.add("AGGTRADE_ID_GAP")
        if row["capture_gap_count"]:
            gap_reasons.add("RAW_CAPTURE_QUEUE_OVERFLOW")

        for session in depth_sessions:
            updates = sorted(
                (item for item in depth_updates if item["session"] == session),
                key=lambda item: (item["first"], item["last"], item["received_at_ms"]),
            )
            snapshots = sorted(
                (item for item in depth_snapshots if item["session"] == session),
                key=lambda item: item["received_at_ms"],
            )
            first_received = updates[0]["received_at_ms"]
            prior_snapshots = [item for item in snapshots if item["received_at_ms"] <= first_received]
            if not prior_snapshots:
                depth_baseline_validated = False
                depth_unanchored_sessions += 1
                gap_reasons.add("DEPTH_BASELINE_MISSING")
                continue
            baseline = prior_snapshots[-1]["last_update_id"]
            first = updates[0]
            if not first["first"] <= baseline + 1 <= first["last"]:
                depth_baseline_validated = False
                depth_sequence_gap_count += max(1, first["first"] - baseline - 1)
                gap_reasons.add("DEPTH_SNAPSHOT_BRIDGE_GAP")
            previous_last = first["last"]
            for update in updates[1:]:
                expected = previous_last + 1
                if update["first"] > expected:
                    depth_sequence_gap_count += update["first"] - expected
                    gap_reasons.add("DEPTH_SEQUENCE_GAP")
                elif update["last"] < expected:
                    depth_sequence_gap_count += 1
                    gap_reasons.add("DEPTH_SEQUENCE_NON_ADVANCING")
                previous_last = max(previous_last, update["last"])

        if depth_sequence_gap_count:
            gap_reasons.add("DEPTH_SEQUENCE_GAP")
        row["sources"] = sorted(row["sources"])
        row["source_counts"] = dict(sorted(row["source_counts"].items()))
        row["stream_sessions"] = sorted(row["stream_sessions"])
        row["session_event_counts"] = dict(sorted(row["session_event_counts"].items()))
        row["trade_id_first"] = trade_ids[0] if trade_ids else None
        row["trade_id_last"] = trade_ids[-1] if trade_ids else None
        row["trade_id_gap_count"] = trade_id_gap_count
        row["trade_ids_contiguous_in_observed_window"] = (
            trade_id_gap_count == 0 if len(trade_ids) >= 2 else None
        )
        row["depth_session_count"] = len(depth_sessions)
        row["reconnect_session_count"] = max(0, len(row["stream_sessions"]) - 1)
        row["depth_sequence_gap_count"] = depth_sequence_gap_count
        row["depth_baseline_validated"] = depth_baseline_validated
        row["depth_unanchored_sessions"] = depth_unanchored_sessions
        row["gap_reasons"] = sorted(gap_reasons)
        row["event_window_total_events"] = int(total_events)
        row["event_window_loaded_events"] = len(events)
        row["event_window_truncated"] = truncated
        row["coverage_is_complete"] = False

        if truncated:
            status = "TRUNCATED_EVENT_WINDOW"
        elif row["capture_gap_count"]:
            status = "CAPTURE_GAP_DETECTED"
        elif trade_id_gap_count or depth_sequence_gap_count:
            status = "DATA_SEQUENCE_GAP_DETECTED"
        elif len(row["stream_sessions"]) > 1:
            status = "MULTI_SESSION_RECONNECT_BACKFILLED" if row["backfill_used"] else "SESSION_BOUNDARY_UNVERIFIED"
        elif depth_unanchored_sessions:
            status = "DEPTH_BASELINE_MISSING"
        elif not row["depth_update_count"]:
            status = "NO_DEPTH_UPDATES"
        elif row["backfill_used"]:
            status = "RECOVERED_WITH_REST_BACKFILL"
        else:
            status = "OBSERVED_PARTIAL_NOT_PROVEN_COMPLETE"
        row["coverage_status"] = status
        result.append(row)
    return result[-limit:]
