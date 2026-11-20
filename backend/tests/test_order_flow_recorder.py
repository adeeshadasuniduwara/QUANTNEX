from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import OrderFlowObservation
from app.order_flow_recorder import (
    is_recordable_order_flow_snapshot,
    load_order_flow_observations,
    record_order_flow_observation,
)


def _snapshot(at=None):
    stamp = (at or datetime(2026, 11, 20, 6, 0, tzinfo=timezone.utc)).isoformat()
    return {
        "symbol": "BTCUSDT",
        "market_type": "BINANCE_SPOT",
        "signal_ready": True,
        "depth_age_seconds": 0.2,
        "trade_state": {
            "last_agg_trade_id": 1001,
            "coverage_complete": True,
            "gap_detected": False,
            "cvd_value": 2.0,
            "cvd_status": "COMPLETE_SINCE_STATE_SEED",
            "cvd_scope": "SINCE_STATE_SEED",
            "session_date_utc": "2026-11-20",
            "session_delta": None,
            "session_coverage_complete": False,
            "last_trade_time_ms": 1795154400000,
            "applied_trade_count": 100,
            "duplicate_count": 0,
            "out_of_order_count": 0,
        },
        "depth_book": {
            "valid": True,
            "sequence_validated": True,
            "last_update_id": 5001,
            "bids": [["100.0", "2.0"], ["99.9", "3.0"]],
            "asks": [["100.1", "2.0"], ["100.2", "3.0"]],
        },
        "order_flow": {
            "market_type": "BINANCE_SPOT",
            "feed_mode": "PUBLIC_WEBSOCKET_STREAM",
            "depth_is_continuous": True,
            "depth_snapshot_update_id": 5001,
            "depth_observed_at": stamp,
            "last_trade_at": stamp,
            "first_trade_at": stamp,
            "trade_data_age_seconds": 0.3,
            "trade_count": 100,
            "unique_aggregate_trade_ids": 100,
            "buy_volume": 6.0,
            "sell_volume": 4.0,
            "delta": 2.0,
            "delta_ratio": 0.2,
            "window_cumulative_delta": 2.0,
            "window_delta_scope": "LATEST_AGGTRADE_RESPONSE_WINDOW",
            "cvd_value": 2.0,
            "cvd_status": "COMPLETE_SINCE_STATE_SEED",
            "cvd_scope": "SINCE_STATE_SEED",
            "quote_delta": 200.0,
            "session_timezone": "UTC",
            "session_date_utc": "2026-11-20",
            "session_delta": None,
            "session_delta_sample": 2.0,
            "session_delta_coverage_complete": False,
            "session_delta_scope": "INCOMPLETE_UTC_SESSION_SAMPLE",
            "session_start_trade_id": None,
            "footprint": [
                {"price": 100.0, "buy_volume": 5.0, "sell_volume": 1.0, "delta": 4.0},
                {"price": 100.1, "buy_volume": 1.0, "sell_volume": 3.0, "delta": -2.0},
            ],
            "volume_profile": {"poc": 100.0, "vah": 100.1, "val": 100.0},
            "order_book": {
                "best_bid": 100.0,
                "best_ask": 100.1,
                "mid_price": 100.05,
                "spread_bps": 1.0,
                "depth_imbalance": 0.1,
                "microprice": 100.02,
            },
            "data_provenance": {
                "bid_ask_semantics": "Aggressor-side inferred trade delta; not consolidated quoted bid/ask volume.",
                "candle_volume_used": False,
            },
            "data_sources": {
                "trades": "Binance Spot public aggTrades",
                "depth_snapshot": "Binance Spot public depth",
                "stream": "wss://data-stream.binance.vision",
            },
            "quality": "OBSERVED_AGGRESSOR_DELTA_AND_SEQUENCE_VALIDATED_L2",
        },
        "data_provenance": {
            "trade_side": "Binance Spot aggregate-trade buyer-is-maker flag; inferred aggressor side",
            "depth": "REST snapshot bridged to diff-depth update IDs",
            "cvd": "Complete only since bounded stream bootstrap seed",
            "session_delta": "Incomplete unless session-start anchor is available",
            "candle_volume_used": False,
        },
        "last_message_at": stamp,
    }


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_recorder_accepts_only_fresh_sequence_validated_spot_streams():
    snapshot = _snapshot()
    assert is_recordable_order_flow_snapshot(snapshot) is True

    snapshot["order_flow"]["feed_mode"] = "REST_SNAPSHOT"
    assert is_recordable_order_flow_snapshot(snapshot) is False

    snapshot = _snapshot()
    snapshot["depth_book"]["sequence_validated"] = False
    assert is_recordable_order_flow_snapshot(snapshot) is False

    snapshot = _snapshot()
    snapshot["trade_state"].pop("gap_detected")
    assert is_recordable_order_flow_snapshot(snapshot) is False

    snapshot = _snapshot()
    snapshot["order_flow"]["data_provenance"]["candle_volume_used"] = True
    assert is_recordable_order_flow_snapshot(snapshot) is False

    snapshot = _snapshot()
    snapshot["depth_age_seconds"] = 5.1
    assert is_recordable_order_flow_snapshot(snapshot) is False


