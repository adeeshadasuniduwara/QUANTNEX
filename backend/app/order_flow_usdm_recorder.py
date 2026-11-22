"""Isolated raw-event archive for Binance USDⓈ-M Futures Order Flow."""
from __future__ import annotations
import json
import math
import re
from datetime import datetime, timedelta, timezone
from sqlalchemy.exc import IntegrityError
from .models import OrderFlowMarketEvent

MARKET_TYPE = "BINANCE_USDM_FUTURES"
MAX_BATCH = 256
RETENTION_DAYS = 7

class UsdmRawEventError(ValueError):
    pass

def _validate_event(event):
    if not isinstance(event, dict) or event.get("market_type") != MARKET_TYPE:
        raise UsdmRawEventError("Only normalized USDⓈ-M Futures events may enter this archive.")
    symbol = str(event.get("symbol") or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,25}", symbol):
        raise UsdmRawEventError("Invalid USDⓈ-M Futures symbol.")
    kind = event.get("event_type")
    if kind not in {"aggTrade", "depthUpdate", "markPriceUpdate", "forceOrder"}:
        raise UsdmRawEventError("Unsupported USDⓈ-M Futures event type.")
    key = str(event.get("event_key") or "")
    payload = event.get("payload")
    if not key or len(key) > 80 or not isinstance(payload, dict):
        raise UsdmRawEventError("Invalid Futures event identity or payload.")
    event_ms, received_ms = event.get("event_time_ms"), event.get("received_at_ms")
    if any(isinstance(x, bool) or not isinstance(x, int) or x <= 0 for x in (event_ms, received_ms)):
        raise UsdmRawEventError("Futures event timestamps must be positive integer milliseconds.")
    source = str(event.get("source") or "WEBSOCKET")
    session = str(event.get("stream_session_id") or "")
    if source not in {"WEBSOCKET", "REST_SNAPSHOT"} or not re.fullmatch(r"[a-f0-9]{32}", session):
        raise UsdmRawEventError("Invalid Futures event source or stream session.")
    first, last = event.get("sequence_first"), event.get("sequence_last")
    if kind == "depthUpdate" and (not isinstance(first, int) or not isinstance(last, int) or first <= 0 or last < first):
        raise UsdmRawEventError("Futures depth event requires a valid sequence range.")
    if kind == "markPriceUpdate":
        try:
            mark, index, funding = float(payload["p"]), float(payload["i"]), float(payload["r"])
            next_funding = int(payload["T"])
        except (KeyError, TypeError, ValueError, OverflowError):
            raise UsdmRawEventError("Futures mark-price event is missing required fields.") from None
        if not all(map(math.isfinite, (mark, index, funding))) or mark <= 0 or index <= 0 or next_funding <= 0:
            raise UsdmRawEventError("Futures mark-price values are invalid.")
    if kind == "forceOrder":
        order = payload.get("o")
        try:
            side = str(order["S"]).upper()
            qty, price, avg, filled = (float(order[key]) for key in ("q", "p", "ap", "z"))
            trade_ms = int(order["T"])
        except (KeyError, TypeError, ValueError, OverflowError):
            raise UsdmRawEventError("Futures force-order event is missing required fields.") from None
        if (not isinstance(order, dict) or str(order.get("s") or "").upper() != symbol
                or side not in {"BUY", "SELL"} or trade_ms <= 0
                or not all(map(__import__("math").isfinite, (qty, price, avg, filled)))
                or qty <= 0 or price < 0 or avg < 0 or filled < 0 or filled > qty + 1e-12):
            raise UsdmRawEventError("Futures force-order fields are invalid.")
    return symbol, kind, key, event_ms, received_ms, source, session, first, last, payload

