import asyncio
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
    from app.telegram_worker import SUBMENUS

    callbacks = [button["callback_data"] for row in SUBMENUS["qx:menu:paper"]["inline_keyboard"] for button in row]
    assert "qx:paper_start" in callbacks
    assert "qx:paper_pause" in callbacks


def test_risk_snapshot_equity_estimate_includes_floating_pnl():
    settings = normalize_settings({"paper_equity": 1000})
    result = risk_snapshot([], settings, unrealized_pnl=-75)
    assert result["paper_equity_estimate"] == 925
    assert result["unrealized_pnl_estimate"] == -75


def test_open_position_risk_snapshot_marks_current_and_unavailable_quotes(monkeypatch):
    from app import phase07_engine, phase10_engine
    from app.phase12_20_engine import open_position_risk_snapshot

    positions = [SimpleNamespace(
        status="OPEN", symbol="BTCUSDT", entry_price=100.0,
        quantity=2.0, side="BUY",
    )]

    async def quote(_symbol):
        return {"price": 90.0, "provider": "test"}

    monkeypatch.setattr(phase07_engine, "get_quote", quote)
    monkeypatch.setattr(phase10_engine, "assess_quote", lambda _quote: {"trading_safe": True})
    pnl, unpriced = asyncio.run(open_position_risk_snapshot(positions))
    assert pnl == -20.0
    assert unpriced is False

    async def unavailable(_symbol):
        raise ValueError("quote unavailable")

    monkeypatch.setattr(phase07_engine, "get_quote", unavailable)
    pnl, unpriced = asyncio.run(open_position_risk_snapshot(positions))
    assert pnl == 0.0
    assert unpriced is True


def test_paper_engine_status_includes_floating_loss_and_unpriced_guard(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app import phase12_20_engine

    client = TestClient(app)
    original = client.get("/api/v1/paper-engine").json()["settings"]
    settings = dict(original)
    settings.update({"enabled": False, "paper_equity": 1000, "max_daily_loss_percent": 2})
    saved = client.put("/api/v1/paper-engine", json=settings)
    assert saved.status_code == 200

    async def floating_loss(_trades):
        return -20.0, False

    monkeypatch.setattr(phase12_20_engine, "open_position_risk_snapshot", floating_loss)
    try:
        response = client.get("/api/v1/paper-engine")
        assert response.status_code == 200
        risk = response.json()["risk"]
        assert risk["paper_equity_estimate"] == 980
        assert risk["unrealized_pnl_estimate"] == -20
        assert risk["entry_allowed"] is False
        assert "DAILY_LOSS_LIMIT" in risk["blocks"]

        async def unpriced(_trades):
            return 0.0, True

        monkeypatch.setattr(phase12_20_engine, "open_position_risk_snapshot", unpriced)
        response = client.get("/api/v1/paper-engine")
        assert response.status_code == 200
        risk = response.json()["risk"]
        assert risk["unpriced_open_position"] is True
        assert risk["entry_allowed"] is False
        assert "UNPRICED_OPEN_POSITION_DATA" in risk["blocks"]
    finally:
        client.put("/api/v1/paper-engine", json=original)
