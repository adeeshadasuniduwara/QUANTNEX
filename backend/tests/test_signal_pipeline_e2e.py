import asyncio
import math
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import signal_engine, telegram_worker
from app.database import Base
from app.models import User



def _order_flow_fixture(side: str, now: datetime, *, contradictory: bool = False, stale: bool = False):
    sign = -1.0 if side == "SELL" else 1.0
    if contradictory:
        sign *= -1.0
    return {
        "market_type": "BINANCE_SPOT",
        "trade_count": 12,
        "trade_data_age_seconds": 20.0 if stale else 1.0,
        "buy_volume": 8.0 if sign > 0 else 2.0,
        "sell_volume": 2.0 if sign > 0 else 8.0,
        "delta": 6.0 * sign,
        "delta_ratio": 0.6 * sign,
        "window_cumulative_delta": 6.0 * sign,
        "window_delta_scope": "LATEST_AGGTRADE_RESPONSE_WINDOW",
        "cvd_value": None,
        "cvd_status": "NOT_AVAILABLE_WITHOUT_CONTINUOUS_TRADE_STATE",
        "session_timezone": "UTC",
        "session_delta": None,
        "session_delta_scope": "RECENT_WINDOW_SAMPLE_ONLY",
        "session_delta_coverage_complete": False,
        "order_book": {
            "best_bid": 99.99, "best_ask": 100.01, "spread_bps": 2.0,
            "bid_depth_quote": 10000.0, "ask_depth_quote": 9000.0,
            "depth_imbalance": 0.25 * sign,
            "microprice": 100.001, "microprice_displacement_bps": 0.1 * sign,
            "source": "BINANCE_SPOT_L2_SNAPSHOT",
        },
        "footprint": [
            {"price": 100.0, "dominant_side": "BUY" if sign > 0 else "SELL", "is_imbalanced": True},
        ],
        "data_provenance": {
            "trade_source": "Binance Spot aggregate trades; buyer-is-maker flag infers aggressor side",
            "book_source": "BINANCE_SPOT_L2_SNAPSHOT",
            "bid_ask_semantics": "Aggressor-side inferred trade delta; not consolidated quoted bid/ask volume.",
            "candle_volume_used": False,
        },
        "data_sources": {
            "trades": "https://data-api.binance.vision",
            "depth": "https://data-api.binance.vision",
            "session_probe": "https://data-api.binance.vision",
        },
        "feed_mode": "DETERMINISTIC_FIXTURE",
        "depth_is_continuous": False,
        "depth_snapshot_update_id": 123456,
        "depth_observed_at": now.isoformat(),
        "session_start_probe_at": None,
        "quality": "OBSERVED_AGGRESSOR_DELTA_AND_L2_SNAPSHOT",
    }


def _install_order_flow_fixture(monkeypatch, side: str, *, contradictory: bool = False, stale: bool = False):
    class FixtureOrderFlowManager:
        async def get_snapshot(self, symbol, _tick_size, **_kwargs):
            snapshot = _order_flow_fixture(
                side, datetime.now(timezone.utc),
                contradictory=contradictory, stale=stale,
            )
            snapshot["feed_mode"] = "PUBLIC_WEBSOCKET_STREAM"
            snapshot["depth_is_continuous"] = True
            snapshot["order_book"]["source"] = "BINANCE_SPOT_SEQUENCE_VALIDATED_DEPTH_STREAM"
            snapshot["data_provenance"]["book_source"] = (
                "Binance Spot sequence-validated diff-depth stream"
            )
            snapshot["quality"] = "OBSERVED_AGGRESSOR_DELTA_AND_SEQUENCE_VALIDATED_L2"
            return {
                "symbol": symbol,
                "market_type": "BINANCE_SPOT",
                "status": "LIVE",
                "signal_ready": True,
                "order_flow": snapshot,
                "manager": {"active_streams": 1, "max_streams": 8},
            }

    monkeypatch.setattr(
        signal_engine,
        "get_binance_spot_order_flow_manager",
        lambda: FixtureOrderFlowManager(),
    )


