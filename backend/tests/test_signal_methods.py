import pytest

from app.signal_methods import (
    STRATEGY_METHOD_REGISTRY,
    evaluate_strategy_registry,
)


def _analysis(side: str):
    if side == "BUY":
        bias = "BULLISH"
        histogram = 0.5
        rsi = 55.0
        structure = {
            "bos_mss": "BULLISH",
            "liquidity_sweep": "BULLISH",
            "premium_discount": "DISCOUNT",
        }
    else:
        bias = "BEARISH"
        histogram = -0.5
        rsi = 40.0
        structure = {
            "bos_mss": "BEARISH",
            "liquidity_sweep": "BEARISH",
            "premium_discount": "PREMIUM",
        }
    return {
        "60": {"bias": bias},
        "30": {"bias": bias},
        "15": {"bias": bias},
        "5": {
            "bias": bias,
            "macd_histogram": histogram,
            "rsi": rsi,
            "adx": 25.0,
            "structure": structure,
        },
    }


def test_registry_preserves_legacy_bullish_confirmation_order_and_raw_count():
    result = evaluate_strategy_registry(
        _analysis("BUY"), "5", "60", in_zone=True
    )

    assert result["buy_reasons"] == [
        "60m EMA trend",
        "30m EMA trend",
        "15m EMA trend",
        "Primary MACD momentum",
        "RSI bullish range",
        "ADX trend strength",
        "Bullish BOS / MSS",
        "Sell-side liquidity sweep",
        "OB / FVG / breaker or premium-discount zone",
        "Trend timeframe aligned",
    ]
    assert result["sell_reasons"] == []
    assert result["baseline_raw_counts"] == {"BUY": 10, "SELL": 0}
    assert result["unique_category_counts"] == {"BUY": 5, "SELL": 0}
    assert result["category_score_status"] == "DIAGNOSTIC_ONLY_NOT_USED_FOR_LIVE_DECISIONS"


def test_registry_preserves_legacy_bearish_confirmation_order_and_raw_count():
    result = evaluate_strategy_registry(
        _analysis("SELL"), "5", "60", in_zone=True
    )

    assert result["sell_reasons"] == [
        "60m EMA trend",
        "30m EMA trend",
        "15m EMA trend",
        "Primary MACD momentum",
        "RSI bearish range",
        "ADX trend strength",
        "Bearish BOS / MSS",
        "Buy-side liquidity sweep",
        "OB / FVG / breaker or premium-discount zone",
        "Trend timeframe aligned",
    ]
    assert result["buy_reasons"] == []
    assert result["baseline_raw_counts"] == {"BUY": 0, "SELL": 10}
    assert result["unique_category_counts"] == {"BUY": 0, "SELL": 5}


def test_registry_keeps_conflicting_method_evidence_separate_by_side():
    analysis = {
        "60": {"bias": "BULLISH"},
        "30": {"bias": "BEARISH"},
        "15": {"bias": "NEUTRAL"},
        "5": {
            "bias": "BULLISH",
            "macd_histogram": 0.2,
            "rsi": 60.0,
            "adx": 22.0,
            "structure": {
                "bos_mss": "BEARISH",
                "liquidity_sweep": "BULLISH",
                "premium_discount": "DISCOUNT",
            },
        },
    }

    result = evaluate_strategy_registry(analysis, "5", "60", in_zone=True)
    evidence_sides = {item["side"] for item in result["evidence"]}

    assert evidence_sides == {"BUY", "SELL"}
    assert "Bearish BOS / MSS" in result["sell_reasons"]
    assert "Bullish BOS / MSS" not in result["buy_reasons"]
    assert result["unique_category_counts"]["BUY"] == 4
    assert result["unique_category_counts"]["SELL"] == 2
    assert any(item["method_id"] == "market_structure_break" and item["side"] == "SELL"
               for item in result["evidence"])


