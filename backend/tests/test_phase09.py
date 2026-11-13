import pytest
from types import SimpleNamespace
from app.phase09_engine import calculate_position_size, portfolio_snapshot, drawdown_guard, stress_test

def test_position_size_uses_explicit_contract_multiplier():
    r=calculate_position_size(10000,1,2000,1990,1)
    assert r["risk_amount"]==100
    assert r["estimated_units"]==10
    assert "not a universal" in r["note"]

@pytest.mark.parametrize("args",[(0,1,100,90,1),(10000,0,100,90,1),(10000,1,100,100,1),(10000,1,100,90,0)])
def test_position_size_rejects_invalid_inputs(args):
    with pytest.raises(ValueError): calculate_position_size(*args)

def test_portfolio_snapshot_aggregates_open_positions_only():
    rows=[SimpleNamespace(id=1,symbol="BTCUSDT",side="BUY",quantity=2,entry_price=100,stop_loss=90,status="OPEN"),
          SimpleNamespace(id=2,symbol="BTCUSDT",side="SELL",quantity=1,entry_price=110,stop_loss=120,status="OPEN"),
          SimpleNamespace(id=3,symbol="ETHUSDT",side="BUY",quantity=1,entry_price=50,stop_loss=45,status="CLOSED")]
    r=portfolio_snapshot(rows)
    assert r["open_positions"]==2
    assert r["gross_notional_estimate"]==310
    assert r["planned_stop_risk_estimate"]==30
    assert r["symbol_concentration_percent"]["BTCUSDT"]==100

def test_guard_blocks_after_consecutive_losses():
    from datetime import datetime, timezone
    now=datetime.now(timezone.utc)
    trades=[SimpleNamespace(status="CLOSED",realized_pnl=-10,closed_at=now,created_at=now,id=i) for i in range(1,5)]
    r=drawdown_guard(trades,1000,3,8,4)
    assert r["trading_allowed"] is False
    assert "LOSS_STREAK" in r["triggers"]

def test_guard_allows_when_no_limits_breached():
    assert drawdown_guard([],1000)["trading_allowed"] is True

def test_stress_test_is_directional_and_explicit():
    rows=[SimpleNamespace(status="OPEN",side="BUY",quantity=2,entry_price=100)]
    r=stress_test(rows,{"shock":-0.1})
    assert r["scenarios"][0]["estimated_pnl_impact"]==-20


def test_drawdown_guard_reconstructs_starting_equity_from_current_equity():
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    trades = [
        SimpleNamespace(status="CLOSED", realized_pnl=100, closed_at=now-timedelta(days=2), created_at=now-timedelta(days=2), id=1),
        SimpleNamespace(status="CLOSED", realized_pnl=-200, closed_at=now-timedelta(days=1), created_at=now-timedelta(days=1), id=2),
    ]
    # Current equity is 900 after +100 then -200 from a reconstructed 1,000 start.
    # The actual peak-to-trough drawdown is 200 / 1,100 = 18.18%, not 20%.
    result = drawdown_guard(trades, 900, 3, 19, 4)
    assert result["historical_max_drawdown_percent"] == 18.1818
    assert result["trading_allowed"] is True
    blocked = drawdown_guard(trades, 900, 3, 18, 4)
    assert blocked["trading_allowed"] is False
    assert "MAX_DRAWDOWN" in blocked["triggers"]
