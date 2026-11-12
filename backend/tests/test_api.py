from uuid import uuid4
from fastapi.testclient import TestClient
from app.main import app

def create_user(client):
    email = f"phase4-{uuid4().hex}@example.com"
    password = "phase-four-test-password"
    registered = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert registered.status_code == 201
    login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}

def test_health_and_authenticated_journal_flow():
    client = TestClient(app)
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["database"] == "connected"
    headers = create_user(client)
    profile = client.get("/api/v1/auth/me", headers=headers)
    assert profile.status_code == 200
    created = client.post("/api/v1/journal", headers=headers, json={
        "symbol": "xauusd", "direction": "BUY", "outcome": "Win", "pnl": 25.5, "notes": "test record"
    })
    assert created.status_code == 201
    assert created.json()["symbol"] == "XAUUSD"
    listed = client.get("/api/v1/journal", headers=headers)
    assert listed.status_code == 200
    assert any(item["id"] == created.json()["id"] for item in listed.json())
    assert client.get("/api/v1/journal").status_code == 401

def test_wallet_ledger_deposits_withdrawals_and_journal_pnl():
    client = TestClient(app)
    headers = create_user(client)

    deposit = client.post("/api/v1/wallet/transactions", headers=headers, json={
        "transaction_type": "deposit", "amount": 500, "description": "Opening balance"
    })
    assert deposit.status_code == 201
    assert deposit.json()["amount"] == 500

    withdrawal = client.post("/api/v1/wallet/transactions", headers=headers, json={
        "transaction_type": "withdrawal", "amount": 100, "description": "Cash out"
    })
    assert withdrawal.status_code == 201
    assert withdrawal.json()["amount"] == -100

    denied = client.post("/api/v1/wallet/transactions", headers=headers, json={
        "transaction_type": "withdrawal", "amount": 1000
    })
    assert denied.status_code == 409

    trade = client.post("/api/v1/journal", headers=headers, json={
        "symbol": "XAUUSD", "direction": "buy", "outcome": "win", "pnl": 35.25
    })
    assert trade.status_code == 201

    summary = client.get("/api/v1/wallet/summary", headers=headers)
    assert summary.status_code == 200
    assert summary.json() == {"balance": 435.25, "deposits": 500.0, "withdrawals": 100.0, "trading_pnl": 35.25}

    transactions = client.get("/api/v1/wallet/transactions", headers=headers)
    assert transactions.status_code == 200
    assert len(transactions.json()) == 3

    deleted = client.delete(f"/api/v1/journal/{trade.json()['id']}", headers=headers)
    assert deleted.status_code == 204
    summary_after_delete = client.get("/api/v1/wallet/summary", headers=headers)
    assert summary_after_delete.json()["balance"] == 400.0


def test_signal_settings_and_telegram_status_are_user_scoped():
    client = TestClient(app)
    headers = create_user(client)
    defaults = client.get("/api/v1/signals/settings", headers=headers)
    assert defaults.status_code == 200
    assert defaults.json()["primary"] == "5"
    updated = client.put("/api/v1/signals/settings", headers=headers, json={
        "primary": "1", "trend": "60", "enabled": ["60", "30", "5", "1"],
        "risk_percent": 0.5, "min_score": 8
    })
    assert updated.status_code == 200
    assert updated.json()["primary"] == "1"
    assert updated.json()["min_score"] == 8
    status = client.get("/api/v1/telegram/status", headers=headers)
    assert status.status_code == 200
    assert status.json()["connected"] is False
    assert client.get("/api/v1/signals/settings").status_code == 401
