import hashlib
import hmac
from urllib.parse import urlencode

import pytest
from pydantic import ValidationError

from app.binance_demo import (
    BinanceRiskSettings,
    _signed_params,
    router,
)


def test_binance_signature_is_valid_hmac_sha256():
    params = _signed_params("demo-secret")
    signature = params.pop("signature")
    expected = hmac.new(
        b"demo-secret", urlencode(params).encode(), hashlib.sha256
    ).hexdigest()
    assert hmac.compare_digest(signature, expected)
    assert "timestamp" in params
    assert params["recvWindow"] == "5000"


def test_risk_defaults_are_conservative_and_bounded():
    settings = BinanceRiskSettings()
    assert settings.max_trades_per_day == 1
    assert settings.max_open_trades == 1
    assert settings.risk_per_trade_percent == 0.5
    assert settings.max_daily_loss_percent == 2


@pytest.mark.parametrize(
    "payload",
    [
        {"max_trades_per_day": 0},
        {"max_trades_per_day": 51},
        {"max_open_trades": 0},
        {"risk_per_trade_percent": 2.01},
        {"max_daily_loss_percent": 5.01},
        {"risk_per_trade_percent": float("nan")},
    ],
)
def test_risk_settings_reject_unsafe_values(payload):
    with pytest.raises(ValidationError):
        BinanceRiskSettings(**payload)


def test_binance_router_exposes_only_demo_connection_and_control_routes():
    paths = {route.path for route in router.routes}
    assert "/api/v1/exchanges/binance/connect" in paths
    assert "/api/v1/exchanges/binance/status" in paths
    assert "/api/v1/exchanges/binance/test" in paths
    assert "/api/v1/exchanges/binance/risk" in paths
    assert "/api/v1/exchanges/binance/auto-trading" in paths
    # This release deliberately has no order-placement route.
    assert not any("order" in path or "trade" in path for path in paths)