def record_usdm_market_events(db, events, *, now=None, retention_days=RETENTION_DAYS):
    if not isinstance(events, list) or not 1 <= len(events) <= MAX_BATCH:
        raise UsdmRawEventError(f"Futures event batch must contain 1–{MAX_BATCH} rows.")
    if isinstance(retention_days, bool) or not isinstance(retention_days, int) or not 1 <= retention_days <= 30:
        raise UsdmRawEventError("Futures retention must be between 1 and 30 days.")
    clock = now or datetime.now(timezone.utc)
    if not isinstance(clock, datetime) or clock.tzinfo is None or clock.utcoffset() is None:
        raise UsdmRawEventError("Recorder clock must be timezone-aware.")
    now_ms = int(clock.astimezone(timezone.utc).timestamp() * 1000)
    db.query(OrderFlowMarketEvent).filter(
        OrderFlowMarketEvent.market_type == MARKET_TYPE,
        OrderFlowMarketEvent.received_at_ms < int((clock - timedelta(days=retention_days)).timestamp() * 1000)
    ).delete(synchronize_session=False)
    seen = {}
    rows = []
    duplicates = 0
    for event in events:
        symbol, kind, key, event_ms, received_ms, source, session, first, last, payload = _validate_event(event)
        if received_ms > now_ms + 2000:
            raise UsdmRawEventError("Futures receive timestamp is ahead of recorder clock.")
        encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False)
        identity = (symbol, kind, key)
        if identity in seen:
            if seen[identity] != (event_ms, encoded):
                raise UsdmRawEventError("Conflicting duplicate Futures event ID in batch.")
            duplicates += 1
            continue
        seen[identity] = (event_ms, encoded)
        rows.append(OrderFlowMarketEvent(
            market_type=MARKET_TYPE, symbol=symbol, event_type=kind, event_key=key,
            event_time_ms=event_ms, received_at_ms=received_ms,
            candle_bucket_ms=(event_ms // 60000) * 60000, source=source,
            stream_session_id=session, sequence_first=first, sequence_last=last,
            payload_json=encoded,
        ))
    stored = 0
    try:
        for row in rows:
            prior = db.query(OrderFlowMarketEvent).filter(
                OrderFlowMarketEvent.market_type == MARKET_TYPE,
                OrderFlowMarketEvent.symbol == row.symbol,
                OrderFlowMarketEvent.event_type == row.event_type,
                OrderFlowMarketEvent.event_key == row.event_key,
            ).first()
            if prior:
                if prior.event_time_ms != row.event_time_ms or prior.payload_json != row.payload_json:
                    raise UsdmRawEventError("Stored Futures event ID conflicts with incoming payload.")
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

def load_usdm_market_events(db, symbol, start_ms, end_ms, *, limit=5000):
    normalized = str(symbol or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,25}", normalized):
        raise ValueError("A valid USDⓈ-M Futures symbol is required.")
    if any(isinstance(x, bool) or not isinstance(x, int) for x in (start_ms, end_ms, limit)):
        raise ValueError("Futures time range and limit must be integers.")
    if start_ms <= 0 or end_ms <= start_ms or not 1 <= limit <= 5000:
        raise ValueError("Use a valid millisecond range and a limit from 1 to 5000.")
    rows = db.query(OrderFlowMarketEvent).filter(
        OrderFlowMarketEvent.market_type == MARKET_TYPE,
        OrderFlowMarketEvent.symbol == normalized,
        OrderFlowMarketEvent.event_time_ms >= start_ms,
        OrderFlowMarketEvent.event_time_ms < end_ms,
    ).order_by(OrderFlowMarketEvent.event_time_ms.asc(), OrderFlowMarketEvent.id.asc()).limit(limit).all()
    return [{
        "id": r.id, "market_type": r.market_type, "symbol": r.symbol,
        "event_type": r.event_type, "event_key": r.event_key,
        "event_time_ms": r.event_time_ms, "received_at_ms": r.received_at_ms,
        "candle_bucket_ms": r.candle_bucket_ms, "source": r.source,
        "stream_session_id": r.stream_session_id, "sequence_first": r.sequence_first,
        "sequence_last": r.sequence_last, "payload": json.loads(r.payload_json),
    } for r in rows]
