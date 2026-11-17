from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import SignalTrade, User
from app.telegram_reporting import build_daily_signal_pdf


def _trade(user_id, symbol, status, realized_r, created, closed):
    return SignalTrade(
        user_id=user_id, fingerprint=f"{symbol}|{status}|{created.isoformat()}",
        source="QUANTNEX_VIEW", symbol=symbol, side="BUY", timeframe="5m",
        entry_type="MARKET", entry_price=100, stop_loss=95, active_stop_loss=100,
        tp1=105, tp2=110, tp3=115, risk_distance=5, status=status,
        signal_time=created, filled_at=created, realized_r=realized_r,
        stopped_at=closed if status in {"SL_HIT", "STOPPED", "PROTECTED_EXIT", "LOCKED_PROFIT_EXIT"} else None,
        tp3_at=closed if status == "TARGETS_COMPLETE" else None,
        created_at=created, updated_at=closed or created,
    )


def test_daily_signal_pdf_reports_pair_win_rates_and_closed_outcomes():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="local@quantnex.invalid", password_hash="")
        db.add(user)
        db.flush()
        opened = datetime(2026, 11, 16, 2, 0, tzinfo=timezone.utc)
        closed = datetime(2026, 11, 16, 4, 0, tzinfo=timezone.utc)
        db.add_all([
            _trade(user.id, "BTCUSDT", "TARGETS_COMPLETE", 2.1, opened, closed),
            _trade(user.id, "ETHUSDT", "SL_HIT", -1.0, opened, closed),
            _trade(user.id, "BTCUSDT", "PROTECTED_EXIT", 0.4, opened, closed),
            _trade(user.id, "SOLUSDT", "OPEN", 0.0, opened, None),
        ])
        db.commit()
        pdf, stats = build_daily_signal_pdf(db, user.id, report_day=date(2026, 11, 16))
        assert pdf.startswith(b"%PDF")
        assert stats["closed"] == 3
        assert stats["wins"] == 2
        assert stats["losses"] == 1
        assert stats["win_rate"] == 66.67
        assert stats["pairs"]["BTCUSDT"]["win_rate"] == 100.0
        assert stats["pairs"]["ETHUSDT"]["win_rate"] == 0.0
        assert stats["open_at_cutoff"] == 1
