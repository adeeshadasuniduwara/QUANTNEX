"""Durable, candle-aligned raw event capture for public Binance Spot Order Flow.

Raw aggTrade and diff-depth events are stored unchanged (JSON payload plus indexed
exchange identifiers). UTC minute manifests expose coverage and gaps. This is
not a fabricated bid/ask split and it does not include candle-volume estimates.
"""
from __future__ import annotations
import json, math, re
from typing import Any
from sqlalchemy.orm import Session
from .models import OrderFlowCandleCapture, OrderFlowRawEvent

MARKET_TYPE = "BINANCE_SPOT"
CANDLE_SECONDS = 60
DEFAULT_RETENTION_DAYS = 7
MAX_BATCH_EVENTS = 500
MAX_EVENT_JSON_BYTES = 262_144

def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool): raise ValueError(f"{label} must be an integer.")
    try: parsed = int(value)
    except (TypeError, ValueError, OverflowError): raise ValueError(f"{label} must be an integer.") from None
    if str(parsed) != str(value).strip() or parsed < 0: raise ValueError(f"{label} must be a non-negative exact integer.")
    return parsed

def _validate_event(event: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(event, dict) or event.get("market_type") != MARKET_TYPE: raise ValueError("Only Binance Spot raw events are accepted.")
    symbol = str(event.get("symbol") or "").upper()
    if not re.fullmatch(r"[A-Z0-9]{5,25}", symbol): raise ValueError("Invalid Binance Spot symbol.")
    kind = str(event.get("event_type") or "")
    if kind not in {"aggTrade", "depthUpdate", "FEED_GAP"}: raise ValueError("Unsupported raw event type.")
    event_ms = _integer(event.get("event_time_ms"), "event_time_ms")
    received_ms = _integer(event.get("received_at_epoch_ms"), "received_at_epoch_ms")
    payload = event.get("payload")
    if not isinstance(payload, dict): raise ValueError("Raw event payload must be an object.")
    continuity = event.get("continuity_validated") is True
    trade_id = first_id = last_id = None
    maker = None
    if kind == "aggTrade":
        trade_id = _integer(payload.get("a"), "aggregate trade ID")
        maker = payload.get("m")
        if not isinstance(maker, bool): raise ValueError("Aggregate trade maker flag must be boolean.")
        for key in ("p", "q"):
            try: value = float(payload.get(key))
            except (TypeError, ValueError, OverflowError): raise ValueError(f"Aggregate trade {key} must be finite.") from None
            if not math.isfinite(value) or value <= 0: raise ValueError(f"Aggregate trade {key} must be finite and positive.")
        if _integer(payload.get("T"), "trade timestamp") != event_ms: raise ValueError("Trade event time must match exchange trade timestamp.")
        event_key = str(trade_id)
    elif kind == "depthUpdate":
        first_id, last_id = _integer(payload.get("U"), "first depth update ID"), _integer(payload.get("u"), "last depth update ID")
        if last_id < first_id: raise ValueError("Depth update ID range is invalid.")
        for side in ("b", "a"):
            levels = payload.get(side)
            if not isinstance(levels, list): raise ValueError("Depth event sides must be arrays.")
            for level in levels:
                if not isinstance(level, list) or len(level) != 2: raise ValueError("Depth levels must contain price and quantity.")
                for raw in level:
                    try: number = float(raw)
                    except (TypeError, ValueError, OverflowError): raise ValueError("Depth levels must be numeric.") from None
                    if not math.isfinite(number) or number < 0: raise ValueError("Depth levels must be finite and non-negative.")
        event_key = f"{first_id}:{last_id}"
    else:
        event_key = str(event.get("event_key") or f"{event_ms}:{payload.get('reason','STREAM_GAP')}")
        continuity = False
    try: payload_json = json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError, OverflowError) as exc: raise ValueError(f"Raw event payload is not strict JSON: {exc}") from exc
    if len(payload_json.encode("utf-8")) > MAX_EVENT_JSON_BYTES: raise ValueError("Raw event payload exceeds 256 KiB.")
    return {"market_type": MARKET_TYPE, "symbol": symbol, "event_type": kind, "event_key": event_key,
            "candle_bucket": event_ms // (CANDLE_SECONDS * 1000), "event_time_ms": event_ms,
            "received_at_epoch_ms": received_ms, "first_update_id": first_id, "last_update_id": last_id,
            "trade_id": trade_id, "buyer_is_maker": maker, "continuity_validated": continuity,
            "payload_json": payload_json}

