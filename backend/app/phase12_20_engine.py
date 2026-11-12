"""Phases 12–20: local paper-autopilot, risk, analytics and journal bridge.

All execution here is simulated. The worker only uses supported public market
quotes and the existing signal engine; it never connects to a broker or places
real orders. Automatic trading is OFF until the local owner explicitly enables it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from datetime import datetime, timezone
from statistics import mean
from typing import Any

import httpx
from sqlalchemy import select
from .database import SessionLocal
from .models import PaperTrade, PaperTradeEvent, Preference, User
from .events import event_hub

logger = logging.getLogger("quantnex.paper_engine")
DEFAULT_SETTINGS = {
    "enabled": False, "interval_seconds": 180,
    "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    "paper_equity": 10000.0, "risk_percent": 0.25,
    "max_daily_loss_percent": 2.0, "max_drawdown_percent": 5.0,
    "max_open_positions": 3, "min_score": 8,
}
SUPPORTED_AUTO_SYMBOLS = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
LEVERAGED_BASE = re.compile(r".*(?:UP|DOWN|BULL|BEAR|[3-5]L|[3-5]S)$", re.I)


def normalize_settings(raw: dict | None) -> dict:
    value = {**DEFAULT_SETTINGS, **(raw or {})}
    value["enabled"] = value.get("enabled") is True
    value["interval_seconds"] = int(max(60, min(3600, int(value.get("interval_seconds", 180)))))
    symbols = list(dict.fromkeys(str(x).upper().strip() for x in value.get("symbols", [])))
    if not symbols or any(x not in SUPPORTED_AUTO_SYMBOLS for x in symbols):
        raise ValueError("Automatic paper mode currently supports BTCUSDT, ETHUSDT and SOLUSDT only. Forex/Gold require verified contract sizing first.")
    value["symbols"] = symbols
    for key, low, high in [
        ("paper_equity", 100, 10000000),
        ("risk_percent", 0.05, 1.0),
        ("max_daily_loss_percent", 0.25, 10.0),
        ("max_drawdown_percent", 0.5, 25.0),
    ]:
        number = float(value.get(key, DEFAULT_SETTINGS[key]))
        if not math.isfinite(number) or not low <= number <= high:
            raise ValueError(f"{key} must be between {low} and {high}.")
        value[key] = number
    value["max_open_positions"] = int(value.get("max_open_positions", 3))
    if not 1 <= value["max_open_positions"] <= 10:
        raise ValueError("max_open_positions must be between 1 and 10.")
    value["min_score"] = int(value.get("min_score", 8))
    if not 8 <= value["min_score"] <= 10:
        raise ValueError("min_score must be between 8 and 10 for automatic paper mode.")
    return value


def risk_snapshot(trades: list[Any], settings: dict, now: datetime | None = None) -> dict:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    closed = sorted((t for t in trades if t.status == "CLOSED" and t.realized_pnl is not None),
                    key=lambda t: t.closed_at or t.created_at)
    today = now.date()
    today_pnl = sum(float(t.realized_pnl or 0) for t in closed
                    if (t.closed_at or t.created_at).date() == today)
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for trade in closed:
        cumulative += float(trade.realized_pnl or 0)
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
    equity = float(settings["paper_equity"]) + cumulative
    daily_limit = float(settings["paper_equity"]) * float(settings["max_daily_loss_percent"]) / 100
    drawdown_limit = float(settings["paper_equity"]) * float(settings["max_drawdown_percent"]) / 100
    open_count = sum(t.status == "OPEN" for t in trades)
    blocks = []
    if today_pnl <= -daily_limit:
        blocks.append("DAILY_LOSS_LIMIT")
    if max_drawdown >= drawdown_limit:
        blocks.append("MAX_DRAWDOWN_LIMIT")
    if open_count >= int(settings["max_open_positions"]):
        blocks.append("MAX_OPEN_POSITIONS")
    return {
        "paper_equity_estimate": round(equity, 2),
        "realized_pnl_today_utc": round(today_pnl, 2),
        "daily_loss_limit": round(daily_limit, 2),
        "max_drawdown_observed": round(max_drawdown, 2),
        "max_drawdown_limit": round(drawdown_limit, 2),
        "open_positions": open_count,
        "max_open_positions": int(settings["max_open_positions"]),
        "entry_allowed": not blocks,
        "blocks": blocks,
        "timezone": "UTC",
        "note": "Risk guard uses persisted paper-ledger realized P&L; it is not a broker balance or prop-firm guarantee.",
    }


def performance_metrics(trades: list[Any], starting_equity: float = 10000.0) -> dict:
    closed = sorted((t for t in trades if t.status == "CLOSED" and t.realized_pnl is not None),
                    key=lambda t: t.closed_at or t.created_at)
    values = [float(t.realized_pnl or 0) for t in closed]
    wins = [x for x in values if x > 0]
    losses = [x for x in values if x < 0]
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    equity = float(starting_equity)
    peak = equity
    max_dd = 0.0
    curve = [{"trade": 0, "equity": round(equity, 2)}]
    for index, pnl in enumerate(values, 1):
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        curve.append({"trade": index, "equity": round(equity, 2)})
    return {
        "mode": "PAPER ONLY",
        "closed_trades": len(values),
        "open_trades": sum(t.status == "OPEN" for t in trades),
        "wins": len(wins), "losses": len(losses),
        "breakeven": sum(x == 0 for x in values),
        "win_rate_percent": round(len(wins) / len(values) * 100, 2) if values else None,
        "gross_profit": round(gross_win, 2), "gross_loss": round(gross_loss, 2),
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss else (None if not gross_win else "INF"),
        "net_realized_pnl": round(sum(values), 2),
        "expectancy_per_trade": round(mean(values), 4) if values else None,
        "max_drawdown_amount": round(max_dd, 2),
        "max_drawdown_percent": round(max_dd / max(1.0, peak) * 100, 3),
        "equity_curve": curve,
        "warning": "Paper results only. Existing ledger has no historical fee/slippage fields; figures are recorded P&L, not fee-adjusted broker net P&L.",
    }


def walk_forward_slices(candles: list[dict], train_ratio: float = 0.7) -> tuple[list[dict], list[dict]]:
    if not 0.6 <= train_ratio <= 0.8:
        raise ValueError("Training ratio must be between 60% and 80%.")
    if len(candles) < 180:
        raise ValueError("At least 180 candles are required for separate warm-up, training and holdout windows.")
    split = int(len(candles) * train_ratio)
    if split < 80 or len(candles) - split < 60:
        raise ValueError("Not enough candles in training or holdout window.")
    return candles[:split], candles[split:]


async def discover_binance_spot_universe(limit: int = 1000) -> dict:
    limit = max(50, min(1000, int(limit)))
    url = "https://api.binance.com/api/v3/exchangeInfo"
    async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=5)) as client:
        response = await client.get(url)
        response.raise_for_status()
        payload = response.json()
    symbols = []
    for item in payload.get("symbols", []):
        base = str(item.get("baseAsset", "")).upper()
        if (item.get("status") != "TRADING" or item.get("quoteAsset") != "USDT"
                or item.get("isSpotTradingAllowed") is False
                or not base or LEVERAGED_BASE.fullmatch(base)):
            continue
        symbols.append({
            "symbol": item["symbol"], "base_asset": base, "quote_asset": "USDT",
            "status": "TRADING", "provider": "Binance Spot",
        })
    symbols.sort(key=lambda x: x["symbol"])
    return {
        "provider": "Binance Spot exchangeInfo",
        "count": len(symbols),
        "symbols": symbols[:limit],
        "complete_count": len(symbols),
        "truncated": len(symbols) > limit,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "note": "Exchange metadata only. This discovery list is not an execution universe; the autonomous signal worker currently trades only the three validated crypto symbols shown in its settings.",
    }


def _pref(db, user_id: int, key: str, default: str = "") -> str:
    row = db.scalar(select(Preference).where(Preference.user_id == user_id, Preference.key == key))
    return row.value if row else default


def _set_pref(db, user_id: int, key: str, value: str) -> None:
    row = db.scalar(select(Preference).where(Preference.user_id == user_id, Preference.key == key))
    if row is None:
        db.add(Preference(user_id=user_id, key=key, value=value))
    else:
        row.value = value


async def paper_autopilot_worker() -> None:
    """Opt-in local worker. Starts disabled and persists all state in local SQLite."""
    last_scan: dict[int, float] = {}
    while True:
        try:
            import time
            from .phase07_engine import get_quote, IntelligenceDataError
            from .phase10_engine import assess_quote
            from .signal_engine import build_signal, MarketDataError
            db = SessionLocal()
            try:
                users = list(db.scalars(select(User).order_by(User.id)))
                for user in users:
                    raw = _pref(db, user.id, "paper_autopilot_settings", "")
                    if not raw:
                        continue
                    try:
                        settings = normalize_settings(json.loads(raw))
                    except (ValueError, TypeError, json.JSONDecodeError):
                        _set_pref(db, user.id, "paper_autopilot_last_error", "Invalid saved paper engine settings.")
                        db.commit()
                        continue
                    if not settings["enabled"]:
                        continue
                    now_mono = time.monotonic()
                    if now_mono - last_scan.get(user.id, 0) < settings["interval_seconds"]:
                        continue
                    last_scan[user.id] = now_mono
                    trades = list(db.scalars(select(PaperTrade).where(PaperTrade.user_id == user.id)))
                    # Monitor only positions created by this worker; manual paper trades
                    # remain under the existing user-controlled close action.
                    auto_ids = {e.trade_id for e in db.scalars(select(PaperTradeEvent).where(
                        PaperTradeEvent.user_id == user.id, PaperTradeEvent.event_type == "AUTO_OPENED"))}
                    for position in [x for x in trades if x.id in auto_ids and x.status == "OPEN"]:
                        try:
                            quote = await get_quote(position.symbol)
                            health = assess_quote(quote)
                            if not health["trading_safe"]:
                                continue
                            price = float(quote["price"])
                            stop_hit = price <= position.stop_loss if position.side == "BUY" else price >= position.stop_loss
                            target_hit = price >= position.take_profit if position.side == "BUY" else price <= position.take_profit
                            if stop_hit or target_hit:
                                reason = "STOP_LOSS" if stop_hit else "TAKE_PROFIT"
                                pnl = (price - position.entry_price) * position.quantity * (1 if position.side == "BUY" else -1)
                                position.exit_price = price
                                position.realized_pnl = round(pnl, 8)
                                position.status = "CLOSED"
                                position.closed_at = datetime.now(timezone.utc)
                                db.add(PaperTradeEvent(user_id=user.id, trade_id=position.id,
                                    event_type=reason, price=price, quantity=position.quantity,
                                    pnl=position.realized_pnl, details_json=json.dumps({"provider": quote["provider"], "data_health": health})))
                                event_hub.publish("paper_trade.changed", "paper_trade", "auto_closed",
                                    {"trade_id": position.id, "symbol": position.symbol, "status": "CLOSED", "reason": reason})
                                db.commit()
                        except (IntelligenceDataError, httpx.HTTPError, ValueError, KeyError):
                            continue
                    trades = list(db.scalars(select(PaperTrade).where(PaperTrade.user_id == user.id)))
                    guard = risk_snapshot(trades, settings)
                    if not guard["entry_allowed"]:
                        _set_pref(db, user.id, "paper_autopilot_last_block", json.dumps(guard["blocks"]))
                        db.commit()
                        continue
                    signal_raw = _pref(db, user.id, "signal_settings",
                        '{"primary":"5","trend":"60","enabled":["60","30","15","5","1"],"risk_percent":1,"min_score":8}')
                    try:
                        signal_settings = json.loads(signal_raw)
                    except ValueError:
                        signal_settings = {"primary":"5","trend":"60","enabled":["60","30","15","5","1"],"risk_percent":1,"min_score":8}
                    signal_settings["min_score"] = settings["min_score"]
                    for symbol in settings["symbols"]:
                        if sum(x.status == "OPEN" for x in trades) >= settings["max_open_positions"]:
                            break
                        if any(x.symbol == symbol and x.status == "OPEN" for x in trades):
                            continue
                        try:
                            scan = await build_signal(signal_settings, symbol)
                            candidate = scan.get("signal")
                            if not candidate:
                                continue
                            fingerprint = "|".join([symbol, str(candidate.get("side")),
                                str(candidate.get("timeframe")), str(candidate.get("signal_candle_time"))])
                            if _pref(db, user.id, "paper_autopilot_fingerprint_" + symbol.lower()) == fingerprint:
                                continue
                            quote = await get_quote(symbol)
                            health = assess_quote(quote)
                            if not health["trading_safe"]:
                                continue
                            entry = float(quote["price"])
                            distance = float(candidate.get("risk_distance", 0))
                            if not math.isfinite(distance) or distance <= 0:
                                continue
                            # Reject late entries if the market has moved more than
                            # half the original stop distance since signal candle.
                            if abs(entry - float(candidate["entry"])) > distance * 0.5:
                                continue
                            side = candidate["side"]
                            stop = entry - distance if side == "BUY" else entry + distance
                            target = entry + distance * 3 if side == "BUY" else entry - distance * 3
                            current_equity = max(100.0, float(guard["paper_equity_estimate"]))
                            risk_cash = current_equity * settings["risk_percent"] / 100
                            quantity = risk_cash / distance
                            if not math.isfinite(quantity) or not 0 < quantity <= 1000000:
                                continue
                            if (side == "BUY" and not stop < entry < target) or (side == "SELL" and not target < entry < stop):
                                continue
                            item = PaperTrade(user_id=user.id, symbol=symbol, side=side, quantity=quantity,
                                entry_price=entry, stop_loss=stop, take_profit=target, status="OPEN")
                            db.add(item)
                            db.flush()
                            db.add(PaperTradeEvent(user_id=user.id, trade_id=item.id, event_type="AUTO_OPENED",
                                price=entry, quantity=quantity, pnl=0.0,
                                details_json=json.dumps({"provider": quote["provider"], "signal": candidate,
                                    "data_health": health, "risk_cash": risk_cash, "mode": "PAPER"})))
                            _set_pref(db, user.id, "paper_autopilot_fingerprint_" + symbol.lower(), fingerprint)
                            _set_pref(db, user.id, "paper_autopilot_last_error", "")
                            record = {"trade_id": item.id, "symbol": symbol, "side": side, "entry": entry,
                                      "stop_loss": stop, "take_profit": target, "quantity": quantity}
                            db.commit()
                            event_hub.publish("paper_trade.changed", "paper_trade", "auto_opened", record)
                            trades.append(item)
                        except (MarketDataError, IntelligenceDataError, httpx.HTTPError, ValueError, KeyError) as exc:
                            _set_pref(db, user.id, "paper_autopilot_last_error", type(exc).__name__)
                            db.commit()
                            continue
            finally:
                db.close()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Paper autopilot cycle failed: %s", type(exc).__name__)
        await asyncio.sleep(5)
