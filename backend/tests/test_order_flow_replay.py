from datetime import datetime, timezone

import pytest

from app.order_flow_replay import OrderFlowReplayError, replay_spot_order_flow_events


BASE_MS = 1_795_248_000_000
START_MS = (BASE_MS // 60_000) * 60_000
SESSION_A = "0123456789abcdef0123456789abcdef"
SESSION_B = "fedcba9876543210fedcba9876543210"


def _now(offset_ms=180_000):
    return datetime.fromtimestamp((START_MS + offset_ms) / 1000, timezone.utc)


def _event(row_id, event_type, source, event_ms, receive_ms, payload, session=SESSION_A):
    if event_type == "aggTrade":
        event_key = str(payload["a"])
    elif event_type == "depthUpdate":
        event_key = str(payload["u"])
    elif event_type == "depthSnapshot":
        event_key = str(payload["lastUpdateId"])
    else:
        event_key = payload["gap_id"]
    return {
        "id": row_id,
        "market_type": "BINANCE_SPOT",
        "symbol": "BTCUSDT",
        "event_type": event_type,
        "event_key": event_key,
        "event_time_ms": event_ms,
        "received_at_ms": receive_ms,
        "source": source,
        "stream_session_id": session,
        "payload": payload,
    }


def _book_events(*, side="BUY", second_session=False):
    if side == "BUY":
        bids = [["99.99", "10"], ["99.98", "8"]]
        asks = [["100.01", "2"], ["100.02", "3"]]
        diff_bids = [["99.99", "12"]]
        diff_asks = [["100.01", "1"]]
    else:
        bids = [["99.99", "2"], ["99.98", "3"]]
        asks = [["100.01", "10"], ["100.02", "8"]]
        diff_bids = [["99.99", "1"]]
        diff_asks = [["100.01", "12"]]

    events = [
        _event(1, "depthSnapshot", "REST_BOOTSTRAP", START_MS + 54_000, START_MS + 54_100,
               {"lastUpdateId": 499, "bids": bids, "asks": asks}),
        _event(2, "depthUpdate", "WEBSOCKET_BUFFER", START_MS + 56_000, START_MS + 56_100,
               {"U": 500, "u": 500, "E": START_MS + 56_000, "b": diff_bids, "a": diff_asks}),
    ]
    trades = (
        [(100, "2", False), (101, "1", False), (102, "0.5", True)]
        if side == "BUY"
        else [(100, "2", True), (101, "1", True), (102, "0.5", False)]
    )
    for index, (trade_id, quantity, maker) in enumerate(trades, start=3):
        stamp = START_MS + 56_200 + (index - 3) * 100
        events.append(_event(
            index, "aggTrade", "WEBSOCKET", stamp, stamp + 20,
            {"a": trade_id, "p": "100", "q": quantity, "T": stamp, "m": maker},
        ))
    if second_session:
        events.extend([
            _event(6, "depthSnapshot", "REST_BOOTSTRAP", START_MS + 114_000, START_MS + 114_100,
                   {"lastUpdateId": 900, "bids": bids, "asks": asks}, SESSION_B),
            _event(7, "depthUpdate", "WEBSOCKET_BUFFER", START_MS + 115_000, START_MS + 115_100,
                   {"U": 901, "u": 901, "E": START_MS + 115_000, "b": diff_bids, "a": diff_asks}, SESSION_B),
            _event(8, "aggTrade", "WEBSOCKET", START_MS + 115_200, START_MS + 115_220,
                   {"a": 103, "p": "100", "q": "1", "T": START_MS + 115_200, "m": False}, SESSION_B),
        ])
    return events


@pytest.mark.parametrize(("side", "expected_delta", "expected_imbalance"), [
    ("BUY", 2.5, 1),
    ("SELL", -2.5, -1),
])
def test_replay_reconstructs_taker_delta_cvd_and_sequence_validated_book(
    side, expected_delta, expected_imbalance
):
    result = replay_spot_order_flow_events(_book_events(side=side), "BTCUSDT", now=_now())
    assert len(result) == 1
    snapshot = result[0]
    assert snapshot["eligible_for_order_flow_replay"] is True
    assert snapshot["coverage_status"] == "OBSERVED_CONTIGUOUS_CAPTURE_NOT_FULL_SESSION"
    assert snapshot["delta"] == pytest.approx(expected_delta)
    assert snapshot["delta_scope"] == "WEBSOCKET_AGGTRADES_RECEIVED_DURING_CAPTURE_BUCKET"
    assert snapshot["cvd_value"] == pytest.approx(expected_delta)
    assert snapshot["cvd_scope"] == "SINCE_CAPTURE_SEED"
    assert snapshot["cvd_status"] == "COMPLETE_SINCE_STATE_SEED"
    assert snapshot["order_book"]["depth_imbalance"] * expected_imbalance > 0
    assert snapshot["depth_is_continuous"] is True
    assert snapshot["session_delta"] is None
    assert snapshot["session_delta_coverage_complete"] is False
    assert snapshot["coverage_is_complete"] is False
    assert snapshot["feed_mode"] == "RAW_EVENT_REPLAY"
    assert snapshot["data_provenance"]["candle_volume_used"] is False
    assert "not quoted bid/ask" in snapshot["data_provenance"]["bid_ask_semantics"]


def test_replay_never_emits_a_partial_receive_time_bucket():
    events = _book_events()
    result = replay_spot_order_flow_events(
        events, "BTCUSDT", now=_now(offset_ms=59_999)
    )
    assert result == []


def test_replay_rejects_unsupported_market_type_and_mixed_symbol_events():
    events = _book_events()
    wrong_market = [dict(row) for row in events]
    wrong_market[0]["market_type"] = "BINANCE_USDM_FUTURES"
    with pytest.raises(OrderFlowReplayError, match="Binance Spot only"):
        replay_spot_order_flow_events(wrong_market, "BTCUSDT", now=_now())

    wrong_symbol = [dict(row) for row in events]
    wrong_symbol[-1]["symbol"] = "ETHUSDT"
    with pytest.raises(OrderFlowReplayError, match="match the requested symbol"):
        replay_spot_order_flow_events(wrong_symbol, "BTCUSDT", now=_now())


def test_trade_id_gap_vetoes_cvd_and_order_flow_replay():
    events = _book_events()
    events[3]["payload"]["a"] = 102
    events[3]["event_key"] = "102"
    events[4]["payload"]["a"] = 103
    events[4]["event_key"] = "103"
    result = replay_spot_order_flow_events(events, "BTCUSDT", now=_now())
    snapshot = result[0]
    assert snapshot["coverage_status"] == "TRADE_SEQUENCE_GAP"
    assert snapshot["cvd_value"] is None
    assert snapshot["eligible_for_order_flow_replay"] is False
    assert snapshot["trade_state"]["gap_detected"] is True


def test_depth_sequence_gap_vetoes_book_metrics():
    events = _book_events()
    events[1]["payload"]["U"] = 502
    events[1]["payload"]["u"] = 502
    result = replay_spot_order_flow_events(events, "BTCUSDT", now=_now())
    snapshot = result[0]
    assert snapshot["coverage_status"] == "DEPTH_SEQUENCE_UNVALIDATED"
    assert snapshot["order_book"] is None
    assert snapshot["depth_is_continuous"] is False
    assert snapshot["eligible_for_order_flow_replay"] is False


def test_capture_gap_permanently_vetoes_archive_replay_eligibility():
    events = _book_events()
    gap_time = START_MS + 56_350
    events.append(_event(
        9, "captureGap", "WEBSOCKET", gap_time, gap_time + 10,
        {"gap_id": "abcdef0123456789abcdef0123456789", "reason": "RAW_CAPTURE_QUEUE_OVERFLOW"},
    ))
    events.sort(key=lambda row: (row["received_at_ms"], row["id"]))
    result = replay_spot_order_flow_events(events, "BTCUSDT", now=_now())
    snapshot = result[0]
    assert snapshot["coverage_status"] == "CAPTURE_GAP_DETECTED"
    assert snapshot["cvd_value"] is None
    assert snapshot["eligible_for_order_flow_replay"] is False


def test_replay_reports_stale_trade_and_depth_ages_at_decision_boundary():
    events = _book_events()
    for row in events:
        row["event_time_ms"] -= 45_000
        row["received_at_ms"] -= 45_000
        if row["event_type"] == "aggTrade":
            row["payload"]["T"] = row["event_time_ms"]
        elif row["event_type"] == "depthUpdate":
            row["payload"]["E"] = row["event_time_ms"]
    result = replay_spot_order_flow_events(events, "BTCUSDT", now=_now())
    snapshot = result[0]
    assert snapshot["trade_age_seconds"] > 15
    assert snapshot["depth_age_seconds"] > 5
    assert snapshot["coverage_status"] == "TRADE_STALE"
    assert snapshot["eligible_for_order_flow_replay"] is False


def test_replay_carries_trade_cvd_across_stream_sessions_after_depth_resnapshot():
    result = replay_spot_order_flow_events(
        _book_events(second_session=True), "BTCUSDT", now=_now(offset_ms=180_000)
    )
    assert len(result) == 2
    assert result[0]["eligible_for_order_flow_replay"] is True
    assert result[1]["eligible_for_order_flow_replay"] is True
    assert result[1]["stream_session_count"] == 2
    assert result[1]["cvd_value"] == pytest.approx(3.5)
    assert result[1]["depth_book"]["last_update_id"] == 901
    assert result[1]["session_delta"] is None


def test_reconnect_invalidates_old_depth_until_new_session_snapshot_and_diff():
    events = _book_events()
    events.append(_event(
        9, "aggTrade", "WEBSOCKET", START_MS + 58_000, START_MS + 58_020,
        {"a": 103, "p": "100", "q": "1", "T": START_MS + 58_000, "m": False},
        SESSION_B,
    ))
    result = replay_spot_order_flow_events(events, "BTCUSDT", now=_now())
    snapshot = result[0]
    assert snapshot["trade_state"]["coverage_complete"] is True
    assert snapshot["order_book"] is None
    assert snapshot["depth_is_continuous"] is False
    assert snapshot["coverage_status"] == "DEPTH_SEQUENCE_UNVALIDATED"
    assert snapshot["eligible_for_order_flow_replay"] is False


def test_capture_gap_remains_a_veto_even_after_later_depth_resnapshot():
    events = _book_events()
    gap_time = START_MS + 57_000
    events.append(_event(
        9, "captureGap", "WEBSOCKET", gap_time, gap_time + 10,
        {"gap_id": "abcdef0123456789abcdef0123456789", "reason": "RAW_CAPTURE_QUEUE_OVERFLOW"},
    ))
    events.extend([
        _event(10, "depthSnapshot", "REST_BOOTSTRAP", START_MS + 114_000, START_MS + 114_100,
               {"lastUpdateId": 900, "bids": [["99.99", "10"]], "asks": [["100.01", "2"]]}, SESSION_B),
        _event(11, "depthUpdate", "WEBSOCKET", START_MS + 115_000, START_MS + 115_100,
               {"U": 901, "u": 901, "E": START_MS + 115_000, "b": [], "a": []}, SESSION_B),
        _event(12, "aggTrade", "WEBSOCKET", START_MS + 115_200, START_MS + 115_220,
               {"a": 103, "p": "100", "q": "1", "T": START_MS + 115_200, "m": False}, SESSION_B),
    ])
    result = replay_spot_order_flow_events(events, "BTCUSDT", now=_now(offset_ms=180_000))
    assert len(result) == 2
    assert result[0]["coverage_status"] == "CAPTURE_GAP_DETECTED"
    assert result[1]["coverage_status"] == "CAPTURE_GAP_DETECTED"
    assert result[1]["depth_is_continuous"] is True
    assert result[1]["cvd_value"] is None
    assert result[1]["eligible_for_order_flow_replay"] is False


def test_late_rest_backfill_recovers_only_the_later_checkpoint_not_the_gap_checkpoint():
    events = [
        _event(1, "depthSnapshot", "REST_BOOTSTRAP", START_MS + 54_000, START_MS + 54_100,
               {"lastUpdateId": 499, "bids": [["99.99", "10"]], "asks": [["100.01", "2"]]}),
        _event(2, "depthUpdate", "WEBSOCKET", START_MS + 56_000, START_MS + 56_100,
               {"U": 500, "u": 500, "E": START_MS + 56_000, "b": [], "a": []}),
        _event(3, "aggTrade", "WEBSOCKET", START_MS + 56_200, START_MS + 56_220,
               {"a": 100, "p": "100", "q": "1", "T": START_MS + 56_200, "m": False}),
        _event(4, "aggTrade", "WEBSOCKET", START_MS + 56_400, START_MS + 56_420,
               {"a": 102, "p": "100", "q": "1", "T": START_MS + 56_400, "m": False}),
        _event(5, "aggTrade", "REST_GAP_BACKFILL", START_MS + 56_300, START_MS + 64_000,
               {"a": 101, "p": "100", "q": "1", "T": START_MS + 56_300, "m": False}),
        _event(6, "depthUpdate", "WEBSOCKET", START_MS + 116_000, START_MS + 116_100,
               {"U": 501, "u": 501, "E": START_MS + 116_000, "b": [], "a": []}),
        _event(7, "aggTrade", "WEBSOCKET", START_MS + 116_200, START_MS + 116_220,
               {"a": 103, "p": "100", "q": "0.5", "T": START_MS + 116_200, "m": True}),
    ]
    result = replay_spot_order_flow_events(events, "BTCUSDT", now=_now(offset_ms=180_000))
    assert len(result) == 2
    assert result[0]["coverage_status"] == "TRADE_SEQUENCE_GAP"
    assert result[0]["cvd_value"] is None
    assert result[0]["eligible_for_order_flow_replay"] is False
    assert result[1]["backfill_used"] is True
    assert result[1]["backfill_trade_count"] == 1
    assert result[1]["cvd_value"] == pytest.approx(2.5)
    assert result[1]["eligible_for_order_flow_replay"] is True


def test_replay_rejects_future_receive_times_and_naive_clock():
    events = _book_events()
    with pytest.raises(OrderFlowReplayError, match="future receive"):
        replay_spot_order_flow_events(
            events, "BTCUSDT", now=datetime.fromtimestamp((START_MS + 1) / 1000, timezone.utc)
        )
    with pytest.raises(OrderFlowReplayError, match="timezone-aware"):
        replay_spot_order_flow_events(events, "BTCUSDT", now=datetime(2026, 11, 23))
