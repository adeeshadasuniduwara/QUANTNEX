"""Persistent, restart-safe signal outcome tracking. Paper analytics only; never sends broker orders."""
from __future__ import annotations

import asyncio
import json
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from .database import SessionLocal
from .models import SignalTrade, SignalTradeEvent
from .events import event_hub

logger = logging.getLogger("quantnex.signal_lifecycle")
TIMEFRAME_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400,
                     "1": 60, "5": 300, "15": 900, "30": 1800, "50": 3000, "60": 3600, "240": 14400}
ACTIVE_STATES = {"OPEN", "PENDING"}


def as_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        stamp = value
    else:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        return stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def _signal_time(signal: dict[str, Any]) -> datetime:
    raw = signal.get("signal_time") or signal.get("generated_at") or signal.get("signal_candle_time")
    if raw:
        stamp = as_utc(raw)
        if signal.get("signal_time") or signal.get("generated_at"):
            return stamp
        interval = str(signal.get("timeframe") or "15m")
        return stamp + timedelta(seconds=TIMEFRAME_SECONDS.get(interval, 900))
    return datetime.now(timezone.utc)


def signal_fingerprint(source: str, symbol: str, side: str, timeframe: str, signal_time: datetime) -> str:
    return "|".join((source.upper(), symbol.upper(), side.upper(), timeframe, signal_time.isoformat()))


def record_signal(db, user_id: int, signal: dict[str, Any], source: str = "QUANTNEX_VIEW",
                  deduplicate_active: bool = True) -> tuple[SignalTrade, bool]:
    """Persist a signal once using a deterministic candle identity."""
    symbol = str(signal.get("symbol") or "").strip().upper()
    side = str(signal.get("side") or "").strip().upper()
    timeframe = str(signal.get("timeframe") or "15m")
    if not symbol or side not in {"BUY", "SELL"}:
        raise ValueError("Signal symbol and direction are required.")
    entry = float(signal.get("entry") or signal.get("entry_price") or 0)
    stop = float(signal.get("stop_loss") or 0)
    tp1, tp2, tp3 = (float(signal.get(key) or 0) for key in ("tp1", "tp2", "tp3"))
    if not all(math.isfinite(x) and x > 0 for x in (entry, stop, tp1, tp2, tp3)):
        raise ValueError("Signal prices must be finite positive values.")
    risk = abs(entry - stop)
    if risk <= 0 or (side == "BUY" and not stop < entry < tp1 < tp2 < tp3) or (side == "SELL" and not tp3 < tp2 < tp1 < entry < stop):
        raise ValueError("Signal levels are not directionally ordered.")
    signal_time = _signal_time(signal)
    entry_type = str(signal.get("entry_type") or "MARKET").upper()
    if entry_type not in {"MARKET", "LIMIT"}:
        entry_type = "MARKET"
    limit_price = float(signal["limit_price"]) if signal.get("limit_price") is not None else None
    fingerprint = signal_fingerprint(source, symbol, side, timeframe, signal_time)
    existing = db.scalar(select(SignalTrade).where(
        SignalTrade.user_id == user_id, SignalTrade.fingerprint == fingerprint
    ))
    if existing is not None:
        return existing, False
    if deduplicate_active:
        active_rows = list(db.scalars(select(SignalTrade).where(
            SignalTrade.user_id == user_id, SignalTrade.source == source.upper(),
            SignalTrade.symbol == symbol, SignalTrade.side == side,
            SignalTrade.timeframe == timeframe, SignalTrade.status.in_(tuple(ACTIVE_STATES)),
        ).order_by(SignalTrade.signal_time.desc()).limit(1)))
        if active_rows:
            return active_rows[0], False
    item = SignalTrade(
        user_id=user_id, fingerprint=fingerprint, source=source.upper(), symbol=symbol,
        side=side, timeframe=timeframe, entry_type=entry_type, entry_price=entry,
        limit_price=limit_price, stop_loss=stop, active_stop_loss=stop,
        tp1=tp1, tp2=tp2, tp3=tp3, risk_distance=risk,
        status="PENDING" if entry_type == "LIMIT" else "OPEN",
        filled_at=None if entry_type == "LIMIT" else signal_time,
        signal_time=signal_time, recovery_status="PENDING",
    )
    db.add(item)
    db.flush()
    return item, True


def _event(db, trade: SignalTrade, event_type: str, price: float, candle_time: datetime,
           details: dict[str, Any] | None = None) -> None:
    event_key = event_type
    exists = db.scalar(select(SignalTradeEvent.id).where(
        SignalTradeEvent.trade_id == trade.id, SignalTradeEvent.event_key == event_key
    ))
    if exists is not None:
        return
    db.add(SignalTradeEvent(
        user_id=trade.user_id, trade_id=trade.id, event_key=event_key,
        event_type=event_type, price=float(price),
        details_json=json.dumps({"candle_time": candle_time.isoformat(), **(details or {})}, separators=(",", ":")),
    ))


