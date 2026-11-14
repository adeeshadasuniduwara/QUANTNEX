import json
import math
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, timezone
import app.main as main_module
from app.database import Base, engine
from app.main import app, local_workspace, backup_legacy_database
from app.models import PaperTrade, Preference, StrategyLabRun, Trade, User, WalletTransaction


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


def test_signal_settings_reject_non_finite_risk_without_mutating_preferences():
    client = TestClient(app)
    before = client.get("/api/v1/signals/settings").json()
    for invalid in (float("nan"), float("inf"), float("-inf")):
        payload = {
            "primary": before["primary"], "trend": before["trend"],
            "enabled": before["enabled"], "risk_percent": invalid,
            "min_score": before["min_score"],
        }
        response = client.put(
            "/api/v1/signals/settings",
            content=json.dumps(payload, allow_nan=True),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422
        assert response.json()["detail"]
    assert client.get("/api/v1/signals/settings").json() == before


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


def test_wallet_rejects_non_finite_and_out_of_range_amounts_without_mutating_balance():
    client = TestClient(app)
    before = client.get("/api/v1/wallet/summary").json()
    invalid_amounts = [0, -1, float("nan"), float("inf"), float("-inf"), 1000000001]
    for amount in invalid_amounts:
        payload = {
            "transaction_type": "deposit", "amount": amount, "description": "invalid amount test"
        }
        response = client.post(
            "/api/v1/wallet/transactions",
            content=json.dumps(payload, allow_nan=True),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422, amount
        detail = response.json()["detail"]
        assert isinstance(detail, list) and detail
        if isinstance(amount, float) and not math.isfinite(amount):
            assert detail[0]["input"] == str(amount).lower()
    after = client.get("/api/v1/wallet/summary").json()
    assert after == before


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



def test_legacy_accounts_are_consolidated_without_losing_local_data():
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(test_engine, "connect")
    def enable_test_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(test_engine)
    with Session(test_engine) as db:
        owner = User(email="first@example.com", password_hash="legacy-password-hash")
        legacy = User(email="second@example.com", password_hash="another-legacy-hash")
        db.add_all([owner, legacy])
        db.flush()
        owner_id = owner.id
        db.add_all([
            Preference(user_id=owner.id, key="signal_settings", value="first-value"),
            Preference(user_id=legacy.id, key="signal_settings", value="second-value"),
            Preference(user_id=legacy.id, key="telegram_chat_id", value="123456"),
            Trade(user_id=legacy.id, symbol="XAUUSD", direction="buy", outcome="win", pnl=12.5, notes="keep me"),
            WalletTransaction(user_id=legacy.id, transaction_type="deposit", amount=50, description="keep wallet"),
            PaperTrade(user_id=legacy.id, symbol="BTCUSDT", side="BUY", quantity=0.01,
                       entry_price=65000, stop_loss=64000, take_profit=67000),
            StrategyLabRun(user_id=legacy.id, run_type="backtest", symbol="BTCUSDT",
                           timeframe="15m", strategy_json='{"name":"EMA"}',
                           result_json='{"net_pnl":12.5}'),
        ])
        db.commit()

        workspace = local_workspace(db)

        assert workspace.id == owner_id
        assert workspace.email == "local@quantnex.invalid"
        assert workspace.password_hash == ""
        assert len(list(db.scalars(select(User)))) == 1
        trades = list(db.scalars(select(Trade)))
        wallet = list(db.scalars(select(WalletTransaction)))
        preferences = {row.key: row.value for row in db.scalars(select(Preference))}
        assert len(trades) == 1 and trades[0].user_id == owner_id
        assert len(wallet) == 1 and wallet[0].user_id == owner_id
        paper_trades = list(db.scalars(select(PaperTrade)))
        research_runs = list(db.scalars(select(StrategyLabRun)))
        assert len(paper_trades) == 1 and paper_trades[0].user_id == owner_id
        assert paper_trades[0].entry_price == 65000
        assert len(research_runs) == 1 and research_runs[0].user_id == owner_id
        assert research_runs[0].result_json == '{"net_pnl":12.5}'
        assert preferences["signal_settings"] == "first-value"
        assert preferences["telegram_chat_id"] == "123456"



def test_legacy_database_is_backed_up_before_password_hashes_are_cleared(tmp_path, monkeypatch):
    database_path = tmp_path / "legacy.db"
    test_engine = create_engine(
        "sqlite:///" + database_path.as_posix(),
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(test_engine)
    with Session(test_engine) as db:
        db.add(User(email="old@example.com", password_hash="legacy-hash"))
        db.commit()
        monkeypatch.setattr(main_module, "DATABASE_URL", "sqlite:///" + database_path.as_posix())

        backup_legacy_database(db)

    backup_dir = Path(__file__).resolve().parents[2] / "data" / "backups"
    backups = sorted(backup_dir.glob("quantnex-pre-local-only-*.db"))
    assert backups
    with sqlite3.connect(backups[-1]) as backup:
        row = backup.execute("SELECT email, password_hash FROM users").fetchone()
    assert row == ("old@example.com", "legacy-hash")


def test_mutating_api_requests_reject_untrusted_browser_origins():
    client = TestClient(app)
    blocked_signal_scan = client.post(
        "/api/v1/signals/scan?symbol=BTCUSDT",
        headers={"Origin": "https://attacker.example"},
    )
    assert blocked_signal_scan.status_code == 403
    assert "Cross-origin" in blocked_signal_scan.json()["detail"]

    blocked_backup = client.post(
        "/api/v1/system/backups",
        headers={"Origin": "https://attacker.example"},
    )
    assert blocked_backup.status_code == 403


def test_mutating_api_requests_allow_the_local_quantnex_web_origin():
    client = TestClient(app)
    response = client.put(
        "/api/v1/preferences/origin_policy_test",
        json={"value": "local-web-origin-accepted"},
        headers={"Origin": "http://127.0.0.1:5500"},
    )
    assert response.status_code == 200


def test_sqlite_engine_uses_foreign_keys_wal_and_busy_timeout():
    if not main_module.DATABASE_URL.startswith("sqlite"):
        return
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() >= 20000
        journal_mode = connection.exec_driver_sql("PRAGMA journal_mode").scalar().lower()
        assert journal_mode in {"wal", "memory"}


def test_chart_candle_endpoint_reports_source_freshness(monkeypatch):
    import asyncio
    import app.signal_engine as signal_engine

    source_time = datetime.now(timezone.utc) - timedelta(seconds=30)
    rows = [{
        "time": source_time.isoformat(), "open": 2300.0, "high": 2301.0,
        "low": 2299.0, "close": 2300.5, "volume": 0.0,
    } for _ in range(210)]

    async def fresh_candles(interval, limit, symbol):
        assert interval == "1min"
        assert limit == 210
        assert symbol == "XAUUSD"
        return rows

    monkeypatch.setattr(signal_engine, "fetch_candles", fresh_candles)
    client = TestClient(app)
    fresh = client.get("/api/v1/charts/candles?symbol=XAUUSD&interval=1m&limit=210")
    assert fresh.status_code == 200
    assert fresh.json()["data_health"] == "ok"
    assert fresh.json()["stale"] is False
    assert fresh.json()["source_timestamp"] == source_time.isoformat()

    stale_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    stale_rows = [{**row, "time": stale_time.isoformat()} for row in rows]

    async def stale_candles(interval, limit, symbol):
        return stale_rows

    monkeypatch.setattr(signal_engine, "fetch_candles", stale_candles)
    stale = client.get("/api/v1/charts/candles?symbol=XAUUSD&interval=1m&limit=210")
    assert stale.status_code == 200
    assert stale.json()["data_health"] == "stale"
    assert stale.json()["stale"] is True



def test_goal_target_update_rejects_nan_and_does_not_mutate_goal():
    client = TestClient(app)
    created = client.post("/api/v1/goals", json={
        "title": "Finite target validation",
        "target_amount": 100,
        "initial_amount": 0,
        "currency": "USD",
    })
    assert created.status_code == 200
    goal_id = created.json()["id"]
    response = client.put(
        f"/api/v1/goals/{goal_id}",
        content=json.dumps({"target_amount": float("nan")}, allow_nan=True),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    goal = next(item for item in client.get("/api/v1/goals").json()["goals"] if item["id"] == goal_id)
    assert goal["target_amount"] == 100
    assert goal["saved_amount"] == 0


def test_goal_contribution_rejects_nan_without_changing_saved_amount():
    client = TestClient(app)
    created = client.post("/api/v1/goals", json={
        "title": "Finite contribution validation",
        "target_amount": 100,
        "initial_amount": 0,
        "currency": "USD",
    })
    assert created.status_code == 200
    goal_id = created.json()["id"]
    response = client.post(
        f"/api/v1/goals/{goal_id}/contributions",
        content=json.dumps({"amount": float("nan"), "confirmed_available_real_funds": True}, allow_nan=True),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    goal = next(item for item in client.get("/api/v1/goals").json()["goals"] if item["id"] == goal_id)
    assert goal["saved_amount"] == 0


def test_lowering_goal_target_to_existing_savings_marks_achieved_and_certificate_verifies():
    client = TestClient(app)
    created = client.post("/api/v1/goals", json={
        "title": "Goal certificate state consistency",
        "target_amount": 100,
        "initial_amount": 20,
        "confirmed_available_real_funds": True,
        "currency": "USD",
    })
    assert created.status_code == 200
    goal_id = created.json()["id"]
    contribution = client.post(f"/api/v1/goals/{goal_id}/contributions", json={
        "amount": 60, "confirmed_available_real_funds": True, "currency": "USD",
    })
    assert contribution.status_code == 200
    assert contribution.json()["saved_amount"] == 80
    assert contribution.json()["achieved"] is False

    locked = client.post(f"/api/v1/goals/{goal_id}/certificate", json={"display_name": "Test Trader"})
    assert locked.status_code == 409

    updated = client.put(f"/api/v1/goals/{goal_id}", json={"target_amount": 75})
    assert updated.status_code == 200
    assert updated.json()["achieved"] is True
    goal = next(item for item in client.get("/api/v1/goals").json()["goals"] if item["id"] == goal_id)
    assert goal["achieved"] is True

    certificate = client.post(f"/api/v1/goals/{goal_id}/certificate", json={"display_name": "Test Trader"})
    assert certificate.status_code == 200
    assert certificate.headers["content-type"].startswith("application/pdf")
    assert certificate.content.startswith(b"%PDF")
    assert client.get(f"/api/v1/goals/{goal_id}/certificate/verify").json()["verified"] is True

    from app.database import SessionLocal
    from app.models import PersonalGoal
    db = SessionLocal()
    try:
        stored_goal = db.get(PersonalGoal, goal_id)
        stored_goal.title = "Tampered goal title"
        db.commit()
    finally:
        db.close()
    verification = client.get(f"/api/v1/goals/{goal_id}/certificate/verify")
    assert verification.status_code == 200
    assert verification.json()["verified"] is False


def test_economic_calendar_without_finnhub_key_is_explicitly_unconfigured(monkeypatch):
    from app import phase07_engine
    monkeypatch.setattr(phase07_engine, "FINNHUB_API_KEY", "")
    response = TestClient(app).get("/api/v1/intelligence/news")
    assert response.status_code == 200
    payload = response.json()
    assert payload["configured"] is False
    assert payload["provider"] == "Finnhub"
    assert payload["events"] == []
    assert "FINNHUB_API_KEY" in payload["note"]


def test_economic_calendar_invalid_provider_key_returns_actionable_502(monkeypatch):
    from app import phase07_engine
    monkeypatch.setattr(phase07_engine, "FINNHUB_API_KEY", "test-key")

    async def provider_error(_client, _url, _params):
        raise phase07_engine.IntelligenceDataError("Invalid Finnhub API key")

    monkeypatch.setattr(phase07_engine, "_get_json", provider_error)
    response = TestClient(app).get("/api/v1/intelligence/news")
    assert response.status_code == 502
    assert "FINNHUB_API_KEY" in response.json()["detail"]
    assert "quota" in response.json()["detail"]


def test_economic_calendar_filters_malformed_rows_and_clamps_horizon(monkeypatch):
    from datetime import date
    from app import phase07_engine
    monkeypatch.setattr(phase07_engine, "FINNHUB_API_KEY", "test-key")
    captured = {}

    async def provider_rows(_client, _url, params):
        captured.update(params)
        return {"economicCalendar": [
            None,
            "not-an-event",
            {"time": "2026-11-20T12:00:00Z", "event": "Later"},
            {"time": "2026-11-15T12:00:00Z", "event": "Earlier"},
        ]}

    monkeypatch.setattr(phase07_engine, "_get_json", provider_rows)
    response = TestClient(app).get("/api/v1/intelligence/news?days=999")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["events"]) == 2
    assert [event["event"] for event in payload["events"]] == ["Earlier", "Later"]
    assert (date.fromisoformat(captured["to"]) - date.fromisoformat(captured["from"])).days == 30


def test_demo_certificate_preview_does_not_require_an_achieved_goal():
    client = TestClient(app)
    response = client.post("/api/v1/goals/demo-certificate", json={
        "display_name": "Preview Name",
        "goal_title": "My Trading Journey",
        "achievement_text": "Built through patience, consistency and discipline.",
        "target_amount": 1000,
        "currency": "USD",
    })
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert "QUANTNEX-DEMO-CERTIFICATE-NOT-VALID.pdf" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")


def test_demo_certificate_preview_uses_safe_defaults_when_payload_is_empty():
    client = TestClient(app)
    response = client.post("/api/v1/goals/demo-certificate", json={})
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
    assert "NOT-VALID" in response.headers["content-disposition"]

def test_chart_quote_uses_mt5_provider_when_mt5_chart_history_is_enabled(monkeypatch):
    from datetime import datetime, timezone
    from app import mt5_feed

    async def fake_quote(_symbol):
        stamp = datetime.now(timezone.utc).isoformat()
        return {"bid": 2345.0, "ask": 2345.2, "last": None, "spread": 0.2,
                "provider": "MetaTrader 5 local terminal", "stale": False,
                "source_timestamp": stamp, "fetch_timestamp": stamp}

    monkeypatch.setattr(main_module, "QUANTNEX_MT5_ENABLED", True)
    monkeypatch.setattr(mt5_feed, "get_quote", fake_quote)
    response = TestClient(app).get("/api/v1/charts/quote?symbol=XAUUSD")
    assert response.status_code == 200
    assert response.json()["price"] == 2345.1
    assert response.json()["provider"] == "MetaTrader 5 local terminal"


def test_chart_quote_uses_twelve_data_provider_when_mt5_is_disabled(monkeypatch):
    from datetime import datetime, timezone
    from app import phase07_engine

    async def fake_quote(_symbol):
        stamp = datetime.now(timezone.utc).isoformat()
        return {"symbol": "XAUUSD", "kind": "gold", "price": 2345.6,
                "provider": "Twelve Data", "source_timestamp": stamp, "timestamp": stamp}

    monkeypatch.setattr(main_module, "QUANTNEX_MT5_ENABLED", False)
    monkeypatch.setattr(phase07_engine, "get_quote", fake_quote)
    response = TestClient(app).get("/api/v1/charts/quote?symbol=XAUUSD")
    assert response.status_code == 200
    assert response.json()["price"] == 2345.6
    assert response.json()["provider"] == "Twelve Data"

def test_chart_quote_marks_twelve_data_price_stale_for_short_timeframes(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app import phase07_engine

    async def fake_quote(_symbol):
        stamp = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        return {"symbol": "XAUUSD", "kind": "gold", "price": 2345.6,
                "provider": "Twelve Data", "source_timestamp": stamp, "timestamp": datetime.now(timezone.utc).isoformat()}

    monkeypatch.setattr(main_module, "QUANTNEX_MT5_ENABLED", False)
    monkeypatch.setattr(phase07_engine, "get_quote", fake_quote)
    response = TestClient(app).get("/api/v1/charts/quote?symbol=XAUUSD&interval=1m")
    assert response.status_code == 200
    assert response.json()["stale"] is True
    assert response.json()["stale_after_seconds"] == 120

def test_smart_open_gold_quote_uses_chart_provider(monkeypatch):
    import asyncio
    from datetime import datetime, timezone

    calls = []
    async def fake_chart_quote(symbol, interval):
        calls.append((symbol, interval))
        stamp = datetime.now(timezone.utc).isoformat()
        return {"symbol": symbol, "price": 2345.6, "provider": "MetaTrader 5 local terminal",
                "source_timestamp": stamp, "timestamp": stamp, "stale": False}

    monkeypatch.setattr(main_module, "chart_quote", fake_chart_quote)
    quote = asyncio.run(main_module._smart_open_quote({"symbol": "XAUUSD", "kind": "gold"}))
    assert calls == [("XAUUSD", "15m")]
    assert quote["price"] == 2345.6
    assert quote["provider"] == "MetaTrader 5 local terminal"
    assert quote["kind"] == "gold"


def test_smart_open_gold_blocks_stale_chart_provider_quote(monkeypatch):
    import asyncio
    from fastapi import HTTPException

    async def fake_chart_quote(_symbol, _interval):
        return {"symbol": "XAUUSD", "price": 2345.6, "provider": "MetaTrader 5 local terminal", "stale": True}

    monkeypatch.setattr(main_module, "chart_quote", fake_chart_quote)
    try:
        asyncio.run(main_module._smart_open_quote({"symbol": "XAUUSD", "kind": "gold"}))
    except HTTPException as exc:
        assert exc.status_code == 503
    else:
        raise AssertionError("Stale Gold quote must block paper entry.")

def test_strategy_research_uses_only_fully_closed_candles():
    now = datetime.now(timezone.utc)
    rows = []
    for index in range(210):
        stamp = now - timedelta(minutes=15 * (211 - index))
        rows.append({"time": stamp.isoformat(), "close": 100 + index})
    rows.append({"time": (now - timedelta(minutes=5)).isoformat(), "close": 999})

    result = main_module._closed_strategy_candles(rows, "15m")
    assert len(result) == 210
    assert result[-1]["close"] == 309

def test_legacy_journal_import_is_idempotent_and_preserves_wallet_balance():
    client = TestClient(app)
    before = client.get("/api/v1/wallet/summary").json()
    source_id = "legacy-browser-import-test-2026"
    payload = {
        "source_id": source_id,
        "rows": [
            {
                "source_ref": "legacy-row-reference-0001",
                "date": "2024-04-02",
                "symbol": "XAUUSD",
                "direction": "buy",
                "outcome": "win",
                "pnl": 125.50,
                "notes": "Imported historical browser journal row",
            },
            {
                "source_ref": "legacy-row-reference-0002",
                "date": "2024-04-03",
                "symbol": "BTCUSDT",
                "direction": "sell",
                "outcome": "loss",
                "pnl": -20.25,
                "notes": "Second historical browser journal row",
            },
        ],
    }

    first = client.post("/api/v1/journal/import", json=payload)
    assert first.status_code == 200
    assert first.json() == {"imported": 2, "total": 2}

    retry = client.post("/api/v1/journal/import", json=payload)
    assert retry.status_code == 200
    assert retry.json() == {"imported": 0, "total": 2}

    retry_from_new_source = {**payload, "source_id": "second-browser-source-test-2026"}
    assert client.post("/api/v1/journal/import", json=retry_from_new_source).json()["imported"] == 0

    after = client.get("/api/v1/wallet/summary").json()
    assert after == before

    rows = client.get("/api/v1/journal?limit=500").json()
    imported = [row for row in rows if "historical browser journal row" in row["notes"]]
    assert len(imported) == 2
    dates = {row["created_at"][:10] for row in imported}
    assert dates == {"2024-04-02", "2024-04-03"}

    deleted_id = imported[0]["id"]
    assert client.delete(f"/api/v1/journal/{deleted_id}").status_code == 204
    retry_after_delete = client.post("/api/v1/journal/import", json=payload)
    assert retry_after_delete.status_code == 200
    assert retry_after_delete.json()["imported"] == 0
    remaining = client.get("/api/v1/journal?limit=500").json()
    assert all(row["id"] != deleted_id for row in remaining)
    assert client.get("/api/v1/wallet/summary").json() == before

    # A newly-created trade queued while the backend was offline must still
    # create exactly one wallet P&L transaction when it later syncs.
    offline_payload = {
        "source_id": "offline-journal-sync-test-2026",
        "rows": [{
            "source_ref": "offline-new-trade-reference-0001",
            "date": "2026-11-14",
            "symbol": "ETHUSDT",
            "direction": "sell",
            "outcome": "loss",
            "pnl": -4.25,
            "notes": "Queued while backend was unavailable",
            "record_wallet": True,
        }],
    }
    queued = client.post("/api/v1/journal/import", json=offline_payload)
    assert queued.status_code == 200 and queued.json()["imported"] == 1
    wallet_after_queue = client.get("/api/v1/wallet/summary").json()
    assert round(wallet_after_queue["balance"] - before["balance"], 2) == -4.25
    duplicate_queue = client.post("/api/v1/journal/import", json=offline_payload)
    assert duplicate_queue.status_code == 200 and duplicate_queue.json()["imported"] == 0
    offline_trade = next(row for row in client.get("/api/v1/journal?limit=500").json()
                         if row["notes"] == "Queued while backend was unavailable")
    assert client.delete(f"/api/v1/journal/{offline_trade['id']}").status_code == 204
    assert client.get("/api/v1/wallet/summary").json() == before

def test_journal_creation_normalizes_timezone_aware_local_dates():
    client = TestClient(app)
    created = client.post("/api/v1/journal", json={
        "symbol": "EURUSD",
        "direction": "buy",
        "outcome": "win",
        "pnl": 1.0,
        "created_at": "2026-11-14T12:00:00+08:00",
        "notes": "timezone date test",
    })
    assert created.status_code == 201
    assert created.json()["created_at"].startswith("2026-11-14T04:00:00")
    assert client.delete(f"/api/v1/journal/{created.json()['id']}").status_code == 204

def test_windows_journal_sync_is_idempotent_when_http_response_is_lost():
    client = TestClient(app)
    before = client.get("/api/v1/wallet/summary").json()
    client_ref = "windows_12345678-1234-1234-1234-123456789012"
    payload = {
        "symbol": "XAUUSD",
        "direction": "buy",
        "outcome": "win",
        "pnl": 12.50,
        "created_at": "2026-11-14T12:00:00+08:00",
        "client_ref": client_ref,
        "notes": "Windows local journal sync",
    }

    first = client.post("/api/v1/journal", json=payload)
    second = client.post("/api/v1/journal", json=payload)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    after_create = client.get("/api/v1/wallet/summary").json()
    assert round(after_create["balance"] - before["balance"], 2) == 12.50

    imported = client.post("/api/v1/journal/import", json={
        "source_id": "web-offline-retry-source-2026",
        "rows": [{
            "source_ref": client_ref,
            "date": "2026-11-14T12:00:00+08:00",
            "symbol": "XAUUSD",
            "direction": "buy",
            "outcome": "win",
            "pnl": 12.50,
            "record_wallet": True,
            "notes": "idempotent online create",
        }],
    })
    assert imported.status_code == 200 and imported.json()["imported"] == 0

    trade_id = first.json()["id"]
    assert client.delete(f"/api/v1/journal/{trade_id}").status_code == 204
    assert client.get("/api/v1/wallet/summary").json() == before

    replay_after_delete = client.post("/api/v1/journal", json=payload)
    assert replay_after_delete.status_code == 409
    assert client.get("/api/v1/wallet/summary").json() == before
