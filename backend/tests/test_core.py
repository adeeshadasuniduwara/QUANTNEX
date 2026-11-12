import pytest
from app.schemas import RegisterRequest, TradeCreate

def test_email_is_normalized():
    assert RegisterRequest(email=" USER@example.com ", password="long-enough-password").email == "user@example.com"

def test_trade_fields_are_normalized():
    item = TradeCreate(symbol=" xauusd ", direction="BUY", outcome="Win", pnl=12.5)
    assert (item.symbol, item.direction, item.outcome) == ("XAUUSD", "buy", "win")

def test_invalid_direction_is_rejected():
    with pytest.raises(ValueError):
        TradeCreate(symbol="EURUSD", direction="hold", outcome="win", pnl=1)
