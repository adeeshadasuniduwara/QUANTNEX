from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone

import pytest

import httpx


def _candles(count: int, minutes: int, *, start_epoch: int = 1_700_000_100, price: float = 100.0):
    rows = []
    start_epoch = (start_epoch // (minutes * 60)) * (minutes * 60)
    for index in range(count):
        value = price + 0.01 * (index % 7)
        rows.append({
            "time": datetime.fromtimestamp(start_epoch + index * minutes * 60, timezone.utc).isoformat(),
            "open": value, "high": value + 0.5, "low": value - 0.5,
            "close": value + 0.1, "volume": 10.0,
        })
    return rows


def test_aggregate_minutes_omits_incomplete_and_duplicate_buckets():
    from app.signal_engine import aggregate_minutes

    rows = _candles(11, 1, start_epoch=1_700_000_100)
    rows.insert(3, dict(rows[2]))  # duplicate minute must not complete a bucket
    aggregated = aggregate_minutes(rows, 5, require_complete=True)

    assert len(aggregated) == 2
    assert aggregated[0]["volume"] == 50.0
    assert aggregated[1]["volume"] == 50.0
    assert aggregated[0]["open"] == rows[0]["open"]


def test_fetch_binance_historical_candles_paginates_and_returns_closed_rows(monkeypatch):
    from app import signal_engine

    async def valid_spot_symbol(symbol):
        return symbol == "BTCUSDT"
    monkeypatch.setattr(signal_engine, "is_binance_spot_symbol", valid_spot_symbol)

    requests = []

    def handler(request):
        requests.append(request)
        start = int(request.url.params["startTime"])
        end = int(request.url.params["endTime"])
        count = min(1000, max(0, (end - start) // 60_000))
        rows = []
        for index in range(count):
            open_ms = start + index * 60_000
            price = 100.0 + (index % 5) * 0.01
            rows.append([
                open_ms, str(price), str(price + 0.1), str(price - 0.1), str(price + 0.02),
                "10", open_ms + 59_999, "1000", 5, "4", "400", "0",
            ])
        return httpx.Response(200, json=rows)

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def mock_client(*args, **kwargs):
        return original_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(signal_engine.httpx, "AsyncClient", mock_client)
    rows = asyncio.run(signal_engine.fetch_binance_historical_candles(
        "BTCUSDT", interval="1m", days=1, max_candles=1500
    ))

    assert len(rows) >= 1400
    assert len(requests) >= 2
    assert rows == sorted(rows, key=lambda row: row["time"])
    assert len({row["time"] for row in rows}) == len(rows)


def test_signal_walk_forward_uses_sequential_oos_folds_and_costs(monkeypatch):
    from app import signal_backtest

    candles_by_tf = {
        "1": _candles(15_000, 1),
        "5": _candles(3_000, 5),
        "15": _candles(1_000, 15),
        "30": _candles(500, 30),
        "60": _candles(250, 60),
    }
    calls = {"count": 0}

    async def fake_build_signal(settings, symbol, *, candles_override, execution_context_override, replay_as_of):
        calls["count"] += 1
        latest = candles_override["5"][-1]["time"]
        as_of_epoch = _epoch(replay_as_of.isoformat())
        assert as_of_epoch > _epoch(latest)
        interval_minutes = {"1": 1, "5": 5, "15": 15, "30": 30, "60": 60}
        for timeframe, rows in candles_override.items():
            minutes = interval_minutes[timeframe]
            assert all(_epoch(row["time"]) + minutes * 60 <= as_of_epoch + 1e-6 for row in rows)
        if calls["count"] % 10:
            return {"status": "WAIT", "signal": None}
        return {
            "status": "SIGNAL",
            "signal": {
                "side": "BUY", "entry_type": "MARKET", "entry": 100.0,
                "stop_loss": 99.0, "tp1": 100.3,
                "signal_candle_time": latest,
                "execution_quality": {"estimated_round_trip_cost_bps": 10.0},
            },
        }

    def _epoch(value):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()

    monkeypatch.setattr(signal_backtest, "build_signal", fake_build_signal)
    info = {
        "quote_asset": "USDT",
        "filters": {
            "PRICE_FILTER": {"tickSize": "0.01"},
            "LOT_SIZE": {"stepSize": "0.001", "minQty": "0.001"},
        },
    }
    result = asyncio.run(signal_backtest.run_signal_walk_forward(
        "BTCUSDT", candles_by_tf, info, train_ratio=0.7,
        assumed_spread_bps=5, assumed_depth_usd=10000,
    ))

    assert result["method"].startswith("Fixed-rule sequential walk-forward")
    assert result["fold_count"] == 3
    assert result["training"]["trade_count"] > 0
    assert result["out_of_sample"]["trade_count"] > 0
    assert result["out_of_sample"]["fold_count"] == 3
    assert len(result["out_of_sample_folds"]) == 3
    assert sum(fold["trade_count"] for fold in result["out_of_sample_folds"]) == result["out_of_sample"]["trade_count"]
    assert sum(fold["sample_bars"] for fold in result["out_of_sample_folds"]) == result["out_of_sample"]["sample_bars"]
    assert result["out_of_sample_folds"][0]["decision_end_exclusive"] == result["out_of_sample_folds"][1]["decision_start"]
    assert result["out_of_sample_folds"][1]["decision_end_exclusive"] == result["out_of_sample_folds"][2]["decision_start"]
    assert result["training"]["win_rate_pct"] == 100.0
    assert result["training"]["win_rate_95_ci_wilson_pct"][0] < 100.0
    assert result["training"]["win_rate_95_ci_wilson_pct"][1] == 100.0
    assert result["out_of_sample"]["estimated_cost_quote"] > 0
    assert result["out_of_sample"]["buy_and_hold_return_pct"] is not None
    assert result["assumptions"]["spread_bps"] == 5


def test_simulate_slice_carries_open_trade_beyond_fold_decision_boundary(monkeypatch):
    from app import signal_backtest

    start = 1_700_002_800
    primary = _candles(220, 60, start_epoch=start)
    minute = _candles(13_200, 1, start_epoch=start)
    calls = {"count": 0}

    async def fake_build_signal(_settings, _symbol, *, candles_override, execution_context_override, replay_as_of):
        calls["count"] += 1
        if calls["count"] > 1:
            return {"status": "WAIT", "signal": None}
        return {
            "status": "SIGNAL",
            "signal": {
                "side": "BUY",
                "entry_type": "MARKET",
                "entry": 100.0,
                "stop_loss": 1.0,
                "tp1": 1000.0,
                "signal_candle_time": candles_override["60"][-1]["time"],
                "execution_quality": {"estimated_round_trip_cost_bps": 0.0},
            },
        }

    monkeypatch.setattr(signal_backtest, "build_signal", fake_build_signal)
    execution_end = _epoch(minute[-1]["time"]) + 60
    decision_end = _epoch(primary[212]["time"])
    result = asyncio.run(signal_backtest._simulate_slice(
        "BTCUSDT",
        {"1": minute, "60": primary},
        {"quote_asset": "USDT", "filters": {"PRICE_FILTER": {"tickSize": "0.01"}}},
        {"primary": "60", "trend": "60", "enabled": ["60"], "min_score": 7},
        5.0,
        10000.0,
        210,
        211,
        execution_end_epoch=execution_end,
    ))

    assert result["trade_count"] == 1
    assert result["trades"][0]["exit_reason"] == "SPLIT_END"
    assert _epoch(result["trades"][0]["exit_time"]) > decision_end
    assert result["_next_signal_index"] == len(primary) - 2


def test_signal_walk_forward_rejects_invalid_assumptions():
    from app import signal_backtest

    candles_by_tf = {"5": _candles(600, 5), "60": _candles(300, 60),
                     "30": _candles(600, 30), "15": _candles(1200, 15),
                     "1": _candles(18_000, 1)}
    info = {"filters": {"PRICE_FILTER": {"tickSize": "0.01"}}}
    with pytest.raises(ValueError):
        asyncio.run(signal_backtest.run_signal_walk_forward(
            "BTCUSDT", candles_by_tf, info, assumed_spread_bps=200
        ))
    with pytest.raises(ValueError, match="fold_count"):
        asyncio.run(signal_backtest.run_signal_walk_forward(
            "BTCUSDT", candles_by_tf, info, fold_count=1
        ))


def test_historical_limit_and_exit_fills_handle_gaps_conservatively():
    from app.signal_backtest import _limit_fill_price, _stop_fill_price, _target_fill_price

    assert _limit_fill_price("BUY", 100.0, {"open": 99.0, "low": 98.0, "high": 99.5}) == 99.0
    assert _limit_fill_price("BUY", 100.0, {"open": 101.0, "low": 99.5, "high": 102.0}) == 100.0
    assert _limit_fill_price("SELL", 100.0, {"open": 101.0, "low": 100.5, "high": 102.0}) == 101.0
    assert _limit_fill_price("SELL", 100.0, {"open": 99.0, "low": 98.0, "high": 100.5}) == 100.0
    assert _limit_fill_price("BUY", 100.0, {"open": 101.0, "low": 100.5, "high": 102.0}) is None
    assert _stop_fill_price("BUY", 99.0, {"open": 98.0}) == 98.0
    assert _target_fill_price("BUY", 101.0, {"open": 102.0}) == 102.0


def test_signal_walk_forward_rejects_large_historical_minute_gaps():
    from app import signal_backtest

    minute_rows = _candles(15_000, 1)
    candles_by_tf = {
        "1": minute_rows[:5000] + minute_rows[5020:],
        "5": _candles(3_000, 5),
        "15": _candles(1_000, 15),
        "30": _candles(500, 30),
        "60": _candles(250, 60),
    }
    info = {"quote_asset": "USDT", "filters": {"PRICE_FILTER": {"tickSize": "0.01"}}}
    with __import__("pytest").raises(ValueError, match="missing bars"):
        asyncio.run(signal_backtest.run_signal_walk_forward("BTCUSDT", candles_by_tf, info))


def test_limit_order_expires_after_15_minutes_even_on_hourly_primary(monkeypatch):
    from app import signal_backtest

    start = 1_700_002_800  # UTC hour boundary
    primary = _candles(220, 60, start_epoch=start)
    minute = _candles(13_200, 1, start_epoch=start)
    signal_open_epoch = int(datetime.fromisoformat(primary[211]["time"]).timestamp())
    touch_index = (signal_open_epoch - int(datetime.fromisoformat(minute[0]["time"]).timestamp())) // 60 + 20
    minute[touch_index]["low"] = 98.9  # Touch occurs 20m after placement, beyond expiry.
    calls = {"count": 0}

    async def fake_build_signal(settings, symbol, *, candles_override, execution_context_override, replay_as_of):
        calls["count"] += 1
        if calls["count"] > 1:
            return {"status": "WAIT", "signal": None}
        return {
            "status": "SIGNAL",
            "signal": {
                "side": "BUY", "entry_type": "LIMIT", "entry": 99.0, "limit_price": 99.0,
                "stop_loss": 98.0, "tp1": 101.0,
                "signal_candle_time": candles_override["60"][-1]["time"],
                "execution_quality": {"estimated_round_trip_cost_bps": 10.0},
            },
        }

    monkeypatch.setattr(signal_backtest, "build_signal", fake_build_signal)
    result = asyncio.run(signal_backtest._simulate_slice(
        "BTCUSDT", {"1": minute, "60": primary},
        {"quote_asset": "USDT", "filters": {"PRICE_FILTER": {"tickSize": "0.01"}}},
        {"primary": "60", "trend": "60", "enabled": ["60"], "min_score": 7},
        5.0, 10000.0, 210, 218,
    ))

    assert result["limit_entries"] == 1
    assert result["limit_expired"] == 1
    assert result["trade_count"] == 0


def test_limit_order_can_fill_and_exit_using_one_minute_execution_data(monkeypatch):
    from app import signal_backtest

    start = 1_700_002_800
    primary = _candles(220, 60, start_epoch=start)
    minute = _candles(13_200, 1, start_epoch=start)
    signal_open_epoch = int(datetime.fromisoformat(primary[211]["time"]).timestamp())
    touch_index = (signal_open_epoch - int(datetime.fromisoformat(minute[0]["time"]).timestamp())) // 60 + 10
    minute[touch_index]["low"] = 98.9
    minute[touch_index + 1]["high"] = 101.2
    calls = {"count": 0}

    async def fake_build_signal(settings, symbol, *, candles_override, execution_context_override, replay_as_of):
        calls["count"] += 1
        if calls["count"] > 1:
            return {"status": "WAIT", "signal": None}
        return {
            "status": "SIGNAL",
            "signal": {
                "side": "BUY", "entry_type": "LIMIT", "entry": 99.0, "limit_price": 99.0,
                "stop_loss": 98.0, "tp1": 101.0,
                "signal_candle_time": candles_override["60"][-1]["time"],
                "execution_quality": {"estimated_round_trip_cost_bps": 10.0},
            },
        }

    monkeypatch.setattr(signal_backtest, "build_signal", fake_build_signal)
    result = asyncio.run(signal_backtest._simulate_slice(
        "BTCUSDT", {"1": minute, "60": primary},
        {"quote_asset": "USDT", "filters": {"PRICE_FILTER": {"tickSize": "0.01"}}},
        {"primary": "60", "trend": "60", "enabled": ["60"], "min_score": 7},
        5.0, 10000.0, 210, 218,
    ))

    assert result["limit_entries"] == 1
    assert result["limit_expired"] == 0
    assert result["trade_count"] == 1
    assert result["trades"][0]["exit_reason"] == "TAKE_PROFIT_1"


def test_signal_replay_rejects_missing_authoritative_price_filter(monkeypatch):
    from app import signal_backtest

    calls = {"count": 0}

    async def fake_build_signal(*_args, **_kwargs):
        calls["count"] += 1
        return {"status": "WAIT", "signal": None}

    monkeypatch.setattr(signal_backtest, "build_signal", fake_build_signal)
    candles_by_tf = {
        "1": _candles(13_200, 1),
        "60": _candles(220, 60),
    }

    try:
        asyncio.run(signal_backtest._simulate_slice(
            "BTCUSDT", candles_by_tf,
            {"quote_asset": "USDT", "filters": {}},
            {"primary": "60", "trend": "60", "enabled": ["60"]},
            5.0, 10_000.0, 210, 211,
        ))
    except ValueError as exc:
        assert "authoritative PRICE_FILTER" in str(exc)
    else:
        raise AssertionError("Replay must reject missing PRICE_FILTER metadata.")

    assert calls["count"] == 0


def test_signal_replay_passes_exchange_price_filter_into_entry_validation(monkeypatch):
    from app import signal_backtest

    captured = []

    async def fake_build_signal(*_args, **kwargs):
        captured.append(kwargs["execution_context_override"])
        return {"status": "WAIT", "signal": None}

    monkeypatch.setattr(signal_backtest, "build_signal", fake_build_signal)
    candles_by_tf = {
        "1": _candles(13_200, 1),
        "60": _candles(220, 60),
    }
    symbol_info = {
        "quote_asset": "USDT",
        "filters": {
            "PRICE_FILTER": {
                "tickSize": "0.01000000",
                "minPrice": "0.01000000",
                "maxPrice": "1000000.00000000",
            },
            "LOT_SIZE": {"stepSize": "0.00100000", "minQty": "0.00100000"},
        },
    }

    asyncio.run(signal_backtest._simulate_slice(
        "BTCUSDT", candles_by_tf, symbol_info,
        {"primary": "60", "trend": "60", "enabled": ["60"]},
        5.0, 10_000.0, 210, 211,
    ))

    assert len(captured) == 1
    assert captured[0]["tick_size"] == "0.01000000"
    assert captured[0]["tick_size_source"] == "BINANCE_EXCHANGEINFO_PRICE_FILTER"
    assert captured[0]["price_filter"] == {
        "tick_size": "0.01000000",
        "min_price": "0.01000000",
        "max_price": "1000000.00000000",
    }


def test_signal_replay_rejects_zero_or_non_finite_exchange_tick_size(monkeypatch):
    from app import signal_backtest

    async def fake_build_signal(*_args, **_kwargs):
        raise AssertionError("Signal evaluation must not run with an invalid exchange tick.")

    monkeypatch.setattr(signal_backtest, "build_signal", fake_build_signal)
    candles_by_tf = {
        "1": _candles(13_200, 1),
        "60": _candles(220, 60),
    }
    for tick_size in ("0", "NaN", "Infinity"):
        try:
            asyncio.run(signal_backtest._simulate_slice(
                "BTCUSDT", candles_by_tf,
                {
                    "quote_asset": "USDT",
                    "filters": {
                        "PRICE_FILTER": {
                            "tickSize": tick_size,
                            "minPrice": "0",
                            "maxPrice": "0",
                        }
                    },
                },
                {"primary": "60", "trend": "60", "enabled": ["60"]},
                5.0, 10_000.0, 210, 211,
            ))
        except ValueError as exc:
            assert "PRICE_FILTER" in str(exc)
        else:
            raise AssertionError(f"Replay must reject invalid tick size {tick_size}.")


def _order_flow_observation(
    captured_at: datetime,
    *,
    trade_at: datetime | None = None,
    depth_at: datetime | None = None,
    side: str = "BUY",
):
    trade_at = trade_at or captured_at - timedelta(seconds=1)
    depth_at = depth_at or captured_at - timedelta(seconds=0.5)
    direction = 1.0 if side == "BUY" else -1.0
    stamp = lambda value: value.astimezone(timezone.utc).isoformat()
    return {
        "capture_version": 2,
        "capture_scope": "ONE_UTC_MINUTE_FEATURE_SNAPSHOT",
        "captured_at": stamp(captured_at),
        "symbol": "BTCUSDT",
        "market_type": "BINANCE_SPOT",
        "trade_state": {
            "last_agg_trade_id": 1234,
            "coverage_complete": True,
            "gap_detected": False,
        },
        "depth_book": {
            "valid": True,
            "sequence_validated": True,
            "last_update_id": 5678,
            "bids": [["100.0", "2.0"]],
            "asks": [["100.1", "2.0"]],
        },
        "order_flow": {
            "market_type": "BINANCE_SPOT",
            "feed_mode": "PUBLIC_WEBSOCKET_STREAM",
            "depth_is_continuous": True,
            "depth_snapshot_update_id": 5678,
            "cvd_status": "COMPLETE_SINCE_STATE_SEED",
            "last_trade_at": stamp(trade_at),
            "depth_observed_at": stamp(depth_at),
            "trade_data_age_seconds": 0.1,
            "trade_count": 25,
            "delta": 2.0 * direction,
            "delta_ratio": 0.2 * direction,
            "data_provenance": {
                "bid_ask_semantics": "Aggressor-side inferred trade delta; not consolidated quoted bid/ask volume.",
                "candle_volume_used": False,
            },
            "data_sources": {"stream": "wss://data-stream.binance.vision"},
            "order_book": {"depth_imbalance": 0.15 * direction, "spread_bps": 1.0},
        },
    }


def test_order_flow_replay_selects_latest_prior_snapshot_and_recomputes_source_age():
    from app.signal_backtest import (
        _select_order_flow_snapshot,
        _validate_order_flow_observations,
    )

    base = datetime(2026, 11, 20, 6, 0, tzinfo=timezone.utc)
    first = _order_flow_observation(base)
    second = _order_flow_observation(
        base + __import__("datetime").timedelta(seconds=30)
    )
    observations = [first, second]
    epochs = _validate_order_flow_observations(observations, "BTCUSDT")

    selected, status = _select_order_flow_snapshot(
        observations, epochs, "BTCUSDT",
        (base + __import__("datetime").timedelta(seconds=31)).timestamp(),
        {"max_order_flow_trade_age_seconds": 15, "max_order_book_snapshot_age_seconds": 5},
    )

    assert status == "AVAILABLE"
    assert selected["last_trade_at"] == second["order_flow"]["last_trade_at"]
    assert selected["trade_data_age_seconds"] == 2.0


def test_order_flow_replay_never_uses_future_snapshot_and_rejects_stale_book():
    from app.signal_backtest import (
        _select_order_flow_snapshot,
        _validate_order_flow_observations,
    )

    base = datetime(2026, 11, 20, 6, 0, tzinfo=timezone.utc)
    future = _order_flow_observation(base + __import__("datetime").timedelta(seconds=30))
    epochs = _validate_order_flow_observations([future], "BTCUSDT")
    selected, status = _select_order_flow_snapshot(
        [future], epochs, "BTCUSDT", base.timestamp(),
        {"max_order_flow_trade_age_seconds": 15, "max_order_book_snapshot_age_seconds": 5},
    )
    assert selected == {}
    assert status == "MISSING"

    stale = _order_flow_observation(
        base,
        trade_at=base - __import__("datetime").timedelta(seconds=2),
        depth_at=base - __import__("datetime").timedelta(seconds=8),
    )
    epochs = _validate_order_flow_observations([stale], "BTCUSDT")
    selected, status = _select_order_flow_snapshot(
        [stale], epochs, "BTCUSDT",
        (base + __import__("datetime").timedelta(seconds=1)).timestamp(),
        {"max_order_flow_trade_age_seconds": 15, "max_order_book_snapshot_age_seconds": 5},
    )
    assert selected == {}
    assert status == "STALE"


def test_order_flow_replay_rejects_gapped_or_unsorted_capture_history():
    from app.signal_backtest import _validate_order_flow_observations, _select_order_flow_snapshot

    base = datetime(2026, 11, 20, 6, 0, tzinfo=timezone.utc)
    invalid = _order_flow_observation(base)
    invalid["trade_state"]["gap_detected"] = True
    epochs = _validate_order_flow_observations([invalid], "BTCUSDT")
    selected, status = _select_order_flow_snapshot(
        [invalid], epochs, "BTCUSDT", (base + __import__("datetime").timedelta(seconds=1)).timestamp(),
        {"max_order_flow_trade_age_seconds": 15, "max_order_book_snapshot_age_seconds": 5},
    )
    assert selected == {}
    assert status == "INVALID"

    later = _order_flow_observation(base + __import__("datetime").timedelta(seconds=30))
    with __import__("pytest").raises(ValueError, match="strictly increasing"):
        _validate_order_flow_observations([later, invalid], "BTCUSDT")


def test_order_flow_replay_passes_historical_snapshot_mode_into_signal_engine(monkeypatch):
    from app import signal_backtest
    from datetime import timedelta

    start = 1_700_002_800
    primary = _candles(220, 60, start_epoch=start)
    minute = _candles(13_200, 1, start_epoch=start)
    as_of = datetime.fromisoformat(primary[211]["time"])
    observation = _order_flow_observation(
        as_of - timedelta(seconds=0.5),
        trade_at=as_of - timedelta(seconds=1.5),
        depth_at=as_of - timedelta(seconds=1.0),
    )
    captured = []

    async def fake_build_signal(settings, symbol, **kwargs):
        captured.append(kwargs)
        return {
            "status": "WAIT",
            "signal": None,
            "order_flow": {
                "data_mode": kwargs.get("order_flow_mode_override"),
                "accepted": False,
            },
        }

    monkeypatch.setattr(signal_backtest, "build_signal", fake_build_signal)
    result = asyncio.run(signal_backtest._simulate_slice(
        "BTCUSDT",
        {"1": minute, "60": primary},
        {"quote_asset": "USDT", "filters": {"PRICE_FILTER": {"tickSize": "0.01"}}},
        {"primary": "60", "trend": "60", "enabled": ["60"]},
        5.0, 10_000.0, 210, 211,
        order_flow_observations=[observation],
    ))

    assert len(captured) == 1
    assert captured[0]["order_flow_mode_override"] == "HISTORICAL_FEATURE_SNAPSHOT_REPLAY"
    assert captured[0]["order_flow_override"]["market_type"] == "BINANCE_SPOT"
    assert captured[0]["order_flow_override"]["trade_data_age_seconds"] == 1.5
    assert result["order_flow_snapshot_matches"] == 1
    assert result["order_flow_confirmed_candidates"] == 0
    assert result["order_flow_rejected_candidates"] == 1


def test_order_flow_replay_fails_closed_when_no_prior_snapshot_exists(monkeypatch):
    from app import signal_backtest

    start = 1_700_002_800
    primary = _candles(220, 60, start_epoch=start)
    minute = _candles(13_200, 1, start_epoch=start)
    captured = []

    async def fake_build_signal(settings, symbol, **kwargs):
        captured.append(kwargs)
        return {
            "status": "WAIT",
            "signal": None,
            "order_flow": {
                "data_mode": kwargs.get("order_flow_mode_override"),
                "accepted": False,
            },
        }

    monkeypatch.setattr(signal_backtest, "build_signal", fake_build_signal)
    result = asyncio.run(signal_backtest._simulate_slice(
        "BTCUSDT",
        {"1": minute, "60": primary},
        {"quote_asset": "USDT", "filters": {"PRICE_FILTER": {"tickSize": "0.01"}}},
        {"primary": "60", "trend": "60", "enabled": ["60"]},
        5.0, 10_000.0, 210, 211,
        order_flow_observations=[],
    ))

    assert captured[0]["order_flow_override"] == {}
    assert result["order_flow_missing_snapshots"] == 1
    assert result["order_flow_rejected_candidates"] == 1


def _synthetic_replay_setup(direction: str, interval: str, as_of: datetime):
    """Create a deterministic causal trend + sweep + structure-break candle fixture."""
    from app.signal_engine import INTERVAL_SECONDS, structure

    rows = []
    for index in range(320):
        if direction == "BUY":
            close = 100 + 0.035 * index + 0.45 * math.sin(index * 0.42)
            previous = (
                100 + 0.035 * (index - 1) + 0.45 * math.sin((index - 1) * 0.42)
                if index else close - 0.02
            )
        else:
            close = 150 - 0.035 * index - 0.45 * math.sin(index * 0.42)
            previous = (
                150 - 0.035 * (index - 1) - 0.45 * math.sin((index - 1) * 0.42)
                if index else close + 0.02
            )
        open_price = previous
        rows.append({
            "open": open_price,
            "high": max(open_price, close) + 0.08,
            "low": min(open_price, close) - 0.08,
            "close": close,
            "volume": 10.0,
        })

    pivots = structure(rows)
    if direction == "BUY":
        swing_high, swing_low = pivots["swing_high"], pivots["swing_low"]
        rows[-2]["close"] = swing_high - 0.10
        rows[-2]["open"] = rows[-3]["close"]
        rows[-2]["high"] = max(rows[-2]["open"], rows[-2]["close"]) + 0.08
        rows[-2]["low"] = min(rows[-2]["open"], rows[-2]["close"]) - 0.08
        rows[-1]["open"] = rows[-2]["close"]
        rows[-1]["close"] = swing_high + 0.10
        rows[-1]["high"] = rows[-1]["close"] + 0.08
        rows[-1]["low"] = swing_low - 0.20
    else:
        swing_high, swing_low = pivots["swing_high"], pivots["swing_low"]
        rows[-2]["close"] = swing_low + 0.10
        rows[-2]["open"] = rows[-3]["close"]
        rows[-2]["high"] = max(rows[-2]["open"], rows[-2]["close"]) + 0.08
        rows[-2]["low"] = min(rows[-2]["open"], rows[-2]["close"]) - 0.08
        rows[-1]["open"] = rows[-2]["close"]
        rows[-1]["close"] = swing_low - 0.10
        rows[-1]["low"] = rows[-1]["close"] - 0.08
        rows[-1]["high"] = swing_high + 0.20

    seconds = INTERVAL_SECONDS[interval]
    last_open = as_of - timedelta(seconds=seconds + 30)
    first_open = last_open - timedelta(seconds=seconds * (len(rows) - 1))
    for index, row in enumerate(rows):
        row["time"] = (first_open + timedelta(seconds=seconds * index)).isoformat()
    return rows


def _next_replay_bar(previous: dict, at: datetime, side: str) -> dict:
    open_price = float(previous["close"])
    close = open_price + (0.02 if side == "BUY" else -0.02)
    return {
        "time": at.isoformat(),
        "open": open_price,
        "high": max(open_price, close) + 0.03,
        "low": min(open_price, close) - 0.03,
        "close": close,
        "volume": 10.0,
    }


def _run_historical_order_flow_replay_fixture(direction: str, observation: dict) -> dict:
    """Run a deterministic qualifying setup through the real replay + signal engine."""
    from app.signal_backtest import _simulate_slice

    as_of = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    minute = _synthetic_replay_setup(direction, "1min", as_of)
    for offset in range(6):
        minute.append(_next_replay_bar(
            minute[-1], as_of + timedelta(minutes=offset), direction
        ))

    primary = _synthetic_replay_setup(direction, "5min", as_of)
    primary.append(_next_replay_bar(primary[-1], as_of, direction))
    primary.append(_next_replay_bar(
        primary[-1], as_of + timedelta(minutes=5), direction
    ))

    candles_by_tf = {
        "1": minute,
        "5": primary,
        "15": _synthetic_replay_setup(direction, "15min", as_of),
        "30": _synthetic_replay_setup(direction, "30min", as_of),
        "60": _synthetic_replay_setup(direction, "1h", as_of),
    }
    symbol_info = {
        "quote_asset": "USDT",
        "filters": {
            "PRICE_FILTER": {"tickSize": "0.01", "minPrice": "0", "maxPrice": "0"},
            "LOT_SIZE": {"stepSize": "0.001", "minQty": "0.001", "maxQty": "100000"},
        },
    }
    settings = {
        "primary": "5",
        "trend": "60",
        "enabled": ["60", "30", "15", "5", "1"],
        "min_score": 8,
    }

    return asyncio.run(_simulate_slice(
        "BTCUSDT",
        candles_by_tf,
        symbol_info,
        settings,
        assumed_spread_bps=5.0,
        assumed_depth_usd=10_000.0,
        start_index=319,
        end_index=320,
        order_flow_observations=[observation],
    ))


@pytest.mark.parametrize(("side", "direction"), [("BUY", "BUY"), ("SELL", "SELL")])
def test_historical_order_flow_replay_generates_real_long_and_short_signals(side, direction):
    """Exercise the actual signal engine with prior, fresh, directionally aligned L2/CVD."""
    as_of = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    observation = _order_flow_observation(
        as_of - timedelta(seconds=1.5),
        trade_at=as_of - timedelta(seconds=2.5),
        depth_at=as_of - timedelta(seconds=2.0),
        side=side,
    )
    result = _run_historical_order_flow_replay_fixture(direction, observation)

    assert result["order_flow_decision_points"] == 1, result
    assert result["order_flow_snapshot_matches"] == 1, result
    assert result["order_flow_confirmed_candidates"] == 1, result
    assert result["order_flow_rejected_candidates"] == 0, result
    assert result["signal_count"] == 1, result
    assert result["trade_count"] == 1
    assert result["market_entries"] == 1
    assert result["trades"][0]["side"] == side
    assert result["trades"][0]["entry_type"] == "MARKET"


@pytest.mark.parametrize(("direction", "opposite_side"), [("BUY", "SELL"), ("SELL", "BUY")])
def test_historical_order_flow_replay_rejects_directionally_contradictory_delta_and_depth(
    direction, opposite_side
):
    """A valid candle setup must remain WAIT when observed trade/book pressure opposes it."""
    as_of = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    observation = _order_flow_observation(
        as_of - timedelta(seconds=1.5),
        trade_at=as_of - timedelta(seconds=2.5),
        depth_at=as_of - timedelta(seconds=2.0),
        side=opposite_side,
    )
    result = _run_historical_order_flow_replay_fixture(direction, observation)

    assert result["order_flow_decision_points"] == 1, result
    assert result["order_flow_snapshot_matches"] == 1, result
    assert result["order_flow_confirmed_candidates"] == 0, result
    assert result["order_flow_rejected_candidates"] == 1, result
    assert result["signal_count"] == 0, result
    assert result["trade_count"] == 0


@pytest.mark.parametrize("direction", ["BUY", "SELL"])
def test_historical_order_flow_replay_rejects_stale_depth_for_valid_candle_setup(direction):
    """A stale L2 source must veto an otherwise qualifying replay setup in either direction."""
    as_of = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    observation = _order_flow_observation(
        as_of - timedelta(seconds=1.5),
        trade_at=as_of - timedelta(seconds=2.5),
        depth_at=as_of - timedelta(seconds=8.0),
        side=direction,
    )
    result = _run_historical_order_flow_replay_fixture(direction, observation)

    assert result["order_flow_decision_points"] == 1, result
    assert result["order_flow_snapshot_matches"] == 0, result
    assert result["order_flow_stale_snapshots"] == 1, result
    assert result["order_flow_confirmed_candidates"] == 0, result
    assert result["order_flow_rejected_candidates"] == 1, result
    assert result["signal_count"] == 0, result
    assert result["trade_count"] == 0


def test_historical_order_flow_replay_rejects_gap_for_valid_candle_setup():
    """A trade-ID gap must invalidate the stored snapshot before signal evaluation."""
    as_of = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    observation = _order_flow_observation(
        as_of - timedelta(seconds=1.5),
        trade_at=as_of - timedelta(seconds=2.5),
        depth_at=as_of - timedelta(seconds=2.0),
        side="BUY",
    )
    observation["trade_state"]["gap_detected"] = True
    result = _run_historical_order_flow_replay_fixture("BUY", observation)

    assert result["order_flow_decision_points"] == 1, result
    assert result["order_flow_snapshot_matches"] == 0, result
    assert result["order_flow_invalid_snapshots"] == 1, result
    assert result["order_flow_confirmed_candidates"] == 0, result
    assert result["order_flow_rejected_candidates"] == 1, result
    assert result["signal_count"] == 0, result
    assert result["trade_count"] == 0


def test_replay_execution_quotes_are_tick_aligned_uncrossed_and_cost_conservative():
    from decimal import Decimal
    from app.signal_backtest import _replay_execution_quotes

    quotes = _replay_execution_quotes(100.003, "0.01", 5.0)
    tick = Decimal("0.01")
    assert quotes["best_bid"] < quotes["best_ask"]
    assert Decimal(str(quotes["best_bid"])) % tick == 0
    assert Decimal(str(quotes["best_ask"])) % tick == 0
    assert quotes["spread_bps"] >= quotes["assumed_spread_bps"]

    zero_spread = _replay_execution_quotes(100.0, "0.01", 0.0)
    assert zero_spread["best_ask"] - zero_spread["best_bid"] == pytest.approx(0.01)
    assert zero_spread["spread_bps"] > 0
