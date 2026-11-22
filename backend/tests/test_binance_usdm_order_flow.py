import pytest
from app.binance_usdm_order_flow import FuturesOrderFlowError, normalize_usdm_agg_trade, normalize_usdm_depth_update, validate_usdm_depth_sequence

def test_usdm_agg_trade_keeps_market_namespace_and_aggressor_flag():
    result=normalize_usdm_agg_trade("BTCUSDT",{"a":123,"p":"90000.1","q":"0.2","T":1700000000000,"m":False},received_at_ms=1700000000001)
    assert result["market_type"]=="BINANCE_USDM_FUTURES"
    assert result["event_key"]=="123"
    assert result["payload"]["m"] is False

def test_usdm_depth_sequence_bridges_snapshot_and_checks_pu_chain():
    one=normalize_usdm_depth_update("BTCUSDT",{"U":101,"u":105,"pu":100,"E":1700000000000,"b":[["90000","1"]],"a":[]},received_at_ms=1700000000001)
    two=normalize_usdm_depth_update("BTCUSDT",{"U":106,"u":110,"pu":105,"E":1700000000002,"b":[],"a":[["90001","2"]]},received_at_ms=1700000000003)
    result=validate_usdm_depth_sequence(103,[one,two])
    assert result["sequence_valid"] is True
    assert result["last_update_id"]==110

def test_usdm_depth_sequence_fails_closed_on_pu_gap():
    one=normalize_usdm_depth_update("BTCUSDT",{"U":101,"u":105,"pu":100,"E":1700000000000,"b":[],"a":[]},received_at_ms=1700000000001)
    two=normalize_usdm_depth_update("BTCUSDT",{"U":106,"u":110,"pu":104,"E":1700000000002,"b":[],"a":[]},received_at_ms=1700000000003)
    with pytest.raises(FuturesOrderFlowError): validate_usdm_depth_sequence(103,[one,two])

def test_usdm_rejects_spot_or_malformed_payload_data():
    with pytest.raises(FuturesOrderFlowError): normalize_usdm_agg_trade("BTCUSDT",{"a":1,"p":"NaN","q":"1","T":1700000000000,"m":True},received_at_ms=1700000000001)
    with pytest.raises(FuturesOrderFlowError): normalize_usdm_depth_update("BTCUSDT",{"U":1,"u":2,"E":1700000000000,"b":[],"a":[]},received_at_ms=1700000000001)