def _synthetic_setup(direction: str, interval: str, now: datetime):
    rows = []
    for index in range(320):
        if direction == "BUY":
            close = 100 + 0.035 * index + 0.45 * math.sin(index * 0.42)
            previous = (100 + 0.035 * (index - 1) + 0.45 * math.sin((index - 1) * 0.42)
                        if index else close - 0.02)
        else:
            close = 150 - 0.035 * index - 0.45 * math.sin(index * 0.42)
            previous = (150 - 0.035 * (index - 1) - 0.45 * math.sin((index - 1) * 0.42)
                        if index else close + 0.02)
        open_price = previous
        rows.append({
            "open": open_price,
            "high": max(open_price, close) + 0.08,
            "low": min(open_price, close) - 0.08,
            "close": close,
            "volume": 10.0,
        })

    pivots = signal_engine.structure(rows)
    if direction == "BUY":
        swing_high, swing_low = pivots["swing_high"], pivots["swing_low"]
        rows[-2]["close"] = swing_high - 0.10
        rows[-2]["open"] = rows[-3]["close"]
        rows[-2]["high"] = max(rows[-2]["open"], rows[-2]["close"]) + 0.08
        rows[-2]["low"] = min(rows[-2]["open"], rows[-2]["close"]) - 0.08
        rows[-1]["open"] = rows[-2]["close"]
        rows[-1]["close"] = swing_high + 0.10
        rows[-1]["high"] = rows[-1]["close"] + 0.08
        rows[-1]["low"] = swing_low - 0.20
    else:
        swing_high, swing_low = pivots["swing_high"], pivots["swing_low"]
        rows[-2]["close"] = swing_low + 0.10
        rows[-2]["open"] = rows[-3]["close"]
        rows[-2]["high"] = max(rows[-2]["open"], rows[-2]["close"]) + 0.08
        rows[-2]["low"] = min(rows[-2]["open"], rows[-2]["close"]) - 0.08
        rows[-1]["open"] = rows[-2]["close"]
        rows[-1]["close"] = swing_low - 0.10
        rows[-1]["low"] = rows[-1]["close"] - 0.08
        rows[-1]["high"] = swing_high + 0.20

    seconds = signal_engine.INTERVAL_SECONDS[interval]
    last_open = now - timedelta(seconds=seconds + 30)
    first_open = last_open - timedelta(seconds=seconds * (len(rows) - 1))
    for index, row in enumerate(rows):
        row["time"] = (first_open + timedelta(seconds=seconds * index)).isoformat()
    return rows


