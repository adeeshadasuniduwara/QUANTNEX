from __future__ import annotations

import asyncio
from datetime import datetime, timezone

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


def test_signal_walk_forward_uses_chronological_holdout_and_costs(monkeypatch):
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

    assert result["method"].startswith("Chronological holdout")
    assert result["training"]["trade_count"] > 0
    assert result["out_of_sample"]["trade_count"] > 0
    assert result["training"]["win_rate_pct"] == 100.0
    assert result["out_of_sample"]["estimated_cost_quote"] > 0
    assert result["out_of_sample"]["buy_and_hold_return_pct"] is not None
    assert result["assumptions"]["spread_bps"] == 5


def test_signal_walk_forward_rejects_invalid_assumptions():
    from app import signal_backtest

    candles_by_tf = {"5": _candles(600, 5), "60": _candles(300, 60),
                     "30": _candles(600, 30), "15": _candles(1200, 15),
                     "1": _candles(18_000, 1)}
    info = {"filters": {"PRICE_FILTER": {"tickSize": "0.01"}}}
    with __import__("pytest").raises(ValueError):
        asyncio.run(signal_backtest.run_signal_walk_forward(
            "BTCUSDT", candles_by_tf, info, assumed_spread_bps=200
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
