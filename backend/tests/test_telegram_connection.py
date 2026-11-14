from fastapi.testclient import TestClient

from app import main as main_module


class FakeTelegramResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeTelegramClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def get(self, url, params=None):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, params))
        return self.responses[method]


def _connect(client, monkeypatch, responses, chat_id="222"):
    fake = FakeTelegramClient(responses)
    monkeypatch.setattr(main_module.httpx, "AsyncClient", lambda **_kwargs: fake)
    return client.post("/api/v1/telegram/connect", json={
        "bot_token": "123456:" + "A" * 32,
        "chat_id": chat_id,
        "display_name": "QUANTNEX Test Bot",
    }), fake


def _bot():
    return FakeTelegramResponse({"ok": True, "result": {
        "id": 111222, "is_bot": True, "first_name": "QUANTNEX", "username": "quantnex_test_bot",
    }})


def test_telegram_connect_rejects_bot_own_id_as_destination(monkeypatch):
    client = TestClient(main_module.app)
    client.delete("/api/v1/telegram/connect")
    response, fake = _connect(client, monkeypatch, {
        "getMe": _bot(),
        "getChat": FakeTelegramResponse({"ok": True, "result": {
            "id": 111222, "type": "private", "first_name": "QUANTNEX",
        }}),
    }, chat_id="111222")
    assert response.status_code == 422
    assert "bot itself" in response.json()["detail"]
    assert [call[0] for call in fake.calls] == ["getMe", "getChat"]
    assert client.get("/api/v1/telegram/status").json()["connected"] is False


def test_telegram_connect_rejects_unresolvable_private_destination(monkeypatch):
    client = TestClient(main_module.app)
    client.delete("/api/v1/telegram/connect")
    response, _fake = _connect(client, monkeypatch, {
        "getMe": _bot(),
        "getChat": FakeTelegramResponse({"ok": False, "description": "Bad Request: chat not found"}, 400),
    })
    assert response.status_code == 422
    assert "/start" in response.json()["detail"]
    assert client.get("/api/v1/telegram/status").json()["connected"] is False


def test_telegram_connect_requires_channel_admin_post_permission(monkeypatch):
    client = TestClient(main_module.app)
    client.delete("/api/v1/telegram/connect")
    response, fake = _connect(client, monkeypatch, {
        "getMe": _bot(),
        "getChat": FakeTelegramResponse({"ok": True, "result": {
            "id": -100123456789, "type": "channel", "title": "QUANTNEX Updates",
        }}),
        "getChatMember": FakeTelegramResponse({"ok": True, "result": {
            "status": "administrator", "can_post_messages": False,
        }}),
    }, chat_id="@QUANTNEXUpdates")
    assert response.status_code == 422
    assert "administrator" in response.json()["detail"]
    assert [call[0] for call in fake.calls] == ["getMe", "getChat", "getChatMember"]
    assert client.get("/api/v1/telegram/status").json()["connected"] is False


def test_telegram_connect_accepts_verified_private_destination(monkeypatch):
    client = TestClient(main_module.app)
    client.delete("/api/v1/telegram/connect")
    response, fake = _connect(client, monkeypatch, {
        "getMe": _bot(),
        "getChat": FakeTelegramResponse({"ok": True, "result": {
            "id": 222333, "type": "private", "first_name": "Test User",
        }}),
    }, chat_id="222333")
    assert response.status_code == 200
    payload = response.json()
    assert payload["connected"] is True
    assert payload["destination_type"] == "private"
    assert payload["chat_id"] == "222333"
    assert [call[0] for call in fake.calls] == ["getMe", "getChat"]
    assert client.get("/api/v1/telegram/status").json()["connected"] is True
    client.delete("/api/v1/telegram/connect")


def test_telegram_connect_accepts_channel_only_when_bot_can_post(monkeypatch):
    client = TestClient(main_module.app)
    client.delete("/api/v1/telegram/connect")
    response, fake = _connect(client, monkeypatch, {
        "getMe": _bot(),
        "getChat": FakeTelegramResponse({"ok": True, "result": {
            "id": -100123456789, "type": "channel", "title": "QUANTNEX Updates",
        }}),
        "getChatMember": FakeTelegramResponse({"ok": True, "result": {
            "status": "administrator", "can_post_messages": True,
        }}),
    }, chat_id="@QUANTNEXUpdates")
    assert response.status_code == 200
    assert response.json()["destination_type"] == "channel"
    assert [call[0] for call in fake.calls] == ["getMe", "getChat", "getChatMember"]
    client.delete("/api/v1/telegram/connect")


def test_telegram_connect_accepts_channel_owner(monkeypatch):
    client = TestClient(main_module.app)
    client.delete("/api/v1/telegram/connect")
    response, _fake = _connect(client, monkeypatch, {
        "getMe": _bot(),
        "getChat": FakeTelegramResponse({"ok": True, "result": {
            "id": -100123456789, "type": "channel", "title": "QUANTNEX Updates",
        }}),
        "getChatMember": FakeTelegramResponse({"ok": True, "result": {
            "status": "creator",
        }}),
    }, chat_id="@QUANTNEXUpdates")
    assert response.status_code == 200
    assert response.json()["destination_type"] == "channel"
    client.delete("/api/v1/telegram/connect")
