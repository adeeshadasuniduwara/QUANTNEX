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

from types import SimpleNamespace
from app.paper_worker import exit_reason

def test_paper_buy_trade_closes_at_stop_or_target():
    trade=SimpleNamespace(side="BUY",stop_loss=95,take_profit=110)
    assert exit_reason(trade,94.5)=="STOP_LOSS"
    assert exit_reason(trade,110)=="TAKE_PROFIT"
    assert exit_reason(trade,100) is None

def test_paper_sell_trade_closes_at_stop_or_target():
    trade=SimpleNamespace(side="SELL",stop_loss=105,take_profit=90)
    assert exit_reason(trade,106)=="STOP_LOSS"
    assert exit_reason(trade,89)=="TAKE_PROFIT"
    assert exit_reason(trade,100) is None

import asyncio
import app.phase07_engine as phase07_engine

def test_economic_calendar_does_not_fabricate_events_without_api_key(monkeypatch):
    monkeypatch.setattr(phase07_engine, "FINNHUB_API_KEY", "")
    result = asyncio.run(phase07_engine.get_economic_calendar(7))
    assert result["configured"] is False
    assert result["provider"] == "Finnhub"
    assert result["events"] == []
    assert "backend/.env" in result["note"]
