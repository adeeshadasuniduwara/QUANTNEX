from datetime import datetime, timezone

import pytest

from app.order_flow import evaluate_cvd_divergence


BASE_MS = 1_795_248_000_000


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def _candles(kind="bullish"):
    lows = [10, 9, 11, 10, 8, 10, 11]
    highs = [12, 11, 13, 12, 10, 12, 13]
    if kind == "bearish":
        lows = [8, 9, 10, 9, 11, 10, 12]
        highs = [10, 12, 11, 13, 12, 14, 13]
    return [
        {
            "time": _iso(BASE_MS + index * 60_000),
            "low": lows[index],
            "high": highs[index],
            "open": lows[index] + 0.5,
            "close": lows[index] + 1.0,
        }
        for index in range(len(lows))
    ]


def _checkpoints(values=None, *, missing=(), ineligible=(), seed_changes=None):
    values = values or {1: 8, 2: 10, 3: 11, 4: 13, 5: 15, 6: 16, 7: 17}
    missing = set(missing)
    ineligible = set(ineligible)
    seed_changes = seed_changes or {}
    rows = []
    for minute in range(1, 8):
        if minute in missing:
            continue
        stamp = BASE_MS + minute * 60_000
        seed_id = seed_changes.get(minute, 100)
        rows.append({
            "market_type": "BINANCE_SPOT",
            "symbol": "BTCUSDT",
            "decision_at_ms": stamp,
            "decision_at": _iso(stamp),
            "cvd_value": float(values.get(minute, minute)),
            "cvd_scope": "SINCE_CAPTURE_SEED",
            "cvd_status": "COMPLETE_SINCE_STATE_SEED",
            "capture_gap_detected": False,
            "depth_is_continuous": True,
            "coverage_status": "OBSERVED_CONTIGUOUS_CAPTURE_NOT_FULL_SESSION",
            "eligible_for_order_flow_replay": minute not in ineligible,
            "trade_state": {
                "coverage_complete": True,
                "gap_detected": False,
                "cvd_seed_trade_id": seed_id,
                "last_agg_trade_id": 100 + minute,
            },
            "depth_book": {"valid": True, "sequence_validated": True},
            "data_provenance": {
                "candle_volume_used": False,
                "bid_ask_semantics": "Aggressor-side inferred trade volume",
            },
        })
    return rows


def _evaluate(candles=None, checkpoints=None, *, decision_at_ms=None):
    return evaluate_cvd_divergence(
        candles or _candles(),
        checkpoints if checkpoints is not None else _checkpoints(),
        "BTCUSDT",
        timeframe_seconds=60,
        decision_at_ms=decision_at_ms or BASE_MS + 7 * 60_000,
        left_bars=1,
        right_bars=1,
    )


def test_confirmed_lower_price_low_with_higher_same_boundary_cvd_is_bullish():
    result = _evaluate()
    assert result["status"] == "BULLISH_DIVERGENCE"
    assert result["direction"] == "BUY"
    assert result["bullish_pivots"]["first"]["price"] == 9
    assert result["bullish_pivots"]["second"]["price"] == 8
    assert result["bullish_pivots"]["first"]["cvd_value"] == 10
    assert result["bullish_pivots"]["second"]["cvd_value"] == 15
    assert result["confirmed_at_ms"] == BASE_MS + 6 * 60_000
    assert result["coverage_is_complete"] is False


def test_confirmed_higher_price_high_with_lower_same_boundary_cvd_is_bearish():
    values = {1: 8, 2: 9, 3: 12, 4: 20, 5: 18, 6: 15, 7: 14}
    result = _evaluate(_candles("bearish"), _checkpoints(values))
    assert result["status"] == "BEARISH_DIVERGENCE"
    assert result["direction"] == "SELL"
    assert result["bearish_pivots"]["first"]["price"] == 13
    assert result["bearish_pivots"]["second"]["price"] == 14
    assert result["bearish_pivots"]["first"]["cvd_value"] == 20
    assert result["bearish_pivots"]["second"]["cvd_value"] == 15


def test_price_and_cvd_moving_in_the_same_direction_is_not_divergence():
    values = {1: 8, 2: 10, 3: 9, 4: 7, 5: 5, 6: 4, 7: 3}
    result = _evaluate(checkpoints=_checkpoints(values))
    assert result["status"] == "NO_DIVERGENCE"
    assert result["direction"] is None


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"missing": (3,)}, "continuity"),
        ({"ineligible": (4,)}, "same-boundary"),
        ({"seed_changes": {4: 200}}, "seed"),
    ],
)
def test_cvd_divergence_fails_closed_on_missing_or_invalid_intervening_checkpoints(kwargs, reason):
    checkpoints = _checkpoints(**kwargs)
    result = _evaluate(checkpoints=checkpoints)
    assert result["status"] == "UNAVAILABLE"
    assert reason in result["reason"].lower()


def test_future_checkpoint_cannot_be_used_for_a_pivot_boundary():
    checkpoints = _checkpoints()
    checkpoints = [row for row in checkpoints if row["decision_at_ms"] != BASE_MS + 5 * 60_000]
    future = _checkpoints()[4].copy()
    future["decision_at_ms"] += 1_000
    future["decision_at"] = _iso(future["decision_at_ms"])
    checkpoints.append(future)
    checkpoints.sort(key=lambda row: row["decision_at_ms"])
    result = _evaluate(checkpoints=checkpoints)
    assert result["status"] == "UNAVAILABLE"
    assert "same-boundary" in result["reason"].lower()


def test_pivot_is_not_confirmed_until_all_right_side_candles_have_closed():
    result = _evaluate(decision_at_ms=BASE_MS + 5 * 60_000)
    assert result["status"] == "NO_DIVERGENCE"
    assert result["direction"] is None


def test_naive_price_timestamps_are_rejected():
    candles = _candles()
    candles[0]["time"] = "2026-11-25T00:00:00"
    result = _evaluate(candles=candles)
    assert result["status"] == "UNAVAILABLE"
    assert "UTC timestamp" in result["reason"]


def test_checkpoint_order_and_symbol_are_validated():
    checkpoints = _checkpoints()
    checkpoints[2]["symbol"] = "ETHUSDT"
    result = _evaluate(checkpoints=checkpoints)
    assert result["status"] == "UNAVAILABLE"
    assert "match" in result["reason"].lower()
