from datetime import datetime, timedelta, timezone

from app.quantnex_view_intelligence import STRATEGY_CATALOG, analyze_candles, backtest_candles


def sample_candles(count=330):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    price = 100.0
    for i in range(count):
        # Deterministic waves create both trend and pullback conditions without look-ahead.
        price += 0.08 if (i // 35) % 2 == 0 else -0.035
        rows.append({
            "time": (start + timedelta(minutes=15*i)).isoformat(),
            "open": price - 0.04, "high": price + 0.15,
            "low": price - 0.16, "close": price,
            "volume": 1000 + (i % 7) * 100,
        })
    return rows


def test_strategy_catalog_has_one_hundred_transparent_entries():
    assert len(STRATEGY_CATALOG) == 100
    assert len({item["id"] for item in STRATEGY_CATALOG}) == 100
    assert {item["family"] for item in STRATEGY_CATALOG} == {
        "Liquidity Sweep + MSS", "FVG Pullback", "Order Block Retest",
        "Breaker Block Retest", "BOS Continuation", "CHoCH Reversal",
        "Premium / Discount Reversal", "EMA Trend Pullback",
        "VWAP Reclaim / Reject", "Silver Bullet Window",
    }


def test_analysis_returns_indicators_and_never_labels_score_as_win_probability():
    result = analyze_candles(sample_candles(), "BTCUSDT", "15m")
    assert result["strategies_evaluated"] == 100
    assert result["features"]["ema200"] > 0
    assert result["features"]["rsi"] >= 0
    assert result["features"]["adx"] >= 0
    structure = result["features"]["structure"]
    assert structure["structure_event"] in {"NONE", "BULLISH_BOS", "BEARISH_BOS", "BULLISH_MSS", "BEARISH_MSS"}
    assert structure["structure_trend"] in {"BULLISH", "BEARISH", "NEUTRAL"}
    assert structure["support_zone"]["low"] < structure["support_zone"]["high"]
    assert structure["resistance_zone"]["low"] < structure["resistance_zone"]["high"]
    assert "not a measured win probability" in result["score_note"]


def test_backtest_is_single_position_per_symbol_and_reports_metrics():
    result = backtest_candles(sample_candles(330), "BTCUSDT", "15m", 10000, 1)
    assert result["one_position_per_symbol"] is True
    assert result["initial_balance"] == 10000
    assert result["trades"] == len(result["trade_history"])
    assert 0 <= result["win_rate"] <= 100
