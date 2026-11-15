from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx


def _candles(count: int, minutes: int, *, start_epoch: int = 1_700_000_000, price: float = 100.0):
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

    rows = _candles(11, 1)
    rows.insert(3, dict(rows[2]))  # duplicate minute must not complete a bucket
    aggregated = aggregate_minutes(rows, 5)

    assert len(aggregated) == 2
    assert aggregated[0]["volume"] == 50.0
    assert aggregated[1]["volume"] == 50.0
    assert aggregated[0]["open"] == rows[0]["open"]


def test_fetch_binance_historical_candles_paginates_and_returns_closed_rows(monkeypatch):
    from app import signal_engine

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
        assert _epoch(replay_as_of.isoformat()) > _epoch(latest)
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
