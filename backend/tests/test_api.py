from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
import sqlite3
from pathlib import Path
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



def test_legacy_accounts_are_consolidated_without_losing_local_data():
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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
