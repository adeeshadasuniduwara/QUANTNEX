"""Resilient, cached public market overview feeds for QUANTNEX.

BTC and XAU spot prices use Gold-API's keyless real-time endpoint first.
BTC falls back to Binance; XAU falls back to Twelve Data when configured.
USD/LKR uses the keyless daily ExchangeRate-API feed, then Twelve Data.
These are indicative prices, not executable quotes.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import time
from typing import Any

import httpx

from .config import TWELVE_DATA_API_KEY

GOLD_API = "https://api.gold-api.com/price"
BINANCE_API = "https://api.binance.com/api/v3/ticker/price"
FX_API = "https://open.er-api.com/v6/latest/USD"
CACHE_SECONDS = 25.0
_FX_CACHE_SECONDS = 3600.0
_cache: dict[str, tuple[float, Any]] = {}


def gold_lkr_per_gram(gold_usd_per_troy_ounce: float, usd_lkr: float) -> float:
    return gold_usd_per_troy_ounce / 31.1034768 * usd_lkr


def _cached(key: str, max_age: float):
    item = _cache.get(key)
    if item and time.monotonic() - item[0] < max_age:
        return item[1]
    return None


def _store(key: str, value: Any):
    _cache[key] = (time.monotonic(), value)
    return value


async def _json(client: httpx.AsyncClient, url: str, **kwargs) -> dict:
    response = await client.get(url, **kwargs)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Market provider returned an invalid response.")
    return payload


async def _gold_api_price(client: httpx.AsyncClient, symbol: str) -> float:
    payload = await _json(client, f"{GOLD_API}/{symbol}")
    value = float(payload["price"])
    if value <= 0:
        raise ValueError("Market provider returned a non-positive price.")
    return value


async def _twelve_price(client: httpx.AsyncClient, symbol: str) -> float | None:
    if not TWELVE_DATA_API_KEY:
        return None
    payload = await _json(
        client,
        "https://api.twelvedata.com/price",
        params={"symbol": symbol, "apikey": TWELVE_DATA_API_KEY},
    )
    if payload.get("status") == "error":
        return None
    value = float(payload["price"])
    return value if value > 0 else None


async def _btc_price(client: httpx.AsyncClient) -> tuple[float | None, str]:
    cached = _cached("btc", CACHE_SECONDS)
    if cached is not None:
        return cached, "cached Gold-API/Binance"
    try:
        value = await _gold_api_price(client, "BTC")
        return _store("btc", value), "Gold-API BTC/USD"
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        try:
            payload = await _json(client, BINANCE_API, params={"symbol": "BTCUSDT"})
            value = float(payload["price"])
            if value <= 0:
                raise ValueError("Invalid Binance BTC price.")
            return _store("btc", value), "Binance BTCUSDT fallback"
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            try:
                payload = await _json(
                    client,
                    "https://api.coingecko.com/api/v3/simple/price",
                    params={"ids": "bitcoin", "vs_currencies": "usd"},
                )
                value = float(payload["bitcoin"]["usd"])
                if value <= 0:
                    raise ValueError("Invalid CoinGecko BTC price.")
                return _store("btc", value), "CoinGecko BTC/USD fallback"
            except (httpx.HTTPError, KeyError, TypeError, ValueError):
                return None, "unavailable"


async def _gold_price(client: httpx.AsyncClient) -> tuple[float | None, str]:
    cached = _cached("gold", CACHE_SECONDS)
    if cached is not None:
        return cached, "cached Gold-API/Twelve Data"
    try:
        value = await _gold_api_price(client, "XAU")
        return _store("gold", value), "Gold-API XAU/USD"
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        try:
            value = await _twelve_price(client, "XAU/USD")
            if value is not None:
                return _store("gold", value), "Twelve Data XAU/USD fallback"
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            pass
        return None, "unavailable"


async def _usd_lkr(client: httpx.AsyncClient) -> tuple[float | None, str]:
    cached = _cached("usd_lkr", _FX_CACHE_SECONDS)
    if cached is not None:
        return cached, "cached ExchangeRate-API"
    try:
        payload = await _json(client, FX_API)
        if payload.get("result") != "success":
            raise ValueError("Exchange rate provider returned an error.")
        value = float(payload["rates"]["LKR"])
        if value <= 0:
            raise ValueError("Invalid USD/LKR rate.")
        return _store("usd_lkr", value), "ExchangeRate-API USD/LKR (daily reference)"
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        try:
            value = await _twelve_price(client, "USD/LKR")
            if value is not None:
                return _store("usd_lkr", value), "Twelve Data USD/LKR fallback"
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            pass
        return None, "unavailable"


async def get_market_overview():
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0), follow_redirects=True) as client:
        btc, gold, fx = await asyncio.gather(
            _btc_price(client), _gold_price(client), _usd_lkr(client)
        )

    btc_price, btc_source = btc
    gold_usd, gold_source = gold
    usd_lkr, fx_source = fx
    gold_lkr_gram = (
        gold_lkr_per_gram(gold_usd, usd_lkr)
        if gold_usd is not None and usd_lkr is not None else None
    )
    return {
        "btc_usd": btc_price,
        "gold_usd_oz": gold_usd,
        "usd_lkr": usd_lkr,
        "gold_lkr_gram": gold_lkr_gram,
        "gold_lkr_8g": gold_lkr_gram * 8 if gold_lkr_gram is not None else None,
        "gold_calculation": "XAU/USD per troy ounce ÷ 31.1034768 × USD/LKR; 8g = gram price × 8",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sources": {"btc": btc_source, "gold": gold_source, "fx": fx_source},
        "provider_status": {
            "btc": "ok" if btc_price is not None else "unavailable",
            "gold": "ok" if gold_usd is not None else "unavailable",
            "usd_lkr": "ok" if usd_lkr is not None else "unavailable",
        },
        "note": "Indicative spot conversion only; not a Sri Lankan jeweller quote. Local taxes, purity and dealer premiums are excluded. USD/LKR reference rate may update daily.",
    }