def _touches(side: str, high: float, low: float, level: float, target: bool) -> bool:
    if side == "BUY":
        return high >= level if target else low <= level
    return low <= level if target else high >= level


def process_trade_candles(db, trade: SignalTrade, candles: list[dict[str, Any]]) -> int:
    """Replay unseen closed OHLC bars. Ambiguous stop/target bars are never guessed."""
    if trade.status not in ACTIVE_STATES or not candles:
        return 0
    ordered = sorted(candles, key=lambda row: as_utc(row["time"]))
    first_time = as_utc(ordered[0]["time"])
    if first_time > as_utc(trade.signal_time):
        trade.recovery_status = "PARTIAL"
        trade.recovery_note = "Provider history begins after this signal; outcome replay is paused to avoid missing an earlier stop or target."
        return 0
    trade.recovery_status = "COMPLETE"
    trade.recovery_note = "Available closed-candle history covers the signal timestamp."
    last_processed = as_utc(trade.last_processed_candle_time) if trade.last_processed_candle_time else None
    signal_time = as_utc(trade.signal_time)
    processed = 0
    for row in ordered:
        candle_time = as_utc(row["time"])
        # A signal is created from a confirmed candle close. Never evaluate the
        # candle that produced the signal as post-entry price action: its OHLC
        # may include movement that happened before the entry existed.
        if candle_time <= signal_time or (last_processed and candle_time <= last_processed):
            continue
        try:
            op, high, low, close = (float(row[key]) for key in ("open", "high", "low", "close"))
            if not all(math.isfinite(x) and x > 0 for x in (op, high, low, close)):
                continue
            if high < max(op, close, low) or low > min(op, close, high):
                continue
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        processed += 1
        trade.last_price = close
        trade.last_processed_candle_time = candle_time

        if trade.status == "PENDING":
            limit = trade.limit_price or trade.entry_price
            filled = low <= limit if trade.side == "BUY" else high >= limit
            if not filled:
                expiry = signal_time + timedelta(seconds=TIMEFRAME_SECONDS.get(trade.timeframe, 900) * 4)
                if candle_time >= expiry:
                    trade.status = "EXPIRED"
                    _event(db, trade, "LIMIT_EXPIRED", close, candle_time, {"limit_price": limit})
                continue
            fill = min(op, limit) if trade.side == "BUY" and op <= limit else max(op, limit) if trade.side == "SELL" and op >= limit else limit
            trade.entry_price = fill
            trade.risk_distance = abs(fill - trade.stop_loss)
            trade.filled_at = candle_time
            trade.status = "OPEN"
            _event(db, trade, "ENTRY_FILLED", fill, candle_time, {"entry_type": "LIMIT"})

        stop = float(trade.active_stop_loss or trade.stop_loss)
        next_target = trade.tp1 if not trade.tp1_hit else trade.tp2 if not trade.tp2_hit else trade.tp3 if not trade.tp3_hit else None
        stop_hit = _touches(trade.side, high, low, stop, False)
        target_hit = next_target is not None and _touches(trade.side, high, low, float(next_target), True)
        if stop_hit and target_hit:
            # OHLC cannot tell which level was reached first. Keep the position
            # active and wait for a later unambiguous closed candle; do not
            # fabricate a STOPPED / TP outcome from an unknowable intrabar path.
            _event(db, trade, "AMBIGUOUS_BAR", close, candle_time, {
                "active_stop": stop, "next_target": next_target,
                "note": "Both levels were inside this candle. Trade remains OPEN until a later candle confirms SL or TP.",
            })
            continue
        if stop_hit:
            if trade.tp2_hit:
                locked_r = 0.3 * abs(float(trade.tp1) - float(trade.entry_price)) / max(float(trade.risk_distance or 0), 1e-12)
                trade.realized_r = round(float(trade.realized_r or 0) + locked_r, 6)
                trade.status = "LOCKED_PROFIT_EXIT"
                event_type = "LOCKED_STOP_HIT"
            elif trade.tp1_hit:
                trade.status = "PROTECTED_EXIT"
                event_type = "PROTECTED_STOP_HIT"
            else:
                trade.realized_r = -1.0
                trade.status = "STOPPED"
                event_type = "SL_HIT"
            trade.stopped_at = candle_time
            observed = op if _touches(trade.side, op, op, stop, False) else stop
            _event(db, trade, event_type, observed, candle_time, {
                "active_stop": stop, "realized_r": trade.realized_r,
                "tp1_hit": trade.tp1_hit, "tp2_hit": trade.tp2_hit,
            })
            break

        # If a bar reaches TP2/TP3, it necessarily crossed the earlier targets.
        # This is only accepted when the active stop was not also touched.
        targets = [(1, trade.tp1, 0.4), (2, trade.tp2, 0.3), (3, trade.tp3, 0.3)]
        for number, target, allocation in targets:
            flag = getattr(trade, f"tp{number}_hit")
            if flag or not _touches(trade.side, high, low, float(target), True):
                continue
            setattr(trade, f"tp{number}_hit", True)
            setattr(trade, f"tp{number}_at", candle_time)
            target_r = abs(float(target) - float(trade.entry_price)) / max(float(trade.risk_distance or 0), 1e-12)
            trade.realized_r = round(float(trade.realized_r or 0) + allocation * target_r, 6)
            observed = op if ((trade.side == "BUY" and op >= target) or (trade.side == "SELL" and op <= target)) else target
            if number == 1:
                trade.active_stop_loss = trade.entry_price
            elif number == 2:
                trade.active_stop_loss = trade.tp1
            else:
                trade.status = "TARGETS_COMPLETE"
            _event(db, trade, f"TP{number}_HIT", observed, candle_time, {
                "target": target, "partial_percent": (40 if number == 1 else 30),
                "realized_r": trade.realized_r,
                "next_target": trade.tp2 if number == 1 else trade.tp3 if number == 2 else None,
                "next_stop": trade.active_stop_loss,
            })
            if trade.status == "TARGETS_COMPLETE":
                break
        if trade.status == "TARGETS_COMPLETE":
            break

    trade.updated_at = datetime.now(timezone.utc)
    return processed


