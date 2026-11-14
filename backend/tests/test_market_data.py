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
