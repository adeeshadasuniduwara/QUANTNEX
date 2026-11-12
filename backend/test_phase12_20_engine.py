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


def test_risk_guard_includes_floating_loss_and_blocks_when_open_feed_is_unpriced():
    settings = normalize_settings({"paper_equity": 1000, "max_daily_loss_percent": 2})
    result = risk_snapshot([trade(status="OPEN")], settings,
        datetime(2026, 11, 13, 12, tzinfo=timezone.utc),
        unrealized_pnl=-21, unpriced_open_position=True)
    assert result["entry_allowed"] is False
    assert "DAILY_LOSS_LIMIT" in result["blocks"]
    assert "UNPRICED_OPEN_POSITION_DATA" in result["blocks"]


def test_daily_pdf_includes_paper_event_ledger_section():
    from datetime import date
    from app.telegram_reporting import build_daily_paper_pdf

    class EmptyDb:
        def scalars(self, _statement):
            return []

    pdf, stats = build_daily_paper_pdf(EmptyDb(), 1, date(2026, 11, 13))
    assert pdf.startswith(b"%PDF")
    assert stats["event_count"] == 0
    assert stats["automatic_entries"] == 0


def test_telegram_menu_has_explicit_paper_engine_start_and_pause_controls():
    from app.telegram_worker import MENU

    callbacks = [button["callback_data"] for row in MENU["inline_keyboard"] for button in row]
    assert "qx:paper_start" in callbacks
    assert "qx:paper_pause" in callbacks
