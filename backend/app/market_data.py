"""Public indicative market overview feeds for the QUANTNEX dashboard."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import httpx
from .config import TWELVE_DATA_API_KEY

def gold_lkr_per_gram(gold_usd_per_troy_ounce: float, usd_lkr: float) -> float:
    return gold_usd_per_troy_ounce / 31.1034768 * usd_lkr

async def _twelve_price(client: httpx.AsyncClient, symbol: str):
    if not TWELVE_DATA_API_KEY:
        return None
    response=await client.get("https://api.twelvedata.com/price",params={"symbol":symbol,"apikey":TWELVE_DATA_API_KEY})
    response.raise_for_status()
    payload=response.json()
    if payload.get("status")=="error":
        return None
    try:return float(payload["price"])
    except (KeyError,TypeError,ValueError):return None

async def get_market_overview():
    async with httpx.AsyncClient(timeout=12) as client:
        async def btc():
            response=await client.get("https://api.binance.com/api/v3/ticker/price",params={"symbol":"BTCUSDT"})
            response.raise_for_status()
            return float(response.json()["price"])
        results=await asyncio.gather(btc(),_twelve_price(client,"XAU/USD"),_twelve_price(client,"USD/LKR"),return_exceptions=True)
    btc_price,gold_usd,usd_lkr=results
    def value(x):return None if isinstance(x,Exception) else x
    btc_price,gold_usd,usd_lkr=map(value,(btc_price,gold_usd,usd_lkr))
    gold_lkr_gram=gold_lkr_per_gram(gold_usd,usd_lkr) if gold_usd is not None and usd_lkr is not None else None
    return {
        "btc_usd":btc_price,"gold_usd_oz":gold_usd,"usd_lkr":usd_lkr,
        "gold_lkr_gram":gold_lkr_gram,"gold_lkr_8g":gold_lkr_gram*8 if gold_lkr_gram is not None else None,
        "gold_calculation":"XAU/USD per troy ounce ÷ 31.1034768 × USD/LKR; 8g = gram price × 8",
        "timestamp":datetime.now(timezone.utc).isoformat(),
        "sources":{"btc":"Binance BTCUSDT ticker","gold":"Twelve Data XAU/USD","fx":"Twelve Data USD/LKR"},
        "note":"Indicative spot conversion only; not a Sri Lankan jeweller quote. Local taxes, purity and dealer premiums are excluded."
    }
