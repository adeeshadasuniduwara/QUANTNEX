import pytest
from app.phase07_engine import calculate_risk, market_info

def test_phase07_market_catalog_normalizes_symbols():
    assert market_info("btcusdt")["kind"] == "crypto"
    assert market_info("XAUUSD")["twelve"] == "XAU/USD"
    assert market_info("eurusd")["label"] == "Euro / US Dollar"

def test_phase07_rejects_unknown_market():
    with pytest.raises(ValueError, match="Unsupported symbol"):
        market_info("DOGEUSD")

def test_risk_calculator_returns_position_units_not_broker_lots():
    result=calculate_risk(10000,1,2000,1990)
    assert result["risk_amount"] == 100
    assert result["estimated_units"] == 10
    assert "Broker lot size" in result["note"]

@pytest.mark.parametrize("args",[
    (0,1,100,90),(10000,0,100,90),(10000,6,100,90),
    (10000,1,0,90),(10000,1,100,100)
])
def test_risk_calculator_rejects_invalid_inputs(args):
    with pytest.raises(ValueError):
        calculate_risk(*args)
