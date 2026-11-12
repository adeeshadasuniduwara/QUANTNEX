import asyncio

from app.market_data import get_market_overview, gold_lkr_per_gram


def test_gold_spot_conversion_to_lkr_per_gram():
    value = gold_lkr_per_gram(3000.0, 300.0)
    assert round(value, 2) == round(3000.0 / 31.1034768 * 300.0, 2)


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
