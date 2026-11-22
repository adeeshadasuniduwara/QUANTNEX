import pytest
from app.order_flow_usdm_recorder import MARKET_TYPE, UsdmRawEventError, _validate_event

def _event(**overrides):
    row={
        "market_type":MARKET_TYPE,"symbol":"BTCUSDT","event_type":"aggTrade",
        "event_key":"123","event_time_ms":1700000000000,"received_at_ms":1700000000001,
        "source":"WEBSOCKET","stream_session_id":"0123456789abcdef0123456789abcdef",
        "payload":{"a":123,"p":"90000","q":"0.1","T":1700000000000,"m":False},
    }
    row.update(overrides)
    return row

def test_usdm_recorder_accepts_normalized_futures_trade():
    validated=_validate_event(_event())
    assert validated[0]=="BTCUSDT"
    assert validated[1]=="aggTrade"
    assert validated[2]=="123"

def test_usdm_recorder_rejects_spot_and_unknown_event_namespaces():
    with pytest.raises(UsdmRawEventError,match="Only normalized"):
        _validate_event(_event(market_type="BINANCE_SPOT"))
    with pytest.raises(UsdmRawEventError,match="Unsupported"):
        _validate_event(_event(event_type="depthSnapshot"))

def test_usdm_recorder_rejects_invalid_sequence_and_session_identity():
    with pytest.raises(UsdmRawEventError,match="sequence range"):
        _validate_event(_event(event_type="depthUpdate",event_key="200",
            sequence_first=201,sequence_last=200,payload={"U":201,"u":200,"pu":199,"E":1700000000000,"b":[],"a":[]}))
    with pytest.raises(UsdmRawEventError,match="source or stream session"):
        _validate_event(_event(stream_session_id="not-a-session"))


def test_usdm_recorder_accepts_mark_price_and_force_order_events():
    mark=_event(event_type="markPriceUpdate",event_key="1700000000000",
        payload={"e":"markPriceUpdate","s":"BTCUSDT","E":1700000000000,"p":"90000","i":"89999","r":"0.0001","T":1700003600000})
    force=_event(event_type="forceOrder",event_key="abcdef1234567890",
        payload={"e":"forceOrder","E":1700000000000,"o":{"s":"BTCUSDT","S":"SELL","o":"LIMIT","f":"IOC",
            "q":"2","p":"90000","ap":"90001","X":"FILLED","z":"2","T":1700000000000}})
    assert _validate_event(mark)[1]=="markPriceUpdate"
    assert _validate_event(force)[1]=="forceOrder"


def test_usdm_recorder_rejects_malformed_derivatives_events():
    bad_mark=_event(event_type="markPriceUpdate",event_key="1700000000000",
        payload={"e":"markPriceUpdate","s":"BTCUSDT","E":1700000000000,"p":"NaN","i":"90000","r":"0","T":1700003600000})
    bad_force=_event(event_type="forceOrder",event_key="bad",
        payload={"e":"forceOrder","E":1700000000000,"o":{"s":"BTCUSDT","S":"SELL","q":"1","p":"1","ap":"1","z":"2","T":1700000000000}})
    with pytest.raises(UsdmRawEventError,match="mark-price"):
        _validate_event(bad_mark)
    with pytest.raises(UsdmRawEventError,match="force-order"):
        _validate_event(bad_force)
