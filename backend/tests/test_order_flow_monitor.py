import pytest

from app.order_flow_monitor import (
    DEFAULT_ORDER_FLOW_SYMBOLS,
    MAX_ORDER_FLOW_MONITOR_SYMBOLS,
    BinanceSpotOrderFlowCaptureWorker,
    get_order_flow_capture_status,
    normalize_order_flow_monitor_symbols,
)


def test_order_flow_monitor_uses_safe_default_symbols_for_missing_or_invalid_values():
    assert normalize_order_flow_monitor_symbols(None) == DEFAULT_ORDER_FLOW_SYMBOLS
    assert normalize_order_flow_monitor_symbols("{broken") == DEFAULT_ORDER_FLOW_SYMBOLS
    assert normalize_order_flow_monitor_symbols({"symbols": ["BTCUSDT"]}) == DEFAULT_ORDER_FLOW_SYMBOLS


def test_order_flow_monitor_normalizes_and_deduplicates_symbols_with_hard_cap():
    values = [
        "btcusdt", "ETHUSDT", "BTCUSDT", "bad pair", "SOLUSDT",
        "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "LINKUSDT", "LTCUSDT",
    ]
    result = normalize_order_flow_monitor_symbols(values)
    assert result == ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "LINKUSDT"]
    assert len(result) == MAX_ORDER_FLOW_MONITOR_SYMBOLS


def test_order_flow_monitor_rejects_empty_list_by_using_defaults():
    assert normalize_order_flow_monitor_symbols([]) == DEFAULT_ORDER_FLOW_SYMBOLS


def test_capture_worker_requires_a_safe_poll_interval():
    with pytest.raises(ValueError, match="at least two seconds"):
        BinanceSpotOrderFlowCaptureWorker(refresh_seconds=1)


def test_capture_status_discloses_minute_alignment_and_no_raw_tick_archive():
    status = get_order_flow_capture_status()
    assert status["capture_alignment"] == "ONE_OBSERVATION_PER_UTC_1M_CANDLE"
    assert status["raw_tick_archive"] is False
    assert status["refresh_seconds"] >= 2



def test_trade_count_baseline_uses_only_stored_minute_observations(monkeypatch):
    from datetime import datetime, timezone
    from app import order_flow_monitor, order_flow_recorder

    class FakeDB:
        def close(self):
            pass

    monkeypatch.setattr(order_flow_monitor, "SessionLocal", FakeDB)
    monkeypatch.setattr(
        order_flow_recorder,
        "load_order_flow_observations",
        lambda *_args, **_kwargs: [
            {"order_flow": {"trade_count": value}}
            for value in [10, 20, 30, 40, 50, "bad", None]
        ],
    )
    baseline = order_flow_monitor.get_recent_trade_count_baseline(
        "BTCUSDT", now=datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    )
    assert baseline == 30.0


def test_trade_count_baseline_waits_for_minimum_historical_coverage(monkeypatch):
    from datetime import datetime, timezone
    from app import order_flow_monitor, order_flow_recorder

    class FakeDB:
        def close(self):
            pass

    monkeypatch.setattr(order_flow_monitor, "SessionLocal", FakeDB)
    monkeypatch.setattr(
        order_flow_recorder,
        "load_order_flow_observations",
        lambda *_args, **_kwargs: [{"order_flow": {"trade_count": value}} for value in [10, 20, 30, 40]],
    )
    baseline = order_flow_monitor.get_recent_trade_count_baseline(
        "BTCUSDT", now=datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    )
    assert baseline is None
