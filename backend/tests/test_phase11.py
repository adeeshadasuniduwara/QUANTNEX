from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import pytest
from app.phase11_engine import advanced_performance

NOW=datetime(2026,11,12,12,0,tzinfo=timezone.utc)
def trade(i,pnl,symbol="BTCUSDT",side="BUY",minutes=60,entry=100,stop=90,qty=1,status="CLOSED",closed=None):
    opened=NOW-timedelta(days=2,minutes=minutes)
    return SimpleNamespace(id=i,status=status,realized_pnl=pnl,symbol=symbol,side=side,
        entry_price=entry,stop_loss=stop,quantity=qty,created_at=opened,
        closed_at=closed or NOW-timedelta(days=1)+timedelta(minutes=i))

def test_advanced_metrics_and_expectancy():
    rows=[trade(1,20),trade(2,-10),trade(3,0)]
    r=advanced_performance(rows,now=NOW)
    assert r["total_trades"]==3 and r["wins"]==1 and r["losses"]==1 and r["breakeven"]==1
    assert r["net_pnl"]==10
    assert r["profit_factor"]==2
    assert round(r["expectancy_per_trade"],5)==round(10/3,5)
    assert r["average_r_multiple"]==pytest.approx(1/3)

def test_equity_curve_drawdown_and_streaks():
    rows=[trade(1,10),trade(2,-15),trade(3,-5),trade(4,20)]
    r=advanced_performance(rows,now=NOW)
    assert r["max_drawdown_amount"]==20
    assert r["max_consecutive_losses"]==2
    assert r["max_consecutive_wins"]==1
    assert r["equity_curve"][-1]["cumulative_pnl"]==10

def test_symbol_breakdown_and_daily_aggregation():
    rows=[trade(1,10,"BTCUSDT"),trade(2,-5,"XAUUSD")]
    r=advanced_performance(rows,now=NOW)
    assert r["by_symbol"]["BTCUSDT"]["net_pnl"]==10
    assert r["by_symbol"]["XAUUSD"]["net_pnl"]==-5
    assert len(r["daily_pnl"])==1

def test_open_trades_and_missing_realized_values_are_excluded():
    rows=[trade(1,10),trade(2,99,status="OPEN"),trade(3,None)]
    assert advanced_performance(rows,now=NOW)["total_trades"]==1

def test_period_filter_uses_closed_time():
    recent=trade(1,10,closed=NOW-timedelta(days=3))
    old=trade(2,20,closed=NOW-timedelta(days=40))
    assert advanced_performance([recent,old],30,NOW)["total_trades"]==1

@pytest.mark.parametrize("period",[1,14,400,-1])
def test_unsupported_period_rejected(period):
    with pytest.raises(ValueError): advanced_performance([],period,NOW)

def test_zero_loss_profit_factor_is_explicitly_infinite():
    r=advanced_performance([trade(1,5)],now=NOW)
    assert r["profit_factor"]=="infinite"

def test_zero_risk_trade_has_no_r_multiple():
    r=advanced_performance([trade(1,5,entry=100,stop=100)],now=NOW)
    assert r["r_multiple_sample"]==0 and r["average_r_multiple"] is None