def _refresh_manifest(row: OrderFlowCandleCapture) -> None:
    if row.is_closed:
        row.coverage_status = "CLOSED_COMPLETE" if row.trade_event_count and row.depth_event_count and row.trade_continuity_validated and row.depth_continuity_validated and row.gap_count == 0 else "CLOSED_INCOMPLETE"
    elif row.gap_count: row.coverage_status = "GAPPED"
    elif row.trade_event_count and row.depth_event_count and row.trade_continuity_validated and row.depth_continuity_validated: row.coverage_status = "OPEN_COMPLETE"
    else: row.coverage_status = "OPEN_PARTIAL"

def record_raw_order_flow_events(db: Session, events: list[dict[str, Any]], *, prune_before_epoch_ms: int | None = None) -> dict[str, Any]:
    if not isinstance(events, list) or len(events) > MAX_BATCH_EVENTS: raise ValueError(f"events must contain at most {MAX_BATCH_EVENTS} items.")
    if prune_before_epoch_ms is not None:
        cutoff = _integer(prune_before_epoch_ms, "retention cutoff")
        db.query(OrderFlowRawEvent).filter(OrderFlowRawEvent.event_time_ms < cutoff).delete(synchronize_session=False)
        db.query(OrderFlowCandleCapture).filter(OrderFlowCandleCapture.updated_at_epoch_ms < cutoff).delete(synchronize_session=False)
    inserted = duplicates = gaps = 0
    for raw in events:
        item = _validate_event(raw)
        exists = db.query(OrderFlowRawEvent.id).filter(OrderFlowRawEvent.market_type == MARKET_TYPE, OrderFlowRawEvent.symbol == item["symbol"], OrderFlowRawEvent.event_type == item["event_type"], OrderFlowRawEvent.event_key == item["event_key"]).first()
        if exists: duplicates += 1; continue
        previous = db.query(OrderFlowCandleCapture).filter(OrderFlowCandleCapture.market_type == MARKET_TYPE, OrderFlowCandleCapture.symbol == item["symbol"], OrderFlowCandleCapture.candle_bucket < item["candle_bucket"], OrderFlowCandleCapture.is_closed.is_(False)).all()
        for old in previous:
            old.is_closed = True
            _refresh_manifest(old)
        row = db.query(OrderFlowCandleCapture).filter(OrderFlowCandleCapture.market_type == MARKET_TYPE, OrderFlowCandleCapture.symbol == item["symbol"], OrderFlowCandleCapture.candle_bucket == item["candle_bucket"]).first()
        if row is None:
            row = OrderFlowCandleCapture(market_type=MARKET_TYPE, symbol=item["symbol"], candle_bucket=item["candle_bucket"], started_at_epoch_ms=item["received_at_epoch_ms"], updated_at_epoch_ms=item["received_at_epoch_ms"], gap_reasons_json="[]")
            db.add(row)
        db.add(OrderFlowRawEvent(**item))
        row.updated_at_epoch_ms = max(row.updated_at_epoch_ms, item["received_at_epoch_ms"])
        if item["event_type"] == "aggTrade":
            row.trade_event_count += 1
            row.first_trade_id = item["trade_id"] if row.first_trade_id is None else min(row.first_trade_id, item["trade_id"])
            row.last_trade_id = item["trade_id"] if row.last_trade_id is None else max(row.last_trade_id, item["trade_id"])
            row.trade_continuity_validated = row.trade_continuity_validated or item["continuity_validated"]
        elif item["event_type"] == "depthUpdate":
            row.depth_event_count += 1
            row.first_depth_update_id = item["first_update_id"] if row.first_depth_update_id is None else min(row.first_depth_update_id, item["first_update_id"])
            row.last_depth_update_id = item["last_update_id"] if row.last_depth_update_id is None else max(row.last_depth_update_id, item["last_update_id"])
            row.depth_continuity_validated = row.depth_continuity_validated or item["continuity_validated"]
        else:
            row.gap_count += 1; gaps += 1
            reasons = json.loads(row.gap_reasons_json or "[]")
            reason = str(json.loads(item["payload_json"]).get("reason") or "STREAM_GAP")[:120]
            if reason not in reasons and len(reasons) < 32: reasons.append(reason)
            row.gap_reasons_json = json.dumps(reasons, separators=(",", ":"))
        _refresh_manifest(row); inserted += 1
    try: db.commit()
    except Exception: db.rollback(); raise
    return {"inserted": inserted, "duplicates": duplicates, "gap_events": gaps}

