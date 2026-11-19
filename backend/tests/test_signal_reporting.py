from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import SignalTrade, User
from app.signal_lifecycle import record_signal
from app.signal_reporting import build_signal_performance_pdf


def _signal(symbol, stamp):
    return {"symbol": symbol, "side": "BUY", "timeframe": "1m", "entry_type": "MARKET",
            "entry": 100, "stop_loss": 95, "tp1": 105, "tp2": 110, "tp3": 115,
            "signal_time": stamp.isoformat()}


def test_signal_report_uses_chart_ledger_period_and_resolved_win_rate():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="signal-report@quantnex.invalid", password_hash="")
        db.add(user)
        db.flush()
        today = datetime(2026, 11, 20, 2, 0, tzinfo=timezone.utc)
        btc, _ = record_signal(db, user.id, _signal("BTCUSDT", today))
        btc.status, btc.realized_r = "TARGETS_COMPLETE", 1.9
        eth, _ = record_signal(db, user.id, _signal("ETHUSDT", today - timedelta(hours=1)))
        eth.status, eth.realized_r = "STOPPED", -1.0
        sol, _ = record_signal(db, user.id, _signal("SOLUSDT", today))
        sol.status, sol.realized_r = "OPEN", 0.4
        old, _ = record_signal(db, user.id, _signal("XRPUSDT", today - timedelta(days=10)))
        old.status, old.realized_r = "STOPPED", -1.0
        db.commit()

        pdf, stats = build_signal_performance_pdf(
            db, user.id, "daily", now=datetime(2026, 11, 20, 4, 0, tzinfo=timezone.utc)
        )
        assert pdf.startswith(b"%PDF")
        assert stats["signals"] == 3
        assert stats["resolved"] == 2
        assert stats["open"] == 1
        assert stats["wins"] == 1 and stats["losses"] == 1
        assert stats["win_rate"] == 50.0
        assert stats["realized_r"] == 1.3
        assert set(stats["by_symbol"]) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}

        _, total = build_signal_performance_pdf(
            db, user.id, "total", now=datetime(2026, 11, 20, 4, 0, tzinfo=timezone.utc)
        )
        assert total["signals"] == 4
        assert total["resolved"] == 3
        assert total["win_rate"] == round(1 / 3 * 100, 2)
        assert total["realized_r"] == 0.3


def test_signal_report_symbol_filter_and_period_validation():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="signal-report-filter@quantnex.invalid", password_hash="")
        db.add(user)
        db.flush()
        stamp = datetime(2026, 11, 20, 2, 0, tzinfo=timezone.utc)
        trade, _ = record_signal(db, user.id, _signal("BTCUSDT", stamp))
        trade.status, trade.realized_r = "STOPPED", -1.0
        db.commit()
        _, stats = build_signal_performance_pdf(
            db, user.id, "weekly", "BTCUSDT",
            now=datetime(2026, 11, 20, 4, 0, tzinfo=timezone.utc)
        )
        assert stats["signals"] == 1
        assert stats["symbol"] == "BTCUSDT"
        try:
            build_signal_performance_pdf(db, user.id, "quarterly")
        except ValueError:
            pass
        else:
            raise AssertionError("unsupported period must be rejected")
