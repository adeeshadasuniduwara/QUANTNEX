from fastapi.testclient import TestClient
from app.main import app


def test_health_and_local_journal_flow():
    client = TestClient(app)
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["database"] == "connected"

    created = client.post("/api/v1/journal", json={
        "symbol": "xauusd", "direction": "BUY", "outcome": "Win",
        "pnl": 25.5, "notes": "local workspace test"
    })
    assert created.status_code == 201
    assert created.json()["symbol"] == "XAUUSD"

    listed = client.get("/api/v1/journal")
    assert listed.status_code == 200
    assert any(item["id"] == created.json()["id"] for item in listed.json())

    deleted = client.delete(f"/api/v1/journal/{created.json()['id']}")
    assert deleted.status_code == 204


def test_login_and_registration_routes_are_removed():
    client = TestClient(app)
    assert client.post("/api/v1/auth/register", json={}).status_code == 404
    assert client.post("/api/v1/auth/login", json={}).status_code == 404
    assert client.get("/api/v1/auth/me").status_code == 404
    schema = client.get("/openapi.json").json()
    assert not any(path.startswith("/api/v1/auth/") for path in schema["paths"])


def test_local_wallet_ledger_deposits_withdrawals_and_journal_pnl():
    client = TestClient(app)
    before = client.get("/api/v1/wallet/summary").json()
    before_rows = client.get("/api/v1/wallet/transactions?limit=500").json()

    deposit = client.post("/api/v1/wallet/transactions", json={
        "transaction_type": "deposit", "amount": 500, "description": "Local opening balance"
    })
    assert deposit.status_code == 201
    assert deposit.json()["amount"] == 500

    withdrawal = client.post("/api/v1/wallet/transactions", json={
        "transaction_type": "withdrawal", "amount": 100, "description": "Local cash withdrawal"
    })
    assert withdrawal.status_code == 201
    assert withdrawal.json()["amount"] == -100

    denied = client.post("/api/v1/wallet/transactions", json={
        "transaction_type": "withdrawal", "amount": 999999999
    })
    assert denied.status_code == 409

    trade = client.post("/api/v1/journal", json={
        "symbol": "XAUUSD", "direction": "buy", "outcome": "win", "pnl": 35.25
    })
    assert trade.status_code == 201

    summary = client.get("/api/v1/wallet/summary")
    assert summary.status_code == 200
    assert round(summary.json()["balance"] - before["balance"], 2) == 435.25
    transactions = client.get("/api/v1/wallet/transactions?limit=500")
    assert len(transactions.json()) == len(before_rows) + 3

    deleted = client.delete(f"/api/v1/journal/{trade.json()['id']}")
    assert deleted.status_code == 204
    summary_after_delete = client.get("/api/v1/wallet/summary").json()
    assert round(summary_after_delete["balance"] - before["balance"], 2) == 400.0


def test_signal_settings_and_telegram_status_work_without_login():
    client = TestClient(app)
    defaults = client.get("/api/v1/signals/settings")
    assert defaults.status_code == 200
    assert defaults.json()["primary"] in {"1", "5", "15", "30", "50", "60"}

    updated = client.put("/api/v1/signals/settings", json={
        "primary": "1", "trend": "60", "enabled": ["60", "30", "5", "1"],
        "risk_percent": 0.5, "min_score": 8
    })
    assert updated.status_code == 200
    assert updated.json()["primary"] == "1"
    assert updated.json()["min_score"] == 8

    status = client.get("/api/v1/telegram/status")
    assert status.status_code == 200
    assert "connected" in status.json()


def test_auto_signal_settings_are_opt_in_without_login():
    client = TestClient(app)
    saved = client.put("/api/v1/telegram/auto-signals", json={
        "enabled": False, "interval_seconds": 300
    })
    assert saved.status_code == 200
    assert saved.json()["enabled"] is False
    assert saved.json()["interval_seconds"] == 300
