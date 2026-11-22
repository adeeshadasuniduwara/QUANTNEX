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
    return [
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
