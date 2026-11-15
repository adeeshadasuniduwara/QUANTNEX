import asyncio
import math
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import signal_engine, telegram_worker
from app.database import Base
from app.models import User


def _synthetic_setup(direction: str, interval: str, now: datetime):
    rows = []
    for index in range(320):
        if direction == "BUY":
            close = 100 + 0.035 * index + 0.45 * math.sin(index * 0.42)
            previous = (100 + 0.035 * (index - 1) + 0.45 * math.sin((index - 1) * 0.42)
                        if index else close - 0.02)
        else:
            close = 150 - 0.035 * index - 0.45 * math.sin(index * 0.42)
            previous = (150 - 0.035 * (index - 1) - 0.45 * math.sin((index - 1) * 0.42)
                        if index else close + 0.02)
        open_price = previous
        rows.append({
            "open": open_price,
            "high": max(open_price, close) + 0.08,
            "low": min(open_price, close) - 0.08,
            "close": close,
        })

    pivots = signal_engine.structure(rows)
    if direction == "BUY":
        swing_high, swing_low = pivots["swing_high"], pivots["swing_low"]
        rows[-2]["close"] = swing_high - 0.10
        rows[-2]["open"] = rows[-3]["close"]
        rows[-2]["high"] = max(rows[-2]["open"], rows[-2]["close"]) + 0.08
        rows[-2]["low"] = min(rows[-2]["open"], rows[-2]["close"]) - 0.08
        rows[-1]["open"] = rows[-2]["close"]
        rows[-1]["close"] = swing_high + 0.10
        rows[-1]["high"] = rows[-1]["close"] + 0.08
        rows[-1]["low"] = swing_low - 0.20
    else:
        swing_high, swing_low = pivots["swing_high"], pivots["swing_low"]
        rows[-2]["close"] = swing_low + 0.10
        rows[-2]["open"] = rows[-3]["close"]
        rows[-2]["high"] = max(rows[-2]["open"], rows[-2]["close"]) + 0.08
        rows[-2]["low"] = min(rows[-2]["open"], rows[-2]["close"]) - 0.08
        rows[-1]["open"] = rows[-2]["close"]
        rows[-1]["close"] = swing_low - 0.10
        rows[-1]["low"] = rows[-1]["close"] - 0.08
        rows[-1]["high"] = swing_high + 0.20

    seconds = signal_engine.INTERVAL_SECONDS[interval]
    last_open = now - timedelta(seconds=seconds + 30)
    first_open = last_open - timedelta(seconds=seconds * (len(rows) - 1))
    for index, row in enumerate(rows):
        row["time"] = (first_open + timedelta(seconds=seconds * index)).isoformat()
    return rows


