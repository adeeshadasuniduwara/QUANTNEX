from datetime import datetime, timezone, timedelta
import pytest
from app.order_flow import (
    OrderFlowDataError, calculate_order_book_metrics, calculate_order_flow, normalize_agg_trades,
)

NOW = datetime(2026, 11, 16, 4, 0, tzinfo=timezone.utc)


def trade(trade_id, price, qty, seconds_ago, buyer_is_maker):
    stamp = NOW - timedelta(seconds=seconds_ago)
    return {"a": trade_id, "p": str(price), "q": str(qty),
            "T": int(stamp.timestamp() * 1000), "m": buyer_is_maker, "M": True}


def test_agg_trade_buyer_maker_flag_maps_to_aggressor_side():
    rows = normalize_agg_trades([trade(1, 100, 2, 2, False), trade(2, 100, 1, 1, True)], now=NOW)
    assert [row["aggressor_side"] for row in rows] == ["BUY", "SELL"]
    assert [float(row["signed_quantity"]) for row in rows] == [2.0, -1.0]


def test_agg_trades_are_deduplicated_and_sorted_by_exchange_time():
    rows = normalize_agg_trades([
        trade(3, 102, 1, 0, False), trade(1, 100, 1, 2, True), trade(3, 102, 1, 0, False)
    ], now=NOW)
    assert [row["aggregate_trade_id"] for row in rows] == [1, 3]


def test_stale_and_future_agg_trades_fail_closed():
    with pytest.raises(OrderFlowDataError, match="stale"):
        normalize_agg_trades([trade(1, 100, 1, 60, False)], now=NOW, max_age_seconds=15)
    future = {"a": 2, "p": "100", "q": "1",
              "T": int((NOW + timedelta(seconds=10)).timestamp() * 1000), "m": False}
    with pytest.raises(OrderFlowDataError, match="future-dated"):
        normalize_agg_trades([future], now=NOW)


def test_order_flow_calculates_aggressor_delta_session_delta_and_footprint():
    rows = [trade(1, 100, 2, 3, False), trade(2, 101, 1, 2, True), trade(3, 100.4, 3, 1, False)]
    result = calculate_order_flow(
        rows, [["100", "2"], ["99.9", "1"]], [["100.1", "1"], ["100.2", "2"]],
        now=NOW, tick_size="1", session_start_trade_id=1,
    )
    assert result["buy_volume"] == 5
    assert result["sell_volume"] == 1
    assert result["delta"] == 4
    assert result["session_delta"] == 4
    assert result["session_delta_coverage_complete"] is True
    assert result["window_cumulative_delta"] == 4
    assert result["cvd_value"] is None
    assert result["quote_delta"] == pytest.approx(400.2)
    assert result["data_provenance"]["candle_volume_used"] is False
    assert result["footprint"][0]["price"] == 100
    assert result["footprint"][0]["buy_volume"] == 5
    assert result["footprint"][1]["sell_volume"] == 1


def test_order_book_metrics_measure_spread_depth_imbalance_and_microprice():
    result = calculate_order_book_metrics(
        [["100", "2"], ["99.9", "1"]], [["100.1", "1"], ["100.2", "2"]]
    )
    assert result["best_bid"] == 100
    assert result["best_ask"] == pytest.approx(100.1)
    assert result["best_bid_quantity"] == 2
    assert result["best_ask_quantity"] == 1
    assert result["best_bid_quote"] == 200
    assert result["best_ask_quote"] == pytest.approx(100.1)
    assert result["spread_bps"] == pytest.approx(9.995, rel=1e-3)
    assert result["microprice"] == pytest.approx(100.0666666667)
    assert result["depth_imbalance"] == pytest.approx((299.9 - 300.5) / (299.9 + 300.5))


def test_crossed_or_unsorted_order_books_are_rejected():
    with pytest.raises(OrderFlowDataError, match="crossed or locked"):
        calculate_order_book_metrics([["100", "1"]], [["100", "1"]])
    with pytest.raises(OrderFlowDataError, match="not price-sorted"):
        calculate_order_book_metrics([["99", "1"], ["100", "1"]], [["101", "1"]])


def test_ohlcv_volume_cannot_be_mistaken_for_observed_delta():
    with pytest.raises(OrderFlowDataError):
        normalize_agg_trades([{"open": 100, "high": 101, "low": 99, "volume": 500}], now=NOW)


