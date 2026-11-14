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


def test_gold_order_book_uses_read_only_mt5_depth_when_enabled(monkeypatch):
    monkeypatch.setattr(phase07_engine, "QUANTNEX_MT5_ENABLED", True)
    monkeypatch.setattr(phase07_engine, "QUANTNEX_MT5_GOLD_SYMBOL", "XAUUSD.a")

    async def fake_depth(symbol, limit):
        assert symbol == "XAUUSD.a"
        assert limit == 20
        return {
            "symbol": symbol, "supported": True,
            "provider": "MetaTrader 5 local terminal",
            "bids": [{"price": 2300.1, "quantity": 2.0}],
            "asks": [{"price": 2300.3, "quantity": 1.0}],
            "bid_quantity": 2.0, "ask_quantity": 1.0,
            "imbalance": 1 / 3, "timestamp": "2026-11-14T00:00:00+00:00",
            "orders_enabled": False, "note": "Broker-provided depth snapshot.",
        }

    monkeypatch.setattr("app.mt5_feed.get_order_book", fake_depth)
    result = asyncio.run(phase07_engine.get_order_book("XAUUSD"))

    assert result["supported"] is True
    assert result["provider"] == "MetaTrader 5 local terminal"
    assert result["orders_enabled"] is False


def test_gold_order_book_never_fabricates_depth_when_mt5_is_disabled(monkeypatch):
    monkeypatch.setattr(phase07_engine, "QUANTNEX_MT5_ENABLED", False)

    result = asyncio.run(phase07_engine.get_order_book("XAUUSD"))

    assert result["supported"] is False
    assert result["status"] == "unavailable"
    assert "No synthetic depth" in result["reason"]


def test_gold_order_book_reports_broker_depth_unavailable(monkeypatch):
    from app.mt5_feed import MT5FeedError

    monkeypatch.setattr(phase07_engine, "QUANTNEX_MT5_ENABLED", True)

    async def unavailable(symbol, limit):
        raise MT5FeedError("Broker does not provide Depth of Market for XAUUSD.")

    monkeypatch.setattr("app.mt5_feed.get_order_book", unavailable)
    result = asyncio.run(phase07_engine.get_order_book("XAUUSD"))

    assert result["supported"] is False
    assert "Broker does not provide Depth of Market" in result["reason"]


def test_gold_order_book_api_route_exposes_mt5_snapshot(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.setattr(phase07_engine, "QUANTNEX_MT5_ENABLED", True)

    async def fake_depth(symbol, limit):
        return {
            "symbol": symbol, "supported": True,
            "provider": "MetaTrader 5 local terminal",
            "bids": [{"price": 2300.1, "quantity": 2.0}],
            "asks": [{"price": 2300.3, "quantity": 1.0}],
            "bid_quantity": 2.0, "ask_quantity": 1.0,
            "imbalance": 1 / 3, "timestamp": "2026-11-14T00:00:00+00:00",
            "orders_enabled": False, "note": "Broker-provided depth snapshot.",
        }

    monkeypatch.setattr("app.mt5_feed.get_order_book", fake_depth)
    response = TestClient(app).get("/api/v1/intelligence/market/XAUUSD/orderbook")

    assert response.status_code == 200
    assert response.json()["supported"] is True
    assert response.json()["provider"] == "MetaTrader 5 local terminal"
    assert response.json()["orders_enabled"] is False