def test_registry_emits_no_directional_evidence_for_neutral_context():
    analysis = {
        "60": {"bias": "NEUTRAL"},
        "30": {"bias": "NEUTRAL"},
        "15": {"bias": "NEUTRAL"},
        "5": {
            "bias": "NEUTRAL",
            "macd_histogram": 0.0,
            "rsi": 80.0,
            "adx": 10.0,
            "structure": {
                "bos_mss": "NONE",
                "liquidity_sweep": "NONE",
                "premium_discount": "EQUILIBRIUM",
            },
        },
    }

    result = evaluate_strategy_registry(analysis, "5", "60", in_zone=False)

    assert result["evidence"] == []
    assert result["buy_reasons"] == []
    assert result["sell_reasons"] == []
    assert result["unique_category_counts"] == {"BUY": 0, "SELL": 0}


def test_registry_method_ids_are_unique_and_categories_are_explicit():
    method_ids = [method.method_id for method in STRATEGY_METHOD_REGISTRY]

    assert len(method_ids) == len(set(method_ids))
    assert {method.category for method in STRATEGY_METHOD_REGISTRY} == {
        "TREND", "MOMENTUM", "STRUCTURE", "LIQUIDITY", "LOCATION", "VALUE",
    }


def test_registry_attaches_observation_time_and_explicit_candle_provenance():
    observed_at = "2026-11-19T07:45:00+00:00"
    result = evaluate_strategy_registry(
        _analysis("BUY"), "5", "60", in_zone=True, observed_at=observed_at
    )

    assert result["evidence"]
    assert all(item["observed_at"] == observed_at for item in result["evidence"])
    assert all(item["source"] == "CANDLE_DERIVED" for item in result["evidence"])
    assert all(item["calibration"] == "UNWEIGHTED_RULE_EVIDENCE"
               for item in result["evidence"])


def _vwap_candles(direction: str, now):
    from datetime import timedelta

    rows = []
    first_open = now - timedelta(minutes=5 * 52)
    for index in range(52):
        if direction == "BUY":
            close = 100.0 + index * 0.1
            open_price = close - 0.02
        else:
            close = 120.0 - index * 0.1
            open_price = close + 0.02
        rows.append({
            "time": (first_open + timedelta(minutes=5 * index)).isoformat(),
            "open": open_price,
            "high": max(open_price, close) + 0.03,
            "low": min(open_price, close) - 0.03,
            "close": close,
            "volume": 10.0 + (index % 3),
        })
    return rows


def test_rolling_vwap_proxy_is_diagnostic_and_does_not_change_legacy_score():
    from datetime import datetime, timedelta, timezone

    observed_at = datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc)
    result = evaluate_strategy_registry(
        _analysis("BUY"), "5", "60", in_zone=True,
        observed_at=observed_at.isoformat(),
        candles=_vwap_candles("BUY", observed_at),
        as_of=observed_at + timedelta(seconds=1),
    )

    assert result["baseline_raw_counts"]["BUY"] == 10
    assert len(result["buy_reasons"]) == 10
    assert not any("VWAP" in reason for reason in result["buy_reasons"])
    assert len(result["diagnostic_only"]) == 1
    evidence = result["diagnostic_only"][0]
    assert evidence["method_id"] == "rolling_vwap_proxy"
    assert evidence["side"] == "BUY"
    assert evidence["category"] == "VALUE"
    assert evidence["decision_role"] == "DIAGNOSTIC_ONLY"
    assert evidence["counts_for_baseline"] is False
    assert evidence["source"] == "OHLCV_TYPICAL_PRICE_PROXY"
    assert evidence["observed_at"] == observed_at.isoformat()
    assert evidence["details"]["scope"] == "ROLLING_50_CLOSED_BARS"
    assert result["unique_category_counts"]["BUY"] == 6


def test_rolling_vwap_proxy_can_emit_bearish_alignment_without_changing_score():
    from datetime import datetime, timedelta, timezone

    observed_at = datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc)
    result = evaluate_strategy_registry(
        _analysis("SELL"), "5", "60", in_zone=True,
        observed_at=observed_at.isoformat(),
        candles=_vwap_candles("SELL", observed_at),
        as_of=observed_at + timedelta(seconds=1),
    )

    evidence = result["diagnostic_only"][0]
    assert evidence["method_id"] == "rolling_vwap_proxy"
    assert evidence["side"] == "SELL"
    assert result["baseline_raw_counts"]["SELL"] == 10


