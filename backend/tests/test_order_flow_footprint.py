import pytest
from app.order_flow_footprint import OrderFlowFootprintError, build_order_flow_footprint

def _trade(stamp, price, quantity, buyer_is_maker):
    return {"event_type":"aggTrade","event_time_ms":stamp,"payload":{"p":price,"q":quantity,"m":buyer_is_maker}}

def test_footprint_groups_aggressor_volume_by_utc_minute_and_tick():
    result=build_order_flow_footprint([_trade(60001,"100.02","2",False),_trade(60002,"100.01","1",True),_trade(60003,"100.01","3",False)],price_step="0.01")
    assert result["accepted_trade_events"] == 3
    assert result["coverage"] == "OBSERVED_EVENTS_ONLY_NOT_PROVEN_COMPLETE"
    candle=result["candles"][0]
    assert candle["open_time_ms"] == 60000
    by_price={row["price"]:row for row in candle["levels"]}
    assert by_price["100.02"]["buy_volume"] == "2"
    assert by_price["100.01"]["sell_volume"] == "1"
    assert by_price["100.01"]["buy_volume"] == "3"
    assert by_price["100.01"]["delta"] == "2"

def test_footprint_calculates_diagonal_imbalance_flags():
    result=build_order_flow_footprint([_trade(120001,"100.02","9",False),_trade(120002,"100.01","2",True),_trade(120003,"100.01","1",False),_trade(120004,"100.00","1",True)],price_step="0.01")
    by_price={row["price"]:row for row in result["candles"][0]["levels"]}
    assert by_price["100.02"]["buy_imbalance"] is True

def test_footprint_ignores_depth_rows_without_fabricating_trade_volume():
    result=build_order_flow_footprint([{"event_type":"depthUpdate","event_time_ms":1,"payload":{"b":[],"a":[]}},_trade(60001,"10","1",False)],price_step="1")
    assert result["ignored_non_trade_events"] == 1
    assert result["accepted_trade_events"] == 1

def test_footprint_rejects_bad_precision_and_unsafe_limits():
    with pytest.raises(OrderFlowFootprintError): build_order_flow_footprint([],price_step="0")
    with pytest.raises(OrderFlowFootprintError): build_order_flow_footprint([],price_step="0.01",interval_ms=123)
    with pytest.raises(OrderFlowFootprintError): build_order_flow_footprint([],price_step="0.01",max_levels=1001)


def test_footprint_reports_stacked_imbalance_only_on_adjacent_price_ticks():
    events = []
    for price in ("100.00", "100.01", "100.02"):
        events.append(_trade(180001, price, "9", False))
        events.append(_trade(180002, f"{float(price)-0.01:.2f}", "1", True))
    result = build_order_flow_footprint(events, price_step="0.01")
    assert any(item["side"] == "BUY" and item["count"] >= 3 for item in result["stacked_imbalances"])


def test_footprint_flags_delta_divergence_as_observed_context():
    events = [
        _trade(60001, "100.00", "10", False), _trade(60002, "99.99", "1", True),
        _trade(120001, "101.00", "6", False), _trade(120002, "100.99", "1", True),
        _trade(180001, "102.00", "2", False), _trade(180002, "101.99", "1", True),
    ]
    result = build_order_flow_footprint(events, price_step="0.01")
    assert result["delta_divergence"]["signal"] == "BEARISH"


def test_footprint_context_labels_absorption_and_iceberg_as_unconfirmed_candidates():
    events = [
        _trade(60001, "100.00", "5", False),
        _trade(60002, "100.00", "4", True),
        _trade(60003, "100.00", "1", False),
        _trade(60004, "100.00", "1", True),
        _trade(60005, "100.00", "1", False),
    ]
    result = build_order_flow_footprint(events, price_step="0.01")
    assert result["absorption_candidates"]
    assert result["iceberg_candidates"]
    assert result["iceberg_candidates"][0]["confidence"] == "LOW"
    assert result["spoofing_detection"]["status"] == "NOT_PROVEN"


def test_footprint_reports_depth_pull_context_without_counting_it_as_traded_volume():
    events = [
        {"event_type":"depthUpdate","event_time_ms":60001,"payload":{"b":[["100.00","2"]],"a":[]}},
        {"event_type":"depthUpdate","event_time_ms":60002,"payload":{"b":[["100.00","0"]],"a":[]}},
        {"event_type":"depthUpdate","event_time_ms":60003,"payload":{"b":[["100.00","3"]],"a":[]}},
        {"event_type":"depthUpdate","event_time_ms":60004,"payload":{"b":[["100.00","0"]],"a":[]}},
    ]
    result = build_order_flow_footprint(events, price_step="0.01")
    assert result["accepted_trade_events"] == 0
    assert result["depth_level_updates"] == 4
    assert result["liquidity_pull_context"][0]["pulls"] == 2
