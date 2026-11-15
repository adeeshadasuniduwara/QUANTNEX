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
        ("BUY", "BUY", "XAUUSD", "MetaTrader 5 local terminal"),
        ("SELL", "SELL", "XAUUSD", "Twelve Data"),
    ],
)
def test_real_signal_pipeline_generates_and_delivers_synthetic_setup(monkeypatch, direction, expected_side, symbol, provider):
    now = datetime.now(timezone.utc)

    async def fake_fetch(interval, _outputsize, _symbol):
        return _synthetic_setup(direction, interval, now), provider

    monkeypatch.setattr(signal_engine, "fetch_candles_with_provider", fake_fetch)
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

    monkeypatch.setattr(signal_engine, "fetch_candles_with_provider", fake_fetch)
    settings = {
        "primary": "5",
        "trend": "60",
        "enabled": ["60", "30", "15", "5", "1"],
        "min_score": 8,
    }
    result = asyncio.run(signal_engine.build_signal(settings, "BTCUSDT"))
    assert result["status"] == "SIGNAL"
    assert result["provider"] == "Binance Spot + Coinbase Exchange fallback"