def test_rolling_vwap_proxy_rejects_incomplete_future_or_zero_volume_inputs():
    from datetime import datetime, timedelta, timezone

    observed_at = datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc)
    rows = _vwap_candles("BUY", observed_at)

    incomplete = evaluate_strategy_registry(
        _analysis("BUY"), "5", "60", in_zone=True,
        candles=rows, as_of=observed_at - timedelta(minutes=10),
    )
    assert incomplete["diagnostic_only"] == []

    gapped_rows = rows[:20] + rows[21:]
    gapped = evaluate_strategy_registry(
        _analysis("BUY"), "5", "60", in_zone=True,
        candles=gapped_rows, as_of=observed_at + timedelta(seconds=1),
    )
    assert gapped["diagnostic_only"] == []

    zero_volume = [dict(row, volume=0.0) for row in rows]
    no_volume = evaluate_strategy_registry(
        _analysis("BUY"), "5", "60", in_zone=True,
        candles=zero_volume, as_of=observed_at + timedelta(seconds=1),
    )
    assert no_volume["diagnostic_only"] == []



def test_category_balanced_score_caps_correlated_votes_at_one_per_category():
    result = evaluate_strategy_registry(
        _analysis("BUY"), "5", "60", in_zone=True
    )

    assert result["baseline_raw_counts"] == {"BUY": 10, "SELL": 0}
    assert result["category_balanced_counts"] == {"BUY": 5, "SELL": 0}
    assert result["category_balanced_categories"]["BUY"] == [
        "LIQUIDITY", "LOCATION", "MOMENTUM", "STRUCTURE", "TREND"
    ]
    assert result["category_balanced_methods"]["BUY"]["TREND"] == [
        "ema_trend", "ema_trend", "ema_trend", "trend_timeframe_alignment"
    ]
    assert result["category_conflicts"] == {}
    assert result["category_balanced_score_status"] == (
        "RESEARCH_DIAGNOSTIC_ONLY_ONE_VOTE_PER_UNANIMOUS_BASELINE_CATEGORY"
    )


def test_category_balanced_score_neutralizes_a_category_with_opposing_methods():
    analysis = {
        "60": {"bias": "BULLISH"},
        "30": {"bias": "BEARISH"},
        "15": {"bias": "NEUTRAL"},
        "5": {
            "bias": "BULLISH",
            "macd_histogram": 0.2,
            "rsi": 60.0,
            "adx": 22.0,
            "structure": {
                "bos_mss": "BEARISH",
                "liquidity_sweep": "BULLISH",
                "premium_discount": "DISCOUNT",
            },
        },
    }

    result = evaluate_strategy_registry(analysis, "5", "60", in_zone=True)

    assert result["category_conflicts"] == {
        "TREND": {
            "BUY": ["ema_trend", "trend_timeframe_alignment"],
            "SELL": ["ema_trend"],
        }
    }
    assert result["category_balanced_categories"]["BUY"] == [
        "LIQUIDITY", "LOCATION", "MOMENTUM"
    ]
    assert result["category_balanced_categories"]["SELL"] == ["STRUCTURE"]
    assert result["category_balanced_counts"] == {"BUY": 3, "SELL": 1}


def test_category_balanced_score_excludes_diagnostic_only_vwap_proxy():
    from datetime import datetime, timedelta, timezone

    observed_at = datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc)
    result = evaluate_strategy_registry(
        _analysis("BUY"), "5", "60", in_zone=True,
        observed_at=observed_at.isoformat(),
        candles=_vwap_candles("BUY", observed_at),
        as_of=observed_at + timedelta(seconds=1),
    )

    assert result["unique_category_counts"]["BUY"] == 6  # includes diagnostic VALUE
    assert result["category_balanced_counts"] == {"BUY": 5, "SELL": 0}
    assert "VALUE" not in result["category_balanced_categories"]["BUY"]
    assert result["category_conflicts"] == {}


