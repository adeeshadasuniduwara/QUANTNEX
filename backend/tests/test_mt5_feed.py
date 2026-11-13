import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import app.mt5_feed as feed


class FakeMT5:
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_M30 = 30
    TIMEFRAME_H1 = 60
    TIMEFRAME_H4 = 240

    def __init__(self):
        self.stopped = False

    def initialize(self, **kwargs):
        return True

    def shutdown(self):
        self.stopped = True

    def last_error(self):
        return (0, "ok")

    def terminal_info(self):
        return SimpleNamespace(connected=True)

    def symbol_info(self, symbol):
        return SimpleNamespace(visible=True)

    def symbol_select(self, symbol, enabled):
        return True

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(time=int(datetime.now(timezone.utc).timestamp()), bid=2300.1, ask=2300.3, last=2300.2)

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        import numpy as np
        dtype = [("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"),
                 ("close", "f8"), ("tick_volume", "i8")]
        now = int(datetime.now(timezone.utc).timestamp()) - count * 60
        data = np.zeros(count, dtype=dtype)
        for i in range(count):
            price = 2300 + i * 0.01
            data[i] = (now + i * 60, price, price + 0.2, price - 0.2, price + 0.05, 100)
        return data


def test_mt5_status_is_explicitly_read_only(monkeypatch):
    fake = FakeMT5()
    monkeypatch.setattr(feed, "_mt5", lambda: fake)
    result = asyncio.run(feed.get_status())
    assert result["connected"] is True
    assert result["mode"] == "read_only_market_data"
    assert result["orders_enabled"] is False


def test_mt5_quote_has_bid_ask_and_freshness(monkeypatch):
    fake = FakeMT5()
    monkeypatch.setattr(feed, "_mt5", lambda: fake)
    result = asyncio.run(feed.get_quote("XAUUSD"))
    assert result["bid"] == 2300.1
    assert result["ask"] == 2300.3
    assert result["stale"] is False


def test_mt5_candles_are_normalized_and_sorted(monkeypatch):
    fake = FakeMT5()
    monkeypatch.setattr(feed, "_mt5", lambda: fake)
    rows = asyncio.run(feed.get_candles("XAUUSD", "1m", 220))
    assert len(rows) == 220
    assert rows[0]["time"] < rows[-1]["time"]
    assert set(("open", "high", "low", "close", "volume")) <= set(rows[0])


def test_mt5_rejects_unsupported_timeframe():
    with pytest.raises(feed.MT5FeedError, match="Supported MT5 timeframes"):
        asyncio.run(feed.get_candles("XAUUSD", "2m", 220))


def test_mt5_rejects_too_few_candles():
    with pytest.raises(feed.MT5FeedError, match="between 210 and 1000"):
        asyncio.run(feed.get_candles("XAUUSD", "15m", 100))


def test_mt5_import_failure_is_actionable(monkeypatch):
    def missing():
        raise feed.MT5FeedError("MetaTrader 5 Python package is not installed.")
    monkeypatch.setattr(feed, "_mt5", missing)
    with pytest.raises(feed.MT5FeedError, match="not installed"):
        asyncio.run(feed.get_status())
