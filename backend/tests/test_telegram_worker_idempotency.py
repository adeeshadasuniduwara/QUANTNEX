import asyncio
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import User
from app import telegram_worker


def _memory_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    user = User(email="signals@example.test", password_hash="test-hash")
    db.add(user)
    db.commit()
    return engine, factory, db, user.id


def test_auto_signal_fingerprint_changes_only_for_a_new_signal_candle():
    candidate = {
        "side": "BUY",
        "timeframe": "5",
        "signal_candle_time": "2026-11-16T12:00:00+00:00",
        "entry": 100.0,
        "stop_loss": 99.0,
        "tp1": 101.0,
    }
    first = telegram_worker._auto_signal_fingerprint("btcusdt", candidate)
    revised_levels_same_candle = telegram_worker._auto_signal_fingerprint(
        "BTCUSDT", {**candidate, "entry": 100.2, "stop_loss": 99.2}
    )
    next_candle = telegram_worker._auto_signal_fingerprint(
        "BTCUSDT", {**candidate, "signal_candle_time": "2026-11-16T12:05:00+00:00"}
    )
    assert first == revised_levels_same_candle
    assert telegram_worker._should_send_auto_signal(first, "") is True
    assert telegram_worker._should_send_auto_signal(first, first) is False
    assert telegram_worker._should_send_auto_signal(next_candle, first) is True
    assert telegram_worker._auto_signal_fingerprint("BTCUSDT", None) == ""