def test_session_delta_is_not_claimed_complete_without_full_session_id_coverage():
    rows = [trade(1, 100, 2, 3, False), trade(3, 101, 1, 2, True)]
    result = calculate_order_flow(
        rows, [["100", "2"]], [["100.1", "1"]],
        now=NOW, tick_size="1", session_start_trade_id=1,
    )
    assert result["session_delta"] is None
    assert result["session_delta_sample"] == 1
    assert result["session_delta_coverage_complete"] is False
    assert result["session_delta_scope"] == "RECENT_WINDOW_SAMPLE_ONLY"


def test_session_delta_is_unavailable_when_latest_trade_window_started_mid_session():
    rows = [trade(10, 100, 2, 3, False), trade(11, 101, 1, 2, True)]
    result = calculate_order_flow(
        rows, [["100", "2"]], [["100.1", "1"]],
        now=NOW, tick_size="1", session_start_trade_id=1,
    )
    assert result["session_delta"] is None
    assert result["session_delta_sample"] == 1
    assert result["session_delta_coverage_complete"] is False


def test_conflicting_duplicate_aggregate_trade_ids_are_rejected():
    rows = [
        trade(1, 100, 2, 2, False),
        trade(1, 100, 3, 2, False),
    ]
    with pytest.raises(OrderFlowDataError, match="conflicting duplicate"):
        normalize_agg_trades(rows, now=NOW)


def test_negative_future_tolerance_is_rejected():
    with pytest.raises(OrderFlowDataError, match="future_tolerance_seconds"):
        normalize_agg_trades(
            [trade(1, 100, 1, 1, False)],
            now=NOW,
            future_tolerance_seconds=-1,
        )


def _order_flow_snapshot(delta_ratio=0.25, depth_imbalance=0.15, age=1.0):
    return {
        "market_type": "BINANCE_SPOT",
        "trade_count": 10,
        "trade_data_age_seconds": age,
        "delta_ratio": delta_ratio,
        "data_provenance": {
            "trade_source": "Binance Spot aggregate trades; buyer-is-maker flag infers aggressor side",
            "book_source": "BINANCE_SPOT_L2_SNAPSHOT",
            "bid_ask_semantics": "Aggressor-side inferred trade delta; not consolidated quoted bid/ask volume.",
            "candle_volume_used": False,
        },
        "data_sources": {"trades": "fixture", "depth": "fixture"},
        "depth_is_continuous": False,
        "depth_snapshot_update_id": 123,
        "depth_observed_at": NOW.isoformat(),
        "feed_mode": "DETERMINISTIC_FIXTURE",
        "order_book": {"depth_imbalance": depth_imbalance},
    }


def test_order_flow_confirmation_accepts_directionally_aligned_long_and_short():
    from app.order_flow import evaluate_order_flow_confirmation

    long_result = evaluate_order_flow_confirmation("BUY", _order_flow_snapshot(0.25, 0.15), now=NOW)
    short_result = evaluate_order_flow_confirmation("SELL", _order_flow_snapshot(-0.25, -0.15), now=NOW)

    assert long_result["status"] == "CONFIRMED"
    assert long_result["accepted"] is True
    assert long_result["support_count"] == 2
    assert short_result["status"] == "CONFIRMED"
    assert short_result["accepted"] is True
    assert short_result["support_count"] == 2


def test_order_flow_confirmation_rejects_contradicted_mixed_and_neutral_evidence():
    from app.order_flow import evaluate_order_flow_confirmation

    contradicted = evaluate_order_flow_confirmation("BUY", _order_flow_snapshot(-0.25, -0.15), now=NOW)
    mixed = evaluate_order_flow_confirmation("BUY", _order_flow_snapshot(0.25, -0.15), now=NOW)
    neutral = evaluate_order_flow_confirmation("BUY", _order_flow_snapshot(0.0, 0.0), now=NOW)

    assert contradicted["status"] == "CONTRADICTED"
    assert contradicted["accepted"] is False
    assert mixed["status"] == "MIXED"
    assert mixed["accepted"] is False
    assert neutral["status"] == "NEUTRAL"
    assert neutral["accepted"] is False


def test_order_flow_confirmation_rejects_stale_or_unproven_trade_side_data():
    from app.order_flow import evaluate_order_flow_confirmation

    with pytest.raises(OrderFlowDataError, match="stale"):
        evaluate_order_flow_confirmation("BUY", _order_flow_snapshot(age=16.0), now=NOW)
    stale_depth = _order_flow_snapshot()
    stale_depth["depth_observed_at"] = (NOW - timedelta(seconds=10)).isoformat()
    with pytest.raises(OrderFlowDataError, match="depth snapshot is stale"):
        evaluate_order_flow_confirmation("BUY", stale_depth, now=NOW)
    unproven = _order_flow_snapshot()
    unproven["data_provenance"]["candle_volume_used"] = True
    with pytest.raises(OrderFlowDataError, match="provenance"):
        evaluate_order_flow_confirmation("BUY", unproven, now=NOW)