def load_raw_order_flow_candles(db: Session, symbol: str, start_epoch_ms: int, end_epoch_ms: int, *, include_events: bool = False, limit: int = 5000) -> list[dict[str, Any]]:
    normalized = str(symbol or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,25}", normalized): raise ValueError("A valid Binance Spot symbol is required.")
    start, end = _integer(start_epoch_ms, "start_epoch_ms"), _integer(end_epoch_ms, "end_epoch_ms")
    if end <= start or end - start > 31 * 24 * 60 * 60 * 1000: raise ValueError("Time window must be positive and no longer than 31 days.")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 5000: raise ValueError("limit must be between 1 and 5000.")
    rows = db.query(OrderFlowCandleCapture).filter(OrderFlowCandleCapture.market_type == MARKET_TYPE, OrderFlowCandleCapture.symbol == normalized, OrderFlowCandleCapture.candle_bucket * 60000 >= start, OrderFlowCandleCapture.candle_bucket * 60000 < end).order_by(OrderFlowCandleCapture.candle_bucket.asc()).limit(limit).all()
    output = []
    for row in rows:
        candle_start = row.candle_bucket * 60000
        item = {"symbol": row.symbol, "market_type": row.market_type, "candle_open_time_ms": candle_start, "candle_close_time_ms": candle_start + 59999, "trade_event_count": row.trade_event_count, "depth_event_count": row.depth_event_count, "first_trade_id": row.first_trade_id, "last_trade_id": row.last_trade_id, "first_depth_update_id": row.first_depth_update_id, "last_depth_update_id": row.last_depth_update_id, "trade_continuity_validated": row.trade_continuity_validated, "depth_continuity_validated": row.depth_continuity_validated, "gap_count": row.gap_count, "is_closed": row.is_closed, "coverage_status": row.coverage_status, "gap_reasons": json.loads(row.gap_reasons_json or "[]")}
        if include_events:
            events = db.query(OrderFlowRawEvent).filter(OrderFlowRawEvent.market_type == MARKET_TYPE, OrderFlowRawEvent.symbol == normalized, OrderFlowRawEvent.event_time_ms >= candle_start, OrderFlowRawEvent.event_time_ms < candle_start + 60000).order_by(OrderFlowRawEvent.event_time_ms.asc(), OrderFlowRawEvent.id.asc()).limit(10000).all()
            item["events"] = [{"event_type": e.event_type, "event_key": e.event_key, "event_time_ms": e.event_time_ms, "received_at_epoch_ms": e.received_at_epoch_ms, "first_update_id": e.first_update_id, "last_update_id": e.last_update_id, "trade_id": e.trade_id, "buyer_is_maker": e.buyer_is_maker, "continuity_validated": e.continuity_validated, "payload": json.loads(e.payload_json)} for e in events]
        output.append(item)
    return output
