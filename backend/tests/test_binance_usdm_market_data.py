from datetime import datetime, timezone, timedelta
import asyncio

import pytest

from app import binance_usdm_market_data as futures
from fastapi.testclient import TestClient
from app.main import app


def test_usdm_universe_filters_to_trading_perpetuals(monkeypatch):
    payload = {"symbols": [
        {"symbol":"BTCUSDT","status":"TRADING","contractType":"PERPETUAL","baseAsset":"BTC","quoteAsset":"USDT","marginAsset":"USDT","pricePrecision":2,"quantityPrecision":3,"filters":[{"filterType":"PRICE_FILTER","tickSize":"0.10"}]},
        {"symbol":"BTCUSDT_260925","status":"TRADING","contractType":"CURRENT_QUARTER","baseAsset":"BTC","quoteAsset":"USDT"},
        {"symbol":"OLDUSDT","status":"PENDING_TRADING","contractType":"PERPETUAL","baseAsset":"OLD","quoteAsset":"USDT"},
        {"symbol":"ETHUSD_PERP","status":"TRADING","contractType":"PERPETUAL","baseAsset":"ETH","quoteAsset":"USD","marginAsset":"BTC"},
    ]}
    async def fake_request(_client, path, params=None):
        assert path == "/fapi/v1/exchangeInfo"
        return payload
    monkeypatch.setattr(futures, "_request_json", fake_request)
    monkeypatch.setattr(futures, "_CACHE", None)
    info = asyncio.run(futures.get_binance_usdm_symbol_info(force_refresh=True))
    assert set(info) == {"BTCUSDT"}  # underscore-delimited COIN-M-style contract is intentionally excluded
    assert info["BTCUSDT"]["filters"]["PRICE_FILTER"]["tickSize"] == "0.10"
    assert "ETHUSD_PERP" not in info  # COIN-M-style symbols are not USDⓈ-M chart instruments


def test_usdm_candles_drop_open_and_malformed_rows(monkeypatch):
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    closed_rows = []
    for i in range(210):
        start = now - (i + 2) * 60000
        closed_rows.append([start, "100", "103", "99", "102", "12", start + 59999])
    opened = [now-60000, "102", "104", "101", "103", "4", now+59999]
    malformed = [now-18000000, "100", "99", "101", "102", "2", now-17940001]
    async def fake_info(force_refresh=False):
        return {"BTCUSDT":{"symbol":"BTCUSDT"}}
    async def fake_request(_client, path, params=None):
        assert path == "/fapi/v1/klines"
        assert params["symbol"] == "BTCUSDT"
        return [malformed, *closed_rows, opened]
    monkeypatch.setattr(futures, "get_binance_usdm_symbol_info", fake_info)
    monkeypatch.setattr(futures, "_request_json", fake_request)
    rows = asyncio.run(futures.fetch_binance_usdm_candles("btcusdt", "1m", 210))
    assert len(rows) == 210
    assert all(row["high"] >= max(row["open"], row["close"], row["low"]) for row in rows)
    assert rows[-1]["close"] == 102


def test_usdm_rejects_unknown_symbols_before_klines(monkeypatch):
    async def fake_info(force_refresh=False):
        return {}
    monkeypatch.setattr(futures, "get_binance_usdm_symbol_info", fake_info)
    with pytest.raises(futures.BinanceUsdMDataError, match="not an active"):
        asyncio.run(futures.fetch_binance_usdm_candles("NOTREALUSDT", "15m", 210))


def test_usdm_rejects_unsupported_interval_and_limit():
    with pytest.raises(futures.BinanceUsdMDataError, match="timeframe"):
        asyncio.run(futures.fetch_binance_usdm_candles("BTCUSDT", "2m", 210))
    with pytest.raises(futures.BinanceUsdMDataError, match="210"):
        asyncio.run(futures.fetch_binance_usdm_candles("BTCUSDT", "1m", 10))


def test_usdm_chart_markets_route_returns_dynamic_perpetual_universe(monkeypatch):
    async def fake_symbols():
        return ["BTCUSDT", "ETHUSDT"]
    monkeypatch.setattr(futures, "get_binance_usdm_symbols", fake_symbols)
    response = TestClient(app).get("/api/v1/charts/markets?market_type=BINANCE_USDM_FUTURES")
    assert response.status_code == 200
    body = response.json()
    assert body["market_type"] == "BINANCE_USDM_FUTURES"
    assert body["symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert body["symbol_suffix"] == ".P"


def test_usdm_chart_candles_route_is_read_only_and_market_scoped(monkeypatch):
    now = datetime.now(timezone.utc)
    rows = [{"time": (now-timedelta(minutes=5)).isoformat(), "open": 100.0,
             "high": 102.0, "low": 99.0, "close": 101.0, "volume": 12.0}]
    async def fake_symbols():
        return ["BTCUSDT"]
    async def fake_candles(symbol, interval, limit):
        assert (symbol, interval, limit) == ("BTCUSDT", "15m", 500)
        return rows
    monkeypatch.setattr(futures, "get_binance_usdm_symbols", fake_symbols)
    monkeypatch.setattr(futures, "fetch_binance_usdm_candles", fake_candles)
    response = TestClient(app).get("/api/v1/charts/futures/candles?symbol=BTCUSDT&interval=15m&limit=500")
    assert response.status_code == 200
    body = response.json()
    assert body["market_type"] == "BINANCE_USDM_FUTURES"
    assert body["provider"] == "Binance USDⓈ-M Futures"
    assert body["candles"] == rows


def test_usdm_chart_candles_route_rejects_unknown_contract(monkeypatch):
    async def fake_symbols():
        return ["BTCUSDT"]
    monkeypatch.setattr(futures, "get_binance_usdm_symbols", fake_symbols)
    response = TestClient(app).get("/api/v1/charts/futures/candles?symbol=UNKNOWNUSDT")
    assert response.status_code == 422


def test_usdm_rate_limit_does_not_fan_out_to_other_hosts(monkeypatch):
    class FakeResponse:
        status_code = 429
        def raise_for_status(self):
            raise AssertionError("rate limit should be handled before raise_for_status")
    class FakeClient:
        calls = 0
        async def get(self, *args, **kwargs):
            self.calls += 1
            return FakeResponse()
    client = FakeClient()
    with pytest.raises(futures.BinanceUsdMDataError, match="rate-limited"):
        asyncio.run(futures._request_json(client, "/fapi/v1/exchangeInfo"))
    assert client.calls == 1


def test_usdm_chart_accepts_short_history_for_newly_listed_pairs(monkeypatch):
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    row = [now-120000, "100", "103", "99", "102", "12", now-60001]
    async def fake_info(force_refresh=False):
        return {"NEWUSDT":{"symbol":"NEWUSDT"}}
    async def fake_request(_client, path, params=None):
        return [row]
    monkeypatch.setattr(futures, "get_binance_usdm_symbol_info", fake_info)
    monkeypatch.setattr(futures, "_request_json", fake_request)
    rows = asyncio.run(futures.fetch_binance_usdm_candles("NEWUSDT", "1m", 210))
    assert len(rows) == 1
    assert rows[0]["close"] == 102