@pytest.mark.parametrize(
    ("direction", "expected_side", "symbol", "provider"),
    [
        ("BUY", "BUY", "BTCUSDT", "Binance Spot"),
        ("SELL", "SELL", "BTCUSDT", "Coinbase Exchange fallback"),
        ("BUY", "BUY", "1000PEPEUSDT", "Binance Spot"),
        ("BUY", "BUY", "XAUUSD", "MetaTrader 5 local terminal"),
        ("SELL", "SELL", "XAUUSD", "Twelve Data"),
    ],
)
@pytest.mark.parametrize("score_mode_override", [None, "CATEGORY_BALANCED"])
def test_real_signal_pipeline_generates_and_delivers_synthetic_setup(
    monkeypatch, direction, expected_side, symbol, provider, score_mode_override
):
    now = datetime.now(timezone.utc)

    async def fake_fetch(interval, _outputsize, _symbol):
        return _synthetic_setup(direction, interval, now), provider

    async def fake_execution(_symbol):
        close = _synthetic_setup(direction, "5min", now)[-1]["close"]
        return {
            "best_bid": close - 0.005, "best_ask": close + 0.005, "mid_price": close,
            "spread_bps": 0.9, "bid_depth_quote": 20000.0, "ask_depth_quote": 20000.0,
            "tick_size": "0.01", "step_size": "0.001", "min_quantity": "0.001",
            "min_notional": "5", "order_types": ["LIMIT", "MARKET"],
            "limit_order_constraints_valid": True, "market_order_constraints_valid": True, "observed_at": now.isoformat(), "provider": "Binance Spot",
        }

    async def fake_valid_symbol(symbol):
        return symbol in {"BTCUSDT", "1000PEPEUSDT"}

    monkeypatch.setattr(signal_engine, "is_binance_spot_symbol", fake_valid_symbol)
    monkeypatch.setattr(signal_engine, "fetch_candles_with_provider", fake_fetch)
    monkeypatch.setattr(signal_engine, "get_binance_spot_execution_context", fake_execution)
    if symbol != "XAUUSD":
        _install_order_flow_fixture(monkeypatch, direction)
    settings = {
        "primary": "5",
        "trend": "60",
        "enabled": ["60", "30", "15", "5", "1"],
        "min_score": 8,
    }
    result = asyncio.run(signal_engine.build_signal(
        settings, symbol, score_mode_override=score_mode_override
    ))
    candidate = result["signal"]

    assert result["status"] == "SIGNAL"
    assert result["provider"] == provider
    assert candidate is not None
    assert candidate["side"] == expected_side
    if score_mode_override == "CATEGORY_BALANCED":
        assert candidate["score"] >= 4
        assert candidate["score"] == candidate["strategy_evidence"]["category_balanced_score"]
        assert candidate["score_mode"] == "CATEGORY_BALANCED"
        assert candidate["score_threshold"] == 4
        assert candidate["out_of"] == 5
        assert result["score_out_of"] == 5
        assert "not a calibrated probability" in result["score_note"]
    else:
        assert candidate["score"] >= 8
        assert candidate["score_mode"] == "LEGACY_RAW"
        assert candidate["score_threshold"] == 8
        assert candidate["out_of"] == 10
        assert result["score_out_of"] == 10
    assert candidate["signal_candle_time"]
    assert candidate["strategy_evidence"]["registry_version"] == 1
    assert candidate["strategy_evidence"]["supporting"]
    assert all(
        item["observed_at"] == result["generated_at"]
        for item in candidate["strategy_evidence"]["supporting"]
    )
    if score_mode_override == "CATEGORY_BALANCED":
        assert candidate["strategy_evidence"]["category_balanced_score"] <= (
            candidate["strategy_evidence"]["unique_category_count"]
        )
    else:
        assert candidate["strategy_evidence"]["unique_category_count"] <= candidate["score"]
    assert candidate["strategy_evidence"]["category_score_status"] == (
        "DIAGNOSTIC_ONLY_NOT_USED_FOR_LIVE_DECISIONS"
    )
    assert candidate["strategy_evidence"]["category_balanced_score"] == (
        result["strategy_evidence"]["category_balanced_counts"][expected_side]
    )
    assert candidate["strategy_evidence"]["category_balanced_score"] <= (
        candidate["strategy_evidence"]["unique_category_count"]
    )
    assert candidate["strategy_evidence"]["category_balanced_score_status"] == (
        "RESEARCH_DIAGNOSTIC_ONLY_ONE_VOTE_PER_UNANIMOUS_BASELINE_CATEGORY"
    )
    assert any(
        item["method_id"] == "rolling_vwap_proxy"
        for item in candidate["strategy_evidence"]["diagnostic_only"]
    )
    assert all(
        item["counts_for_baseline"] is False
        for item in candidate["strategy_evidence"]["diagnostic_only"]
    )
    assert not any("VWAP" in reason for reason in candidate["confirmations"])
    if symbol != "XAUUSD":
        assert candidate["order_flow"]["status"] == "CONFIRMED"
        assert candidate["order_flow"]["data_mode"] == "PUBLIC_WEBSOCKET_STREAM"
    assert all(result["quality_filters"].values())
    if symbol != "XAUUSD":
        assert candidate["entry_type"] == "MARKET"
        assert candidate["market_type"] == "BINANCE_SPOT"
        assert candidate["execution_quality"]["accepted"] is True

    if expected_side == "BUY":
        assert 0 < candidate["stop_loss"] < candidate["entry"] < candidate["tp1"] < candidate["tp2"] < candidate["tp3"]
    else:
        assert 0 < candidate["tp3"] < candidate["tp2"] < candidate["tp1"] < candidate["entry"] < candidate["stop_loss"]

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    user = User(email=f"signal-{direction.lower()}-{symbol.lower()}@example.test", password_hash="test-hash")
    db.add(user)
    db.commit()
    user_id = user.id
    calls = []

    async def fake_telegram_send(_client, _token, _chat_id, message):
        calls.append(message)
        return {"ok": True, "result": {"message_id": 987}}

    monkeypatch.setattr(telegram_worker, "_send", fake_telegram_send)
    key = "auto_signal_last_fingerprint_" + symbol.lower()
    fingerprint = telegram_worker._auto_signal_fingerprint(symbol, candidate)
    assert fingerprint
    previous = telegram_worker._get(db, user_id, key)
    assert asyncio.run(telegram_worker._deliver_auto_signal(
        None, "fake-token", "fake-chat", "synthetic signal", fingerprint, previous, db, user_id, key
    )) is True
    db.commit()
    assert len(calls) == 1
    assert telegram_worker._get(db, user_id, key) == fingerprint

    db.close()
    reopened = factory()
    previous_after_restart = telegram_worker._get(reopened, user_id, key)
    assert previous_after_restart == fingerprint
    assert asyncio.run(telegram_worker._deliver_auto_signal(
        None, "fake-token", "fake-chat", "duplicate synthetic signal",
        fingerprint, previous_after_restart, reopened, user_id, key
    )) is False
    assert len(calls) == 1

    reopened.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_signal_reports_all_sources_when_timeframes_use_mixed_providers(monkeypatch):
    now = datetime.now(timezone.utc)

    async def fake_fetch(interval, _outputsize, _symbol):
        provider = "Coinbase Exchange fallback" if interval == "1h" else "Binance Spot"
        return _synthetic_setup("BUY", interval, now), provider

    async def fake_execution(_symbol):
        close = _synthetic_setup("BUY", "5min", now)[-1]["close"]
        return {
            "best_bid": close - 0.005, "best_ask": close + 0.005, "mid_price": close,
            "spread_bps": 0.9, "bid_depth_quote": 20000.0, "ask_depth_quote": 20000.0,
            "tick_size": "0.01", "step_size": "0.001", "min_quantity": "0.001",
            "min_notional": "5", "order_types": ["LIMIT", "MARKET"],
            "limit_order_constraints_valid": True, "market_order_constraints_valid": True, "observed_at": now.isoformat(), "provider": "Binance Spot",
        }

    async def valid_spot_symbol(candidate):
        return candidate == "BTCUSDT"
    monkeypatch.setattr(signal_engine, "is_binance_spot_symbol", valid_spot_symbol)
    monkeypatch.setattr(signal_engine, "fetch_candles_with_provider", fake_fetch)
    monkeypatch.setattr(signal_engine, "get_binance_spot_execution_context", fake_execution)
    _install_order_flow_fixture(monkeypatch, "BUY")
    settings = {
        "primary": "5",
        "trend": "60",
        "enabled": ["60", "30", "15", "5", "1"],
        "min_score": 8,
    }
    result = asyncio.run(signal_engine.build_signal(settings, "BTCUSDT"))
    assert result["status"] == "SIGNAL"
    assert result["provider"] == "Binance Spot + Coinbase Exchange fallback"


