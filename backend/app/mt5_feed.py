"""Read-only local MetaTrader 5 market-data bridge.

This module deliberately exposes quotes and OHLC candles only. It never imports
or calls order_send, positions management, account login, or trade APIs.
MetaTrader5 is an optional Windows-terminal dependency and is imported lazily.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import math
import os
from contextlib import contextmanager
from typing import Any
from .mt5_session import MT5_LOCK

TIMEFRAMES = {
    "1m": "TIMEFRAME_M1",
    "5m": "TIMEFRAME_M5",
    "15m": "TIMEFRAME_M15",
    "30m": "TIMEFRAME_M30",
    "1h": "TIMEFRAME_H1",
    "4h": "TIMEFRAME_H4",
}
DEFAULT_SYMBOL = os.getenv("QUANTNEX_MT5_GOLD_SYMBOL", "XAUUSD").strip().upper() or "XAUUSD"


class MT5FeedError(RuntimeError):
    """A local MT5 terminal or market-data operation is unavailable."""


def _mt5():
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise MT5FeedError(
            "MetaTrader 5 Python package is not installed. Install the official "
            "MetaTrader5 package in the QUANTNEX backend environment."
        ) from exc
    return mt5


def _initialize(mt5):
    path = os.getenv("QUANTNEX_MT5_TERMINAL_PATH", "").strip()
    ok = mt5.initialize(path=path) if path else mt5.initialize()
    if not ok:
        code, message = mt5.last_error()
        raise MT5FeedError(f"Could not connect to the local MT5 terminal ({code}: {message}).")
    return mt5


def _shutdown(mt5):
    try:
        mt5.shutdown()
    except Exception:
        pass


@contextmanager
def _feed_session():
    """Serialize feed calls and preserve a terminal session owned by the guardian."""
    with MT5_LOCK:
        mt5 = _mt5()
        try:
            already_initialized = mt5.terminal_info() is not None
        except Exception:
            already_initialized = False
        try:
            _initialize(mt5)
            yield mt5
        finally:
            # Do not shut down a terminal connection established by the
            # Prop Challenge Guardian (or another QUANTNEX MT5 owner).
            if not already_initialized:
                _shutdown(mt5)


def _symbol(mt5, symbol: str):
    normalized = str(symbol or DEFAULT_SYMBOL).strip().upper()
    if not normalized or len(normalized) > 32:
        raise MT5FeedError("Invalid MT5 symbol.")
    info = mt5.symbol_info(normalized)
    if info is None and not mt5.symbol_select(normalized, True):
        raise MT5FeedError(f"MT5 symbol {normalized} is unavailable. Check the broker's symbol name.")
    info = mt5.symbol_info(normalized)
    if info is None:
        raise MT5FeedError(f"MT5 symbol {normalized} is unavailable.")
    if not info.visible and not mt5.symbol_select(normalized, True):
        raise MT5FeedError(f"MT5 could not enable market watch for {normalized}.")
    return normalized


def _status_sync() -> dict[str, Any]:
    with _feed_session() as mt5:
        terminal = mt5.terminal_info()
        connected = bool(terminal and getattr(terminal, "connected", False))
        return {
            "provider": "MetaTrader 5 local terminal",
            "enabled": True,
            "connected": connected,
            "terminal_available": terminal is not None,
            "symbol": DEFAULT_SYMBOL,
            "mode": "read_only_market_data",
            "orders_enabled": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": "Connected to local MT5 terminal." if connected else "MT5 terminal is open but not connected to its trade server.",
        }


def _quote_sync(symbol: str) -> dict[str, Any]:
    with _feed_session() as mt5:
        normalized = _symbol(mt5, symbol)
        tick = mt5.symbol_info_tick(normalized)
        if tick is None:
            raise MT5FeedError(f"No MT5 tick is available for {normalized}.")
        stamp = datetime.fromtimestamp(int(tick.time), timezone.utc)
        bid, ask = float(tick.bid), float(tick.ask)
        last = float(getattr(tick, "last", 0.0) or 0.0)
        if not all(math.isfinite(x) and x > 0 for x in (bid, ask)) or ask < bid:
            raise MT5FeedError(f"MT5 returned an invalid bid/ask quote for {normalized}.")
        age = max(0.0, (datetime.now(timezone.utc) - stamp).total_seconds())
        return {
            "symbol": normalized, "bid": bid, "ask": ask, "last": last if last > 0 else None,
            "spread": ask - bid, "source_timestamp": stamp.isoformat(),
            "fetch_timestamp": datetime.now(timezone.utc).isoformat(),
            "age_seconds": round(age, 3), "stale": age > 30,
            "provider": "MetaTrader 5 local terminal",
            "note": "Broker quote for analysis only; not an executable order price.",
        }


def _candles_sync(symbol: str, interval: str, limit: int) -> list[dict[str, Any]]:
    if interval not in TIMEFRAMES:
        raise MT5FeedError("Supported MT5 timeframes: 1m, 5m, 15m, 30m, 1h and 4h.")
    if not 210 <= int(limit) <= 1000:
        raise MT5FeedError("Candle limit must be between 210 and 1000.")
    with _feed_session() as mt5:
        normalized = _symbol(mt5, symbol)
        timeframe = getattr(mt5, TIMEFRAMES[interval], None)
        if timeframe is None:
            raise MT5FeedError(f"MT5 does not expose timeframe {interval}.")
        rates = mt5.copy_rates_from_pos(normalized, timeframe, 0, int(limit))
        if rates is None or len(rates) < 210:
            raise MT5FeedError(
                f"MT5 returned fewer than 210 {normalized} {interval} candles. "
                "Load more history in the terminal and try again."
            )
        rows = []
        seen = set()
        for row in rates:
            try:
                stamp = datetime.fromtimestamp(int(row["time"]), timezone.utc)
                values = [float(row[key]) for key in ("open", "high", "low", "close")]
                if not all(math.isfinite(x) and x > 0 for x in values):
                    continue
                op, high, low, close = values
                if high < max(op, close, low) or low > min(op, close, high):
                    continue
                epoch = int(stamp.timestamp())
                if epoch in seen:
                    continue
                seen.add(epoch)
                rows.append({
                    "time": stamp.isoformat(), "open": op, "high": high,
                    "low": low, "close": close,
                    "volume": max(0.0, float(row.get("tick_volume", 0.0))) if isinstance(row, dict) else (max(0.0, float(row["tick_volume"])) if "tick_volume" in (getattr(getattr(row, "dtype", None), "names", None) or ()) else 0.0),
                })
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
        rows.sort(key=lambda item: item["time"])
        if len(rows) < 210:
            raise MT5FeedError(f"Only {len(rows)} valid {normalized} {interval} candles were received.")
        return rows[-int(limit):]


async def get_status() -> dict[str, Any]:
    return await asyncio.to_thread(_status_sync)


async def get_quote(symbol: str = DEFAULT_SYMBOL) -> dict[str, Any]:
    return await asyncio.to_thread(_quote_sync, symbol)


async def get_candles(symbol: str = DEFAULT_SYMBOL, interval: str = "15m", limit: int = 500) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_candles_sync, symbol, interval, limit)
