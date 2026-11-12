import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.events import EventHub, event_hub
from app.main import app


def test_event_hub_sequence_and_bounded_queue_resync():
    hub = EventHub(queue_size=1)
    first = hub.publish("journal.changed", "journal", "created", {"trade_id": 1})
    second = hub.publish("wallet.changed", "wallet", "updated", {"transaction_id": 2})
    assert first["event_id"] == 1
    assert second["event_id"] == 2
    assert first["schema_version"] == 1
    assert second["payload"]["transaction_id"] == 2


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
