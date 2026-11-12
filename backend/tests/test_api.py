from uuid import uuid4
from fastapi.testclient import TestClient
from app.main import app

def test_health_and_authenticated_journal_flow():
    client = TestClient(app)
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["database"] == "connected"

    email = f"phase4-{uuid4().hex}@example.com"
    password = "phase-four-test-password"
    registered = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert registered.status_code == 201

    login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    profile = client.get("/api/v1/auth/me", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["email"] == email

    created = client.post("/api/v1/journal", headers=headers, json={
        "symbol": "xauusd", "direction": "BUY", "outcome": "Win", "pnl": 25.5, "notes": "test record"
    })
    assert created.status_code == 201
    assert created.json()["symbol"] == "XAUUSD"

    listed = client.get("/api/v1/journal", headers=headers)
    assert listed.status_code == 200
    assert any(item["id"] == created.json()["id"] for item in listed.json())

    assert client.get("/api/v1/journal").status_code == 401