@pytest.mark.parametrize(
    ("direction", "expected_side", "symbol", "provider"),
    [
        ("BUY", "BUY", "BTCUSDT", "Binance Spot"),
        ("SELL", "SELL", "BTCUSDT", "Coinbase Exchange fallback"),
        ("BUY", "BUY", "1000PEPEUSDT", "Binance Spot"),
        ("BUY", "BUY", "XAUUSD", "MetaTrader 5 local terminal"),
        ("SELL", "SELL", "XAUUSD", "Twelve Data"),
    ],
)
def test_real_signal_pipeline_generates_and_delivers_synthetic_setup(monkeypatch, direction, expected_side, symbol, provider):
    now = datetime.now(timezone.utc)

    async def fake_fetch(interval, _outputsize, _symbol):
        return _synthetic_setup(direction, interval, now), provider

    async def fake_execution(_symbol):
        close = _synthetic_setup(direction, "5min", now)[-1]["close"]
        return {
            "best_bid": close - 0.005, "best_ask": close + 0.005, "mid_price": close,
            "spread_bps": 0.9, "bid_depth_quote": 20000.0, "ask_depth_quote": 20000.0,
            "tick_size": "0.01", "step_size": "0.001", "min_quantity": "0.001",
            "min_notional": "5", "observed_at": now.isoformat(), "provider": "Binance Spot",
        }

    async def fake_valid_symbol(symbol):
        return symbol in {"BTCUSDT", "1000PEPEUSDT"}

    monkeypatch.setattr(signal_engine, "is_binance_spot_symbol", fake_valid_symbol)
    monkeypatch.setattr(signal_engine, "fetch_candles_with_provider", fake_fetch)
    monkeypatch.setattr(signal_engine, "get_binance_spot_execution_context", fake_execution)
    settings = {
        "primary": "5",
        "trend": "60",
        "enabled": ["60", "30", "15", "5", "1"],
        "min_score": 8,
    }
    result = asyncio.run(signal_engine.build_signal(settings, symbol))
    candidate = result["signal"]

    assert result["status"] == "SIGNAL"
    assert result["provider"] == provider
    assert candidate is not None
    assert candidate["side"] == expected_side
    assert candidate["score"] >= 8
    assert candidate["signal_candle_time"]
    assert all(result["quality_filters"].values())
    if symbol != "XAUUSD":
        assert candidate["entry_type"] == "MARKET"
        assert candidate["market_type"] == "BINANCE_SPOT"
        assert candidate["execution_quality"]["accepted"] is True

    if expected_side == "BUY":
        assert 0 < candidate["stop_loss"] < candidate["entry"] < candidate["tp1"] < candidate["tp2"] < candidate["tp3"]
    else:
        assert 0 < candidate["tp3"] < candidate["tp2"] < candidate["tp1"] < candidate["entry"] < candidate["stop_loss"]

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    user = User(email=f"signal-{direction.lower()}-{symbol.lower()}@example.test", password_hash="test-hash")
    db.add(user)
    db.commit()
    user_id = user.id
    calls = []

    async def fake_telegram_send(_client, _token, _chat_id, message):
        calls.append(message)
        return {"ok": True, "result": {"message_id": 987}}

    monkeypatch.setattr(telegram_worker, "_send", fake_telegram_send)
    key = "auto_signal_last_fingerprint_" + symbol.lower()
    fingerprint = telegram_worker._auto_signal_fingerprint(symbol, candidate)
    assert fingerprint
    previous = telegram_worker._get(db, user_id, key)
    assert asyncio.run(telegram_worker._deliver_auto_signal(
        None, "fake-token", "fake-chat", "synthetic signal", fingerprint, previous, db, user_id, key
    )) is True
    db.commit()
    assert len(calls) == 1
    assert telegram_worker._get(db, user_id, key) == fingerprint

    db.close()
    reopened = factory()
    previous_after_restart = telegram_worker._get(reopened, user_id, key)
    assert previous_after_restart == fingerprint
    assert asyncio.run(telegram_worker._deliver_auto_signal(
        None, "fake-token", "fake-chat", "duplicate synthetic signal",
        fingerprint, previous_after_restart, reopened, user_id, key
    )) is False
    assert len(calls) == 1

    reopened.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_signal_reports_all_sources_when_timeframes_use_mixed_providers(monkeypatch):
    now = datetime.now(timezone.utc)

    async def fake_fetch(interval, _outputsize, _symbol):
        provider = "Coinbase Exchange fallback" if interval == "1h" else "Binance Spot"
        return _synthetic_setup("BUY", interval, now), provider

    async def fake_execution(_symbol):
        close = _synthetic_setup("BUY", "5min", now)[-1]["close"]
        return {
            "best_bid": close - 0.005, "best_ask": close + 0.005, "mid_price": close,
            "spread_bps": 0.9, "bid_depth_quote": 20000.0, "ask_depth_quote": 20000.0,
            "tick_size": "0.01", "step_size": "0.001", "min_quantity": "0.001",
            "min_notional": "5", "observed_at": now.isoformat(), "provider": "Binance Spot",
        }

    monkeypatch.setattr(signal_engine, "fetch_candles_with_provider", fake_fetch)
    monkeypatch.setattr(signal_engine, "get_binance_spot_execution_context", fake_execution)
    settings = {
        "primary": "5",
        "trend": "60",
        "enabled": ["60", "30", "15", "5", "1"],
        "min_score": 8,
    }
    result = asyncio.run(signal_engine.build_signal(settings, "BTCUSDT"))
    assert result["status"] == "SIGNAL"
    assert result["provider"] == "Binance Spot + Coinbase Exchange fallback"


