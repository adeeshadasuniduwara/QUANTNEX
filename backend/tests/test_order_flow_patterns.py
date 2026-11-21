import pytest

from app.order_flow_patterns import detect_order_flow_patterns


def snapshot(delta_ratio, depth_imbalance, trade_count=100):
    return {
        "market_type": "BINANCE_SPOT",
        "feed_mode": "PUBLIC_WEBSOCKET_STREAM",
        "depth_is_continuous": True,
        "data_provenance": {"candle_volume_used": False},
        "delta_ratio": delta_ratio,
        "trade_count": trade_count,
        "trade_data_age_seconds": 1.0,
        "last_trade_at": "2026-11-21T12:00:05+00:00",
        "depth_age_seconds": 1.0,
        "order_book": {"depth_imbalance": depth_imbalance},
    }


def test_detects_buy_absorption_from_aggressive_selling_and_bid_support():
    result = detect_order_flow_patterns(
        "BUY",
        {"time": "2026-11-21T12:00:00+00:00", "open": 100, "high": 103, "low": 99, "close": 102.5},
        snapshot(-0.55, 0.30),
    )
    assert result["status"] == "BUY_ABSORPTION"
    assert result["direction"] == "BUY"
    assert result["accepted_for_side"] is True
    assert len(result["evidence"]) == 3


def test_detects_sell_absorption_and_flags_buy_setup_conflict():
    result = detect_order_flow_patterns(
        "BUY",
        {"time": "2026-11-21T12:00:00+00:00", "open": 102, "high": 103, "low": 99, "close": 99.5},
        snapshot(0.55, -0.30),
    )
    assert result["status"] == "SELL_ABSORPTION"
    assert result["direction"] == "SELL"
    assert result["accepted_for_side"] is False


def test_detects_sell_exhaustion_only_with_observed_trade_count_baseline():
    candle = {"time": "2026-11-21T12:00:00+00:00", "open": 100, "high": 105, "low": 99, "close": 101}
    result = detect_order_flow_patterns("SELL", candle, snapshot(0.60, -0.05, 100), baseline_trade_count=40)
    assert result["status"] == "SELL_EXHAUSTION"
    assert result["accepted_for_side"] is True


def test_exhaustion_is_not_guessed_without_enough_historical_baseline():
    result = detect_order_flow_patterns(
        "SELL",
        {"time": "2026-11-21T12:00:00+00:00", "open": 100, "high": 105, "low": 99, "close": 101},
        snapshot(0.60, -0.05, 100),
    )
    assert result["status"] == "NO_PATTERN"
    assert "baseline" in result["reason"]


def test_detects_buy_exhaustion_after_aggressive_selling_spike():
    result = detect_order_flow_patterns(
        "BUY",
        {"time": "2026-11-21T12:00:00+00:00", "open": 104, "high": 105, "low": 99, "close": 103},
        snapshot(-0.60, 0.05, 100),
        baseline_trade_count=40,
    )
    assert result["status"] == "BUY_EXHAUSTION"
    assert result["accepted_for_side"] is True


def test_pattern_classifier_rejects_unverified_or_stale_order_flow():
    invalid = snapshot(0.6, -0.3)
    invalid["depth_is_continuous"] = False
    with pytest.raises(ValueError, match="sequence-validated"):
        detect_order_flow_patterns("SELL", {"time": "2026-11-21T12:00:00+00:00", "open": 100, "high": 101, "low": 99, "close": 100}, invalid)

    stale = snapshot(0.6, -0.3)
    stale["depth_age_seconds"] = 9
    with pytest.raises(ValueError, match="stale"):
        detect_order_flow_patterns("SELL", {"time": "2026-11-21T12:00:00+00:00", "open": 100, "high": 101, "low": 99, "close": 100}, stale)


def test_pattern_classifier_rejects_candle_volume_substitution():
    invalid = snapshot(0.6, -0.3)
    invalid["data_provenance"]["candle_volume_used"] = True
    with pytest.raises(ValueError, match="provenance"):
        detect_order_flow_patterns("SELL", {"time": "2026-11-21T12:00:00+00:00", "open": 100, "high": 101, "low": 99, "close": 100}, invalid)
