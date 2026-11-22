import asyncio
import json
from datetime import datetime, timezone, timedelta

import pytest

from app import binance_order_flow_stream as stream_module
from app.binance_order_flow_stream import (
    BinanceSpotOrderFlowStream,
    BinanceSpotOrderFlowStreamError,
    _decode_combined_event,
)


def trade(trade_id, price, quantity, stamp, buyer_is_maker=False):
    return {
        "a": trade_id,
        "p": str(price),
        "q": str(quantity),
        "T": int(stamp.timestamp() * 1000),
        "m": buyer_is_maker,
        "s": "BTCUSDT",
    }


def test_combined_stream_decoder_routes_aggtrade_and_depth_and_rejects_other_symbol():
    agg = {
        "stream": "btcusdt@aggTrade",
        "data": {"e": "aggTrade", "s": "BTCUSDT", "a": 1, "p": "100", "q": "1", "T": 1, "m": False},
    }
    depth = {
        "stream": "btcusdt@depth@100ms",
        "data": {"e": "depthUpdate", "s": "BTCUSDT", "U": 2, "u": 2, "b": [], "a": []},
    }

    assert _decode_combined_event(json.dumps(agg), "BTCUSDT")[0] == "aggTrade"
    assert _decode_combined_event(json.dumps(depth).encode(), "BTCUSDT")[0] == "depthUpdate"
    with pytest.raises(BinanceSpotOrderFlowStreamError, match="symbol"):
        _decode_combined_event(json.dumps({
            "stream": "ethusdt@aggTrade",
            "data": {"e": "aggTrade", "s": "ETHUSDT"},
        }), "BTCUSDT")


def test_stream_snapshot_waits_for_depth_sequence_bridge_then_exposes_stream_cvd():
    now = datetime.now(timezone.utc)
    stream = BinanceSpotOrderFlowStream("BTCUSDT", "0.1")
    first = trade(10, 100, 2, now - timedelta(seconds=2), False)
    second = trade(11, 100.1, 1, now - timedelta(seconds=1), True)
    stream.trade_state.begin_stream_seed(first["a"], first["T"])
    assert stream.trade_state.ingest(first) == "APPLIED"
    assert stream.trade_state.ingest(second) == "APPLIED"
    stream._remember_trade(first)
    stream._remember_trade(second)
    stream.depth_book.load_snapshot(
        200, [["100", "2"], ["99.9", "1"]], [["100.1", "1"], ["100.2", "2"]]
    )
    stream.depth_observed_at = now

    before_bridge = stream.snapshot(now=now)
    assert before_bridge["signal_ready"] is False
    assert before_bridge["order_flow"] is None

    assert stream._apply_depth_event({
        "U": 201, "u": 201, "b": [["100", "3"]], "a": [],
    }) == "APPLIED"
    ready = stream.snapshot()
    assert ready["signal_ready"] is True
    assert ready["order_flow"]["feed_mode"] == "PUBLIC_WEBSOCKET_STREAM"
    assert ready["order_flow"]["depth_is_continuous"] is True
    assert ready["order_flow"]["cvd_value"] == 1.0
    assert ready["order_flow"]["session_delta"] is None
    assert ready["order_flow"]["session_delta_scope"] == "INCOMPLETE_UTC_SESSION_SAMPLE"


def test_stream_recovers_trade_id_gap_with_bounded_rest_backfill(monkeypatch):
    now = datetime.now(timezone.utc)
    stream = BinanceSpotOrderFlowStream("BTCUSDT", "0.1", max_backfill_pages=3)
    first = trade(100, 100, 1, now - timedelta(seconds=4), False)
    stream.trade_state.begin_stream_seed(first["a"], first["T"])
    assert stream.trade_state.ingest(first) == "APPLIED"
    stream._remember_trade(first)

    async def fake_public(_client, path, params):
        assert path == "/api/v3/aggTrades"
        start_id = params["fromId"]
        rows = {
            101: [trade(101, 100, 2, now - timedelta(seconds=3), True),
                  trade(102, 100, 3, now - timedelta(seconds=2), False)],
            103: [trade(103, 100, 4, now - timedelta(seconds=1), True)],
        }[start_id]
        return rows, "fixture"

    monkeypatch.setattr(stream_module, "get_binance_public_json", fake_public)
    result = asyncio.run(stream._apply_trade_row(
        object(), trade(103, 100, 4, now - timedelta(seconds=1), True)
    ))

    assert result == "RECOVERED_GAP"
    snapshot = stream.trade_state.snapshot()
    assert snapshot["gap_detected"] is False
    assert snapshot["cvd_value"] == -2.0
    assert snapshot["last_agg_trade_id"] == 103
    assert [int(row["a"]) for row in stream.recent_trades] == [100, 101, 102, 103]