def test_auto_signal_fingerprint_persists_and_suppresses_duplicate_after_restart(monkeypatch):
    engine, factory, db, user_id = _memory_session()
    calls = []

    async def fake_send(_client, _token, _chat_id, message):
        calls.append(message)
        return {"message_id": 123}

    monkeypatch.setattr(telegram_worker, "_send", fake_send)
    key = "auto_signal_last_fingerprint_btcusdt"
    fingerprint = "BTCUSDT|BUY|5|2026-11-16T12:00:00+00:00"

    assert asyncio.run(telegram_worker._deliver_auto_signal(
        None, "token", "chat", "signal message", fingerprint, "", db, user_id, key
    )) is True
    db.commit()
    assert len(calls) == 1

    db.close()
    reopened = factory()
    previous = telegram_worker._get(reopened, user_id, key)
    assert previous == fingerprint
    assert asyncio.run(telegram_worker._deliver_auto_signal(
        None, "token", "chat", "duplicate message", fingerprint, previous, reopened, user_id, key
    )) is False
    reopened.commit()
    assert len(calls) == 1
    reopened.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_failed_auto_signal_send_does_not_mark_fingerprint_as_delivered(monkeypatch):
    engine, _factory, db, user_id = _memory_session()
    key = "auto_signal_last_fingerprint_ethusdt"
    fingerprint = "ETHUSDT|SELL|15|2026-11-16T12:00:00+00:00"

    async def fail_send(*_args):
        raise httpx.ConnectError("simulated Telegram network failure")

    monkeypatch.setattr(telegram_worker, "_send", fail_send)
    with pytest.raises(httpx.ConnectError):
        asyncio.run(telegram_worker._deliver_auto_signal(
            None, "token", "chat", "signal message", fingerprint, "", db, user_id, key
        ))
    db.commit()
    assert telegram_worker._get(db, user_id, key) == ""
    db.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_telegram_outbound_rate_limit_applies_per_chat_and_globally(monkeypatch):
    clock = [100.0]
    sleeps = []

    def fake_monotonic():
        return clock[0]

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(telegram_worker.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(telegram_worker.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(telegram_worker, "_TELEGRAM_CHAT_LOCKS", {})
    monkeypatch.setattr(telegram_worker, "_TELEGRAM_CHAT_LAST_SENT", {})
    monkeypatch.setattr(telegram_worker, "_TELEGRAM_GLOBAL_LOCK", asyncio.Lock())
    monkeypatch.setattr(telegram_worker, "_TELEGRAM_GLOBAL_LAST_SENT", 0.0)

    async def run():
        await telegram_worker._wait_telegram_rate_limit("chat-a")
        await telegram_worker._wait_telegram_rate_limit("chat-a")
        await telegram_worker._wait_telegram_rate_limit("chat-b")

    asyncio.run(run())
    assert any(delay >= 1.19 for delay in sleeps)
    assert any(0 < delay <= 0.05 for delay in sleeps)


def test_send_does_not_issue_extra_typing_action(monkeypatch):
    methods = []

    async def fake_post(_client, _token, method, payload):
        methods.append((method, payload))
        return {"message_id": 321}

    monkeypatch.setattr(telegram_worker, "_telegram_post", fake_post)
    result = asyncio.run(telegram_worker._send(None, "token", "chat-a", "hello"))
    assert result["message_id"] == 321
    assert [method for method, _payload in methods] == ["sendMessage"]


def test_legacy_stopped_status_is_presented_as_stop_loss_hit():
    assert telegram_worker._normalise_outcome_status("STOPPED") == "SL_HIT"
    assert telegram_worker._normalise_outcome_status("SL_HIT") == "SL_HIT"
    assert telegram_worker._normalise_outcome_status("OPEN") == "OPEN"


def test_signal_card_uses_branded_readable_levels_and_risk_footer():
    trade = SimpleNamespace(
        last_price=101.0, entry_price=100.0, risk_distance=5.0, stop_loss=95.0,
        active_stop_loss=100.0, side="BUY", status="OPEN", realized_r=0.0,
        symbol="BTCUSDT", tp1=105.0, tp2=110.0, tp3=115.0,
        tp1_hit=True, tp2_hit=False, tp3_hit=False,
    )
    message = telegram_worker._signal_live_message(trade)
    assert "QUANTNEX BOT SIGNAL" in message
    assert "Entry :" in message
    assert "TP 1 :" in message
    assert "TP 2 :" in message
    assert "All TP :" in message
    assert "Stop Loss :" in message
    assert "Risk management is the key" in message
    formatted = telegram_worker._format_telegram_message(message)
    assert "<b>Entry :</b>" in formatted
    assert "<b>Stop Loss :</b>" in formatted


def test_first_connection_signal_watermark_excludes_existing_trade_backlog(monkeypatch):
    from datetime import datetime, timezone
    from app.signal_lifecycle import record_signal

    engine, _factory, db, user_id = _memory_session()
    now = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
    trade, _ = record_signal(db, user_id, {
        "symbol": "BTCUSDT", "side": "BUY", "timeframe": "1m",
        "entry": 100, "stop_loss": 95, "tp1": 105, "tp2": 110, "tp3": 115,
        "signal_time": now.isoformat(),
    })
    telegram_worker._set(db, user_id, "telegram_signal_start_after_id", str(trade.id))
    db.commit()
    sent = []

    async def fake_send(_client, _token, _chat_id, message):
        sent.append(message)
        return {"message_id": 1}

    monkeypatch.setattr(telegram_worker, "_send", fake_send)
    asyncio.run(telegram_worker._sync_signal_trade_messages(None, db, user_id, "token", "chat"))
    assert sent == []
    db.close()
    Base.metadata.drop_all(engine)
    engine.dispose()



def test_telegram_pause_and_resume_skip_paused_signal_backlog(monkeypatch):
    from datetime import datetime, timezone
    from app.signal_lifecycle import record_signal

    engine, _factory, db, user_id = _memory_session()
    now = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
    trade, _ = record_signal(db, user_id, {
        "symbol": "BTCUSDT", "side": "BUY", "timeframe": "1m",
        "entry": 100, "stop_loss": 95, "tp1": 105, "tp2": 110, "tp3": 115,
        "signal_time": now.isoformat(),
    }, source="QUANTNEX_VIEW")
    db.commit()

    paused = asyncio.run(telegram_worker._handle_command(
        None, db, user_id, "token", "chat", "/pause"
    ))
    assert "PAUSED" in paused
    assert telegram_worker._get(db, user_id, "telegram_notifications_paused") == "true"

    resumed = asyncio.run(telegram_worker._handle_command(
        None, db, user_id, "token", "chat", "/resume"
    ))
    assert "RESUMED" in resumed
    assert telegram_worker._get(db, user_id, "telegram_notifications_paused") == "false"
    assert telegram_worker._get(db, user_id, "telegram_signal_start_after_id") == str(trade.id)

    sent = []
    async def fake_send(_client, _token, _chat_id, message):
        sent.append(message)
        return {"message_id": 99}

    monkeypatch.setattr(telegram_worker, "_send", fake_send)
    asyncio.run(telegram_worker._sync_signal_trade_messages(None, db, user_id, "token", "chat"))
    assert sent == []

    db.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_telegram_signal_sync_ignores_backtest_source_rows(monkeypatch):
    from datetime import datetime, timezone
    from app.signal_lifecycle import record_signal

    engine, _factory, db, user_id = _memory_session()
    record_signal(db, user_id, {
        "symbol": "BTCUSDT", "side": "SELL", "timeframe": "1m",
        "entry": 100, "stop_loss": 105, "tp1": 95, "tp2": 90, "tp3": 85,
        "signal_time": datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc).isoformat(),
    }, source="BACKTEST")
    db.commit()
    telegram_worker._set(db, user_id, "telegram_signal_start_after_id", "0")
    db.commit()

    sent = []
    async def fake_send(_client, _token, _chat_id, message):
        sent.append(message)
        return {"message_id": 100}

    monkeypatch.setattr(telegram_worker, "_send", fake_send)
    asyncio.run(telegram_worker._sync_signal_trade_messages(None, db, user_id, "token", "chat"))
    assert sent == []

    db.close()
    Base.metadata.drop_all(engine)
    engine.dispose()
