from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app import signal_engine


AS_OF = datetime(2026, 1, 15, 8, 0, tzinfo=timezone.utc)


def _closed_candles(interval_minutes: int, count: int = 320) -> list[dict]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index in range(count):
        stamp = start + timedelta(minutes=index * interval_minutes)
        rows.append({
            "time": stamp.isoformat(),
            "open": 100.4,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1000.0,
        })
    return rows


def _analysis(side: str) -> dict:
    bullish = side == "BUY"
    structure = {
        "bos_mss": "BULLISH" if bullish else "BEARISH",
        "liquidity_sweep": "BULLISH" if bullish else "BEARISH",
        "bullish_fvg": {"low": 100.4, "high": 100.6} if bullish else None,
        "bearish_fvg": {"low": 100.4, "high": 100.6} if not bullish else None,
        "bullish_order_block": None,
        "bearish_order_block": None,
        "bullish_breaker_block": None,
        "bearish_breaker_block": None,
        "bullish_ifvg": None,
        "bearish_ifvg": None,
        "premium_discount": "DISCOUNT" if bullish else "PREMIUM",
        "swing_low": 99.0,
        "swing_high": 102.0,
    }
    return {
        "bias": "BULLISH" if bullish else "BEARISH",
        "close": 100.5,
        "ema20": 100.4 if bullish else 100.6,
        "ema50": 100.2 if bullish else 100.8,
        "ema200": 100.0 if bullish else 101.0,
        "macd_histogram": 0.1 if bullish else -0.1,
        "rsi": 55.0 if bullish else 45.0,
        "adx": 25.0,
        "atr": 1.0,
        "structure": structure,
    }


def _execution_context() -> dict:
    return {
        "symbol": "BTCUSDT",
        "provider": "Deterministic Binance Spot replay fixture",
        "best_bid": 100.49,
        "best_ask": 100.51,
        "mid_price": 100.5,
        "spread_bps": 2.0,
        "bid_depth_quote": 20_000.0,
        "ask_depth_quote": 20_000.0,
        "bid_depth_usd": 20_000.0,
        "ask_depth_usd": 20_000.0,
        "quote_asset": "USDT",
        "quote_asset_usd_rate": 1.0,
        "quote_asset_usd_rate_source": "stablecoin_parity_assumption",
        "tick_size": "0.01",
        "price_filter": {
            "tick_size": "0.01",
            "min_price": "0.01",
            "max_price": "1000000",
        },
        "step_size": "0.001",
        "min_quantity": "0.001",
        "min_notional": "5",
        "order_types": ["MARKET", "LIMIT"],
        "market_order_constraints_valid": True,
        "limit_order_constraints_valid": True,
        "observed_at": AS_OF.isoformat(),
        "is_replay": True,
    }


def _order_flow(side: str, *, trade_age: float = 1.0, contradict: bool = False) -> dict:
    direction = -1.0 if (side == "BUY") == contradict else 1.0
    imbalance = direction * 0.25
    return {
        "market_type": "BINANCE_SPOT",
        "trade_count": 20,
        "trade_data_age_seconds": trade_age,
        "buy_volume": 15.0 if imbalance > 0 else 5.0,
        "sell_volume": 5.0 if imbalance > 0 else 15.0,
        "delta": 10.0 if imbalance > 0 else -10.0,
        "delta_ratio": imbalance,
        "window_cumulative_delta": 10.0 if imbalance > 0 else -10.0,
        "window_delta_scope": "LATEST_AGGTRADE_RESPONSE_WINDOW",
        "cvd_value": 10.0 if imbalance > 0 else -10.0,
        "cvd_status": "COMPLETE_SINCE_STATE_SEED",
        "cvd_scope": "SINCE_STATE_SEED",
        "session_timezone": "UTC",
        "session_delta": None,
        "session_delta_scope": "INCOMPLETE_UTC_SESSION_SAMPLE",
        "session_delta_coverage_complete": False,
        "order_book": {
            "best_bid": 100.49,
            "best_ask": 100.51,
            "mid_price": 100.5,
            "spread_bps": 2.0,
            "bid_depth_quote": 20_000.0,
            "ask_depth_quote": 20_000.0,
            "depth_imbalance": imbalance,
            "microprice": 100.5,
            "microprice_displacement_bps": 0.0,
            "source": "BINANCE_SPOT_SEQUENCE_VALIDATED_DEPTH_STREAM",
        },
        "footprint": [],
        "volume_profile": {
            "status": "AVAILABLE",
            "source": "BINANCE_SPOT_AGGTRADES",
            "scope": "LATEST_AGGTRADE_INPUT_WINDOW",
            "poc": 100.0,
            "val": 99.0,
            "vah": 101.0,
            "price_location": "INSIDE_VALUE_AREA",
            "candle_volume_used": False,
        },
        "data_provenance": {
            "trade_source": "Deterministic Binance Spot aggTrade fixture",
            "book_source": "Deterministic sequence-validated depth fixture",
            "bid_ask_semantics": "Aggressor-side inferred trade delta; not consolidated quoted bid/ask volume.",
            "candle_volume_used": False,
        },
        "data_sources": {
            "trades": "fixture://binance-aggtrades",
            "depth": "fixture://binance-depth",
        },
        "feed_mode": "DETERMINISTIC_FIXTURE",
        "depth_is_continuous": True,
        "depth_snapshot_update_id": 123456,
        "depth_observed_at": AS_OF.isoformat(),
        "quality": "OBSERVED_AGGRESSOR_DELTA_AND_SEQUENCE_VALIDATED_L2",
    }