def test_depth_gap_invalidates_stream_book_and_requires_resnapshot():
    stream = BinanceSpotOrderFlowStream("BTCUSDT", "0.1")
    stream.depth_book.load_snapshot(200, [["100", "2"]], [["100.1", "2"]])

    with pytest.raises(BinanceSpotOrderFlowStreamError, match="fresh REST snapshot"):
        stream._apply_depth_event({"U": 202, "u": 202, "b": [], "a": []})

    assert stream.depth_book.snapshot()["valid"] is False
    assert stream.depth_book.snapshot()["bids"] == []
    assert stream.depth_book.snapshot()["asks"] == []


def test_bootstrap_buffers_live_trade_and_depth_events_until_rest_snapshot_is_ready(monkeypatch):
    now = datetime.now(timezone.utc)
    stream = BinanceSpotOrderFlowStream("BTCUSDT", "0.1")

    live_trade = {**trade(101, 100.1, 1, now - timedelta(seconds=1), False), "e": "aggTrade"}
    depth_event = {
        "e": "depthUpdate", "s": "BTCUSDT", "U": 201, "u": 201,
        "b": [["100", "3"]], "a": [],
    }
    messages = [
        json.dumps({"stream": "btcusdt@aggTrade", "data": live_trade}),
        json.dumps({"stream": "btcusdt@depth@100ms", "data": depth_event}),
    ]

    class FakeWebSocket:
        async def recv(self):
            if messages:
                return messages.pop(0)
            await asyncio.Future()

    async def fake_fetch(_client, path, _params):
        await asyncio.sleep(0.01)
        if path.endswith("aggTrades"):
            return [trade(100, 100, 1, now - timedelta(seconds=2), False)], "fixture-trades"
        return {
            "lastUpdateId": 200,
            "bids": [["100", "2"], ["99.9", "1"]],
            "asks": [["100.1", "1"], ["100.2", "2"]],
        }, "fixture-depth"

    monkeypatch.setattr(stream, "_fetch_public", fake_fetch)

    async def run_bootstrap():
        recv_task = await stream._bootstrap(FakeWebSocket(), object())
        assert stream.trade_state.snapshot()["last_agg_trade_id"] == 101
        assert stream.depth_book.snapshot()["sequence_validated"] is True
        assert stream.snapshot()["signal_ready"] is True
        recv_task.cancel()
        await asyncio.gather(recv_task, return_exceptions=True)

    asyncio.run(run_bootstrap())


def test_stream_queues_only_applied_raw_trade_and_depth_events_with_session_provenance():
    now = datetime.now(timezone.utc)
    stream = BinanceSpotOrderFlowStream("BTCUSDT", "0.1", max_buffered_events=8)
    first = trade(700, 100, 2, now - timedelta(seconds=2), False)
    stream.trade_state.begin_stream_seed(first["a"], first["T"])
    assert asyncio.run(stream._apply_trade_row(object(), first, source="REST_BOOTSTRAP")) == "APPLIED"
    stream.depth_book.load_snapshot(900, [["100", "2"]], [["100.1", "2"]])
    stream.depth_observed_at = now
    depth_event = {
        "U": 901, "u": 902, "E": int(now.timestamp() * 1000),
        "b": [["100", "3"]], "a": [],
    }
    assert stream._apply_depth_event(depth_event) == "APPLIED"
    rows = stream.drain_capture_events(limit=8)
    assert [row["event_type"] for row in rows] == ["aggTrade", "depthUpdate"]
    assert rows[0]["source"] == "REST_BOOTSTRAP"
    assert rows[0]["payload"]["a"] == 700
    assert rows[1]["payload"]["U"] == 901
    assert rows[1]["payload"]["u"] == 902
    assert rows[0]["stream_session_id"] == stream.stream_session_id
    assert rows[1]["stream_session_id"] == stream.stream_session_id
    assert stream.drain_capture_events(limit=8) == []


def test_stream_raw_event_queue_fails_closed_on_overflow():
    now = datetime.now(timezone.utc)
    stream = BinanceSpotOrderFlowStream("BTCUSDT", "0.1", max_buffered_events=1)
    first = trade(701, 100, 1, now - timedelta(seconds=1), False)
    stream.trade_state.begin_stream_seed(first["a"], first["T"])
    asyncio.run(stream._apply_trade_row(object(), first))
    second = trade(702, 100, 1, now, False)
    with pytest.raises(BinanceSpotOrderFlowStreamError, match="queue overflowed"):
        asyncio.run(stream._apply_trade_row(object(), second))
