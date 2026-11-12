import pytest
from app.phase08_engine import ema, optimize, run_backtest, validate_strategy

def test_strategy_builder_validates_ema_order_and_risk_reward():
    assert validate_strategy({"fast_ema":8,"slow_ema":34,"risk_reward":2.5})["slow_ema"] == 34
    with pytest.raises(ValueError):
        validate_strategy({"fast_ema":21,"slow_ema":9})
    with pytest.raises(ValueError):
        validate_strategy({"fast_ema":9,"slow_ema":21,"risk_reward":12})

def test_ema_is_deterministic_and_returns_same_length():
    values=[1,2,3,4,5]
    result=ema(values,3)
    assert len(result)==len(values)
    assert result[0]==1
    assert result[-1] > result[-2]

def test_backtest_rejects_insufficient_history():
    with pytest.raises(ValueError,match="At least 60 candles"):
        run_backtest([{"open":1,"high":2,"low":1,"close":1.5}]*20,{})

def test_backtest_returns_auditable_metrics_and_limitations():
    candles=[]
    closes=[100+i*0.4 for i in range(80)]+[132-i*0.55 for i in range(80)]+[88+i*0.6 for i in range(80)]
    for i,close in enumerate(closes):
        candles.append({"time":str(i),"open":close,"high":close+1,"low":close-1,"close":close,"volume":1})
    result=run_backtest(candles,{"fast_ema":5,"slow_ema":20,"risk_reward":2})
    assert result["candle_count"]==len(candles)
    assert result["trade_count"]>=1
    assert "do not predict future" in result["limitations"].lower()
    assert all("exit_reason" in trade and "r_multiple" in trade for trade in result["trades"])

def test_optimizer_limits_search_to_explicit_parameter_grid():
    candles=[]
    for i in range(260):
        close=100+i*0.1 if i<130 else 113-(i-130)*0.08
        candles.append({"time":str(i),"open":close,"high":close+0.5,"low":close-0.5,"close":close,"volume":1})
    result=optimize(candles)
    assert result["tested"]==27
    assert len(result["ranked"])<=10
    assert "overfit" in result["warning"].lower()
