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
        now = int(datetime.now(timezone.utc).timestamp()) - count * 60
        data = []
        for i in range(count):
            price = 2300 + i * 0.01
            data.append({"time": now + i * 60, "open": price, "high": price + 0.2,
                         "low": price - 0.2, "close": price + 0.05, "tick_volume": 100})
        return data


def test_mt5_status_is_explicitly_read_only(monkeypatch):
    fake = FakeMT5()
    monkeypatch.setattr(feed, "_mt5", lambda: fake)
    result = asyncio.run(feed.get_status())
    assert result["connected"] is True
    assert result["mode"] == "read_only_market_data"
    assert result["orders_enabled"] is False
    # A feed read must not close a terminal session already owned by another service.
    assert fake.stopped is False


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
    assert rows[0]["volume"] == 100


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



def test_signal_engine_uses_mt5_when_explicitly_enabled(monkeypatch):
    import app.signal_engine as signal_engine
    import app.mt5_feed as mt5_feed

    async def fake_candles(symbol, interval, limit):
        assert symbol == "XAUUSD.a"
        assert interval == "15m"
        assert limit == 250
        return [{"time": "2026-01-01T00:00:00+00:00", "open": 1, "high": 2,
                 "low": 0.5, "close": 1.5, "volume": 12}]

    monkeypatch.setattr(signal_engine, "QUANTNEX_MT5_ENABLED", True)
    monkeypatch.setattr(signal_engine, "QUANTNEX_MT5_GOLD_SYMBOL", "XAUUSD.a")
    monkeypatch.setattr(mt5_feed, "get_candles", fake_candles)
    rows = asyncio.run(signal_engine.fetch_candles("15min", 250, "XAUUSD"))
    assert rows[0]["close"] == 1.5


def test_mt5_api_routes_expose_read_only_contract(monkeypatch):
    from fastapi.testclient import TestClient
    import app.mt5_feed as mt5_feed
    from app.main import app

    async def status():
        return {"connected": True, "mode": "read_only_market_data", "orders_enabled": False}

    async def quote(symbol):
        return {"symbol": symbol, "bid": 2300.1, "ask": 2300.2, "stale": False}

    async def candles(symbol, interval, limit):
        return [{"time": "2026-01-01T00:00:00+00:00", "open": 1, "high": 2,
                 "low": 0.5, "close": 1.5, "volume": 10}] * 210

    monkeypatch.setattr(mt5_feed, "get_status", status)
    monkeypatch.setattr(mt5_feed, "get_quote", quote)
    monkeypatch.setattr(mt5_feed, "get_candles", candles)
    client = TestClient(app)
    assert client.get("/api/v1/market/mt5/status").json()["orders_enabled"] is False
    assert client.get("/api/v1/market/mt5/quote?symbol=XAUUSD").json()["bid"] == 2300.1
    result = client.get("/api/v1/market/mt5/candles?symbol=XAUUSD&interval=15m&limit=500")
    assert result.status_code == 200
    assert result.json()["mode"] == "read_only_market_data"
    assert result.json()["orders_enabled"] is False
    assert result.json()["count"] == 210

def test_mt5_feed_closes_only_a_session_it_initialized(monkeypatch):
    class ColdMT5(FakeMT5):
        def __init__(self):
            super().__init__()
            self.initialized = False

        def initialize(self, **kwargs):
            self.initialized = True
            return True

        def terminal_info(self):
            return SimpleNamespace(connected=True) if self.initialized else None

    fake = ColdMT5()
    monkeypatch.setattr(feed, "_mt5", lambda: fake)
    asyncio.run(feed.get_status())
    assert fake.stopped is True


def test_mt5_feed_and_prop_guardian_share_the_same_terminal_lock():
    from app import prop_challenge

    assert prop_challenge.MT5_LOCK is feed.MT5_LOCK
