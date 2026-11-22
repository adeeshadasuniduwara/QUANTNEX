import pytest

from app.order_flow_monitor import (
    DEFAULT_ORDER_FLOW_SYMBOLS,
    MAX_ORDER_FLOW_MONITOR_SYMBOLS,
    BinanceSpotOrderFlowCaptureWorker,
    get_order_flow_capture_status,
    get_minute_aligned_order_flow_snapshot,
    get_recent_trade_count_baseline,
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
    assert "manager" in status
    assert isinstance(status["observations_last_24h"], int)


def test_capture_status_reports_manager_stream_and_database_counts(monkeypatch):
    from types import SimpleNamespace
    from app import binance_order_flow_manager, order_flow_monitor

    class FakeQuery:
        def __init__(self, value):
            self.value = value

        def filter(self, *_args, **_kwargs):
            return self

        def scalar(self):
            return self.value

    class FakeDB:
        def __init__(self):
            self.values = iter([7, 1795262400000])

        def query(self, *_args, **_kwargs):
            return FakeQuery(next(self.values))

        def close(self):
            pass

    manager = SimpleNamespace(
        active_stream_count=3,
        max_streams=8,
        last_capture_at="2026-11-21T12:00:59+00:00",
        last_capture_error=None,
    )
    monkeypatch.setattr(order_flow_monitor, "SessionLocal", FakeDB)
    monkeypatch.setattr(
        binance_order_flow_manager,
        "get_binance_spot_order_flow_manager",
        lambda: manager,
    )

    status = get_order_flow_capture_status()

    assert status["manager"]["active_streams"] == 3
    assert status["manager"]["max_streams"] == 8
    assert status["observations_last_24h"] == 7
    assert status["latest_observation_at"] is not None
    assert status["recorder_error_type"] is None



def _baseline_row(bucket, count):
    return {"storage": {"sample_bucket": bucket}, "order_flow": {"trade_count": count}}


def test_trade_count_baseline_uses_five_consecutive_prior_utc_minutes(monkeypatch):
    from datetime import datetime, timezone
    from app import order_flow_monitor, order_flow_recorder

    class FakeDB:
        def close(self):
            pass

    now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    minute = int(now.timestamp()) // 60
    rows = [_baseline_row(minute - offset, value) for offset, value in zip(
        range(5, 0, -1), [10, 20, 30, 40, 50]
    )]
    rows.append(_baseline_row(minute, 999))  # forming/current minute must not enter the baseline
    monkeypatch.setattr(order_flow_monitor, "SessionLocal", FakeDB)
    monkeypatch.setattr(order_flow_recorder, "load_order_flow_observations", lambda *_a, **_k: rows)

    baseline = get_recent_trade_count_baseline("BTCUSDT", now=now)

    assert baseline == 30.0


def test_trade_count_baseline_rejects_short_or_gapped_minute_coverage(monkeypatch):
    from datetime import datetime, timezone
    from app import order_flow_monitor, order_flow_recorder

    class FakeDB:
        def close(self):
            pass

    now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    minute = int(now.timestamp()) // 60
    monkeypatch.setattr(order_flow_monitor, "SessionLocal", FakeDB)

    monkeypatch.setattr(order_flow_recorder, "load_order_flow_observations", lambda *_a, **_k: [
        _baseline_row(minute - offset, value)
        for offset, value in zip(range(4, 0, -1), [10, 20, 30, 40])
    ])
    assert get_recent_trade_count_baseline("BTCUSDT", now=now) is None

    monkeypatch.setattr(order_flow_recorder, "load_order_flow_observations", lambda *_a, **_k: [
        _baseline_row(minute - offset, value)
        for offset, value in [(1, 10), (2, 20), (4, 40), (5, 50), (6, 60)]
    ])
    assert get_recent_trade_count_baseline("BTCUSDT", now=now) is None


def _recorded_minute_snapshot():
    from datetime import datetime, timezone

    candle_start = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    captured = datetime(2026, 11, 21, 12, 0, 59, 500000, tzinfo=timezone.utc)
    trade = datetime(2026, 11, 21, 12, 0, 59, tzinfo=timezone.utc)
    depth = datetime(2026, 11, 21, 12, 0, 58, 500000, tzinfo=timezone.utc)
    bucket = int(candle_start.timestamp()) // 60
    return {
        "market_type": "BINANCE_SPOT",
        "captured_at": captured.isoformat(),
        "storage": {"sample_bucket": bucket, "captured_at": captured.isoformat()},
        "trade_state": {"coverage_complete": True, "gap_detected": False},
        "depth_book": {"valid": True, "sequence_validated": True},
        "data_provenance": {"candle_volume_used": False, "trade_side": "Binance aggregate trade buyer-is-maker"},
        "order_flow": {
            "market_type": "BINANCE_SPOT",
            "feed_mode": "PUBLIC_WEBSOCKET_STREAM",
            "depth_is_continuous": True,
            "trade_count": 120,
            "delta_ratio": 0.42,
            "delta": 24.0,
            "trade_data_age_seconds": 0.5,
            "last_trade_at": trade.isoformat(),
            "depth_observed_at": depth.isoformat(),
            "order_book": {"depth_imbalance": 0.24, "spread_bps": 1.2},
        },
    }


def test_minute_aligned_snapshot_uses_exact_closed_candle_and_recomputes_source_ages(monkeypatch):
    from datetime import datetime, timezone
    from app import order_flow_monitor, order_flow_recorder

    class FakeDB:
        def close(self):
            pass

    payload = _recorded_minute_snapshot()
    monkeypatch.setattr(order_flow_monitor, "SessionLocal", FakeDB)
    monkeypatch.setattr(order_flow_recorder, "load_order_flow_observations", lambda *_a, **_k: [payload])
    now = datetime(2026, 11, 21, 12, 1, 2, tzinfo=timezone.utc)

    result = get_minute_aligned_order_flow_snapshot(
        "BTCUSDT",
        {"time": "2026-11-21T12:00:00+00:00"},
        now=now,
    )

    assert result is not None
    assert result["market_type"] == "BINANCE_SPOT"
    assert result["depth_is_continuous"] is True
    assert result["order_book"]["depth_imbalance"] == 0.24
    assert result["observation_minute"] == "2026-11-21T12:00:00+00:00"
    assert result["trade_data_age_seconds"] == 3.0
    assert result["depth_age_seconds"] == 3.5


def test_minute_aligned_snapshot_rejects_future_stale_or_cross_minute_data(monkeypatch):
    from datetime import datetime, timezone
    from app import order_flow_monitor, order_flow_recorder

    class FakeDB:
        def close(self):
            pass

    payload = _recorded_minute_snapshot()
    monkeypatch.setattr(order_flow_monitor, "SessionLocal", FakeDB)
    monkeypatch.setattr(order_flow_recorder, "load_order_flow_observations", lambda *_a, **_k: [payload])
    candle = {"time": "2026-11-21T12:00:00+00:00"}

    assert get_minute_aligned_order_flow_snapshot(
        "BTCUSDT", candle,
        now=datetime(2026, 11, 21, 12, 0, 59, tzinfo=timezone.utc),
    ) is None

    assert get_minute_aligned_order_flow_snapshot(
        "BTCUSDT", candle,
        now=datetime(2026, 11, 21, 12, 1, 10, tzinfo=timezone.utc),
    ) is None

    payload["order_flow"]["last_trade_at"] = "2026-11-21T12:01:01+00:00"
    assert get_minute_aligned_order_flow_snapshot(
        "BTCUSDT", candle,
        now=datetime(2026, 11, 21, 12, 1, 2, tzinfo=timezone.utc),
    ) is None
