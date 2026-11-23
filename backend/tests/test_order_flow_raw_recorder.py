from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import OrderFlowMarketEvent
from app.order_flow_raw_recorder import (
    OrderFlowRawEventError,
    load_order_flow_market_events,
    record_order_flow_market_events,
    summarize_order_flow_candles,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _events():
    session = "0123456789abcdef0123456789abcdef"
    start = 1_795_248_000_000
    events = [
        {
            "symbol": "BTCUSDT", "event_type": "aggTrade",
            "event_time_ms": start + 10_000, "received_at_ms": start + 10_100,
            "source": "WEBSOCKET", "stream_session_id": session,
            "payload": {"a": 101, "p": "90000.10", "q": "0.25", "T": start + 10_000, "m": False},
        },
        {
            "symbol": "BTCUSDT", "event_type": "depthUpdate",
            "event_time_ms": start + 10_050, "received_at_ms": start + 10_100,
            "source": "WEBSOCKET", "stream_session_id": session,
            "payload": {"U": 500, "u": 502, "E": start + 10_050, "b": [["90000.0", "1.2"]], "a": [["90000.2", "0.8"]]},
        },
        {
            "symbol": "BTCUSDT", "event_type": "depthSnapshot",
            "event_time_ms": start + 10_000, "received_at_ms": start + 10_100,
            "source": "REST_BOOTSTRAP", "stream_session_id": session,
            "payload": {"lastUpdateId": 499, "bids": [["90000", "1"]], "asks": [["90001", "2"]]},
        },
    ]
    # Live bootstrap queues the REST snapshot before buffered depth diffs.
    # Keep receive ordering explicit when both events share a millisecond.
    events[2]["received_at_ms"] = events[1]["received_at_ms"] - 1
    return events


def test_raw_event_recorder_persists_exchange_times_sequence_and_candle_bucket(db):
    events = _events()
    now = datetime.fromtimestamp((events[0]["received_at_ms"] + 1000) / 1000, timezone.utc)
    result = record_order_flow_market_events(db, events, now=now)
    assert result["stored"] == 3
    assert result["duplicates"] == 0
    rows = load_order_flow_market_events(
        db, "BTCUSDT", events[0]["event_time_ms"] - 1,
        events[0]["event_time_ms"] + 60_000,
    )
    assert len(rows) == 3
    trade = next(row for row in rows if row["event_type"] == "aggTrade")
    depth = next(row for row in rows if row["event_type"] == "depthUpdate")
    assert trade["payload"]["m"] is False
    assert trade["payload"]["a"] == 101
    assert depth["sequence_first"] == 500
    assert depth["sequence_last"] == 502
    assert depth["candle_bucket_ms"] == (events[0]["event_time_ms"] // 60_000) * 60_000
    assert depth["source"] == "WEBSOCKET"


def test_raw_event_recorder_is_idempotent_for_duplicate_trade_and_depth_ids(db):
    events = _events()
    now = datetime.fromtimestamp((events[0]["received_at_ms"] + 1000) / 1000, timezone.utc)
    first = record_order_flow_market_events(db, events, now=now)
    second = record_order_flow_market_events(db, events, now=now)
    assert first["stored"] == 3
    assert second["stored"] == 0
    assert second["duplicates"] == 3
    assert db.query(OrderFlowMarketEvent).count() == 3


@pytest.mark.parametrize("mutation", [
    lambda e: e.update(symbol="BTC/USDT"),
    lambda e: e.update(stream_session_id="bad"),
    lambda e: e.update(event_time_ms=0),
    lambda e: e.update(source="UNTRUSTED"),
    lambda e: e.update(event_type="unknown"),
    lambda e: e["payload"].update(p="NaN"),
])
def test_raw_event_recorder_rejects_invalid_market_events(db, mutation):
    event = _events()[0]
    mutation(event)
    now = datetime.fromtimestamp((event["received_at_ms"] + 1000) / 1000, timezone.utc)
    with pytest.raises(OrderFlowRawEventError):
        record_order_flow_market_events(db, [event], now=now)
    assert db.query(OrderFlowMarketEvent).count() == 0


def test_raw_event_recorder_rejects_conflicting_duplicate_ids_in_same_batch_or_database(db):
    events = _events()
    now = datetime.fromtimestamp((events[0]["received_at_ms"] + 1000) / 1000, timezone.utc)
    record_order_flow_market_events(db, events, now=now)
    conflicting = _events()[0]
    conflicting["payload"]["p"] = "90001"
    with pytest.raises(OrderFlowRawEventError, match="conflicting payload"):
        record_order_flow_market_events(db, [conflicting], now=now)
    assert db.query(OrderFlowMarketEvent).count() == 3


def test_raw_event_recorder_rejects_future_received_or_oversized_batches(db):
    event = _events()[0]
    now = datetime.fromtimestamp(event["received_at_ms"] / 1000, timezone.utc)
    event["received_at_ms"] += 10_000
    with pytest.raises(OrderFlowRawEventError, match="ahead"):
        record_order_flow_market_events(db, [event], now=now)
    with pytest.raises(OrderFlowRawEventError, match="batch"):
        record_order_flow_market_events(db, [event] * 2049, now=now)


def test_candle_summary_marks_backfilled_buckets_and_never_claims_complete(db):
    events = _events()
    events[0]["source"] = "REST_GAP_BACKFILL"
    now = datetime.fromtimestamp((events[0]["received_at_ms"] + 1000) / 1000, timezone.utc)
    record_order_flow_market_events(db, events, now=now)
    rows = summarize_order_flow_candles(
        db, "BTCUSDT", events[0]["event_time_ms"] - 60_000,
        events[0]["event_time_ms"] + 60_000,
    )
    assert len(rows) == 1
    assert rows[0]["trade_count"] == 1
    assert rows[0]["depth_update_count"] == 1
    assert rows[0]["depth_snapshot_count"] == 1
    assert rows[0]["coverage_status"] == "RECOVERED_WITH_REST_BACKFILL"
    assert "COMPLETE" not in rows[0]["coverage_status"]


def test_recorder_prunes_only_by_received_time_retention_window(db):
    events = _events()
    old_now = datetime.fromtimestamp((events[0]["received_at_ms"] + 1000) / 1000, timezone.utc)
    record_order_flow_market_events(db, events, now=old_now, retention_days=1)
    later_events = _events()
    later_events[0]["payload"]["a"] = 102
    later_events[0]["event_time_ms"] += 60_000
    later_events[0]["received_at_ms"] += 2 * 86_400_000
    later_events[0]["payload"]["T"] += 60_000
    later_events[1]["event_time_ms"] += 60_000
    later_events[1]["received_at_ms"] += 2 * 86_400_000
    later_events[1]["payload"]["E"] += 60_000
    later_events[1]["payload"]["u"] += 10
    later_events[1]["payload"]["U"] += 10
    later_events[2]["event_time_ms"] += 60_000
    later_events[2]["received_at_ms"] += 2 * 86_400_000
    later_events[2]["payload"]["lastUpdateId"] += 10
    later_now = datetime.fromtimestamp((later_events[0]["received_at_ms"] + 1000) / 1000, timezone.utc)
    record_order_flow_market_events(db, later_events, now=later_now, retention_days=1, prune_before=later_now.replace(microsecond=0) - __import__("datetime").timedelta(days=1))
    assert db.query(OrderFlowMarketEvent).count() == 3


def test_candle_summary_marks_explicit_capture_gap_as_incomplete(db):
    event = {
        "symbol": "BTCUSDT", "event_type": "captureGap",
        "event_time_ms": 1_795_248_000_000, "received_at_ms": 1_795_248_000_100,
        "source": "WEBSOCKET", "stream_session_id": "0123456789abcdef0123456789abcdef",
        "payload": {"gap_id": "abcdef0123456789abcdef0123456789", "reason": "RAW_CAPTURE_QUEUE_OVERFLOW"},
    }
    now = datetime.fromtimestamp((event["received_at_ms"] + 1000) / 1000, timezone.utc)
    record_order_flow_market_events(db, [event], now=now)
    rows = summarize_order_flow_candles(
        db, "BTCUSDT", event["event_time_ms"] - 1, event["event_time_ms"] + 60_000,
    )
    assert rows[0]["capture_gap_count"] == 1
    assert rows[0]["gap_detected"] is True
    assert rows[0]["coverage_status"] == "CAPTURE_GAP_DETECTED"


def test_raw_event_recorder_accepts_full_binance_1000_level_depth_snapshot(db):
    events = _events()
    snapshot = events[2]
    snapshot["payload"]["bids"] = [
        [f"{90_000 - index * 0.01:.2f}", f"{1 + index * 0.001:.6f}"]
        for index in range(1000)
    ]
    snapshot["payload"]["asks"] = [
        [f"{90_001 + index * 0.01:.2f}", f"{1 + index * 0.001:.6f}"]
        for index in range(1000)
    ]
    import json
    assert len(json.dumps(snapshot["payload"], separators=(",", ":")).encode("utf-8")) > 16_384
    now = datetime.fromtimestamp((snapshot["received_at_ms"] + 1000) / 1000, timezone.utc)
    result = record_order_flow_market_events(db, [snapshot], now=now)
    assert result["stored"] == 1
    rows = load_order_flow_market_events(
        db, "BTCUSDT", snapshot["event_time_ms"] - 1, snapshot["event_time_ms"] + 60_000,
    )
    assert len(rows) == 1
    assert len(rows[0]["payload"]["bids"]) == 1000
    assert len(rows[0]["payload"]["asks"]) == 1000

def test_candle_summary_detects_aggtrade_and_depth_sequence_gaps(db):
    events = _events()
    trade_gap = {
        **events[0],
        "event_time_ms": events[0]["event_time_ms"] + 200,
        "received_at_ms": events[0]["received_at_ms"] + 200,
        "payload": {**events[0]["payload"], "a": 103, "T": events[0]["event_time_ms"] + 200},
    }
    depth_gap = {
        **events[1],
        "event_time_ms": events[1]["event_time_ms"] + 300,
        "received_at_ms": events[1]["received_at_ms"] + 300,
        "payload": {
            **events[1]["payload"],
            "U": 504,
            "u": 505,
            "E": events[1]["event_time_ms"] + 300,
        },
    }
    events.extend([trade_gap, depth_gap])
    now = datetime.fromtimestamp((events[0]["received_at_ms"] + 2000) / 1000, timezone.utc)
    record_order_flow_market_events(db, events, now=now)
    rows = summarize_order_flow_candles(
        db, "BTCUSDT", events[0]["event_time_ms"] - 1,
        events[0]["event_time_ms"] + 60_000,
    )
    row = rows[0]
    assert row["trade_id_gap_count"] == 1
    assert row["depth_sequence_gap_count"] == 1
    assert row["coverage_status"] == "DATA_SEQUENCE_GAP_DETECTED"
    assert row["gap_detected"] is True
    assert "AGGTRADE_ID_GAP" in row["gap_reasons"]
    assert "DEPTH_SEQUENCE_GAP" in row["gap_reasons"]
    assert row["coverage_is_complete"] is False


def test_candle_summary_rejects_unbridged_depth_snapshot_sequence(db):
    events = _events()
    events[1]["payload"]["U"] = 501
    now = datetime.fromtimestamp((events[0]["received_at_ms"] + 1000) / 1000, timezone.utc)
    record_order_flow_market_events(db, events, now=now)
    row = summarize_order_flow_candles(
        db, "BTCUSDT", events[0]["event_time_ms"] - 1,
        events[0]["event_time_ms"] + 60_000,
    )[0]
    assert row["depth_baseline_validated"] is False
    assert row["depth_sequence_gap_count"] == 1
    assert "DEPTH_SNAPSHOT_BRIDGE_GAP" in row["gap_reasons"]
    assert row["coverage_status"] == "DATA_SEQUENCE_GAP_DETECTED"


def test_candle_summary_tracks_session_boundaries_and_rest_backfill(db):
    events = _events()
    second_session = "fedcba9876543210fedcba9876543210"
    trade = {
        **events[0],
        "event_time_ms": events[0]["event_time_ms"] + 200,
        "received_at_ms": events[0]["received_at_ms"] + 200,
        "source": "REST_GAP_BACKFILL",
        "stream_session_id": second_session,
        "payload": {**events[0]["payload"], "a": 102, "T": events[0]["event_time_ms"] + 200},
    }
    snapshot = {
        **events[2],
        "event_time_ms": events[2]["event_time_ms"] + 250,
        "received_at_ms": events[2]["received_at_ms"] + 250,
        "stream_session_id": second_session,
        "payload": {**events[2]["payload"], "lastUpdateId": 503},
    }
    depth = {
        **events[1],
        "event_time_ms": events[1]["event_time_ms"] + 300,
        "received_at_ms": events[1]["received_at_ms"] + 300,
        "stream_session_id": second_session,
        "payload": {
            **events[1]["payload"],
            "U": 504,
            "u": 505,
            "E": events[1]["event_time_ms"] + 300,
        },
    }
    events.extend([trade, snapshot, depth])
    now = datetime.fromtimestamp((events[0]["received_at_ms"] + 2000) / 1000, timezone.utc)
    record_order_flow_market_events(db, events, now=now)
    row = summarize_order_flow_candles(
        db, "BTCUSDT", events[0]["event_time_ms"] - 1,
        events[0]["event_time_ms"] + 60_000,
    )[0]
    assert row["session_transition_count"] == 1
    assert row["depth_session_count"] == 2
    assert row["depth_baseline_validated"] is True
    assert row["trade_id_gap_count"] == 0
    assert row["backfill_used"] is True
    assert row["source_counts"]["REST_GAP_BACKFILL"] == 1
    assert row["coverage_status"] == "MULTI_SESSION_WITH_REST_BACKFILL"
    assert row["coverage_is_complete"] is False


def test_candle_summary_reports_bounded_event_window_truncation(db):
    session = "0123456789abcdef0123456789abcdef"
    start = 1_795_248_000_000
    events = []
    for index in range(201):
        event_time = start + 10_000 + index
        events.append({
            "symbol": "BTCUSDT",
            "event_type": "aggTrade",
            "event_time_ms": event_time,
            "received_at_ms": event_time + 100,
            "source": "WEBSOCKET",
            "stream_session_id": session,
            "payload": {
                "a": 1000 + index,
                "p": "90000.10",
                "q": "0.01",
                "T": event_time,
                "m": False,
            },
        })
    now = datetime.fromtimestamp((events[-1]["received_at_ms"] + 1000) / 1000, timezone.utc)
    record_order_flow_market_events(db, events, now=now)
    row = summarize_order_flow_candles(
        db, "BTCUSDT", start - 1, start + 60_000, limit=1
    )[0]
    assert row["event_window_total_events"] == 201
    assert row["event_window_loaded_events"] == 200
    assert row["event_window_truncated"] is True
    assert row["coverage_status"] == "TRUNCATED_EVENT_WINDOW"
    assert row["coverage_is_complete"] is False


def test_candle_summary_rejects_invalid_limit(db):
    event = _events()[0]
    now = datetime.fromtimestamp((event["received_at_ms"] + 1000) / 1000, timezone.utc)
    record_order_flow_market_events(db, [event], now=now)
    with pytest.raises(ValueError, match="limit"):
        summarize_order_flow_candles(
            db, "BTCUSDT", event["event_time_ms"] - 1,
            event["event_time_ms"] + 60_000, limit=0,
        )

def test_depth_sequence_baseline_carries_across_minute_and_query_boundaries(db):
    events = _events()
    second_update = {
        **events[1],
        "event_time_ms": events[1]["event_time_ms"] + 60_000,
        "received_at_ms": events[1]["received_at_ms"] + 60_000,
        "payload": {
            **events[1]["payload"],
            "U": 503,
            "u": 504,
            "E": events[1]["event_time_ms"] + 60_000,
        },
    }
    now = datetime.fromtimestamp(
        (second_update["received_at_ms"] + 1000) / 1000, timezone.utc
    )
    record_order_flow_market_events(db, [*events, second_update], now=now)

    rows = summarize_order_flow_candles(
        db, "BTCUSDT", events[0]["event_time_ms"] - 1,
        events[0]["event_time_ms"] + 120_000,
    )
    assert len(rows) == 2
    assert rows[0]["depth_baseline_validated"] is True
    assert rows[1]["depth_baseline_validated"] is True
    assert rows[1]["depth_sequence_gap_count"] == 0
    assert "DEPTH_BASELINE_MISSING" not in rows[1]["gap_reasons"]

    # A query beginning in minute two must seed from the last validated
    # update in minute one, not compare directly against the old REST snapshot.
    second_minute = summarize_order_flow_candles(
        db, "BTCUSDT", events[0]["event_time_ms"] + 60_000,
        events[0]["event_time_ms"] + 120_000,
    )
    assert len(second_minute) == 1
    assert second_minute[0]["depth_baseline_validated"] is True
    assert second_minute[0]["coverage_status"] == "NO_DEPTH_UPDATES" or (
        second_minute[0]["coverage_status"] == "OBSERVED_PARTIAL_NOT_PROVEN_COMPLETE"
    )


def test_depth_sequence_gap_at_minute_boundary_invalidates_following_state(db):
    events = _events()
    gap_update = {
        **events[1],
        "event_time_ms": events[1]["event_time_ms"] + 60_000,
        "received_at_ms": events[1]["received_at_ms"] + 60_000,
        "payload": {
            **events[1]["payload"],
            "U": 504,
            "u": 505,
            "E": events[1]["event_time_ms"] + 60_000,
        },
    }
    later_update = {
        **gap_update,
        "event_time_ms": gap_update["event_time_ms"] + 60_000,
        "received_at_ms": gap_update["received_at_ms"] + 60_000,
        "payload": {
            **gap_update["payload"],
            "U": 506,
            "u": 507,
            "E": gap_update["event_time_ms"] + 60_000,
        },
    }
    now = datetime.fromtimestamp(
        (later_update["received_at_ms"] + 1000) / 1000, timezone.utc
    )
    record_order_flow_market_events(db, [*events, gap_update, later_update], now=now)

    rows = summarize_order_flow_candles(
        db, "BTCUSDT", events[0]["event_time_ms"] - 1,
        events[0]["event_time_ms"] + 180_000,
    )
    by_bucket = {row["candle_open_time_ms"]: row for row in rows}
    gap_bucket = (gap_update["event_time_ms"] // 60_000) * 60_000
    later_bucket = (later_update["event_time_ms"] // 60_000) * 60_000
    assert by_bucket[gap_bucket]["depth_sequence_gap_count"] == 1
    assert "DEPTH_SEQUENCE_GAP" in by_bucket[gap_bucket]["gap_reasons"]
    assert by_bucket[later_bucket]["depth_baseline_validated"] is False
    assert "DEPTH_SEQUENCE_STATE_INVALID" in by_bucket[later_bucket]["gap_reasons"]


def test_trade_id_gap_crossing_minute_boundary_is_detected(db):
    events = _events()
    next_trade = {
        **events[0],
        "event_time_ms": events[0]["event_time_ms"] + 60_000,
        "received_at_ms": events[0]["received_at_ms"] + 60_000,
        "payload": {
            **events[0]["payload"],
            "a": 103,
            "T": events[0]["event_time_ms"] + 60_000,
        },
    }
    now = datetime.fromtimestamp(
        (next_trade["received_at_ms"] + 1000) / 1000, timezone.utc
    )
    record_order_flow_market_events(db, [events[0], next_trade], now=now)
    rows = summarize_order_flow_candles(
        db, "BTCUSDT", events[0]["event_time_ms"] - 1,
        events[0]["event_time_ms"] + 120_000,
    )
    next_bucket = (next_trade["event_time_ms"] // 60_000) * 60_000
    row = next(item for item in rows if item["candle_open_time_ms"] == next_bucket)
    assert row["trade_id_gap_count"] == 1
    assert row["trade_ids_contiguous_in_observed_window"] is False
    assert "AGGTRADE_ID_GAP" in row["gap_reasons"]
    assert row["coverage_status"] == "DATA_SEQUENCE_GAP_DETECTED"

