import json
from fastapi.testclient import TestClient
from app.main import app


def _reset(client):
    response = client.post("/api/v1/prop-challenge/reset")
    assert response.status_code == 200


def test_virtual_prop_challenge_daily_loss_breach_locks_account():
    client = TestClient(app)
    _reset(client)
    created = client.post("/api/v1/prop-challenge/challenge", json={
        "mode": "virtual", "starting_balance": 10000,
        "profit_target_pct": 10, "daily_loss_pct": 5,
        "max_loss_pct": 10, "minimum_trading_days": 2,
        "timezone": "Asia/Colombo", "drawdown_type": "static"
    })
    assert created.status_code == 201
    assert created.json()["challenge"]["status"] == "ACTIVE"
    trade = client.post("/api/v1/prop-challenge/virtual-trades", json={"symbol": "XAUUSD", "pnl": -500})
    assert trade.status_code == 201
    assert trade.json()["challenge"]["status"] == "FAILED"
    assert trade.json()["challenge"]["status_reason"] == "Daily maximum loss breached."
    assert trade.json()["metrics"]["daily_loss_used_pct"] == 100
    blocked = client.post("/api/v1/prop-challenge/virtual-trades", json={"symbol": "XAUUSD", "pnl": 25})
    assert blocked.status_code == 409
    _reset(client)


def test_virtual_prop_challenge_profit_target_requires_minimum_days():
    client = TestClient(app)
    _reset(client)
    created = client.post("/api/v1/prop-challenge/challenge", json={
        "mode": "virtual", "starting_balance": 10000,
        "profit_target_pct": 1, "daily_loss_pct": 5,
        "max_loss_pct": 10, "minimum_trading_days": 2,
        "timezone": "Asia/Colombo", "drawdown_type": "static"
    })
    assert created.status_code == 201
    first = client.post("/api/v1/prop-challenge/virtual-trades", json={"symbol": "EURUSD", "pnl": 100})
    assert first.status_code == 201
    assert first.json()["challenge"]["status"] == "ACTIVE"
    assert "remaining minimum trading days" in first.json()["challenge"]["status_reason"]
    _reset(client)


def test_prop_challenge_rejects_inconsistent_loss_rules():
    client = TestClient(app)
    response = client.post("/api/v1/prop-challenge/challenge", json={
        "mode": "virtual", "starting_balance": 10000,
        "profit_target_pct": 10, "daily_loss_pct": 6,
        "max_loss_pct": 5, "minimum_trading_days": 1,
        "timezone": "Asia/Colombo"
    })
    assert response.status_code == 422


def test_mt5_bridge_is_unavailable_off_windows_without_fake_connection():
    import os
    client = TestClient(app)
    _reset(client)
    if os.name != "nt":
        client.post("/api/v1/prop-challenge/challenge", json={"mode": "mt5_demo", "starting_balance": 10000})
        response = client.post("/api/v1/prop-challenge/mt5/connect", json={
            "login": 123456, "password": "not-a-real-password", "server": "Broker-Demo"
        })
        assert response.status_code == 503
        assert "Windows" in response.json()["detail"]
    _reset(client)


def _post_json_allow_nonfinite(client, path, payload):
    return client.post(
        path,
        content=json.dumps(payload, allow_nan=True),
        headers={"Content-Type": "application/json"},
    )


def test_prop_challenge_rejects_non_finite_limits_without_creating_state():
    client = TestClient(app)
    _reset(client)
    base = {
        "mode": "virtual", "starting_balance": 10000,
        "profit_target_pct": 10, "daily_loss_pct": 5,
        "max_loss_pct": 10, "minimum_trading_days": 2,
        "timezone": "Asia/Colombo", "drawdown_type": "static",
    }
    for field in ("starting_balance", "profit_target_pct", "daily_loss_pct", "max_loss_pct"):
        for invalid in (float("nan"), float("inf"), float("-inf")):
            payload = dict(base)
            payload[field] = invalid
            response = _post_json_allow_nonfinite(client, "/api/v1/prop-challenge/challenge", payload)
            assert response.status_code == 422, (field, invalid)
            assert response.json()["detail"]
            assert client.get("/api/v1/prop-challenge/state").json()["challenge"] is None
    _reset(client)


def test_virtual_practice_rejects_non_finite_pnl_without_recording_trade():
    client = TestClient(app)
    _reset(client)
    created = client.post("/api/v1/prop-challenge/challenge", json={
        "mode": "virtual", "starting_balance": 10000,
        "profit_target_pct": 10, "daily_loss_pct": 5,
        "max_loss_pct": 10, "minimum_trading_days": 1,
        "timezone": "Asia/Colombo", "drawdown_type": "static",
    })
    assert created.status_code == 201
    for invalid in (float("nan"), float("inf"), float("-inf")):
        response = _post_json_allow_nonfinite(
            client, "/api/v1/prop-challenge/virtual-trades",
            {"symbol": "XAUUSD", "pnl": invalid},
        )
        assert response.status_code == 422
        assert response.json()["detail"]
    state = client.get("/api/v1/prop-challenge/state").json()
    assert state["challenge"]["status"] == "ACTIVE"
    assert state["recent_trades"] == []
    _reset(client)


def test_virtual_prop_challenge_trailing_drawdown_uses_peak_equity():
    client = TestClient(app)
    _reset(client)
    created = client.post("/api/v1/prop-challenge/challenge", json={
        "mode": "virtual", "starting_balance": 10000,
        "profit_target_pct": 50, "daily_loss_pct": 8,
        "max_loss_pct": 10, "minimum_trading_days": 1,
        "timezone": "Asia/Colombo", "drawdown_type": "trailing",
    })
    assert created.status_code == 201
    profit = client.post("/api/v1/prop-challenge/virtual-trades", json={"symbol": "XAUUSD", "pnl": 500})
    assert profit.status_code == 201
    assert profit.json()["challenge"]["status"] == "ACTIVE"
    assert profit.json()["metrics"]["peak_equity"] == 10500
    loss = client.post("/api/v1/prop-challenge/virtual-trades", json={"symbol": "XAUUSD", "pnl": -1000})
    assert loss.status_code == 201
    assert loss.json()["challenge"]["status"] == "FAILED"
    assert loss.json()["challenge"]["status_reason"] == "Maximum overall loss breached."
    assert loss.json()["metrics"]["max_loss_floor"] == 9500
    _reset(client)