def test_signal_reports_combined_provider_sources_for_mixed_timeframes(monkeypatch):
    now = datetime.now(timezone.utc)

    async def fake_fetch(interval, _outputsize, _symbol):
        provider = "Coinbase Exchange fallback" if interval == "1h" else "Binance Spot"
        return _synthetic_setup("BUY", interval, now), provider

    async def fake_execution(_symbol):
        close = _synthetic_setup("BUY", "5min", now)[-1]["close"]
        return {
            "best_bid": close - 0.005, "best_ask": close + 0.005, "mid_price": close,
            "spread_bps": 0.9, "bid_depth_quote": 20000.0, "ask_depth_quote": 20000.0,
            "tick_size": "0.01", "step_size": "0.001", "min_quantity": "0.001",
            "min_notional": "5", "order_types": ["LIMIT", "MARKET"],
            "limit_order_constraints_valid": True, "market_order_constraints_valid": True, "observed_at": now.isoformat(), "provider": "Binance Spot",
        }

    async def valid_spot_symbol(candidate):
        return candidate == "BTCUSDT"
    monkeypatch.setattr(signal_engine, "is_binance_spot_symbol", valid_spot_symbol)
    monkeypatch.setattr(signal_engine, "fetch_candles_with_provider", fake_fetch)
    monkeypatch.setattr(signal_engine, "get_binance_spot_execution_context", fake_execution)
    _install_order_flow_fixture(monkeypatch, "BUY")
    settings = {
        "primary": "5",
        "trend": "60",
        "enabled": ["60", "30", "15", "5", "1"],
        "min_score": 8,
    }
    result = asyncio.run(signal_engine.build_signal(settings, "BTCUSDT"))
    assert result["status"] == "SIGNAL"
    assert result["provider"] == "Binance Spot + Coinbase Exchange fallback"


def test_real_signal_pipeline_generates_a_resting_limit_at_ob_zone(monkeypatch):
    now = datetime.now(timezone.utc)

    async def fake_fetch(interval, _outputsize, _symbol):
        return _synthetic_setup("BUY", interval, now), "Binance Spot"

    zone = {"low": 101.0, "high": 101.2}
    structure = {
        "bos_mss": "BULLISH", "liquidity_sweep": "BULLISH",
        "bullish_fvg": zone, "bullish_order_block": None,
        "bullish_breaker_block": None, "bullish_ifvg": None,
        "bearish_fvg": None, "bearish_order_block": None,
        "bearish_breaker_block": None, "bearish_ifvg": None,
        "premium_discount": "DISCOUNT", "swing_low": 99.0, "swing_high": 105.0,
    }

    def bullish_analysis(_rows):
        return {
            "bias": "BULLISH", "close": 100.0, "ema20": 99.8, "ema50": 99.5,
            "ema200": 99.0, "macd_histogram": 0.2, "rsi": 55.0, "adx": 25.0,
            "atr": 2.0, "structure": structure,
        }

    async def fake_execution(_symbol):
        return {
            "best_bid": 102.0, "best_ask": 102.02, "mid_price": 102.01,
            "spread_bps": 2.0, "bid_depth_quote": 2000.0, "ask_depth_quote": 2000.0,
            "tick_size": "0.01", "step_size": "0.001", "min_quantity": "0.001",
            "min_notional": "5", "order_types": ["LIMIT", "MARKET"],
            "limit_order_constraints_valid": True, "market_order_constraints_valid": True, "observed_at": now.isoformat(), "provider": "Binance Spot",
        }

    async def valid_spot_symbol(candidate):
        return candidate == "BTCUSDT"
    monkeypatch.setattr(signal_engine, "is_binance_spot_symbol", valid_spot_symbol)
    monkeypatch.setattr(signal_engine, "fetch_candles_with_provider", fake_fetch)
    monkeypatch.setattr(signal_engine, "inspect_tf", bullish_analysis)
    monkeypatch.setattr(signal_engine, "get_binance_spot_execution_context", fake_execution)
    _install_order_flow_fixture(monkeypatch, "BUY")
    settings = {"primary": "5", "trend": "60", "enabled": ["60", "30", "15", "5", "1"], "min_score": 8}
    result = asyncio.run(signal_engine.build_signal(settings, "BTCUSDT"))
    signal = result["signal"]

    assert result["status"] == "SIGNAL"
    assert signal is not None
    assert signal["entry_type"] == "LIMIT"
    assert signal["limit_price"] == signal["entry"]
    assert signal["entry"] < 102.02
    assert signal["entry_expires_at"]
    assert "zone midpoint" in signal["entry_selection_reason"]
    assert signal["execution_quality"]["accepted"] is True


