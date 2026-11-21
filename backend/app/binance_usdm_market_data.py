"""Read-only Binance USDⓈ-M perpetual market data for QUANTNEX VIEW.

This adapter is chart-only. It does not enable Futures signal generation or order
execution. COIN-M delivery/perpetual contracts are intentionally not included.
"""
from __future__ import annotations

import asyncio
import math
import time
from weakref import WeakKeyDictionary
from datetime import datetime, timezone
from typing import Any

import httpx

BASES = (
    "https://fapi.binance.com",
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
    "https://fapi3.binance.com",
    "https://fapi4.binance.com",
)
INTERVALS = {"1m", "5m", "15m", "30m", "1h", "4h"}
_CACHE: tuple[float, dict[str, dict[str, Any]]] | None = None
_CACHE_TTL = 300.0
_LOCKS: WeakKeyDictionary = WeakKeyDictionary()


async def _cache_guard():
    loop = asyncio.get_running_loop()
    lock = _LOCKS.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[loop] = lock
    async with lock:
        yield


class BinanceUsdMDataError(RuntimeError):
    pass


async def _request_json(client: httpx.AsyncClient, path: str,
                        params: dict[str, Any] | None = None) -> Any:
    errors: list[str] = []
    for base in BASES:
        try:
            response = await client.get(base + path, params=params)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict) and payload.get("code", 0) not in (0, None):
                raise BinanceUsdMDataError(
                    f"Binance USDⓈ-M API error {payload.get('code')}: {payload.get('msg', 'unknown')}"
                )
            return payload
        except BinanceUsdMDataError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            errors.append(f"{base}: {exc}")
    raise BinanceUsdMDataError("Binance USDⓈ-M public endpoints unavailable: " + " | ".join(errors))


async def get_binance_usdm_symbol_info(force_refresh: bool = False) -> dict[str, dict[str, Any]]:
    global _CACHE
    cached = _CACHE
    if not force_refresh and cached and time.monotonic() - cached[0] < _CACHE_TTL:
        return cached[1]
    async with _cache_guard():
        cached = _CACHE
        if not force_refresh and cached and time.monotonic() - cached[0] < _CACHE_TTL:
            return cached[1]
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(12, connect=4)) as client:
                payload = await _request_json(client, "/fapi/v1/exchangeInfo")
        except (BinanceUsdMDataError, httpx.HTTPError, ValueError, TypeError) as exc:
            raise BinanceUsdMDataError(f"Could not retrieve USDⓈ-M exchangeInfo: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("symbols"), list):
            raise BinanceUsdMDataError("Binance returned invalid USDⓈ-M exchange metadata.")
        symbols: dict[str, dict[str, Any]] = {}
        for row in payload["symbols"]:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").upper()
            if (row.get("status") != "TRADING" or row.get("contractType") != "PERPETUAL"
                    or not symbol.isalnum() or not row.get("baseAsset") or not row.get("quoteAsset")):
                continue
            filters = {
                str(f.get("filterType")): f
                for f in (row.get("filters") or [])
                if isinstance(f, dict) and f.get("filterType")
            }
            symbols[symbol] = {
                "symbol": symbol,
                "base_asset": str(row.get("baseAsset") or "").upper(),
                "quote_asset": str(row.get("quoteAsset") or "").upper(),
                "margin_asset": str(row.get("marginAsset") or "").upper(),
                "status": row.get("status"),
                "contract_type": row.get("contractType"),
                "price_precision": row.get("pricePrecision"),
                "quantity_precision": row.get("quantityPrecision"),
                "filters": filters,
            }
        if not symbols:
            raise BinanceUsdMDataError("No active USDⓈ-M perpetual contracts were returned.")
        _CACHE = (time.monotonic(), symbols)
        return symbols


async def get_binance_usdm_symbols(force_refresh: bool = False) -> list[str]:
    return sorted((await get_binance_usdm_symbol_info(force_refresh)).keys())


async def fetch_binance_usdm_candles(symbol: str, interval: str, limit: int = 1000) -> list[dict[str, Any]]:
    normalized = str(symbol or "").strip().upper()
    if interval not in INTERVALS:
        raise BinanceUsdMDataError("Unsupported USDⓈ-M chart timeframe.")
    if not 210 <= int(limit) <= 1000:
        raise BinanceUsdMDataError("Choose between 210 and 1,000 Futures candles.")
    info = await get_binance_usdm_symbol_info()
    if normalized not in info:
        raise BinanceUsdMDataError(f"{normalized} is not an active USDⓈ-M perpetual contract.")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5)) as client:
            payload = await _request_json(client, "/fapi/v1/klines", {
                "symbol": normalized, "interval": interval, "limit": int(limit)
            })
    except (BinanceUsdMDataError, httpx.HTTPError, ValueError, TypeError) as exc:
        raise BinanceUsdMDataError(f"Could not load {normalized} USDⓈ-M candles: {exc}") from exc
    if not isinstance(payload, list):
        raise BinanceUsdMDataError("Binance returned invalid USDⓈ-M kline data.")
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    rows: list[dict[str, Any]] = []
    for row in payload:
        try:
            if not isinstance(row, list) or len(row) < 7 or int(row[6]) >= now_ms:
                continue
            stamp = datetime.fromtimestamp(int(row[0]) / 1000, timezone.utc).isoformat()
            op, high, low, close, volume = (float(row[i]) for i in (1, 2, 3, 4, 5))
            if not all(math.isfinite(x) for x in (op, high, low, close, volume)):
                continue
            if min(op, high, low, close) <= 0 or volume < 0 or high < max(op, close, low) or low > min(op, close, high):
                continue
            rows.append({"time": stamp, "open": op, "high": high, "low": low,
                         "close": close, "volume": volume})
        except (IndexError, TypeError, ValueError, OverflowError):
            continue
    rows.sort(key=lambda x: x["time"])
    if len(rows) < 210:
        raise BinanceUsdMDataError(f"Only {len(rows)} closed valid {normalized} Futures candles; 210 required.")
    return rows[-int(limit):]
