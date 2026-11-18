import asyncio

from app.market_data import get_market_overview, gold_lkr_per_gram


def test_gold_spot_conversion_to_lkr_per_gram():
    value = gold_lkr_per_gram(3000.0, 300.0)
    assert round(value, 2) == round(3000.0 / 31.1034768 * 300.0, 2)



def test_bitcoin_overview_falls_back_to_coinbase_when_gold_api_and_binance_fail(monkeypatch):
    import asyncio
    import httpx
    import app.market_data as market_data

    async def gold_unavailable(_client, _symbol):
        raise httpx.ConnectError("Gold-API unavailable")
    async def json_provider(_client, url, **_kwargs):
        if url == market_data.BINANCE_API:
            raise httpx.ConnectError("Binance unavailable")
        if url == market_data.COINBASE_TICKER_API:
            return {"price": "67000.25"}
        raise AssertionError("Unexpected provider: " + url)

    monkeypatch.setattr(market_data, "_gold_api_price", gold_unavailable)
    monkeypatch.setattr(market_data, "_json", json_provider)
    market_data._cache.pop("btc", None)
    async def run():
        async with httpx.AsyncClient() as client:
            return await market_data._btc_price(client)
    value, source = asyncio.run(run())
    assert value == 67000.25
    assert source == "Coinbase Exchange BTC-USD fallback"

def test_market_overview_combines_provider_fallbacks(monkeypatch):
    import app.market_data as market_data

    async def btc(_client):
        return 65000.0, "Binance BTCUSDT fallback"

    async def gold(_client):
        return 3000.0, "Gold-API XAU/USD"

    async def fx(_client):
        return 300.0, "ExchangeRate-API USD/LKR (daily reference)"

    monkeypatch.setattr(market_data, "_btc_price", btc)
    monkeypatch.setattr(market_data, "_gold_price", gold)
    monkeypatch.setattr(market_data, "_usd_lkr", fx)

    result = asyncio.run(get_market_overview())
    assert result["btc_usd"] == 65000.0
    assert result["gold_usd_oz"] == 3000.0
    assert result["usd_lkr"] == 300.0
    assert result["provider_status"] == {"btc": "ok", "gold": "ok", "usd_lkr": "ok"}
    assert result["gold_lkr_8g"] == result["gold_lkr_gram"] * 8


def test_market_prices_reject_nan_and_infinity():
    import math
    import pytest
    import app.market_data as market_data

    for invalid in (float("nan"), float("inf"), float("-inf"), 0.0, -1.0):
        with pytest.raises(ValueError):
            market_data._positive_finite_price(invalid, "test price")
        with pytest.raises(ValueError):
            gold_lkr_per_gram(invalid, 300.0)
        with pytest.raises(ValueError):
            gold_lkr_per_gram(3000.0, invalid)


def test_btc_invalid_provider_values_fall_through_to_next_provider(monkeypatch):
    import httpx
    import app.market_data as market_data

    async def gold_invalid(_client, _symbol):
        raise ValueError("invalid Gold-API value")

    async def json_provider(_client, url, **_kwargs):
        if url == market_data.BINANCE_API:
            return {"price": "NaN"}
        if url == market_data.COINBASE_TICKER_API:
            return {"price": "Infinity"}
        if "coingecko.com" in url:
            return {"bitcoin": {"usd": "67000.25"}}
        raise AssertionError("Unexpected provider: " + url)

    monkeypatch.setattr(market_data, "_gold_api_price", gold_invalid)
    monkeypatch.setattr(market_data, "_json", json_provider)
    market_data._cache.pop("btc", None)

    async def run():
        async with httpx.AsyncClient() as client:
            return await market_data._btc_price(client)

    value, source = asyncio.run(run())
    assert value == 67000.25
    assert math.isfinite(value)
    assert source == "CoinGecko BTC/USD fallback"


def test_usd_lkr_invalid_primary_value_uses_finite_fallback(monkeypatch):
    import httpx
    import app.market_data as market_data

    async def json_provider(_client, url, **_kwargs):
        assert url == market_data.FX_API
        return {"result": "success", "rates": {"LKR": "Infinity"}}

    async def twelve_fallback(_client, _symbol):
        return 415.0

    monkeypatch.setattr(market_data, "_json", json_provider)
    monkeypatch.setattr(market_data, "_twelve_price", twelve_fallback)
    market_data._cache.pop("usd_lkr", None)

    async def run():
        async with httpx.AsyncClient() as client:
            return await market_data._usd_lkr(client)

    value, source = asyncio.run(run())
    assert value == 415.0
    assert source == "Twelve Data USD/LKR fallback"