def test_signal_reports_combined_provider_sources_for_mixed_timeframes(monkeypatch):
    now = datetime.now(timezone.utc)

    async def fake_fetch(interval, _outputsize, _symbol):
        provider = "Coinbase Exchange fallback" if interval == "1h" else "Binance Spot"
        return _synthetic_setup("BUY", interval, now), provider

    async def fake_execution(_symbol):
        close = _synthetic_setup("BUY", "5min", now)[-1]["close"]
        return {
            "best_bid": close - 0.005, "best_ask": close + 0.005, "mid_price": close,
            "spread_bps": 0.9, "bid_depth_quote": 20000.0, "ask_depth_quote": 20000.0,
            "tick_size": "0.01", "step_size": "0.001", "min_quantity": "0.001",
            "min_notional": "5", "observed_at": now.isoformat(), "provider": "Binance Spot",
        }

    monkeypatch.setattr(signal_engine, "fetch_candles_with_provider", fake_fetch)
    monkeypatch.setattr(signal_engine, "get_binance_spot_execution_context", fake_execution)
    settings = {
        "primary": "5",
        "trend": "60",
        "enabled": ["60", "30", "15", "5", "1"],
        "min_score": 8,
    }
    result = asyncio.run(signal_engine.build_signal(settings, "BTCUSDT"))
    assert result["status"] == "SIGNAL"
    assert result["provider"] == "Binance Spot + Coinbase Exchange fallback"


def test_real_signal_pipeline_generates_a_resting_limit_at_ob_zone(monkeypatch):
    now = datetime.now(timezone.utc)

    async def fake_fetch(interval, _outputsize, _symbol):
        return _synthetic_setup("BUY", interval, now), "Binance Spot"

    zone = {"low": 101.0, "high": 101.2}
    structure = {
        "bos_mss": "BULLISH", "liquidity_sweep": "BULLISH",
        "bullish_fvg": zone, "bullish_order_block": None,
        "bullish_breaker_block": None, "bullish_ifvg": None,
        "bearish_fvg": None, "bearish_order_block": None,
        "bearish_breaker_block": None, "bearish_ifvg": None,
        "premium_discount": "DISCOUNT", "swing_low": 99.0, "swing_high": 105.0,
    }

    def bullish_analysis(_rows):
        return {
            "bias": "BULLISH", "close": 100.0, "ema20": 99.8, "ema50": 99.5,
            "ema200": 99.0, "macd_histogram": 0.2, "rsi": 55.0, "adx": 25.0,
            "atr": 2.0, "structure": structure,
        }

    async def fake_execution(_symbol):
        return {
            "best_bid": 102.0, "best_ask": 102.02, "mid_price": 102.01,
            "spread_bps": 2.0, "bid_depth_quote": 2000.0, "ask_depth_quote": 2000.0,
            "tick_size": "0.01", "step_size": "0.001", "min_quantity": "0.001",
            "min_notional": "5", "observed_at": now.isoformat(), "provider": "Binance Spot",
        }

    monkeypatch.setattr(signal_engine, "fetch_candles_with_provider", fake_fetch)
    monkeypatch.setattr(signal_engine, "inspect_tf", bullish_analysis)
    monkeypatch.setattr(signal_engine, "get_binance_spot_execution_context", fake_execution)
    settings = {"primary": "5", "trend": "60", "enabled": ["60", "30", "15", "5", "1"], "min_score": 8}
    result = asyncio.run(signal_engine.build_signal(settings, "BTCUSDT"))
    signal = result["signal"]

    assert result["status"] == "SIGNAL"
    assert signal is not None
    assert signal["entry_type"] == "LIMIT"
    assert signal["limit_price"] == signal["entry"]
    assert signal["entry"] < 102.02
    assert signal["entry_expires_at"]
    assert "zone midpoint" in signal["entry_selection_reason"]
    assert signal["execution_quality"]["accepted"] is True
