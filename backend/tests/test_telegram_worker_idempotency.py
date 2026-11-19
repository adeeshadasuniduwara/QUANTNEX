import asyncio

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


def test_telegram_formatter_normalizes_literal_newlines_and_styles_message():
    rendered = telegram_worker._format_telegram_message(
        "🎯 QUANTNEX · BTCUSDT BUY · TP1 REACHED\\nObserved price: 64639.9\\nEntry: 64431.46\\nLevel-touch alert only."
    )
    assert "\\\\n" not in rendered
    assert "Observed price:" in rendered
    assert "<b>✨ 🎯 QUANTNEX" in rendered
    assert "<b>Observed price:</b>" in rendered
    assert "<i>Level-touch alert only.</i>" in rendered


def test_telegram_formatter_escapes_untrusted_html():
    rendered = telegram_worker._format_telegram_message("QUANTNEX <alert>\\nPrice: < 100")
    assert "&lt;alert&gt;" in rendered
    assert "&lt; 100" in rendered


def test_telegram_delivery_claim_is_unique_and_persists_sent_state():
    engine, factory, db, user_id = _memory_session()
    key = "source-update:" + "a" * 40
    assert telegram_worker._claim_telegram_delivery(db, user_id, key) is True
    # A reopened database session (as used after a worker restart) sees the lease.
    db.close()
    reopened = factory()
    assert telegram_worker._claim_telegram_delivery(reopened, user_id, key) is False
    telegram_worker._finish_telegram_delivery(reopened, user_id, key, True)
    assert telegram_worker._claim_telegram_delivery(reopened, user_id, key) is False
    reopened.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_failed_telegram_delivery_claim_can_be_retried():
    engine, _factory, db, user_id = _memory_session()
    key = "signal-event:123"
    assert telegram_worker._claim_telegram_delivery(db, user_id, key) is True
    telegram_worker._finish_telegram_delivery(db, user_id, key, False)
    assert telegram_worker._claim_telegram_delivery(db, user_id, key) is True
    db.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_installed_update_endpoint_deduplicates_repeated_client_notices(monkeypatch):
    engine, _factory, db, user_id = _memory_session()
    from app import main
    user = db.get(User, user_id)
    db.add(telegram_worker.Preference(user_id=user_id, key="telegram_bot_token_enc", value="encrypted"))
    db.add(telegram_worker.Preference(user_id=user_id, key="telegram_chat_id", value="123456"))
    db.commit()
    calls = []

    class FakeResponse:
        status_code = 200
        def json(self):
            return {"ok": True, "result": {"message_id": 77}}

    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            return False
        async def post(self, _url, json=None):
            calls.append(json)
            return FakeResponse()

    monkeypatch.setattr(main, "decrypt_secret", lambda _value: "12345:token")
    monkeypatch.setattr(main.httpx, "AsyncClient", FakeClient)
    payload = {"message": "WEB UPDATE INSTALLED", "notification_key": "web-update-installed:main@abcdef1"}
    first = asyncio.run(main.notify_connected_telegram(payload, user, db))
    second = asyncio.run(main.notify_connected_telegram(payload, user, db))
    assert first["ok"] is True and first["duplicate"] is False
    assert second["ok"] is True and second["duplicate"] is True
    assert len(calls) == 1
    db.close()
    Base.metadata.drop_all(engine)
    engine.dispose()