def test_signal_pipeline_explains_directional_quality_filter_rejections(monkeypatch):
    now = datetime.now(timezone.utc)

    async def fake_fetch(interval, _outputsize, _symbol):
        return _synthetic_setup("BUY", interval, now), "Binance Spot"

    zone = {"low": 101.0, "high": 101.2}
    structure = {
        "bos_mss": "BULLISH", "liquidity_sweep": "BULLISH",
        "bullish_fvg": zone, "bullish_order_block": None,
        "bullish_breaker_block": None, "bullish_ifvg": None,
        "bearish_fvg": None, "bearish_order_block": None,
        "bearish_breaker_block": None, "bearish_ifvg": None,
        "premium_discount": "DISCOUNT", "swing_low": 99.0, "swing_high": 105.0,
    }

    def analysis_with_bearish_trend(rows):
        seconds = (
            datetime.fromisoformat(rows[1]["time"])
            - datetime.fromisoformat(rows[0]["time"])
        ).total_seconds()
        return {
            "bias": "BEARISH" if seconds == 3600 else "BULLISH",
            "close": 100.0, "ema20": 99.8, "ema50": 99.5,
            "ema200": 99.0, "macd_histogram": 0.2, "rsi": 55.0,
            "adx": 25.0, "atr": 2.0, "structure": structure,
        }

    def qualifying_registry(*_args, **_kwargs):
        return {"buy_reasons": [f"BUY evidence {index}" for index in range(8)], "sell_reasons": []}

    async def valid_spot_symbol(candidate):
        return candidate == "BTCUSDT"

    monkeypatch.setattr(signal_engine, "is_binance_spot_symbol", valid_spot_symbol)
    monkeypatch.setattr(signal_engine, "fetch_candles_with_provider", fake_fetch)
    monkeypatch.setattr(signal_engine, "inspect_tf", analysis_with_bearish_trend)
    monkeypatch.setattr(signal_engine, "evaluate_strategy_registry", qualifying_registry)
    settings = {
        "primary": "5", "trend": "60",
        "enabled": ["60", "30", "15", "5", "1"], "min_score": 8,
    }

    result = asyncio.run(signal_engine.build_signal(settings, "BTCUSDT"))

    assert result["status"] == "WAIT"
    assert result["signal"] is None
    assert result["quality_filters"]["primary_bias_aligned"] is True
    assert result["quality_filters"]["trend_bias_aligned"] is False
    assert result["wait_reasons"] == [
        "Directional candidate rejected by quality filters: trend timeframe bias misaligned."
    ]
    assert result["message"] == "WAIT — " + result["wait_reasons"][0]

