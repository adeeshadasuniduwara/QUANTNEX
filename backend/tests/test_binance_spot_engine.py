import hashlib
import hmac
from urllib.parse import parse_qs, urlsplit

import pytest

from app.binance_spot_engine import (
    SPOT_DEMO_BASE,
    _floor_step,
    _round_price,
    _signed_query,
    _validate_geometry,
    normalize_config,
)


def test_spot_engine_is_pinned_to_binance_demo_host():
    assert SPOT_DEMO_BASE == "https://demo-api.binance.com"
    assert "testnet" not in SPOT_DEMO_BASE
    assert "api.binance.com" not in SPOT_DEMO_BASE.replace("demo-api.binance.com", "")


def test_signed_query_uses_hmac_sha256():
    query = _signed_query("demo-secret", {"symbol": "BTCUSDT", "side": "BUY"})
    values = parse_qs(query)
    signature = values.pop("signature")[0]
    unsigned = query.split("&signature=", 1)[0]
    expected = hmac.new(b"demo-secret", unsigned.encode(), hashlib.sha256).hexdigest()
    assert hmac.compare_digest(signature, expected)
    assert values["symbol"] == ["BTCUSDT"]
    assert values["recvWindow"] == ["5000"]


def test_config_forces_demo_spot_safe_defaults_and_disables_dca():
    config = normalize_config({
        "environment": "LIVE",
        "symbols": ["btcusdt", "BTCUSDT", "ETHBUSD", "bad symbol"],
        "risk_per_trade_percent": 99,
        "dca_enabled": True,
        "max_open_trades": 99,
    })
    assert config["environment"] == "BINANCE_DEMO"
    assert config["symbols"] == ["BTCUSDT"]
    assert config["risk_per_trade_percent"] == 1
    assert config["max_open_trades"] == 3
    assert config["dca_enabled"] is False


def test_quantity_and_price_are_rounded_down_to_exchange_steps():
    assert _floor_step(0.01239, "0.001") == 0.012
    assert _round_price(12.349, "0.01") == 12.34


def test_spot_buy_requires_valid_stop_target_and_reward_risk():
    _validate_geometry(100, 95, 110, 1.5)
    with pytest.raises(ValueError):
        _validate_geometry(100, 101, 110, 1.5)
    with pytest.raises(ValueError):
        _validate_geometry(100, 95, 106, 1.5)
