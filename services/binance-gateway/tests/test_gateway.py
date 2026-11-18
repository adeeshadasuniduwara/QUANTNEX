import os
from cryptography.fernet import Fernet

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_binance_gateway.db")
os.environ.setdefault("QUANTNEX_GATEWAY_PUBLIC_URL", "https://gateway.test")
os.environ.setdefault("QUANTNEX_GATEWAY_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("QUANTNEX_GATEWAY_ALLOW_INSECURE_LOCAL", "1")

import pytest
from fastapi.testclient import TestClient
import app as gateway


@pytest.fixture()
def client():
    gateway.Base.metadata.drop_all(bind=gateway.engine)
    gateway.Base.metadata.create_all(bind=gateway.engine)
    return TestClient(gateway.app)


def test_workspace_key_is_required_and_not_stored_raw(client):
    response = client.post("/v1/setup-sessions", json={"telegram_chat_id": "123456"})
    assert response.status_code == 401
    key = "w" * 64
    response = client.post("/v1/setup-sessions", headers={"X-QUANTNEX-Workspace-Key": key},
                           json={"telegram_chat_id": "123456"})
    assert response.status_code == 200
    assert response.json()["one_time"] is True
    assert "#"+response.json()["setup_url"].split("#")[-1] in response.json()["setup_url"]
    with gateway.SessionLocal() as db:
        row = db.query(gateway.SetupSession).one()
        assert row.workspace_hash == gateway._hash(key)
        assert row.workspace_hash != key
        assert row.token_hash != response.json()["setup_url"].split("#")[-1]


def test_session_is_one_time_and_credentials_are_never_returned(client, monkeypatch):
    async def verified(*_args, **_kwargs):
        return {"canTrade": True}
    monkeypatch.setattr(gateway, "_verify", verified)
    key = "k" * 64
    headers = {"X-QUANTNEX-Workspace-Key": key}
    link = client.post("/v1/setup-sessions", headers=headers,
                       json={"telegram_chat_id": "987654"}).json()["setup_url"]
    token = link.split("#", 1)[1]
    payload = {"session_token": token, "spot_api_key": "S"*32, "spot_api_secret": "s"*32,
               "futures_api_key": "F"*32, "futures_api_secret": "f"*32}
    response = client.post("/v1/setup-sessions/complete", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is True and body["orders_placed"] is False
    assert "api_key" not in str(body).lower() and "secret" not in str(body).lower()
    assert client.post("/v1/setup-sessions/complete", json=payload).status_code == 410
    status = client.get("/v1/workspaces/status", headers=headers).json()
    assert status["spot_connected"] and status["futures_connected"]
    with gateway.SessionLocal() as db:
        row = db.query(gateway.BinanceCredential).one()
        assert row.spot_api_key_enc != "S"*32
        assert gateway.fernet.decrypt(row.spot_api_key_enc.encode()).decode() == "S"*32


def test_disconnect_removes_encrypted_record(client):
    key = "d" * 64
    headers = {"X-QUANTNEX-Workspace-Key": key}
    assert client.delete("/v1/workspaces/credentials", headers=headers).json()["deleted"] is True
    assert client.get("/v1/workspaces/status", headers=headers).json()["spot_connected"] is False


def test_invalid_chat_id_is_rejected(client):
    response = client.post("/v1/setup-sessions", headers={"X-QUANTNEX-Workspace-Key": "a"*64},
                           json={"telegram_chat_id": "-100123"})
    assert response.status_code == 422

def test_expired_session_is_rejected(client):
    from datetime import datetime, timedelta, timezone
    key = "e" * 64
    headers = {"X-QUANTNEX-Workspace-Key": key}
    link = client.post("/v1/setup-sessions", headers=headers,
                       json={"telegram_chat_id": "456789"}).json()["setup_url"]
    token = link.split("#", 1)[1]
    with gateway.SessionLocal() as db:
        row = db.query(gateway.SetupSession).one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    payload = {"session_token": token, "spot_api_key": "S"*32, "spot_api_secret": "s"*32,
               "futures_api_key": "F"*32, "futures_api_secret": "f"*32}
    response = client.post("/v1/setup-sessions/complete", json=payload)
    assert response.status_code == 410


def test_validation_error_never_echoes_submitted_secrets(client):
    marker = "THIS_IS_A_SECRET_VALUE_THAT_MUST_NOT_ECHO"
    response = client.post("/v1/setup-sessions/complete", json={
        "session_token": "x"*48, "spot_api_key": "short", "spot_api_secret": marker,
        "futures_api_key": "F"*32, "futures_api_secret": "f"*32,
    })
    assert response.status_code == 422
    assert marker not in response.text


def test_no_order_placement_route_exists(client):
    paths = {route.path for route in gateway.app.routes}
    assert not any("order" in path.lower() or "trade" in path.lower() for path in paths)