def test_signal_pipeline_returns_wait_when_spread_blocks_market_and_limit(monkeypatch):
    now = datetime.now(timezone.utc)

    async def fake_fetch(interval, _outputsize, _symbol):
        return _synthetic_setup("BUY", interval, now), "Binance Spot"

    zone = {"low": 101.0, "high": 101.2}
    structure = {
        "bos_mss": "BULLISH", "liquidity_sweep": "BULLISH",
        "bullish_fvg": zone, "bullish_order_block": None,
        "bullish_breaker_block": None, "bullish_ifvg": None,
        "bearish_fvg": None, "bearish_order_block": None,
        "bearish_breaker_block": None, "bearish_ifvg": None,
        "premium_discount": "DISCOUNT", "swing_low": 99.0, "swing_high": 105.0,
    }

    def bullish_analysis(_rows):
        return {
            "bias": "BULLISH", "close": 100.0, "ema20": 99.8, "ema50": 99.5,
            "ema200": 99.0, "macd_histogram": 0.2, "rsi": 55.0, "adx": 25.0,
            "atr": 2.0, "structure": structure,
        }

    async def wide_spread_execution(_symbol):
        return {
            "best_bid": 102.0, "best_ask": 102.8, "mid_price": 102.4,
            "spread_bps": 78.12, "bid_depth_quote": 50000.0, "ask_depth_quote": 50000.0,
            "tick_size": "0.01", "step_size": "0.001", "min_quantity": "0.001",
            "min_notional": "5", "order_types": ["LIMIT", "MARKET"],
            "limit_order_constraints_valid": True, "market_order_constraints_valid": True, "observed_at": now.isoformat(), "provider": "Binance Spot",
        }

    async def valid_spot_symbol(candidate):
        return candidate == "BTCUSDT"
    monkeypatch.setattr(signal_engine, "is_binance_spot_symbol", valid_spot_symbol)
    monkeypatch.setattr(signal_engine, "fetch_candles_with_provider", fake_fetch)
    monkeypatch.setattr(signal_engine, "inspect_tf", bullish_analysis)
    monkeypatch.setattr(signal_engine, "get_binance_spot_execution_context", wide_spread_execution)
    settings = {"primary": "5", "trend": "60", "enabled": ["60", "30", "15", "5", "1"], "min_score": 8}
    result = asyncio.run(signal_engine.build_signal(settings, "BTCUSDT"))

    assert result["status"] == "WAIT"
    assert result["signal"] is None
    assert result["quality_filters"]["execution_quality"] is False
    assert result["execution_quality"]["accepted"] is False
    assert "No safe MARKET entry" in result["message"]


def test_build_signal_supports_historical_replay_without_live_provider_calls(monkeypatch):
    now = datetime.now(timezone.utc)
    replay_as_of = now + timedelta(minutes=5)
    candles_by_tf = {
        tf: _synthetic_setup("BUY", interval, now)
        for tf, interval in {"60": "1h", "30": "30min", "15": "15min", "5": "5min", "1": "1min"}.items()
    }
    close = candles_by_tf["5"][-1]["close"]

    async def no_live_fetch(*_args, **_kwargs):
        raise AssertionError("Historical replay must not fetch live candles.")
    async def no_live_symbol_lookup(_symbol):
        raise AssertionError("Historical replay must not fetch live exchange metadata.")

    def bullish_analysis(_rows):
        structure = {
            "bos_mss": "BULLISH", "liquidity_sweep": "BULLISH",
            "bullish_fvg": {"low": close - 0.1, "high": close + 0.1},
            "bullish_order_block": None, "bullish_breaker_block": None,
            "bullish_ifvg": None, "bearish_fvg": None, "bearish_order_block": None,
            "bearish_breaker_block": None, "bearish_ifvg": None,
            "premium_discount": "DISCOUNT", "swing_low": close - 1.0, "swing_high": close + 1.0,
        }
        return {
            "bias": "BULLISH", "close": close, "ema20": close - 0.2, "ema50": close - 0.4,
            "ema200": close - 0.6, "macd_histogram": 0.2, "rsi": 55.0, "adx": 25.0,
            "atr": 0.5, "structure": structure,
        }

    execution = {
        "best_bid": close - 0.005, "best_ask": close + 0.005, "mid_price": close,
        "spread_bps": 0.9, "bid_depth_quote": 20000.0, "ask_depth_quote": 20000.0,
        "bid_depth_usd": 20000.0, "ask_depth_usd": 20000.0,
        "tick_size": "0.01", "step_size": "0.001", "min_quantity": "0.001",
        "min_notional": "5", "order_types": ["LIMIT", "MARKET"],
            "limit_order_constraints_valid": True, "market_order_constraints_valid": True, "observed_at": replay_as_of.isoformat(),
        "provider": "Historical Binance Spot replay", "is_replay": True,
    }

    monkeypatch.setattr(signal_engine, "fetch_candles_with_provider", no_live_fetch)
    monkeypatch.setattr(signal_engine, "is_binance_spot_symbol", no_live_symbol_lookup)
    monkeypatch.setattr(signal_engine, "inspect_tf", bullish_analysis)
    settings = {"primary": "5", "trend": "60", "enabled": ["60", "30", "15", "5", "1"], "min_score": 8}
    result = asyncio.run(signal_engine.build_signal(
        settings, "BTCUSDT", candles_override=candles_by_tf,
        execution_context_override=execution, replay_as_of=replay_as_of,
    ))

    assert result["provider"] == "Historical Binance Spot replay"
    assert result["generated_at"] == replay_as_of.isoformat()
    assert result["signal"]["entry_type"] == "MARKET"
    assert result["signal"]["entry_expires_at"] == (replay_as_of + timedelta(seconds=60)).isoformat()
    assert result["signal"]["execution_quality"]["data_mode"] == "HISTORICAL_REPLAY_ASSUMED"
    assert result["order_flow"]["status"] == "NOT_AVAILABLE_CANDLE_ONLY_REPLAY"


