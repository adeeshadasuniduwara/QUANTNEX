import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.events import EventHub, _is_loopback_host, event_hub
from app.main import app


def test_event_hub_sequence_and_bounded_queue_resync():
    hub = EventHub(queue_size=1)
    first = hub.publish("journal.changed", "journal", "created", {"trade_id": 1})
    second = hub.publish("wallet.changed", "wallet", "updated", {"transaction_id": 2})
    assert first["event_id"] == 1
    assert second["event_id"] == 2
    assert first["schema_version"] == 1
    assert second["payload"]["transaction_id"] == 2

    queue = hub.connect()
    hub._broadcast(first)
    hub._broadcast(second)
    overflow = queue.get_nowait()
    assert overflow["type"] == "stream.resync_required"
    assert overflow["payload"]["reason"] == "client_queue_overflow"
    hub.disconnect(queue)


def test_event_stream_host_validation_is_loopback_only():
    assert _is_loopback_host("127.0.0.1")
    assert _is_loopback_host("::1")
    assert _is_loopback_host("localhost")
    assert not _is_loopback_host("192.0.2.10")


def test_local_event_stream_delivers_workspace_events():
    client = TestClient(app)
    with client.websocket_connect(
        "/api/v1/events/stream", headers={"origin": "http://testserver"}
    ) as websocket:
        ready = websocket.receive_json()
        assert ready["type"] == "stream.ready"
        assert ready["replay"] is False
        event_hub.publish("wallet.changed", "wallet", "updated", {"transaction_id": 987})
        event = websocket.receive_json()
        assert event["type"] == "wallet.changed"
        assert event["payload"]["transaction_id"] == 987
        assert event["event_id"] > ready["event_id"]


def test_local_event_stream_rejects_untrusted_origin():
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/api/v1/events/stream", headers={"origin": "https://example.invalid"}
        ):
            pass


def test_event_hub_rejects_invalid_names_and_oversized_payloads():
    hub = EventHub()
    with pytest.raises(ValueError):
        hub.publish("INVALID EVENT", "wallet", "updated", {})
    with pytest.raises(ValueError):
        hub.publish("wallet.changed", "wallet", "updated", {"data": "x" * 17000})


def test_auto_closed_paper_trades_publish_workspace_refresh_events(monkeypatch):
    from app import paper_worker

    published = []
    monkeypatch.setattr(paper_worker.event_hub, "publish", lambda *args: published.append(args))
    paper_worker.publish_auto_closed([{
        "trade_id": 42,
        "symbol": "BTCUSDT",
        "reason": "TAKE_PROFIT",
        "exit_price": 70000.0,
        "realized_pnl": 25.0,
    }])

    assert len(published) == 1
    event_type, entity, action, payload = published[0]
    assert (event_type, entity, action) == ("paper_trade.changed", "paper_trade", "auto_closed")
    assert payload["trade_id"] == 42
    assert payload["reason"] == "TAKE_PROFIT"


def test_telegram_timeframe_commands_publish_preference_change(monkeypatch):
    from app import telegram_worker

    published = []
    monkeypatch.setattr(telegram_worker.event_hub, "publish", lambda *args: published.append(args))
    telegram_worker._publish_signal_settings_changed()

    assert len(published) == 1
    event_type, entity, action, payload = published[0]
    assert (event_type, entity, action) == ("preferences.changed", "preferences", "updated")
    assert payload == {"key": "signal_settings"}