def _structure_zone_analysis(side: str):
    analysis = _analysis(side)
    primary = analysis["5"]
    primary["close"] = 100.0
    structure = primary["structure"]
    if side == "BUY":
        structure.update({
            "bullish_fvg": {"low": 99.5, "high": 100.5},
            "bullish_order_block": {"low": 99.7, "high": 100.3},
            "bullish_breaker_block": {"low": 98.0, "high": 99.0},
            "support_zone": {"low": 99.8, "high": 100.2},
            "resistance_zone": {"low": 101.0, "high": 102.0},
            "premium_discount": "DISCOUNT",
            "equilibrium": 101.0,
            "swing_low": 95.0,
            "swing_high": 105.0,
        })
    else:
        structure.update({
            "bearish_fvg": {"low": 99.5, "high": 100.5},
            "bearish_order_block": {"low": 99.7, "high": 100.3},
            "bearish_breaker_block": {"low": 101.0, "high": 102.0},
            "support_zone": {"low": 98.0, "high": 99.0},
            "resistance_zone": {"low": 99.8, "high": 100.2},
            "premium_discount": "PREMIUM",
            "equilibrium": 99.0,
            "swing_low": 95.0,
            "swing_high": 105.0,
        })
    return analysis


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_structure_zone_methods_are_separate_diagnostics_without_changing_live_score(side):
    analysis = _structure_zone_analysis(side)
    result = evaluate_strategy_registry(
        analysis, "5", "60", in_zone=True,
        observed_at="2026-11-27T07:00:00+00:00",
    )

    diagnostic = result["diagnostic_only"]
    ids = {item["method_id"] for item in diagnostic}
    assert ids == {
        "fair_value_gap_zone_touch",
        "order_block_zone_overlap",
        "breaker_block_reclaim",
        "support_zone_touch" if side == "BUY" else "resistance_zone_touch",
        "premium_discount_location",
    }
    assert all(item["side"] == side for item in diagnostic)
    assert all(item["source"] == "CLOSED_OHLC_STRUCTURE" for item in diagnostic)
    assert all(item["calibration"] == "UNWEIGHTED_DIAGNOSTIC_ONLY" for item in diagnostic)
    assert all(item["counts_for_baseline"] is False for item in diagnostic)
    assert all(item["observed_at"] == "2026-11-27T07:00:00+00:00" for item in diagnostic)

    # The legacy score and its one combined location vote remain unchanged.
    assert result["baseline_raw_counts"] == (
        {"BUY": 10, "SELL": 0} if side == "BUY" else {"BUY": 0, "SELL": 10}
    )
    assert result["category_balanced_counts"] == (
        {"BUY": 5, "SELL": 0} if side == "BUY" else {"BUY": 0, "SELL": 5}
    )
    assert result["buy_reasons" if side == "BUY" else "sell_reasons"][-2] == (
        "OB / FVG / breaker or premium-discount zone"
    )
    for methods in result["category_balanced_methods"].values():
        for method_ids in methods.values():
            assert not ids.intersection(method_ids)


def test_structure_zone_diagnostics_reject_malformed_or_untouched_zones():
    analysis = _analysis("BUY")
    primary = analysis["5"]
    primary["close"] = 100.0
    primary["structure"].update({
        "bullish_fvg": {"low": 101.0, "high": 99.0},
        "bullish_order_block": {"low": float("nan"), "high": 101.0},
        "bullish_breaker_block": {"low": 101.0, "high": 102.0},
        "support_zone": {"low": 99.0, "high": 99.5},
        "resistance_zone": {"low": 101.0, "high": 102.0},
        "premium_discount": "EQUILIBRIUM",
    })

    result = evaluate_strategy_registry(analysis, "5", "60", in_zone=False)

    assert result["diagnostic_only"] == []
    assert result["baseline_raw_counts"] == {"BUY": 9, "SELL": 0}