def _run(side: str, *, order_flow: dict | None = None) -> dict:
    candles = {
        "5": _closed_candles(5),
        "60": _closed_candles(60),
    }
    settings = {
        "primary": "5",
        "trend": "60",
        "enabled": ["5", "60"],
        "min_score": 6,
    }
    return asyncio.run(signal_engine.build_signal(
        settings,
        "BTCUSDT",
        candles_override=candles,
        execution_context_override=_execution_context(),
        order_flow_override=order_flow if order_flow is not None else _order_flow(side),
        replay_as_of=AS_OF,
    ))


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_build_signal_generates_end_to_end_long_and_short_from_orderflow_fixtures(monkeypatch, side):
    monkeypatch.setattr(signal_engine, "inspect_tf", lambda _rows: _analysis(side))

    result = _run(side)
    signal = result["signal"]

    assert result["status"] == "SIGNAL"
    assert signal is not None
    assert signal["market_type"] == "BINANCE_SPOT"
    assert signal["symbol"] == "BTCUSDT"
    assert signal["side"] == side
    assert signal["entry_type"] == "MARKET"
    assert signal["entry_price"] == signal["entry"]
    assert signal["entry_expires_at"] is not None
    assert signal["execution_quality"]["accepted"] is True
    assert signal["risk_distance"] > 0
    assert signal["order_flow"]["status"] == "CONFIRMED"
    assert signal["order_flow"]["accepted"] is True
    assert signal["order_flow"]["volume_profile"]["poc"] == 100.0
    assert signal["strategy_evidence"]["supporting"]
    assert result["quality_filters"]["order_flow_confirmation"] is True

    if side == "BUY":
        assert signal["stop_loss"] < signal["entry"] < signal["tp1"] < signal["tp2"] < signal["tp3"]
    else:
        assert signal["stop_loss"] > signal["entry"] > signal["tp1"] > signal["tp2"] > signal["tp3"]


def test_build_signal_waits_when_orderflow_contradicts_a_qualified_long_setup(monkeypatch):
    monkeypatch.setattr(signal_engine, "inspect_tf", lambda _rows: _analysis("BUY"))

    result = _run("BUY", order_flow=_order_flow("BUY", contradict=True))

    assert result["status"] == "WAIT"
    assert result["signal"] is None
    assert result["order_flow"]["status"] == "CONTRADICTED"
    assert result["order_flow"]["accepted"] is False
    assert result["quality_filters"]["order_flow_confirmation"] is False


def test_build_signal_waits_when_orderflow_trade_data_is_stale(monkeypatch):
    monkeypatch.setattr(signal_engine, "inspect_tf", lambda _rows: _analysis("BUY"))

    result = _run("BUY", order_flow=_order_flow("BUY", trade_age=16.0))

    assert result["status"] == "WAIT"
    assert result["signal"] is None
    assert result["order_flow"]["status"] == "ERROR"
    assert result["order_flow"]["accepted"] is False
    assert result["quality_filters"]["order_flow_confirmation"] is False