def trade_payload(trade: SignalTrade, events: list[SignalTradeEvent] | None = None) -> dict[str, Any]:
    def stamp(value):
        return as_utc(value).isoformat() if value else None
    return {
        "id": trade.id, "source": trade.source, "symbol": trade.symbol, "side": trade.side,
        "timeframe": trade.timeframe, "entry_type": trade.entry_type,
        "entry_price": trade.entry_price, "limit_price": trade.limit_price,
        "stop_loss": trade.stop_loss, "active_stop_loss": trade.active_stop_loss,
        "tp1": trade.tp1, "tp2": trade.tp2, "tp3": trade.tp3,
        "status": trade.status, "signal_time": stamp(trade.signal_time),
        "filled_at": stamp(trade.filled_at), "tp1_hit": trade.tp1_hit,
        "tp2_hit": trade.tp2_hit, "tp3_hit": trade.tp3_hit,
        "tp1_at": stamp(trade.tp1_at), "tp2_at": stamp(trade.tp2_at), "tp3_at": stamp(trade.tp3_at),
        "stopped_at": stamp(trade.stopped_at), "last_price": trade.last_price,
        "realized_r": trade.realized_r, "recovery_status": trade.recovery_status,
        "recovery_note": trade.recovery_note, "created_at": stamp(trade.created_at),
        "events": [{
            "event_type": event.event_type, "price": event.price,
            "created_at": stamp(event.created_at),
            "details": json.loads(event.details_json or "{}"),
        } for event in (events or [])],
    }


async def signal_lifecycle_worker() -> None:
    """Reconcile persisted signals against provider OHLC after startup and throughout the day."""
    from .signal_engine import fetch_candles_with_provider, closed_candles, MarketDataError
    last_fetch: dict[str, float] = {}
    cached_candles: dict[str, list[dict[str, Any]]] = {}
    while True:
        try:
            with SessionLocal() as db:
                active = list(db.scalars(select(SignalTrade).where(SignalTrade.status.in_(tuple(ACTIVE_STATES)))))
                symbols = sorted({trade.symbol for trade in active})
                now = asyncio.get_running_loop().time()
                for symbol in symbols:
                    if symbol not in cached_candles or now - last_fetch.get(symbol, 0) >= 30:
                        try:
                            candles, _provider = await fetch_candles_with_provider("1min", 3200, symbol)
                            cached_candles[symbol] = closed_candles(candles, "1min")
                            last_fetch[symbol] = now
                        except (MarketDataError, Exception) as exc:
                            logger.warning("Signal lifecycle feed unavailable for %s: %s", symbol, type(exc).__name__)
                            for trade in active:
                                if trade.symbol == symbol:
                                    trade.recovery_status = "UNAVAILABLE"
                                    trade.recovery_note = "Historical candle provider is unavailable; no outcome was guessed."
                            db.commit()
                            continue
                    for trade in active:
                        if trade.symbol != symbol or trade.status not in ACTIVE_STATES:
                            continue
                        previous_recovery = (trade.recovery_status, trade.recovery_note)
                        changed = process_trade_candles(db, trade, cached_candles[symbol])
                        recovery_changed = previous_recovery != (trade.recovery_status, trade.recovery_note)
                        if changed or recovery_changed:
                            db.commit()
                            event_hub.publish("signals.lifecycle.changed", "signal_trade", "reconciled", {
                                "trade_id": trade.id, "symbol": trade.symbol, "status": trade.status,
                            })
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Signal lifecycle worker cycle failed: %s", type(exc).__name__)
        await asyncio.sleep(15)
