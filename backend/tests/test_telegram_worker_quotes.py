import asyncio
from datetime import datetime, timedelta, timezone

from app import mt5_feed, phase07_engine, telegram_worker


def test_telegram_gold_level_price_prefers_fresh_mt5_tick(monkeypatch):
    monkeypatch.setattr(telegram_worker, "QUANTNEX_MT5_ENABLED", True)
    monkeypatch.setattr(telegram_worker, "TWELVE_DATA_API_KEY", "")

    async def fresh_quote(symbol):
        assert symbol == telegram_worker.QUANTNEX_MT5_GOLD_SYMBOL
        return {
            "bid": 2300.0, "ask": 2301.0, "last": 2300.5,
            "age_seconds": 2.0, "stale": False,
        }

    monkeypatch.setattr(mt5_feed, "get_quote", fresh_quote)
    assert asyncio.run(telegram_worker._price()) == 2300.5


def test_telegram_gold_level_price_falls_back_to_fresh_twelve_data(monkeypatch):
    monkeypatch.setattr(telegram_worker, "QUANTNEX_MT5_ENABLED", True)
    monkeypatch.setattr(telegram_worker, "TWELVE_DATA_API_KEY", "test-key")

    async def stale_mt5_quote(_symbol):
        return {
            "bid": 2299.0, "ask": 2300.0, "last": 2299.5,
            "age_seconds": 90.0, "stale": True,
        }

    async def fresh_twelve_data_quote(symbol):
        assert symbol == "XAUUSD"
        stamp = datetime.now(timezone.utc).isoformat()
        return {
            "symbol": "XAUUSD", "kind": "gold", "price": 2302.25,
            "provider": "Twelve Data", "source_timestamp": stamp, "timestamp": stamp,
        }

    monkeypatch.setattr(mt5_feed, "get_quote", stale_mt5_quote)
    monkeypatch.setattr(phase07_engine, "get_quote", fresh_twelve_data_quote)
    assert asyncio.run(telegram_worker._price()) == 2302.25


def test_telegram_gold_level_price_rejects_stale_mt5_without_fallback(monkeypatch):
    monkeypatch.setattr(telegram_worker, "QUANTNEX_MT5_ENABLED", True)
    monkeypatch.setattr(telegram_worker, "TWELVE_DATA_API_KEY", "")

    async def stale_quote(_symbol):
        return {
            "bid": 2300.0, "ask": 2301.0, "last": 2300.5,
            "age_seconds": 120.0, "stale": True,
        }

    monkeypatch.setattr(mt5_feed, "get_quote", stale_quote)
    assert asyncio.run(telegram_worker._price()) is None


def test_telegram_gold_level_price_rejects_stale_twelve_data(monkeypatch):
    monkeypatch.setattr(telegram_worker, "QUANTNEX_MT5_ENABLED", False)
    monkeypatch.setattr(telegram_worker, "TWELVE_DATA_API_KEY", "test-key")

    async def stale_twelve_data_quote(_symbol):
        stamp = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        return {
            "symbol": "XAUUSD", "kind": "gold", "price": 2302.25,
            "provider": "Twelve Data", "source_timestamp": stamp, "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    monkeypatch.setattr(phase07_engine, "get_quote", stale_twelve_data_quote)
    assert asyncio.run(telegram_worker._price()) is None


def test_telegram_gold_level_price_falls_back_when_mt5_connection_fails(monkeypatch):
    monkeypatch.setattr(telegram_worker, "QUANTNEX_MT5_ENABLED", True)
    monkeypatch.setattr(telegram_worker, "TWELVE_DATA_API_KEY", "test-key")

    async def unavailable_mt5_quote(_symbol):
        raise mt5_feed.MT5FeedError("terminal is not connected")

    async def fresh_twelve_data_quote(_symbol):
        stamp = datetime.now(timezone.utc).isoformat()
        return {
            "symbol": "XAUUSD", "kind": "gold", "price": 2303.5,
            "provider": "Twelve Data", "source_timestamp": stamp, "timestamp": stamp,
        }

    monkeypatch.setattr(mt5_feed, "get_quote", unavailable_mt5_quote)
    monkeypatch.setattr(phase07_engine, "get_quote", fresh_twelve_data_quote)
    assert asyncio.run(telegram_worker._price()) == 2303.5
