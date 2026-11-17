from datetime import date, datetime, timezone

import pytest

from app.binance_order_flow_state import (
    AggTradeCvdState,
    BinanceSpotDepthBook,
    OrderFlowStateError,
)


def agg_trade(trade_id, price, quantity, *, day=17, hour=12, minute=0, buyer_is_maker=False):
    stamp = datetime(2026, 11, day, hour, minute, tzinfo=timezone.utc)
    return {
        "a": trade_id,
        "p": str(price),
        "q": str(quantity),
        "T": int(stamp.timestamp() * 1000),
        "m": buyer_is_maker,
    }


def test_aggtrade_state_computes_session_delta_and_cvd_from_known_anchor():
    state = AggTradeCvdState("BTCUSDT")
    state.begin_utc_session(100, date(2026, 11, 17))

    assert state.ingest(agg_trade(100, 100, 2, buyer_is_maker=False)) == "APPLIED"
    assert state.ingest(agg_trade(101, 101, 1, buyer_is_maker=True)) == "APPLIED"

    snapshot = state.snapshot()
    assert snapshot["cvd_status"] == "COMPLETE_SINCE_STATE_SEED"
    assert snapshot["cvd_value"] == 1.0
    assert snapshot["session_delta"] == 1.0
    assert snapshot["session_quote_delta"] == 99.0
    assert snapshot["last_agg_trade_id"] == 101
    assert snapshot["session_delta_coverage_complete"] is True


def test_aggtrade_duplicate_and_out_of_order_events_do_not_double_count():
    state = AggTradeCvdState("ETHUSDT")
    state.begin_utc_session(50, date(2026, 11, 17))
    row = agg_trade(50, 10, 3)

    assert state.ingest(row) == "APPLIED"
    assert state.ingest(row) == "DUPLICATE"
    assert state.ingest(agg_trade(49, 10, 7)) == "OUT_OF_ORDER"
    snapshot = state.snapshot()
    assert snapshot["cvd_value"] == 3.0
    assert snapshot["applied_trade_count"] == 1
    assert snapshot["duplicate_count"] == 2


def test_aggtrade_gap_invalidates_cvd_until_contiguous_backfill_recovers():
    state = AggTradeCvdState("BTCUSDT")
    state.begin_utc_session(100, date(2026, 11, 17))
    state.ingest(agg_trade(100, 100, 1))

    assert state.ingest(agg_trade(102, 100, 5)) == "GAP_DETECTED"
    assert state.snapshot()["cvd_value"] is None
    assert state.ingest(agg_trade(103, 100, 7)) == "GAP_PENDING"

    assert state.apply_backfill([
        agg_trade(101, 100, 2),
        agg_trade(102, 100, 3),
        agg_trade(103, 100, 4),
    ]) == "RECOVERED"
    snapshot = state.snapshot()
    assert snapshot["gap_detected"] is False
    assert snapshot["cvd_value"] == 10.0
    assert snapshot["session_delta"] == 10.0
    assert snapshot["last_agg_trade_id"] == 103


def test_aggtrade_partial_backfill_keeps_state_incomplete_until_gap_closes():
    state = AggTradeCvdState("BTCUSDT")
    state.begin_utc_session(10, date(2026, 11, 17))
    state.ingest(agg_trade(10, 100, 1))
    state.ingest(agg_trade(13, 100, 1))

    assert state.apply_backfill([agg_trade(11, 100, 1)]) == "BACKFILL_INCOMPLETE"
    assert state.snapshot()["cvd_value"] is None
    assert state.apply_backfill([agg_trade(12, 100, 1), agg_trade(13, 100, 1)]) == "RECOVERED"
    assert state.snapshot()["cvd_value"] == 4.0


def test_aggtrade_utc_rollover_keeps_cvd_scope_but_marks_new_session_incomplete():
    state = AggTradeCvdState("BTCUSDT")
    state.begin_utc_session(100, date(2026, 11, 17))
    state.ingest(agg_trade(100, 100, 2, day=17, hour=23, minute=59))
    state.ingest(agg_trade(101, 100, 3, day=18, hour=0, minute=0))

    snapshot = state.snapshot()
    assert snapshot["cvd_value"] == 5.0
    assert snapshot["session_date_utc"] == "2026-11-18"
    assert snapshot["session_delta"] is None
    assert snapshot["session_delta_coverage_complete"] is False


def test_aggtrade_state_started_without_session_anchor_is_explicitly_incomplete():
    state = AggTradeCvdState("SOLUSDT")
    assert state.ingest(agg_trade(500, 150, 1)) == "APPLIED"
    snapshot = state.snapshot()
    assert snapshot["cvd_value"] is None
    assert snapshot["session_delta"] is None
    assert snapshot["cvd_status"] == "INCOMPLETE_STREAM_START"


def test_depth_snapshot_bridges_buffered_events_and_applies_zero_quantity_deletes():
    book = BinanceSpotDepthBook()
    result = book.load_snapshot(
        100,
        [["100.0", "2"], ["99.9", "1"]],
        [["100.1", "3"], ["100.2", "1"]],
        buffered_events=[
            {"U": 99, "u": 100, "b": [["100.0", "5"]], "a": []},
            {"U": 99, "u": 101, "b": [["100.0", "4"]], "a": []},
        ],
    )
    assert result == "SNAPSHOT_BRIDGED"
    assert book.snapshot()["sequence_validated"] is True
    assert book.snapshot()["last_update_id"] == 101

    assert book.apply_diff({"U": 102, "u": 102, "b": [], "a": [["100.1", "0"]]}) == "APPLIED"
    snapshot = book.snapshot()
    assert snapshot["asks"][0] == ["100.2", "1"]
    assert snapshot["last_update_id"] == 102


def test_depth_gap_invalidates_book_and_requires_fresh_snapshot():
    book = BinanceSpotDepthBook()
    assert book.load_snapshot(200, [["100", "2"]], [["100.1", "2"]]) == "SNAPSHOT_READY"
    assert book.apply_diff({"U": 202, "u": 202, "b": [], "a": []}) == "GAP_DETECTED"
    assert book.snapshot()["valid"] is False
    assert book.apply_diff({"U": 203, "u": 203, "b": [], "a": []}) == "RESYNC_REQUIRED"

    assert book.load_snapshot(202, [["100", "2"]], [["100.1", "2"]]) == "SNAPSHOT_READY"
    assert book.apply_diff({"U": 203, "u": 203, "b": [["100", "3"]], "a": []}) == "APPLIED"
    assert book.snapshot()["sequence_validated"] is True


def test_depth_update_that_crosses_book_invalidates_state():
    book = BinanceSpotDepthBook()
    book.load_snapshot(10, [["100", "2"]], [["100.1", "2"]])
    assert book.apply_diff({"U": 11, "u": 11, "b": [["100.2", "1"]], "a": []}) == "INVALID_BOOK"
    assert book.snapshot()["valid"] is False


def test_depth_snapshot_rejects_crossed_or_malformed_levels():
    book = BinanceSpotDepthBook()
    with pytest.raises(OrderFlowStateError, match="crossed"):
        book.load_snapshot(10, [["100.2", "2"]], [["100.1", "2"]])
    with pytest.raises(OrderFlowStateError, match="decimal"):
        book.load_snapshot(10, [["bad", "2"]], [["100.1", "2"]])
