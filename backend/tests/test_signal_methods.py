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
    assert result["unique_category_counts"]["SELL"] == 1
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
        "TREND", "MOMENTUM", "STRUCTURE", "LIQUIDITY", "LOCATION",
    }