def test_live_websocket_confirmation_requires_sequence_validated_depth():
    from app.order_flow import evaluate_order_flow_confirmation

    snapshot = _order_flow_snapshot()
    snapshot["feed_mode"] = "PUBLIC_WEBSOCKET_STREAM"
    snapshot["depth_is_continuous"] = False
    with pytest.raises(OrderFlowDataError, match="sequence-validated depth"):
        evaluate_order_flow_confirmation("BUY", snapshot, now=NOW)


def test_live_websocket_confirmation_reports_stream_seed_and_session_limitations():
    from app.order_flow import evaluate_order_flow_confirmation

    snapshot = _order_flow_snapshot()
    snapshot["feed_mode"] = "PUBLIC_WEBSOCKET_STREAM"
    snapshot["depth_is_continuous"] = True
    snapshot["cvd_status"] = "COMPLETE_SINCE_STATE_SEED"
    snapshot["cvd_scope"] = "SINCE_STATE_SEED"
    snapshot["session_delta_coverage_complete"] = False

    result = evaluate_order_flow_confirmation("BUY", snapshot, now=NOW)

    assert result["accepted"] is True
    assert any("sequence-validated" in item.lower() for item in result["limitations"])
    assert any("bootstrap seed" in item.lower() for item in result["limitations"])
    assert any("full utc session delta is unavailable" in item.lower() for item in result["limitations"])


def test_observed_trade_volume_profile_calculates_poc_value_area_and_quote_volume():
    rows = [
        trade(1, 100, 5, 4, False),
        trade(2, 101.4, 3, 3, False),
        trade(3, 102, 2, 2, True),
        trade(4, 103, 1, 1, True),
    ]
    result = calculate_order_flow(
        rows,
        [["100.6", "2"]],
        [["100.8", "2"]],
        now=NOW,
        tick_size="1",
    )

    profile = result["volume_profile"]
    assert profile["status"] == "AVAILABLE"
    assert profile["source"] == "BINANCE_SPOT_AGGTRADES"
    assert profile["scope"] == "LATEST_AGGTRADE_INPUT_WINDOW"
    assert profile["volume_unit"] == "BASE_ASSET_QUANTITY"
    assert profile["candle_volume_used"] is False
    assert profile["full_session"] is False
    assert profile["historical"] is False
    assert profile["price_bucket_count"] == 4
    assert profile["total_base_volume"] == 11
    assert profile["total_quote_volume"] == pytest.approx(1111.2)
    assert profile["poc"] == 100
    assert profile["poc_base_volume"] == 5
    assert profile["val"] == 100
    assert profile["vah"] == 101
    assert profile["value_area_target_fraction"] == 0.70
    assert profile["value_area_covered_fraction"] == pytest.approx(8 / 11)
    assert profile["price_location"] == "INSIDE_VALUE_AREA"


def test_observed_trade_volume_profile_uses_deterministic_low_price_tie_breaks():
    rows = [
        trade(1, 99, 2, 5, False),
        trade(2, 100, 5, 4, False),
        trade(3, 101, 2, 3, True),
        trade(4, 102, 5, 2, False),
    ]
    result = calculate_order_flow(
        rows,
        [["100.4", "2"]],
        [["100.6", "2"]],
        now=NOW,
        tick_size="1",
    )

    profile = result["volume_profile"]
    assert profile["poc"] == 100
    assert profile["poc_tie_break"] == "LOWEST_PRICE"
    assert profile["value_area_tie_break"] == "LOWER_PRICE_FIRST"
    assert profile["val"] == 99
    assert profile["vah"] == 102
    assert profile["value_area_covered_fraction"] == 1.0


def test_order_flow_signal_summary_preserves_observed_volume_profile_scope():
    from app.order_flow import summarize_order_flow_snapshot

    snapshot = {
        "volume_profile": {
            "source": "BINANCE_SPOT_AGGTRADES",
            "scope": "LATEST_AGGTRADE_INPUT_WINDOW",
            "poc": 100.0,
            "val": 99.0,
            "vah": 101.0,
            "candle_volume_used": False,
        }
    }
    result = summarize_order_flow_snapshot(snapshot, {"status": "CONFIRMED", "accepted": True})

    assert result["volume_profile"] == snapshot["volume_profile"]
