"""Regression tests for Phase 11 paper-performance analytics."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.phase11_engine import advanced_performance


def make_trade(*, pnl=0.0, status="CLOSED", closed_at=None, created_at=None,
               entry_price=100.0, stop_loss=95.0, quantity=2.0, symbol="BTCUSDT"):
    stamp = datetime(2026, 11, 14, 0, 0, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=1,
        symbol=symbol,
        side="BUY",
        status=status,
        realized_pnl=pnl,
        entry_price=entry_price,
        stop_loss=stop_loss,
        quantity=quantity,
        created_at=created_at or stamp - timedelta(hours=2),
        closed_at=closed_at or stamp - timedelta(hours=1),
    )


def test_all_history_excludes_open_missing_and_future_dated_rows():
    now = datetime(2026, 11, 14, 0, 0, tzinfo=timezone.utc)
    trades = [
        make_trade(pnl=12.0, closed_at=now - timedelta(minutes=5)),
        make_trade(pnl=999.0, status="OPEN"),
        make_trade(pnl=None),
        make_trade(pnl=500.0, closed_at=now + timedelta(seconds=1)),
    ]

    result = advanced_performance(trades, now=now)

    assert result["total_trades"] == 1
    assert result["net_pnl"] == 12.0
    assert result["wins"] == 1


def test_rolling_period_includes_exact_boundary_and_excludes_older_and_future_rows():
    now = datetime(2026, 11, 14, 0, 0, tzinfo=timezone.utc)
    trades = [
        make_trade(pnl=10.0, closed_at=now - timedelta(days=7)),
        make_trade(pnl=20.0, closed_at=now - timedelta(days=7, microseconds=1)),
        make_trade(pnl=30.0, closed_at=now + timedelta(minutes=1)),
    ]

    result = advanced_performance(trades, period_days=7, now=now)

    assert result["total_trades"] == 1
    assert result["net_pnl"] == 10.0


def test_naive_database_timestamps_are_treated_as_utc_for_holding_time_and_r():
    now = datetime(2026, 11, 14, 0, 0)
    trade = make_trade(
        pnl=10.0,
        created_at=now - timedelta(hours=2),
        closed_at=now - timedelta(hours=1),
        entry_price=100.0,
        stop_loss=95.0,
        quantity=2.0,
    )

    result = advanced_performance([trade], now=now)

    assert result["average_holding_minutes"] == 60.0
    assert result["average_r_multiple"] == 1.0
    assert result["r_multiple_sample"] == 1


def test_equity_curve_drawdown_and_streaks_use_closed_trade_order():
    now = datetime(2026, 11, 14, 0, 0, tzinfo=timezone.utc)
    trades = [
        make_trade(pnl=100.0, closed_at=now - timedelta(minutes=3)),
        make_trade(pnl=-150.0, closed_at=now - timedelta(minutes=2)),
        make_trade(pnl=25.0, closed_at=now - timedelta(minutes=1)),
    ]

    result = advanced_performance(trades, now=now)

    assert result["net_pnl"] == -25.0
    assert result["max_drawdown_amount"] == 150.0
    assert result["max_drawdown_percent_of_peak_pnl"] == 150.0
    assert result["max_consecutive_wins"] == 1
    assert result["max_consecutive_losses"] == 1
    assert result["equity_curve"][-1]["cumulative_pnl"] == -25.0


def test_empty_history_is_explicit_and_period_values_are_restricted():
    result = advanced_performance([], now=datetime(2026, 11, 14, tzinfo=timezone.utc))

    assert result["mode"] == "PAPER ONLY"
    assert result["total_trades"] == 0
    assert result["win_rate"] is None
    assert result["profit_factor"] is None
    assert result["max_drawdown_percent_of_peak_pnl"] is None
    with pytest.raises(ValueError, match="period_days"):
        advanced_performance([], period_days=1)
