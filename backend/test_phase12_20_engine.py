from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.phase12_20_engine import (
    DEFAULT_SETTINGS, normalize_settings, performance_metrics,
    risk_snapshot, walk_forward_slices,
)


def trade(status="CLOSED", pnl=0.0, day=None, symbol="BTCUSDT"):
    stamp = day or datetime(2026, 11, 13, tzinfo=timezone.utc)
    return SimpleNamespace(status=status, realized_pnl=pnl, closed_at=stamp,
                           created_at=stamp, symbol=symbol)


def test_engine_defaults_are_off_and_symbols_are_limited_to_validated_crypto():
    settings = normalize_settings({})
    assert settings["enabled"] is False
    assert settings["symbols"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def test_engine_rejects_fx_gold_until_contract_sizing_is_verified():
    with pytest.raises(ValueError, match="BTCUSDT"):
        normalize_settings({**DEFAULT_SETTINGS, "symbols": ["XAUUSD"]})


def test_risk_guard_blocks_at_daily_loss_and_open_position_limit():
    settings = normalize_settings({"paper_equity": 1000, "max_daily_loss_percent": 2,
                                   "max_open_positions": 1})
    closed = trade(pnl=-20)
    open_trade = trade(status="OPEN", pnl=0)
    result = risk_snapshot([closed, open_trade], settings,
                           datetime(2026, 11, 13, 12, tzinfo=timezone.utc))
    assert result["entry_allowed"] is False
    assert "DAILY_LOSS_LIMIT" in result["blocks"]
    assert "MAX_OPEN_POSITIONS" in result["blocks"]


def test_performance_metrics_report_paper_only_results_and_equity_curve():
    result = performance_metrics([trade(pnl=10), trade(pnl=-4), trade(pnl=0)], 1000)
    assert result["mode"] == "PAPER ONLY"
    assert result["closed_trades"] == 3
    assert result["win_rate_percent"] == pytest.approx(33.33)
    assert result["net_realized_pnl"] == 6
    assert result["equity_curve"][-1]["equity"] == 1006


def test_walk_forward_requires_enough_candles_and_keeps_holdout_separate():
    candles = [{"close": float(i)} for i in range(1, 201)]
    train, holdout = walk_forward_slices(candles)
    assert len(train) == 140
    assert len(holdout) == 60
    assert train[-1]["close"] < holdout[0]["close"]
    with pytest.raises(ValueError):
        walk_forward_slices(candles[:100])