def test_live_signal_waits_when_order_flow_contradicts_direction(monkeypatch):
    now = datetime.now(timezone.utc)

    async def fake_fetch(interval, _outputsize, _symbol):
        return _synthetic_setup("BUY", interval, now), "Binance Spot"

    async def fake_execution(_symbol):
        close = _synthetic_setup("BUY", "5min", now)[-1]["close"]
        return {
            "best_bid": close - 0.005, "best_ask": close + 0.005, "mid_price": close,
            "spread_bps": 0.9, "bid_depth_quote": 20000.0, "ask_depth_quote": 20000.0,
            "tick_size": "0.01", "step_size": "0.001", "min_quantity": "0.001",
            "min_notional": "5", "order_types": ["LIMIT", "MARKET"],
            "limit_order_constraints_valid": True, "market_order_constraints_valid": True, "observed_at": now.isoformat(), "provider": "Binance Spot",
        }

    async def valid_symbol(candidate):
        return candidate == "BTCUSDT"

    monkeypatch.setattr(signal_engine, "is_binance_spot_symbol", valid_symbol)
    monkeypatch.setattr(signal_engine, "fetch_candles_with_provider", fake_fetch)
    monkeypatch.setattr(signal_engine, "get_binance_spot_execution_context", fake_execution)
    _install_order_flow_fixture(monkeypatch, "BUY", contradictory=True)
    settings = {"primary": "5", "trend": "60", "enabled": ["60", "30", "15", "5", "1"], "min_score": 8}

    result = asyncio.run(signal_engine.build_signal(settings, "BTCUSDT"))

    assert result["status"] == "WAIT"
    assert result["signal"] is None
    assert result["quality_filters"]["order_flow_confirmation"] is False
    assert result["order_flow"]["status"] == "CONTRADICTED"
    assert "Order Flow did not confirm BUY" in result["message"]


def test_live_signal_waits_when_order_flow_data_is_stale(monkeypatch):
    now = datetime.now(timezone.utc)

    async def fake_fetch(interval, _outputsize, _symbol):
        return _synthetic_setup("BUY", interval, now), "Binance Spot"

    async def fake_execution(_symbol):
        close = _synthetic_setup("BUY", "5min", now)[-1]["close"]
        return {
            "best_bid": close - 0.005, "best_ask": close + 0.005, "mid_price": close,
            "spread_bps": 0.9, "bid_depth_quote": 20000.0, "ask_depth_quote": 20000.0,
            "tick_size": "0.01", "step_size": "0.001", "min_quantity": "0.001",
            "min_notional": "5", "order_types": ["LIMIT", "MARKET"],
            "limit_order_constraints_valid": True, "market_order_constraints_valid": True, "observed_at": now.isoformat(), "provider": "Binance Spot",
        }

    async def valid_symbol(candidate):
        return candidate == "BTCUSDT"

    monkeypatch.setattr(signal_engine, "is_binance_spot_symbol", valid_symbol)
    monkeypatch.setattr(signal_engine, "fetch_candles_with_provider", fake_fetch)
    monkeypatch.setattr(signal_engine, "get_binance_spot_execution_context", fake_execution)
    _install_order_flow_fixture(monkeypatch, "BUY", stale=True)
    settings = {"primary": "5", "trend": "60", "enabled": ["60", "30", "15", "5", "1"], "min_score": 8}

    result = asyncio.run(signal_engine.build_signal(settings, "BTCUSDT"))

    assert result["status"] == "WAIT"
    assert result["signal"] is None
    assert result["quality_filters"]["order_flow_confirmation"] is False
    assert result["order_flow"]["status"] == "ERROR"
    assert "stale" in result["order_flow"]["error"].lower()


