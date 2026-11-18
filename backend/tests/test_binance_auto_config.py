import pytest
from pydantic import ValidationError
from app.binance_auto_config import (
    AutoTradingConfig, calculate_position_quantity, eligible_usdt_symbols,
    filter_by_quote_volume, safe_auto_status, select_futures_leverage,
    stable_event_id, validate_protection,
)


def test_defaults_are_disabled_testnet_and_conservative():
    cfg = AutoTradingConfig()
    assert cfg.enabled is False and cfg.environment == "BINANCE_TESTNET"
    assert cfg.futures_leverage_cap == 3 and cfg.risk_per_trade_percent == 0.5
    assert cfg.max_daily_loss_percent == 2 and cfg.dca_enabled is False


@pytest.mark.parametrize("payload", [
    {"environment": "LIVE"}, {"futures_margin_type": "CROSSED"},
    {"dca_enabled": False, "dca_max_addons": 1},
    {"futures_leverage_cap": 4}, {"risk_per_trade_percent": float("nan")},
])
def test_rejects_unsafe_configuration(payload):
    with pytest.raises(ValidationError):
        AutoTradingConfig(**payload)


def test_symbol_universe_filters_non_trading_stable_and_leveraged_tokens():
    info = {"symbols": [
        {"symbol":"BTCUSDT","status":"TRADING","quoteAsset":"USDT","baseAsset":"BTC"},
        {"symbol":"USDCUSDT","status":"TRADING","quoteAsset":"USDT","baseAsset":"USDC"},
        {"symbol":"ETHUSDT","status":"BREAK","quoteAsset":"USDT","baseAsset":"ETH"},
        {"symbol":"BTCUPUSDT","status":"TRADING","quoteAsset":"USDT","baseAsset":"BTCUP"},
    ]}
    assert eligible_usdt_symbols(info) == {"BTCUSDT"}


def test_volume_filter_rejects_non_finite_and_universe_misses():
    assert filter_by_quote_volume({"BTCUSDT"}, [
        {"symbol":"BTCUSDT","quoteVolume":"11000000"},
        {"symbol":"ETHUSDT","quoteVolume":"50000000"},
        {"symbol":"BTCUSDT","quoteVolume":"NaN"},
    ], 10_000_000) == {"BTCUSDT"}


def test_position_size_is_stop_risk_based_and_step_rounded():
    qty = calculate_position_quantity(equity=1000, risk_percent=0.5, entry=100,
                                     stop=99, step_size="0.001", min_qty="0.001")
    assert qty == 5
    assert float(qty) * 1 <= 5


def test_position_size_rejects_exchange_minimum_that_breaks_risk_budget():
    with pytest.raises(ValueError):
        calculate_position_quantity(equity=100, risk_percent=0.1, entry=100,
                                    stop=90, step_size="1", min_qty="1")


def test_leverage_is_clamped_to_symbol_and_global_limit():
    assert select_futures_leverage(20, 3) == 3
    assert select_futures_leverage(2, 3) == 2
    assert select_futures_leverage(1, 10) == 1


def test_stop_target_geometry_and_rr():
    validate_protection("BUY", 100, 98, 104, 2)
    validate_protection("SELL", 100, 102, 96, 2)
    with pytest.raises(ValueError):
        validate_protection("BUY", 100, 101, 104)
    with pytest.raises(ValueError):
        validate_protection("BUY", 100, 98, 101)


def test_telegram_event_identifier_is_deterministic():
    a = stable_event_id(2, "ORDER", "123", "FILLED")
    assert a == stable_event_id(2, "ORDER", "123", "FILLED")
    assert a != stable_event_id(2, "ORDER", "123", "CANCELED")


def test_auto_start_stays_blocked_until_every_gate_passes():
    result = safe_auto_status(AutoTradingConfig(enabled=True), spot_verified=True,
        futures_verified=True, worker_ready=True, protection_ready=False)
    assert result["ready"] is False and result["enabled"] is False
