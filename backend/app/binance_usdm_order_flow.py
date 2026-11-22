"""Phase 4 foundation: strict Binance USDⓈ-M Futures Order Flow event validation.

This module normalizes public exchange payloads only. It does not start a stream,
claim capture completeness, or merge Futures data with Spot observations.
"""
from __future__ import annotations
import math
import re
from typing import Any

MARKET_TYPE = "BINANCE_USDM_FUTURES"

class FuturesOrderFlowError(ValueError):
    """Raised for malformed or out-of-sequence Futures market events."""

def _symbol(value: str) -> str:
    symbol = str(value or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,25}", symbol): raise FuturesOrderFlowError("Invalid USD-M Futures symbol.")
    return symbol

def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise FuturesOrderFlowError(f"{name} must be an integer.")
    try: number = int(value)
    except (TypeError, ValueError, OverflowError):
        raise FuturesOrderFlowError(f"{name} must be an integer.") from None
    if str(value).strip() != str(number) or number < minimum:
        raise FuturesOrderFlowError(f"{name} is outside valid integer bounds.")
    return number

def _timestamp(value: Any, name: str) -> int:
    stamp = _integer(value, name, minimum=1)
    return stamp

def normalize_usdm_agg_trade(symbol: str, payload: dict[str, Any], *, received_at_ms: int) -> dict[str, Any]:
    """Normalize a Binance USD-M aggTrade event while preserving exchange IDs and maker side."""
    symbol = _symbol(symbol)
    if not isinstance(payload, dict): raise FuturesOrderFlowError("Futures aggTrade payload must be an object.")
    try:
        trade_id = _integer(payload["a"], "aggregate trade ID")
        price = float(payload["p"]); quantity = float(payload["q"])
        event_ms = _timestamp(payload["T"], "trade time"); maker = payload["m"]
    except (KeyError, TypeError, ValueError, OverflowError): raise FuturesOrderFlowError("Futures aggTrade is missing required Binance fields.") from None
    receive_ms = _timestamp(received_at_ms, "receive time")
    if event_ms > receive_ms + 2_000:
        raise FuturesOrderFlowError("Futures aggTrade event time is ahead of receive time.")
    if trade_id < 0 or not math.isfinite(price) or not math.isfinite(quantity) or price <= 0 or quantity <= 0 or not isinstance(maker, bool):
        raise FuturesOrderFlowError("Futures aggTrade failed ID, price, quantity or side validation.")
    return {"market_type":MARKET_TYPE,"symbol":symbol,"event_type":"aggTrade","event_key":str(trade_id),
        "event_time_ms":event_ms,"received_at_ms":receive_ms,"payload":{"a":trade_id,"p":str(payload["p"]),"q":str(payload["q"]),"T":event_ms,"m":maker}}

def normalize_usdm_depth_update(symbol: str, payload: dict[str, Any], *, received_at_ms: int) -> dict[str, Any]:
    """Normalize a Binance USD-M diff-depth event including its pu sequence link."""
    symbol = _symbol(symbol)
    if not isinstance(payload, dict): raise FuturesOrderFlowError("Futures depth payload must be an object.")
    try:
        first=_integer(payload["U"], "first update ID", minimum=1)
        last=_integer(payload["u"], "last update ID", minimum=1)
        previous=_integer(payload["pu"], "previous update ID")
        event_ms=_timestamp(payload["E"],"event time"); bids=payload["b"]; asks=payload["a"]
    except (KeyError, TypeError, ValueError, OverflowError): raise FuturesOrderFlowError("Futures depth update requires U, u, pu, E, b and a.") from None
    receive_ms=_timestamp(received_at_ms,"receive time")
    if event_ms > receive_ms + 2_000:
        raise FuturesOrderFlowError("Futures depth event time is ahead of receive time.")
    if first<=0 or previous<0 or last<first or not isinstance(bids,list) or not isinstance(asks,list):
        raise FuturesOrderFlowError("Futures depth update failed sequence or side-array validation.")
    for side in (bids,asks):
        for level in side:
            if not isinstance(level,(list,tuple)) or len(level)<2: raise FuturesOrderFlowError("Futures depth level must contain price and quantity.")
            try: price=float(level[0]); qty=float(level[1])
            except (TypeError,ValueError,OverflowError): raise FuturesOrderFlowError("Futures depth level is not numeric.") from None
            if not math.isfinite(price) or not math.isfinite(qty) or price<=0 or qty<0: raise FuturesOrderFlowError("Futures depth level is outside valid bounds.")
    return {"market_type":MARKET_TYPE,"symbol":symbol,"event_type":"depthUpdate","event_key":str(last),
        "event_time_ms":event_ms,"received_at_ms":receive_ms,"sequence_first":first,"sequence_last":last,
        "payload":{"U":first,"u":last,"pu":previous,"E":event_ms,"b":bids,"a":asks}}

def validate_usdm_depth_sequence(snapshot_last_update_id: int, updates: list[dict[str, Any]]) -> dict[str, Any]:
    """Require the first diff event to bridge the snapshot and pu continuity thereafter."""
    if isinstance(snapshot_last_update_id,bool) or not isinstance(snapshot_last_update_id,int) or snapshot_last_update_id<0:
        raise FuturesOrderFlowError("Snapshot update ID must be a non-negative integer.")
    if not isinstance(updates,list) or not updates: raise FuturesOrderFlowError("At least one Futures depth update is required.")
    first_event=updates[0]
    if not isinstance(first_event,dict) or first_event.get("market_type")!=MARKET_TYPE or first_event.get("event_type")!="depthUpdate":
        raise FuturesOrderFlowError("Only normalized USD-M Futures depth events are accepted.")
    symbol=first_event.get("symbol")
    first=first_event.get("payload",{})
    if not isinstance(first,dict) or not (int(first.get("U",-1))<=snapshot_last_update_id<=int(first.get("u",-1))):
        raise FuturesOrderFlowError("First Futures depth event does not bridge the REST snapshot.")
    previous=int(first["u"]); accepted=1
    for event in updates[1:]:
        if not isinstance(event,dict) or event.get("market_type")!=MARKET_TYPE or event.get("event_type")!="depthUpdate" or event.get("symbol")!=symbol:
            raise FuturesOrderFlowError("Futures depth sequence cannot mix market types, event types or symbols.")
        payload=event.get("payload",{})
        if not isinstance(payload,dict) or int(payload.get("pu",-1))!=previous:
            raise FuturesOrderFlowError("Futures depth pu sequence gap detected; discard book and resnapshot.")
        current=int(payload.get("u",-1))
        if current<=previous: raise FuturesOrderFlowError("Futures depth update ID did not advance.")
        previous=current; accepted+=1
    return {"market_type":MARKET_TYPE,"sequence_valid":True,"snapshot_last_update_id":snapshot_last_update_id,
        "first_update_id":int(first["U"]),"last_update_id":previous,"accepted_updates":accepted}