def test_live_candidate_waits_until_sequence_validated_orderflow_stream_is_ready(monkeypatch):
    now = datetime.now(timezone.utc)

    async def fake_fetch(interval, _outputsize, _symbol):
        return _synthetic_setup("BUY", interval, now), "Binance Spot"

    async def fake_execution(_symbol):
        close = _synthetic_setup("BUY", "5min", now)[-1]["close"]
        return {
            "best_bid": close - 0.005, "best_ask": close + 0.005, "mid_price": close,
            "spread_bps": 0.9, "bid_depth_quote": 20000.0, "ask_depth_quote": 20000.0,
            "tick_size": "0.01", "step_size": "0.001", "min_quantity": "0.001",
            "min_notional": "5", "order_types": ["LIMIT", "MARKET"],
            "limit_order_constraints_valid": True, "market_order_constraints_valid": True,
            "observed_at": now.isoformat(), "provider": "Binance Spot",
        }

    class NotReadyOrderFlowManager:
        async def get_snapshot(self, symbol, _tick_size, **_kwargs):
            return {
                "symbol": symbol,
                "market_type": "BINANCE_SPOT",
                "status": "BOOTSTRAPPING",
                "signal_ready": False,
                "order_flow": None,
                "last_error": None,
                "manager": {"active_streams": 1, "max_streams": 8},
            }

    async def fake_valid_symbol(_symbol):
        return True

    monkeypatch.setattr(signal_engine, "is_binance_spot_symbol", fake_valid_symbol)
    monkeypatch.setattr(signal_engine, "fetch_candles_with_provider", fake_fetch)
    monkeypatch.setattr(signal_engine, "get_binance_spot_execution_context", fake_execution)
    monkeypatch.setattr(
        signal_engine, "get_binance_spot_order_flow_manager",
        lambda: NotReadyOrderFlowManager(),
    )

    result = asyncio.run(signal_engine.build_signal({
        "primary": "5",
        "trend": "60",
        "enabled": ["60", "30", "15", "5", "1"],
        "min_score": 8,
    }, "BTCUSDT"))

    assert result["status"] == "WAIT"
    assert result["signal"] is None
    assert result["quality_filters"]["order_flow_confirmation"] is False
    assert result["order_flow"]["status"] == "BOOTSTRAPPING"
    assert result["order_flow"]["data_mode"] == "PUBLIC_WEBSOCKET_STREAM"
    assert "sequence-validated" in result["message"].lower()

def test_live_signal_waits_when_same_minute_recorded_auction_pattern_conflicts(monkeypatch):
    now = datetime.now(timezone.utc)

    async def fake_fetch(interval, _outputsize, _symbol):
        rows = _synthetic_setup("BUY", interval, now)
        if interval == "1min":
            last_open = now.replace(second=0, microsecond=0) - timedelta(minutes=1)
            first_open = last_open - timedelta(minutes=len(rows) - 1)
            for index, row in enumerate(rows):
                row["time"] = (first_open + timedelta(minutes=index)).isoformat()
            rows[-1].update({"open": 102.0, "high": 103.0, "low": 99.0, "close": 99.5})
        return rows, "Binance Spot"

    async def fake_execution(_symbol):
        close = _synthetic_setup("BUY", "5min", now)[-1]["close"]
        return {
            "best_bid": close - 0.005, "best_ask": close + 0.005, "mid_price": close,
            "spread_bps": 0.9, "bid_depth_quote": 20000.0, "ask_depth_quote": 20000.0,
            "tick_size": "0.01", "step_size": "0.001", "min_quantity": "0.001",
            "min_notional": "5", "order_types": ["LIMIT", "MARKET"],
            "limit_order_constraints_valid": True, "market_order_constraints_valid": True,
            "observed_at": now.isoformat(), "provider": "Binance Spot",
        }

    async def valid_symbol(candidate):
        return candidate == "BTCUSDT"

    from app import order_flow_monitor
    observed_candles = []

    def aligned_snapshot(_symbol, candle, **_kwargs):
        observed_candles.append(candle)
        candle_time = datetime.fromisoformat(candle["time"].replace("Z", "+00:00"))
        return {
            "market_type": "BINANCE_SPOT",
            "feed_mode": "PUBLIC_WEBSOCKET_STREAM",
            "depth_is_continuous": True,
            "data_provenance": {"candle_volume_used": False},
            "trade_count": 120,
            "delta_ratio": 0.60,
            "trade_data_age_seconds": 1.0,
            "last_trade_at": (candle_time + timedelta(seconds=55)).isoformat(),
            "depth_observed_at": (candle_time + timedelta(seconds=54)).isoformat(),
            "depth_age_seconds": 1.0,
            "order_book": {"depth_imbalance": -0.30},
        }

    monkeypatch.setattr(signal_engine, "is_binance_spot_symbol", valid_symbol)
    monkeypatch.setattr(signal_engine, "fetch_candles_with_provider", fake_fetch)
    monkeypatch.setattr(signal_engine, "get_binance_spot_execution_context", fake_execution)
    monkeypatch.setattr(order_flow_monitor, "get_minute_aligned_order_flow_snapshot", aligned_snapshot)
    monkeypatch.setattr(order_flow_monitor, "get_recent_trade_count_baseline", lambda *_a, **_k: None)
    _install_order_flow_fixture(monkeypatch, "BUY")

    result = asyncio.run(signal_engine.build_signal({
        "primary": "5", "trend": "60",
        "enabled": ["60", "30", "15", "5", "1"], "min_score": 8,
    }, "BTCUSDT"))

    assert observed_candles
    assert result["status"] == "WAIT"
    assert result["signal"] is None
    assert result["quality_filters"]["order_flow_pattern_confirmation"] is False
    assert result["order_flow"]["auction_patterns"]["status"] == "SELL_ABSORPTION"
    assert "conflicts with BUY" in result["message"]