def test_recorder_deduplicates_utc_minute_and_loads_chronologically_without_lookahead(db):
    start = datetime(2026, 11, 20, 6, 0, tzinfo=timezone.utc)
    snapshot = _snapshot()
    first = record_order_flow_observation(
        db, snapshot, captured_at=start + timedelta(seconds=10)
    )
    duplicate = record_order_flow_observation(
        db, snapshot, captured_at=start + timedelta(seconds=40)
    )
    later_snapshot = _snapshot(start + timedelta(minutes=1, seconds=5))
    later_snapshot["order_flow"]["delta_ratio"] = -0.4
    later_snapshot["order_flow"]["delta"] = -4.0
    later_snapshot["trade_state"]["last_agg_trade_id"] = 1002
    later_snapshot["order_flow"]["depth_snapshot_update_id"] = 5002
    later_snapshot["depth_book"]["last_update_id"] = 5002
    second = record_order_flow_observation(
        db, later_snapshot, captured_at=start + timedelta(minutes=1, seconds=10)
    )

    assert first["recorded"] is True
    assert duplicate["recorded"] is False
    assert duplicate["reason"] == "DUPLICATE_UTC_MINUTE_BUCKET"
    assert second["recorded"] is True
    assert db.query(OrderFlowObservation).count() == 2

    loaded = load_order_flow_observations(
        db,
        "BTCUSDT",
        start + timedelta(seconds=30),
        start + timedelta(minutes=2),
    )
    assert len(loaded) == 1
    assert loaded[0]["order_flow"]["delta_ratio"] == -0.4
    assert loaded[0]["depth_book"]["sequence_validated"] is True
    assert loaded[0]["order_flow"]["data_provenance"]["candle_volume_used"] is False
    assert loaded[0]["storage"]["last_agg_trade_id"] == 1002
    assert loaded[0]["trade_state"]["coverage_complete"] is True
    assert loaded[0]["trade_state"]["gap_detected"] is False
    assert loaded[0]["capture_version"] == 2


def test_recorder_prunes_old_rows_only_when_a_retention_cutoff_is_supplied(db):
    old_time = datetime(2026, 11, 1, tzinfo=timezone.utc)
    current_time = datetime(2026, 11, 20, tzinfo=timezone.utc)
    assert record_order_flow_observation(db, _snapshot(old_time), captured_at=old_time)["recorded"] is True

    current = record_order_flow_observation(
        db,
        _snapshot(current_time),
        captured_at=current_time,
        prune_before=datetime(2026, 11, 13, tzinfo=timezone.utc),
    )
    assert current["recorded"] is True
    rows = db.query(OrderFlowObservation).all()
    assert len(rows) == 1
    assert rows[0].captured_at_epoch_ms == int(current_time.timestamp() * 1000)


def test_recorder_rejects_non_finite_delta_instead_of_serializing_it(db):
    snapshot = _snapshot(datetime(2026, 11, 20, 6, 0, tzinfo=timezone.utc))
    snapshot["order_flow"]["delta_ratio"] = float("nan")
    result = record_order_flow_observation(
        db,
        snapshot,
        captured_at=datetime(2026, 11, 20, 6, 0, tzinfo=timezone.utc),
    )
    assert result["recorded"] is False
    assert result["reason"] == "SNAPSHOT_NOT_READY_OR_NOT_SEQUENCE_VALIDATED"
    assert db.query(OrderFlowObservation).count() == 0



def test_recorder_rejects_source_timestamps_after_the_capture_clock(db):
    snapshot_time = datetime(2026, 11, 20, 6, 0, tzinfo=timezone.utc)
    result = record_order_flow_observation(
        db,
        _snapshot(snapshot_time),
        captured_at=snapshot_time - timedelta(seconds=5),
    )
    assert result["recorded"] is False
    assert result["reason"] == "FUTURE_DATED_SOURCE_TIMESTAMP"
    assert db.query(OrderFlowObservation).count() == 0
