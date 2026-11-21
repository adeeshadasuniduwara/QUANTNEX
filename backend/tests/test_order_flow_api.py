from fastapi.testclient import TestClient
from app.main import app


class FakeOrderFlowManager:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.calls = []

    async def get_snapshot(self, symbol, tick_size, **kwargs):
        self.calls.append((symbol, tick_size, kwargs))
        return self.snapshot


def _snapshot(*, ready=True, depth_age=0.8, sequence_validated=True):
    flow = {
        "trade_count": 12, "buy_volume": 8.0, "sell_volume": 5.0,
        "delta": 3.0, "delta_ratio": 3.0 / 13.0,
        "window_cumulative_delta": 3.0, "window_delta_scope": "LATEST_AGGTRADE_RESPONSE_WINDOW",
        "cvd_value": 6.5, "cvd_status": "COMPLETE_SINCE_STATE_SEED", "cvd_scope": "SINCE_STATE_SEED",
        "quote_delta": 301.0, "session_timezone": "UTC", "session_date_utc": "2026-11-21",
        "session_delta": None, "session_delta_sample": 3.0, "session_delta_coverage_complete": False,
        "session_delta_scope": "INCOMPLETE_UTC_SESSION_SAMPLE", "session_start_trade_id": None,
        "trade_data_age_seconds": 1.2, "last_trade_at": "2026-11-21T07:00:00+00:00",
        "footprint": [{"price": 100.0, "buy_volume": 8.0, "sell_volume": 5.0, "delta": 3.0, "is_imbalanced": False}],
        "volume_profile": {"poc": 100.0, "vah": 101.0, "val": 99.0},
        "data_provenance": {"trade_source": "Binance Spot aggregate trades"},
        "quality": "OBSERVED_AGGRESSOR_DELTA_AND_SEQUENCE_VALIDATED_L2",
    } if ready else None
    return {
        "symbol": "BTCUSDT", "market_type": "BINANCE_SPOT", "status": "LIVE" if ready else "DEPTH_BRIDGING",
        "signal_ready": ready, "trade_state": {"cvd_status": "COMPLETE_SINCE_STATE_SEED" if ready else "INCOMPLETE_STREAM_START"},
        "depth_book": {"valid": True, "sequence_validated": sequence_validated, "last_update_id": 123456,
                       "bids": [["100.0", "2.0"], ["99.9", "3.0"]],
                       "asks": [["101.0", "2.5"], ["101.1", "4.0"]]},
        "order_flow": flow, "depth_age_seconds": depth_age,
        "last_message_at": "2026-11-21T07:00:00+00:00",
        "data_provenance": {
            "trade_side": "Binance Spot aggregate-trade buyer-is-maker flag; inferred aggressor side",
            "depth": "REST snapshot bridged to diff-depth update IDs; sequence-valid only after first bridge event",
            "cvd": "Complete only since bounded stream bootstrap seed; not full historical or UTC-session CVD",
            "session_delta": "Unavailable as full-session value unless session coverage is independently anchored",
            "candle_volume_used": False,
        },
        "manager": {"active_streams": 1, "max_streams": 3},
    }


def _patch_api(monkeypatch, manager, *, valid=True):
    from app import signal_engine, binance_order_flow_manager
    async def valid_symbol(symbol):
        return valid and symbol == "BTCUSDT"
    async def symbol_info(_symbol):
        return {"quote_asset": "USDT", "filters": {"PRICE_FILTER": {"tickSize": "0.01"}}}
    monkeypatch.setattr(signal_engine, "is_binance_spot_symbol", valid_symbol)
    monkeypatch.setattr(signal_engine, "get_binance_spot_symbol_info", symbol_info)
    monkeypatch.setattr(binance_order_flow_manager, "get_binance_spot_order_flow_manager", lambda: manager)


def test_order_flow_api_exposes_validated_spot_trade_and_depth_provenance(monkeypatch):
    manager = FakeOrderFlowManager(_snapshot())
    _patch_api(monkeypatch, manager)
    response = TestClient(app).get("/api/v1/order-flow/spot/BTCUSDT")
    assert response.status_code == 200
    data = response.json()
    assert data["depth_ready"] is True and data["trade_flow_ready"] is True and data["signal_ready"] is True
    assert data["market_type"] == "BINANCE_SPOT" and data["quote_asset"] == "USDT"
    assert data["liquidity"]["sequence_validated"] is True and data["liquidity"]["depth_update_id"] == 123456
    assert data["liquidity"]["best_bid"] == 100.0 and data["liquidity"]["bid_depth_quote"] == 499.7
    assert data["trade_flow"]["delta"] == 3.0 and data["trade_flow"]["cvd_scope"] == "SINCE_STATE_SEED"
    assert data["trade_flow"]["session_delta"] is None
    assert data["trade_flow"]["footprint"][0]["delta"] == 3.0
    assert data["data_provenance"]["candle_volume_used"] is False
    assert manager.calls[0][0:2] == ("BTCUSDT", "0.01")


def test_order_flow_api_rejects_unknown_spot_symbols_without_starting_a_stream(monkeypatch):
    manager = FakeOrderFlowManager(_snapshot())
    _patch_api(monkeypatch, manager, valid=False)
    response = TestClient(app).get("/api/v1/order-flow/spot/NOTALIVEUSDT")
    assert response.status_code == 422 and manager.calls == []


def test_order_flow_api_keeps_depth_and_trade_readiness_separate(monkeypatch):
    manager = FakeOrderFlowManager(_snapshot(ready=False))
    _patch_api(monkeypatch, manager)
    response = TestClient(app).get("/api/v1/order-flow/spot/BTCUSDT")
    assert response.status_code == 200
    data = response.json()
    assert data["depth_ready"] is True and data["trade_flow_ready"] is False and data["signal_ready"] is False
    assert data["liquidity"]["sequence_validated"] is True and data["trade_flow"] is None


def test_order_flow_api_rejects_stale_or_unsequenced_depth(monkeypatch):
    manager = FakeOrderFlowManager(_snapshot(depth_age=8.0, sequence_validated=False))
    _patch_api(monkeypatch, manager)
    response = TestClient(app).get("/api/v1/order-flow/spot/BTCUSDT")
    assert response.status_code == 200
    data = response.json()
    assert data["depth_ready"] is False and data["signal_ready"] is False and data["liquidity"] is None
