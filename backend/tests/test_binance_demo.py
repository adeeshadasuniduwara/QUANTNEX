import hashlib
import hmac
from urllib.parse import urlencode

import pytest
from pydantic import ValidationError

from app.binance_demo import (
    BinanceRiskSettings,
    _signed_params,
    _store_credentials,
    _get,
    router,
)
from app.database import Base
from app.models import Preference, User
from app.security import decrypt_secret
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


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



def test_spot_and_futures_credentials_are_independent_and_persistent():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with Session() as db:
        user = User(email="local@quantnex.invalid", password_hash="")
        db.add(user)
        db.commit()
        db.refresh(user)
        _store_credentials(db, user.id, "spot", "S" * 24, "s" * 24)
        db.commit()
        _store_credentials(db, user.id, "futures", "F" * 24, "f" * 24)
        db.commit()
        assert decrypt_secret(_get(db, user.id, "binance_spot_api_key_enc")) == "S" * 24
        assert decrypt_secret(_get(db, user.id, "binance_futures_api_key_enc")) == "F" * 24
    # A fresh DB session represents a backend restart / application update.
    with Session() as db:
        user = db.scalar(select(User))
        assert decrypt_secret(_get(db, user.id, "binance_spot_api_secret_enc")) == "s" * 24
        assert decrypt_secret(_get(db, user.id, "binance_futures_api_secret_enc")) == "f" * 24
        # Updating Spot must not touch the saved Futures pair.
        _store_credentials(db, user.id, "spot", "N" * 24, "n" * 24)
        db.commit()
    with Session() as db:
        user = db.scalar(select(User))
        assert decrypt_secret(_get(db, user.id, "binance_spot_api_key_enc")) == "N" * 24
        assert decrypt_secret(_get(db, user.id, "binance_futures_api_key_enc")) == "F" * 24
    engine.dispose()


def test_binance_router_has_separate_spot_and_futures_routes():
    paths = {route.path for route in router.routes}
    assert "/api/v1/exchanges/binance/connect/spot" in paths
    assert "/api/v1/exchanges/binance/connect/futures" in paths
    assert "/api/v1/exchanges/binance/test/spot" in paths
    assert "/api/v1/exchanges/binance/test/futures" in paths
    assert "/api/v1/exchanges/binance/connect/spot" in paths
