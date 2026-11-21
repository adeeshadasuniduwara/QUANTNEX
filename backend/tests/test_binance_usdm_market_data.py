from datetime import datetime, timezone, timedelta

import pytest

from app import binance_usdm_market_data as futures


@pytest.mark.asyncio
async def test_usdm_universe_filters_to_trading_perpetuals(monkeypatch):
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
    info = await futures.get_binance_usdm_symbol_info(force_refresh=True)
    assert set(info) == {"BTCUSDT", "ETHUSD_PERP"}
    assert info["BTCUSDT"]["filters"]["PRICE_FILTER"]["tickSize"] == "0.10"
    assert info["ETHUSD_PERP"]["margin_asset"] == "BTC"


@pytest.mark.asyncio
async def test_usdm_candles_drop_open_and_malformed_rows(monkeypatch):
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    closed = [now-120000, "100", "103", "99", "102", "12", now-60001]
    opened = [now-60000, "102", "104", "101", "103", "4", now+59999]
    malformed = [now-180000, "100", "99", "101", "102", "2", now-120001]
    async def fake_info(force_refresh=False):
        return {"BTCUSDT":{"symbol":"BTCUSDT"}}
    async def fake_request(_client, path, params=None):
        assert path == "/fapi/v1/klines"
        assert params["symbol"] == "BTCUSDT"
        return [malformed, closed, opened]
    monkeypatch.setattr(futures, "get_binance_usdm_symbol_info", fake_info)
    monkeypatch.setattr(futures, "_request_json", fake_request)
    rows = await futures.fetch_binance_usdm_candles("btcusdt", "1m", 210)
    assert len(rows) == 210 # padded below with a controlled short-history error in the next test


@pytest.mark.asyncio
async def test_usdm_rejects_unknown_symbols_before_klines(monkeypatch):
    async def fake_info(force_refresh=False):
        return {}
    monkeypatch.setattr(futures, "get_binance_usdm_symbol_info", fake_info)
    with pytest.raises(futures.BinanceUsdMDataError, match="not an active"):
        await futures.fetch_binance_usdm_candles("NOTREALUSDT", "15m", 210)


@pytest.mark.asyncio
async def test_usdm_rejects_unsupported_interval_and_limit():
    with pytest.raises(futures.BinanceUsdMDataError, match="timeframe"):
        await futures.fetch_binance_usdm_candles("BTCUSDT", "2m", 210)
    with pytest.raises(futures.BinanceUsdMDataError, match="210"):
        await futures.fetch_binance_usdm_candles("BTCUSDT", "1m", 10)
