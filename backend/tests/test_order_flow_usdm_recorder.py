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
