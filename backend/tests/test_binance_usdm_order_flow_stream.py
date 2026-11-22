import pytest
from app.binance_usdm_order_flow import normalize_usdm_depth_update
from app.binance_usdm_order_flow_stream import BinanceUsdmOrderFlowStream, UsdmStreamError

def _depth(first, last, previous, *, bids=None, asks=None):
    return normalize_usdm_depth_update(
        "BTCUSDT",
        {"U":first,"u":last,"pu":previous,"E":1700000000000,
         "b":bids or [],"a":asks or []},
        received_at_ms=1700000000001,
    )

def test_usdm_stream_requires_snapshot_bridge_then_contiguous_pu_chain():
    stream=BinanceUsdmOrderFlowStream("BTCUSDT")
    stream.snapshot_update_id=100
    stream.last_update_id=None
    assert stream._apply_depth(_depth(99,101,98,bids=[["90000","2"]])) is True
    assert stream.sequence_valid is True
    assert stream.last_update_id==101
    assert stream._apply_depth(_depth(102,104,101,asks=[["90001","3"]])) is True
    assert stream.last_update_id==104
    assert stream.snapshot()["depth_ready"] is True
    assert float(stream.snapshot()["bids"][0]["quantity"])==pytest.approx(2.0)

def test_usdm_stream_discards_old_snapshot_buffer_events_before_bridge():
    stream=BinanceUsdmOrderFlowStream("BTCUSDT")
    stream.snapshot_update_id=100
    stream.last_update_id=None
    assert stream._apply_depth(_depth(90,99,89)) is False
    assert stream.sequence_valid is False
    assert stream._apply_depth(_depth(100,101,99)) is True

def test_usdm_stream_invalidates_book_on_pu_gap():
    stream=BinanceUsdmOrderFlowStream("BTCUSDT")
    stream.snapshot_update_id=100
    stream._apply_depth(_depth(99,101,98))
    with pytest.raises(UsdmStreamError,match="pu sequence gap"):
        stream._apply_depth(_depth(102,105,100))
    assert stream.sequence_valid is False
    assert stream.gap_count==1

def test_usdm_stream_captures_aggressor_side_trade_in_separate_namespace():
    stream=BinanceUsdmOrderFlowStream("BTCUSDT")
    stream._apply_trade({"a":7,"p":"90000.5","q":"0.2","T":1700000000000,"m":False},1700000000001)
    event=stream.capture_events[-1]
    assert event["market_type"]=="BINANCE_USDM_FUTURES"
    assert event["event_type"]=="aggTrade"
    assert event["payload"]["m"] is False
    assert stream.last_trade["buyer_is_maker"] is False

def test_usdm_stream_raw_queue_overflow_fails_closed():
    stream=BinanceUsdmOrderFlowStream("BTCUSDT",max_buffered_events=100)
    stream.sequence_valid=True
    for index in range(100):
        stream.capture_events.append({"event_key":str(index)})
    with pytest.raises(UsdmStreamError,match="queue overflow"):
        stream._queue({"event_key":"overflow"})
    assert stream.sequence_valid is False
    assert stream.dropped_events==1
