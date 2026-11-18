"""Multi-timeframe confluence engine for Binance Spot pairs and XAUUSD.

Scores are rule-based confluence counts, never estimated win probabilities.
Binance signals require fresh order-book data and a validated MARKET/LIMIT entry.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
import math
import time
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from weakref import WeakKeyDictionary
from typing import Any
import httpx
from .config import TWELVE_DATA_API_KEY, QUANTNEX_MT5_ENABLED, QUANTNEX_MT5_GOLD_SYMBOL
from .binance_public import BinancePublicDataError, get_binance_public_json
from .binance_order_flow_feed import BinanceOrderFlowFeedError, fetch_spot_order_flow
from .order_flow import OrderFlowDataError, evaluate_order_flow_confirmation, summarize_order_flow_snapshot

BASE = "https://api.twelvedata.com/time_series"
INTERVALS = {"1": "1min", "5": "5min", "15": "15min", "30": "30min", "60": "1h", "240": "4h"}

class MarketDataError(RuntimeError):
    pass


def gold_feed_provider() -> str | None:
    """Return the configured historical XAUUSD candle provider, if any."""
    if QUANTNEX_MT5_ENABLED:
        return "MetaTrader 5 local terminal"
    if TWELVE_DATA_API_KEY:
        return "Twelve Data"
    return None


def gold_feed_configured() -> bool:
    """Whether an XAUUSD historical candle provider is configured."""
    return gold_feed_provider() is not None

CRYPTO_SYMBOLS = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT", "BCHUSDT", "DOTUSDT", "TRXUSDT", "TONUSDT", "SUIUSDT", "NEARUSDT", "UNIUSDT", "AAVEUSDT", "SHIBUSDT", "PEPEUSDT"}

# Binance Spot is the authoritative crypto universe. CRYPTO_SYMBOLS remains a
# compatibility set for older callers; new symbols are resolved dynamically.
_BINANCE_SPOT_SYMBOLS_CACHE: tuple[float, dict[str, dict[str, Any]]] | None = None
_BINANCE_SPOT_SYMBOLS_TTL = 300.0
_BINANCE_SYMBOL_LOCKS: WeakKeyDictionary = WeakKeyDictionary()


@asynccontextmanager
async def _binance_symbol_cache_guard():
    loop = asyncio.get_running_loop()
    lock = _BINANCE_SYMBOL_LOCKS.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _BINANCE_SYMBOL_LOCKS[loop] = lock
    async with lock:
        yield


async def get_binance_spot_symbols(force_refresh: bool = False) -> list[str]:
    """Return all currently tradable Binance Spot symbols from exchangeInfo."""
    global _BINANCE_SPOT_SYMBOLS_CACHE
    cached = _BINANCE_SPOT_SYMBOLS_CACHE
    if not force_refresh and cached and time.monotonic() - cached[0] < _BINANCE_SPOT_SYMBOLS_TTL:
        return sorted(cached[1].keys())

    async with _binance_symbol_cache_guard():
        cached = _BINANCE_SPOT_SYMBOLS_CACHE
        if not force_refresh and cached and time.monotonic() - cached[0] < _BINANCE_SPOT_SYMBOLS_TTL:
            return sorted(cached[1].keys())
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5)) as client:
                payload, _source_base = await get_binance_public_json(client, "/api/v3/exchangeInfo")
        except (BinancePublicDataError, httpx.HTTPError, ValueError, TypeError) as exc:
            raise MarketDataError(f"Could not retrieve Binance Spot exchange symbol metadata: {exc}") from exc

        if not isinstance(payload, dict) or not isinstance(payload.get("symbols"), list):
            raise MarketDataError("Binance returned invalid Spot exchange metadata.")
        symbols: dict[str, dict[str, Any]] = {}
        for item in payload["symbols"]:
            if not isinstance(item, dict) or item.get("status") != "TRADING":
                continue
            symbol = str(item.get("symbol") or "").upper()
            base = str(item.get("baseAsset") or "").upper()
            quote = str(item.get("quoteAsset") or "").upper()
            permissions = item.get("permissions") or []
            permission_sets = item.get("permissionSets") or []
            spot_allowed = item.get("isSpotTradingAllowed")
            if spot_allowed is False:
                continue
            if spot_allowed is not True and "SPOT" not in permissions and not any(
                isinstance(group, list) and "SPOT" in group for group in permission_sets
            ):
                continue
            if not symbol.isalnum() or not base or not quote or symbol != base + quote:
                continue
            filters = {
                str(value.get("filterType")): value
                for value in (item.get("filters") or [])
                if isinstance(value, dict) and value.get("filterType")
            }
            order_types = item.get("orderTypes") or []
            if not isinstance(order_types, list):
                order_types = []
            symbols[symbol] = {
                "symbol": symbol,
                "base_asset": base,
                "quote_asset": quote,
                "status": str(item.get("status") or ""),
                "is_spot_trading_allowed": spot_allowed is True or (
                    spot_allowed is None and (
                        "SPOT" in permissions or any(
                            isinstance(group, list) and "SPOT" in group
                            for group in permission_sets
                        )
                    )
                ),
                "permissions": list(permissions) if isinstance(permissions, list) else [],
                "permission_sets": [
                    list(group) for group in permission_sets if isinstance(group, list)
                ],
                "order_types": sorted({str(value).upper() for value in order_types if str(value).strip()}),
                "base_asset_precision": item.get("baseAssetPrecision"),
                "quote_asset_precision": item.get("quoteAssetPrecision"),
                "quote_precision": item.get("quotePrecision"),
                "quote_order_qty_market_allowed": item.get("quoteOrderQtyMarketAllowed") is True,
                "filters": filters,
            }
        if not symbols:
            raise MarketDataError("Binance exchange metadata contained no eligible Spot trading pairs.")
        _BINANCE_SPOT_SYMBOLS_CACHE = (time.monotonic(), symbols)
        return sorted(symbols.keys())


async def get_binance_spot_symbol_info(symbol: str) -> dict[str, Any]:
    """Return cached Binance exchange filters for one active Spot symbol."""
    normalized = str(symbol or "").strip().upper()
    await get_binance_spot_symbols()
    cached = _BINANCE_SPOT_SYMBOLS_CACHE
    info = cached[1].get(normalized) if cached else None
    if info is None:
        raise MarketDataError(f"{normalized} is not a currently tradable Binance Spot pair.")
    return info


async def is_binance_spot_symbol(symbol: str) -> bool:
    """Validate a Binance Spot pair, including pairs listed after app release."""
    normalized = str(symbol or "").strip().upper()
    if not normalized or not normalized.isalnum() or len(normalized) > 30 or normalized == "XAUUSD":
        return False
    # The old CRYPTO_SYMBOLS constant is retained for compatibility with
    # legacy UI defaults only. It must never bypass authoritative exchangeInfo:
    # a previously-known pair may be delisted or lose Spot trading permission.
    return normalized in set(await get_binance_spot_symbols())


async def get_binance_spot_execution_context(symbol: str) -> dict[str, Any]:
    """Fetch fresh top-of-book and depth plus the pair's exchange price filters."""
    normalized = str(symbol or "").strip().upper()
    info = await get_binance_spot_symbol_info(normalized)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12, connect=5)) as client:
            quote, quote_source_base = await get_binance_public_json(
                client, "/api/v3/ticker/bookTicker", {"symbol": normalized}
            )
            depth, depth_source_base = await get_binance_public_json(
                client, "/api/v3/depth", {"symbol": normalized, "limit": 20}
            )
            quote_asset = str(info.get("quote_asset") or "").upper()
            stable_quotes = {"USDT", "USDC", "FDUSD", "BUSD", "TUSD", "USDP", "DAI", "USDE"}
            quote_asset_usd_rate = 1.0 if quote_asset in stable_quotes else None
            quote_asset_usd_rate_source = "stablecoin_parity_assumption" if quote_asset_usd_rate else None
            if quote_asset_usd_rate is None and _BINANCE_SPOT_SYMBOLS_CACHE:
                known_symbols = _BINANCE_SPOT_SYMBOLS_CACHE[1]
                conversion_symbol = next(
                    (quote_asset + suffix for suffix in ("USDT", "USDC", "FDUSD", "BUSD")
                     if quote_asset + suffix in known_symbols),
                    None,
                )
                if conversion_symbol:
                    try:
                        conversion, _conversion_source_base = await get_binance_public_json(
                            client, "/api/v3/ticker/bookTicker", {"symbol": conversion_symbol}
                        )
                        conversion_bid = float(conversion["bidPrice"])
                        conversion_ask = float(conversion["askPrice"])
                        if (
                            math.isfinite(conversion_bid) and math.isfinite(conversion_ask)
                            and conversion_bid > 0 and conversion_ask >= conversion_bid
                        ):
                            quote_asset_usd_rate = (conversion_bid + conversion_ask) / 2
                            quote_asset_usd_rate_source = conversion_symbol
                    except (BinancePublicDataError, httpx.HTTPError, ValueError, TypeError, KeyError):
                        quote_asset_usd_rate = None
    except (BinancePublicDataError, httpx.HTTPError, ValueError, TypeError) as exc:
        raise MarketDataError(f"Could not retrieve fresh Binance Spot execution data for {normalized}: {exc}") from exc

    try:
        bid = float(quote["bidPrice"])
        ask = float(quote["askPrice"])
        bid_qty = float(quote["bidQty"])
        ask_qty = float(quote["askQty"])
        if not all(math.isfinite(value) for value in (bid, ask, bid_qty, ask_qty)):
            raise ValueError()
        if bid <= 0 or ask < bid or bid_qty < 0 or ask_qty < 0:
            raise ValueError()
        bids = depth.get("bids", [])
        asks = depth.get("asks", [])
        bid_depth_quote = sum(float(row[0]) * float(row[1]) for row in bids[:10])
        ask_depth_quote = sum(float(row[0]) * float(row[1]) for row in asks[:10])
        if not all(math.isfinite(value) and value >= 0 for value in (bid_depth_quote, ask_depth_quote)):
            raise ValueError()
    except (AttributeError, KeyError, IndexError, TypeError, ValueError, OverflowError):
        raise MarketDataError(f"Binance returned invalid top-of-book/depth data for {normalized}.") from None

def _normalise_lot_filter(filter_data: Any) -> dict[str, Any]:
    """Preserve Binance lot constraints and mark them usable only when complete."""
    raw = filter_data if isinstance(filter_data, dict) else {}
    fields = {
        "step_size": raw.get("stepSize"),
        "min_quantity": raw.get("minQty"),
        "max_quantity": raw.get("maxQty"),
    }
    try:
        step = Decimal(str(fields["step_size"]))
        minimum = Decimal(str(fields["min_quantity"]))
        maximum = Decimal(str(fields["max_quantity"]))
        valid = (
            step.is_finite() and step > 0
            and minimum.is_finite() and minimum >= 0
            and maximum.is_finite() and maximum > 0
            and maximum >= minimum
        )
    except (ArithmeticError, TypeError, ValueError):
        valid = False
    return {**fields, "valid": valid}


def _normalise_price_filter(filter_data: Any) -> dict[str, Any]:
    """Return exact price bounds/tick; never invent a fallback tick size."""
    raw = filter_data if isinstance(filter_data, dict) else {}
    fields = {
        "tick_size": raw.get("tickSize"),
        "min_price": raw.get("minPrice"),
        "max_price": raw.get("maxPrice"),
    }
    try:
        tick = Decimal(str(fields["tick_size"]))
        minimum = Decimal(str(fields["min_price"] or "0"))
        maximum = Decimal(str(fields["max_price"] or "0"))
        valid = (
            tick.is_finite() and tick > 0
            and minimum.is_finite() and minimum >= 0
            and maximum.is_finite() and maximum >= 0
            and (maximum == 0 or minimum == 0 or maximum >= minimum)
        )
    except (ArithmeticError, TypeError, ValueError):
        valid = False
    return {**fields, "valid": valid}


def _normalise_notional_filter(filter_data: Any) -> dict[str, Any]:
    """Preserve both current NOTIONAL and legacy MIN_NOTIONAL market flags."""
    raw = filter_data if isinstance(filter_data, dict) else {}
    minimum_raw = raw.get("minNotional", raw.get("minNotionalValue"))
    maximum_raw = raw.get("maxNotional")
    try:
        minimum = Decimal(str(minimum_raw))
        minimum_valid = minimum.is_finite() and minimum > 0
    except (ArithmeticError, TypeError, ValueError):
        minimum_valid = False
    maximum_valid = True
    if maximum_raw not in (None, ""):
        try:
            maximum = Decimal(str(maximum_raw))
            maximum_valid = maximum.is_finite() and maximum > 0
        except (ArithmeticError, TypeError, ValueError):
            maximum_valid = False
    apply_min = raw.get("applyMinToMarket")
    if apply_min is None:
        apply_min = raw.get("applyToMarket")
    # Unknown market applicability is treated conservatively as enabled.
    if not isinstance(apply_min, bool):
        apply_min = True
    return {
        "min_notional": minimum_raw,
        "max_notional": maximum_raw,
        "apply_min_to_market": apply_min,
        "apply_max_to_market": raw.get("applyMaxToMarket") is True,
        "valid": minimum_valid and maximum_valid,
        "present": bool(raw),
    }


    mid = (bid + ask) / 2
    spread_bps = ((ask - bid) / mid) * 10000 if mid > 0 else float("inf")
    filters = info.get("filters", {})
    price_constraints = _normalise_price_filter(filters.get("PRICE_FILTER"))
    limit_lot_constraints = _normalise_lot_filter(filters.get("LOT_SIZE"))
    market_lot_constraints = _normalise_lot_filter(filters.get("MARKET_LOT_SIZE"))
    notional_filter = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL")
    notional_constraints = _normalise_notional_filter(notional_filter)
    order_types = list(info.get("order_types") or [])
    tick_size = str(price_constraints["tick_size"]) if price_constraints["valid"] else None
    limit_order_constraints_valid = bool(
        "LIMIT" in order_types and price_constraints["valid"]
        and limit_lot_constraints["valid"] and notional_constraints["valid"]
    )
    market_order_constraints_valid = bool(
        "MARKET" in order_types and price_constraints["valid"]
        and market_lot_constraints["valid"] and notional_constraints["present"]
        and notional_constraints["valid"]
    )
    filter_reasons = []
    if "MARKET" not in order_types:
        filter_reasons.append("MARKET is not listed in exchangeInfo orderTypes")
    elif not market_lot_constraints["valid"]:
        filter_reasons.append("MARKET_LOT_SIZE is missing or invalid")
    if "LIMIT" not in order_types:
        filter_reasons.append("LIMIT is not listed in exchangeInfo orderTypes")
    elif not limit_lot_constraints["valid"]:
        filter_reasons.append("LOT_SIZE is missing or invalid")
    if not price_constraints["valid"]:
        filter_reasons.append("PRICE_FILTER tickSize is missing or invalid")
    if not notional_constraints["valid"]:
        filter_reasons.append("NOTIONAL/MIN_NOTIONAL constraints are missing or invalid")
    return {
        "symbol": normalized,
        "provider": "Binance Spot",
        "best_bid": bid,
        "best_ask": ask,
        "best_bid_quantity": bid_qty,
        "best_ask_quantity": ask_qty,
        "mid_price": mid,
        "spread_bps": spread_bps,
        "bid_depth_quote": bid_depth_quote,
        "ask_depth_quote": ask_depth_quote,
        "quote_asset": info.get("quote_asset"),
        "quote_asset_usd_rate": quote_asset_usd_rate,
        "quote_asset_usd_rate_source": quote_asset_usd_rate_source,
        "bid_depth_usd": bid_depth_quote * quote_asset_usd_rate if quote_asset_usd_rate else 0.0,
        "ask_depth_usd": ask_depth_quote * quote_asset_usd_rate if quote_asset_usd_rate else 0.0,
        "tick_size": tick_size,
        "step_size": str(limit_lot_constraints["step_size"] or ""),
        "min_quantity": str(limit_lot_constraints["min_quantity"] or ""),
        "min_notional": str(notional_constraints["min_notional"] or ""),
        "order_types": order_types,
        "base_asset_precision": info.get("base_asset_precision"),
        "quote_asset_precision": info.get("quote_asset_precision"),
        "quote_precision": info.get("quote_precision"),
        "quote_order_qty_market_allowed": info.get("quote_order_qty_market_allowed") is True,
        "price_filter": price_constraints,
        "limit_lot_size": limit_lot_constraints,
        "market_lot_size": market_lot_constraints,
        "notional_filter": notional_constraints,
        "limit_order_constraints_valid": limit_order_constraints_valid,
        "market_order_constraints_valid": market_order_constraints_valid,
        "order_filter_rejection_reason": "; ".join(filter_reasons) or None,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "data_sources": {"quote": quote_source_base, "depth": depth_source_base},
    }


def round_price_to_tick(value: float, tick_size: str, *, round_up: bool) -> float:
    """Round a price to the exchange tick without introducing float-step errors."""
    try:
        price = Decimal(str(value))
        tick = Decimal(str(tick_size))
        if not price.is_finite() or not tick.is_finite() or price <= 0 or tick <= 0:
            raise ValueError()
        units = (price / tick).to_integral_value(rounding=ROUND_UP if round_up else ROUND_DOWN)
        return float(units * tick)
    except (ArithmeticError, ValueError, TypeError):
        raise MarketDataError("Binance returned an invalid price tick size.") from None


def select_binance_entry(
    side: str, close: float, atr_value: float, zone: dict[str, float] | None,
    execution: dict[str, Any], settings: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Choose a marketable entry or a technically justified resting limit."""
    settings = settings or {}
    spread = float(execution["spread_bps"])
    depth = float(
        execution.get("ask_depth_usd", execution.get("ask_depth_quote", 0.0))
        if side == "BUY" else
        execution.get("bid_depth_usd", execution.get("bid_depth_quote", 0.0))
    )
    bid = float(execution["best_bid"])
    ask = float(execution["best_ask"])
    mid = float(execution["mid_price"])
    if not all(math.isfinite(value) for value in (spread, depth, bid, ask, mid, close, atr_value)):
        return None
    if atr_value <= 0 or spread < 0 or depth < 0 or ask < bid:
        return None

    market_spread_cap = float(settings.get("max_market_spread_bps", 10.0))
    limit_spread_cap = float(settings.get("max_limit_spread_bps", 25.0))
    market_depth_floor = float(settings.get("min_market_depth_usd", settings.get("min_market_depth_quote", 5000.0)))
    limit_depth_floor = float(settings.get("min_limit_depth_usd", settings.get("min_limit_depth_quote", 1000.0)))
    market_drift_cap = float(settings.get("max_market_entry_deviation_atr", 0.20))
    limit_distance_cap = float(settings.get("max_limit_entry_distance_atr", 0.75))
    is_replay = execution.get("is_replay") is True
    order_types = {
        str(value).upper() for value in (execution.get("order_types") or [])
        if str(value).strip()
    }
    market_allowed = is_replay or (
        "MARKET" in order_types and execution.get("market_order_constraints_valid") is True
    )
    limit_allowed = is_replay or (
        "LIMIT" in order_types and execution.get("limit_order_constraints_valid") is True
    )

    def within_price_filter(value: float) -> bool:
        try:
            minimum = float(execution.get("price_filter", {}).get("min_price") or 0)
            maximum = float(execution.get("price_filter", {}).get("max_price") or 0)
            return (
                math.isfinite(minimum) and math.isfinite(maximum)
                and (minimum <= 0 or value >= minimum)
                and (maximum <= 0 or value <= maximum)
            )
        except (TypeError, ValueError, AttributeError, OverflowError):
            return False

    market_price = ask if side == "BUY" else bid
    market_drift = abs(market_price - close) / atr_value

    if (
        market_allowed and within_price_filter(market_price)
        and spread <= market_spread_cap and depth >= market_depth_floor
        and market_drift <= market_drift_cap
    ):
        return {
            "entry_type": "MARKET",
            "entry_price": market_price,
            "reason": (
                "Historical replay model: assumed spread/depth pass the MARKET gate."
                if execution.get("is_replay") else
                "Fresh spread and top-book liquidity are acceptable, and price remains close to the confirmed signal candle."
            ),
        }

    if zone and isinstance(zone, dict):
        try:
            candidate = (float(zone["low"]) + float(zone["high"])) / 2
        except (KeyError, TypeError, ValueError, OverflowError):
            candidate = 0.0
        favorable = candidate < ask if side == "BUY" else candidate > bid
        distance = abs(mid - candidate) / atr_value if candidate > 0 else float("inf")
        if (
            limit_allowed and within_price_filter(candidate)
            and spread <= limit_spread_cap
            and depth >= limit_depth_floor
            and favorable
            and distance <= limit_distance_cap
        ):
            return {
                "entry_type": "LIMIT",
                "entry_price": candidate,
                "reason": (
                    "Historical replay model: assumed spread/depth pass; resting LIMIT is placed at the OB/FVG zone midpoint."
                    if execution.get("is_replay") else
                    "Price has moved away from the signal close; a resting limit is placed at the confirmed OB/FVG zone midpoint."
                ),
            }
    return None


BINANCE_INTERVALS = {"1min":"1m", "5min":"5m", "15min":"15m", "30min":"30m", "1h":"1h", "4h":"4h"}
INTERVAL_SECONDS = {"1min":60, "5min":300, "15min":900, "30min":1800,
                    "1h":3600, "4h":14400, "50min":3000}


def validate_candle_freshness(candles: list[dict[str, Any]], interval: str,
                              now: datetime | None = None) -> float:
    """Reject candles whose latest fully closed bar is too old or future-dated."""
    seconds = INTERVAL_SECONDS.get(interval)
    if seconds is None:
        raise MarketDataError(f"Unsupported candle interval for freshness validation: {interval}.")
    if not candles:
        raise MarketDataError(f"No {interval} candles are available for freshness validation.")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)
    try:
        stamp = datetime.fromisoformat(str(candles[-1]["time"]).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        close_time = stamp.astimezone(timezone.utc) + timedelta(seconds=seconds)
    except (KeyError, TypeError, ValueError, OverflowError):
        raise MarketDataError(f"The latest {interval} candle has an invalid timestamp.") from None
    age = (current - close_time).total_seconds()
    if age < -30:
        raise MarketDataError(f"The latest {interval} candle closes {abs(age):.0f}s in the future.")
    max_age = max(120, seconds * 2)
    if age > max_age:
        raise MarketDataError(
            f"The latest {interval} candle is stale ({age:.0f}s old; maximum allowed age is {max_age}s)."
        )
    return age


def closed_candles(candles: list[dict[str, Any]], interval: str,
                   now: datetime | None = None) -> list[dict[str, Any]]:
    """Keep only candles whose full interval has elapsed at the supplied UTC time."""
    seconds = INTERVAL_SECONDS.get(interval)
    if seconds is None:
        raise MarketDataError(f"Unsupported candle interval for close validation: {interval}.")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)
    result = []
    for candle in candles:
        try:
            stamp = datetime.fromisoformat(str(candle["time"]).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            if stamp.astimezone(timezone.utc).timestamp() + seconds <= current.timestamp():
                result.append(candle)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return result
_GOLD_CANDLE_CACHE: dict[tuple[str, str, int], tuple[float, list[dict[str, Any]]]] = {}
_GOLD_CANDLE_CACHE_TTL = 45.0
_GOLD_CANDLE_CACHE_LOCKS: WeakKeyDictionary = WeakKeyDictionary()


@asynccontextmanager
async def _gold_candle_cache_guard(cache_key: tuple[str, str, int]):
    """Serialize same-key fetches and release idle locks after the last waiter."""
    loop = asyncio.get_running_loop()
    loop_locks = _GOLD_CANDLE_CACHE_LOCKS.get(loop)
    if loop_locks is None:
        loop_locks = {}
        _GOLD_CANDLE_CACHE_LOCKS[loop] = loop_locks
    entry = loop_locks.get(cache_key)
    if entry is None:
        entry = {"lock": asyncio.Lock(), "users": 0}
        loop_locks[cache_key] = entry
    entry["users"] += 1
    try:
        async with entry["lock"]:
            yield
    finally:
        entry["users"] -= 1
        if entry["users"] <= 0:
            loop_locks.pop(cache_key, None)


def _cached_gold_candles(cache_key: tuple[str, str, int]) -> list[dict[str, Any]] | None:
    cached = _GOLD_CANDLE_CACHE.get(cache_key)
    if cached and time.monotonic() - cached[0] < _GOLD_CANDLE_CACHE_TTL:
        return [dict(row) for row in cached[1]]
    return None


def _normalize_gold_candles(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate and normalize provider OHLC rows into unique ascending UTC candles."""
    normalized: dict[int, dict[str, Any]] = {}
    for row in values:
        try:
            raw_time = str(row["datetime"]).replace("Z", "+00:00")
            stamp = datetime.fromisoformat(raw_time)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            stamp = stamp.astimezone(timezone.utc)
            prices = [float(row[key]) for key in ("open", "high", "low", "close")]
            if not all(math.isfinite(value) and value > 0 for value in prices):
                continue
            op, high, low, close = prices
            if high < max(op, close, low) or low > min(op, close, high):
                continue
            volume = float(row.get("volume", 0.0) or 0.0)
            if not math.isfinite(volume) or volume < 0:
                volume = 0.0
            normalized[int(stamp.timestamp())] = {
                "time": stamp.isoformat(), "open": op, "high": high,
                "low": low, "close": close, "volume": volume,
            }
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return [normalized[key] for key in sorted(normalized)]

async def _fetch_coinbase_candles(symbol: str, interval: str, requested: int) -> list[dict[str, Any]]:
    """Public BTC/ETH/SOL USD candles used only when Binance history is unreachable."""
    products = {"BTCUSDT": "BTC-USD", "ETHUSDT": "ETH-USD", "SOLUSDT": "SOL-USD"}
    product = products.get(symbol)
    granularities = {"1min": 60, "5min": 300, "15min": 900, "1h": 3600}
    granularity = granularities.get(interval)
    if not product or granularity is None:
        raise MarketDataError("Coinbase fallback supports BTCUSDT, ETHUSDT and SOLUSDT at 1m, 5m, 15m or 1h.")
    count = min(max(int(requested), 210), 300)
    end = datetime.now(timezone.utc)
    begin = end - timedelta(seconds=granularity * (count + 2))
    params = {
        "granularity": granularity,
        "start": begin.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "end": end.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(18, connect=5), follow_redirects=True,
                                 headers={"User-Agent": "QUANTNEX-Market-Data"}) as client:
        response = await client.get(f"https://api.exchange.coinbase.com/products/{product}/candles", params=params)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, list):
        raise MarketDataError("Coinbase returned an unexpected candle response.")
    candles = []
    for row in payload:
        try:
            # Coinbase Exchange order: [time, low, high, open, close, volume].
            stamp = datetime.fromtimestamp(int(row[0]), timezone.utc).isoformat()
            low, high, op, close, volume = (float(row[i]) for i in (1, 2, 3, 4, 5))
            if not all(math.isfinite(value) for value in (low, high, op, close, volume)):
                continue
            if min(low, high, op, close) <= 0 or volume < 0 or high < max(op, close, low) or low > min(op, close, high):
                continue
            candles.append({"time": stamp, "open": op, "high": high, "low": low,
                            "close": close, "volume": volume})
        except (IndexError, TypeError, ValueError, OverflowError):
            continue
    candles.sort(key=lambda item: item["time"])
    candles = closed_candles(candles, interval)
    if len(candles) < 210:
        raise MarketDataError(f"Coinbase returned only {len(candles)} valid closed {interval} candles; 210 are required.")
    return candles[-count:]


async def fetch_candles_with_provider(interval: str, outputsize: int = 320,
                                      symbol: str = "XAUUSD") -> tuple[list[dict[str, Any]], str]:
    """Fetch validated candles and return the actual provider used for the chart."""
    symbol = str(symbol).upper()
    if await is_binance_spot_symbol(symbol):
        binance_interval = BINANCE_INTERVALS.get(interval)
        if not binance_interval:
            raise MarketDataError(f"Unsupported Binance candle interval: {interval}.")
        requested = min(max(int(outputsize), 210), 3200)
        try:
            rows = []
            end_time = None
            async with httpx.AsyncClient(timeout=httpx.Timeout(18, connect=5)) as client:
                while len(rows) < requested:
                    limit = min(1000, requested - len(rows))
                    params = {"symbol":symbol,"interval":binance_interval,"limit":limit}
                    if end_time is not None:
                        params["endTime"] = end_time
                    payload, _source_base = await get_binance_public_json(
                        client, "/api/v3/klines", params
                    )
                    if not isinstance(payload, list) or not payload:
                        raise MarketDataError("Binance returned no candle rows.")
                    rows = payload + rows
                    end_time = int(payload[0][0]) - 1
                    if len(payload) < limit:
                        break
            candles=[]
            for row in rows[-requested:]:
                try:
                    stamp=datetime.fromtimestamp(int(row[0])/1000, timezone.utc).isoformat()
                    op, high, low, close, volume = (float(row[i]) for i in (1, 2, 3, 4, 5))
                    if not all(math.isfinite(value) for value in (op, high, low, close, volume)):
                        continue
                    if min(op, high, low, close) <= 0 or volume < 0 or high < max(op, close, low) or low > min(op, close, high):
                        continue
                    candles.append({"time":stamp,"open":op,"high":high,"low":low,"close":close,"volume":volume})
                except (IndexError,TypeError,ValueError,OverflowError):
                    continue
            candles = closed_candles(candles, interval)
            if len(candles) < 210:
                raise MarketDataError(f"Not enough CLOSED {symbol} {interval} Binance candles ({len(candles)} received).")
            return candles, "Binance Spot"
        except (BinancePublicDataError, httpx.HTTPError, MarketDataError, ValueError, TypeError, IndexError) as binance_error:
            try:
                candles = await _fetch_coinbase_candles(symbol, interval, requested)
                return candles, "Coinbase Exchange fallback"
            except (httpx.HTTPError, MarketDataError, ValueError, TypeError) as coinbase_error:
                raise MarketDataError(
                    f"Binance candles unavailable ({binance_error}); Coinbase fallback unavailable ({coinbase_error})."
                ) from coinbase_error

    if symbol != "XAUUSD":
        raise MarketDataError("Unsupported market. Choose a currently tradable Binance Spot pair or XAUUSD.")
    mt5_error = None
    if QUANTNEX_MT5_ENABLED:
        from .mt5_feed import get_candles as get_mt5_candles, MT5FeedError
        try:
            candles = await get_mt5_candles(QUANTNEX_MT5_GOLD_SYMBOL, interval.replace("min", "m"), min(max(outputsize, 210), 1000))
            candles = closed_candles(candles, interval)
            if len(candles) < 210:
                raise MarketDataError(f"Not enough CLOSED MT5 {interval} XAUUSD candles ({len(candles)} received).")
            return candles, "MetaTrader 5 local terminal"
        except (MT5FeedError, MarketDataError) as exc:
            mt5_error = str(exc)
    if not TWELVE_DATA_API_KEY:
        detail = "Gold historical candles require a connected MT5 terminal with QUANTNEX_MT5_ENABLED=true or a TWELVE_DATA_API_KEY in backend/.env."
        if mt5_error:
            detail += " MT5 detail: " + mt5_error
        raise MarketDataError(detail)
    requested = min(max(int(outputsize), 210), 5000)
    cache_key = (symbol, interval, requested)
    cached = _cached_gold_candles(cache_key)
    if cached is not None:
        return cached, "Twelve Data (cached)"
    async with _gold_candle_cache_guard(cache_key):
        # Recheck after waiting: another concurrent scan may have filled this key.
        cached = _cached_gold_candles(cache_key)
        if cached is not None:
            return cached, "Twelve Data (cached)"
        async with httpx.AsyncClient(timeout=18) as client:
            response = await client.get(BASE, params={"symbol":"XAU/USD","interval":interval,
                "outputsize":requested,"timezone":"UTC","apikey":TWELVE_DATA_API_KEY})
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict) or payload.get("status") == "error" or not isinstance(payload.get("values"), list):
            detail = payload.get("message") or payload.get("code") if isinstance(payload, dict) else "Provider returned an invalid candle response."
            raise MarketDataError(str(detail or "Provider returned no candle data."))
        candles = _normalize_gold_candles(payload["values"])
        candles = closed_candles(candles, interval)
        if len(candles) < 210:
            raise MarketDataError(f"Not enough valid CLOSED {interval} XAUUSD candles for stable indicator calculations ({len(candles)} received).")
        candles = candles[-requested:]
        _GOLD_CANDLE_CACHE[cache_key] = (time.monotonic(), candles)
        return [dict(row) for row in candles], "Twelve Data"


async def fetch_candles(interval: str, outputsize: int = 320, symbol: str = "XAUUSD") -> list[dict[str, Any]]:
    candles, _provider = await fetch_candles_with_provider(interval, outputsize, symbol)
    return candles

async def fetch_binance_historical_candles(
    symbol: str, interval: str = "1m", days: int = 30, max_candles: int = 43200
) -> list[dict[str, Any]]:
    """Fetch closed Binance Spot history with bounded, rate-conscious pagination."""
    normalized = str(symbol or "").strip().upper()
    if interval not in {"1m", "5m", "15m", "30m", "1h", "4h"}:
        raise MarketDataError("Historical Binance interval is unsupported.")
    if not 1 <= int(days) <= 30:
        raise MarketDataError("Historical replay supports between 1 and 30 days.")
    if not await is_binance_spot_symbol(normalized):
        raise MarketDataError(f"{normalized} is not a tradable Binance Spot pair.")
    interval_ms = {"1m": 60_000, "5m": 300_000, "15m": 900_000,
                   "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}[interval]
    end_time = datetime.now(timezone.utc)
    end_ms = int(end_time.timestamp() * 1000)
    start_ms = int((end_time - timedelta(days=int(days))).timestamp() * 1000)
    candles: list[dict[str, Any]] = []
    seen_open_times: set[int] = set()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(18, connect=5)) as client:
            while start_ms < end_ms and len(candles) < max_candles:
                rows, _source_base = await get_binance_public_json(
                    client, "/api/v3/klines",
                    {"symbol": normalized, "interval": interval,
                     "startTime": start_ms, "endTime": end_ms, "limit": 1000},
                )
                if not isinstance(rows, list):
                    raise MarketDataError("Binance returned an invalid historical candle page.")
                if not rows:
                    break
                last_open = None
                for row in rows:
                    try:
                        open_ms = int(row[0])
                        close_ms = int(row[6])
                        values = [float(row[index]) for index in (1, 2, 3, 4, 5)]
                        if open_ms in seen_open_times or close_ms >= end_ms:
                            continue
                        op, high, low, close, volume = values
                        if not all(math.isfinite(value) and value > 0 for value in (op, high, low, close)):
                            continue
                        if high < max(op, close, low) or low > min(op, close, high) or volume < 0:
                            continue
                        seen_open_times.add(open_ms)
                        candles.append({
                            "time": datetime.fromtimestamp(open_ms / 1000, timezone.utc).isoformat(),
                            "open": op, "high": high, "low": low, "close": close, "volume": volume,
                        })
                        last_open = open_ms if last_open is None else max(last_open, open_ms)
                    except (IndexError, TypeError, ValueError, OverflowError):
                        continue
                if last_open is None:
                    break
                next_start = last_open + interval_ms
                if next_start <= start_ms:
                    raise MarketDataError("Binance historical pagination did not advance.")
                start_ms = next_start
                if len(rows) < 1000:
                    break
                await asyncio.sleep(0.05)
    except (BinancePublicDataError, httpx.HTTPError, ValueError) as exc:
        raise MarketDataError(f"Binance historical data request failed: {exc}") from exc
    candles.sort(key=lambda row: row["time"])
    if len(candles) < 210:
        raise MarketDataError(f"Only {len(candles)} closed historical candles were available; at least 210 are required.")
    return candles[-max_candles:]


def aggregate_minutes(
    candles: list[dict[str, Any]], minutes: int, *, require_complete: bool = False
) -> list[dict[str, Any]]:
    """Aggregate unique 1-minute UTC buckets; historical replay can require full buckets."""
    from datetime import datetime
    if minutes < 1:
        raise ValueError("Aggregation interval must be positive.")
    buckets: dict[int, dict[str, Any]] = {}
    seen: set[tuple[int, int]] = set()
    for candle in sorted(candles, key=lambda row: str(row.get("time") or "")):
        try:
            stamp = datetime.fromisoformat(str(candle["time"]).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            epoch = int(stamp.timestamp())
            op, high, low, close = (float(candle[key]) for key in ("open", "high", "low", "close"))
            volume = float(candle.get("volume") or 0)
            if not all(math.isfinite(value) and value > 0 for value in (op, high, low, close)):
                continue
            if high < max(op, close, low) or low > min(op, close, high) or not math.isfinite(volume) or volume < 0:
                continue
        except (KeyError, ValueError, TypeError, OverflowError):
            continue
        key = epoch // (minutes * 60)
        minute_key = (key, epoch)
        if minute_key in seen:
            continue
        seen.add(minute_key)
        bucket = buckets.get(key)
        if bucket is None:
            bucket_start = datetime.fromtimestamp(key * minutes * 60, timezone.utc).isoformat()
            buckets[key] = {
                "time": bucket_start, "open": op, "high": high, "low": low,
                "close": close, "volume": volume, "count": 1,
            }
        else:
            bucket["high"] = max(bucket["high"], high)
            bucket["low"] = min(bucket["low"], low)
            bucket["close"] = close
            bucket["volume"] += volume
            bucket["count"] += 1
    complete = []
    for key in sorted(buckets):
        bucket = buckets[key]
        if not require_complete or bucket["count"] == minutes:
            complete.append({name: value for name, value in bucket.items() if name != "count"})
    return complete

def ema(values: list[float], period: int) -> list[float]:
    if not values: return []
    alpha=2/(period+1); out=[values[0]]
    for value in values[1:]: out.append(alpha*value+(1-alpha)*out[-1])
    return out

def rsi(values: list[float], period: int=14) -> float:
    changes=[values[i]-values[i-1] for i in range(1,len(values))]
    if len(changes)<period: return 50.0
    gains=[max(x,0) for x in changes]; losses=[max(-x,0) for x in changes]
    avg_gain=sum(gains[:period])/period; avg_loss=sum(losses[:period])/period
    for i in range(period,len(changes)):
        avg_gain=(avg_gain*(period-1)+gains[i])/period
        avg_loss=(avg_loss*(period-1)+losses[i])/period
    if avg_loss==0: return 100.0
    rs=avg_gain/avg_loss
    return 100-(100/(1+rs))

def atr(c: list[dict[str,Any]], period: int=14) -> float:
    trs=[]
    for i in range(1,len(c)):
        prev=c[i-1]["close"]; row=c[i]
        trs.append(max(row["high"]-row["low"],abs(row["high"]-prev),abs(row["low"]-prev)))
    return sum(trs[-period:])/min(period,len(trs)) if trs else 0.0

def adx(c: list[dict[str,Any]], period: int=14) -> float:
    if len(c)<period*2+1:return 0.0
    trs=[]; plus=[]; minus=[]
    for i in range(1,len(c)):
        cur,prev=c[i],c[i-1]
        up=cur["high"]-prev["high"]; down=prev["low"]-cur["low"]
        plus.append(up if up>down and up>0 else 0.0)
        minus.append(down if down>up and down>0 else 0.0)
        trs.append(max(cur["high"]-cur["low"],abs(cur["high"]-prev["close"]),abs(cur["low"]-prev["close"])))
    dx=[]
    for i in range(period-1,len(trs)):
        tr=sum(trs[i-period+1:i+1]); p=sum(plus[i-period+1:i+1]); m=sum(minus[i-period+1:i+1])
        if tr<=0: continue
        pdi=100*p/tr; mdi=100*m/tr
        dx.append(100*abs(pdi-mdi)/max(pdi+mdi,1e-9))
    return sum(dx[-period:])/len(dx[-period:]) if dx else 0.0

def macd(values: list[float]) -> tuple[float,float,float]:
    fast=ema(values,12); slow=ema(values,26)
    line=[a-b for a,b in zip(fast,slow)]
    signal=ema(line,9)
    return line[-1],signal[-1],line[-1]-signal[-1]

def structure(c: list[dict[str,Any]]) -> dict[str,Any]:
    """Return confirmed two-sided swing structure and the latest BOS/MSS event.

    Swing points use a 2-left/2-right confirmation window, so the newest two
    candles are never treated as confirmed pivots. The event is emitted only
    when the latest candle closes through a previously confirmed swing.
    """
    recent=c[-120:]
    if len(recent)<8:
        raise ValueError("At least eight candles are required for structure analysis.")
    highs=[];lows=[]
    for i in range(2,len(recent)-2):
        row=recent[i]
        if row["high"]>=max(x["high"] for x in recent[i-2:i]) and row["high"]>max(x["high"] for x in recent[i+1:i+3]):
            highs.append((i,row))
        if row["low"]<=min(x["low"] for x in recent[i-2:i]) and row["low"]<min(x["low"] for x in recent[i+1:i+3]):
            lows.append((i,row))
    fallback=recent[-32:-2]
    swing_high=highs[-1][1]["high"] if highs else max(x["high"] for x in fallback)
    swing_low=lows[-1][1]["low"] if lows else min(x["low"] for x in fallback)
    trend="NEUTRAL"
    if len(highs)>=2 and len(lows)>=2:
        hh=highs[-1][1]["high"]>highs[-2][1]["high"]
        hl=lows[-1][1]["low"]>lows[-2][1]["low"]
        lh=highs[-1][1]["high"]<highs[-2][1]["high"]
        ll=lows[-1][1]["low"]<lows[-2][1]["low"]
        if hh and hl: trend="BULLISH"
        elif lh and ll: trend="BEARISH"
    last=recent[-1];prev=recent[-2]
    bullish_break=prev["close"]<=swing_high and last["close"]>swing_high
    bearish_break=prev["close"]>=swing_low and last["close"]<swing_low
    event="NONE"
    if bullish_break:
        event="BULLISH_MSS" if trend=="BEARISH" else "BULLISH_BOS"
    elif bearish_break:
        event="BEARISH_MSS" if trend=="BULLISH" else "BEARISH_BOS"
    direction="BULLISH" if event.startswith("BULLISH") else "BEARISH" if event.startswith("BEARISH") else "NONE"
    sweep="BULLISH" if last["low"]<swing_low and last["close"]>swing_low else "BEARISH" if last["high"]>swing_high and last["close"]<swing_high else "NONE"
    bull_fvg=None;bear_fvg=None
    for i in range(max(2,len(recent)-40),len(recent)):
        a,b,d=recent[i-2],recent[i-1],recent[i]
        if a["high"]<d["low"]: bull_fvg={"low":a["high"],"high":d["low"]}
        if a["low"]>d["high"]: bear_fvg={"low":d["high"],"high":a["low"]}
    bull_ob=None;bear_ob=None
    if direction=="BULLISH":
        for row in reversed(recent[-12:-1]):
            if row["close"]<row["open"]: bull_ob={"low":row["low"],"high":row["high"]};break
    if direction=="BEARISH":
        for row in reversed(recent[-12:-1]):
            if row["close"]>row["open"]: bear_ob={"low":row["low"],"high":row["high"]};break
    bull_ifvg={"low":bull_fvg["low"],"high":bull_fvg["high"]} if bull_fvg and last["close"]<bull_fvg["low"] else None
    bear_ifvg={"low":bear_fvg["low"],"high":bear_fvg["high"]} if bear_fvg and last["close"]>bear_fvg["high"] else None
    bear_breaker={"low":bull_ob["low"],"high":bull_ob["high"]} if bull_ob and last["close"]<bull_ob["low"] else None
    bull_breaker={"low":bear_ob["low"],"high":bear_ob["high"]} if bear_ob and last["close"]>bear_ob["high"] else None
    volatility=atr(recent,14)
    pad=max(volatility*0.12,abs(last["close"])*0.00001)
    support={"low":swing_low-pad,"high":swing_low+pad}
    resistance={"low":swing_high-pad,"high":swing_high+pad}
    equilibrium=(swing_high+swing_low)/2
    premium_discount="DISCOUNT" if last["close"]<equilibrium else "PREMIUM"
    return {"bos_mss":direction,"structure_event":event,"structure_trend":trend,
            "liquidity_sweep":sweep,"bullish_fvg":bull_fvg,"bearish_fvg":bear_fvg,
            "bullish_ifvg":bull_ifvg,"bearish_ifvg":bear_ifvg,
            "bullish_order_block":bull_ob,"bearish_order_block":bear_ob,
            "bullish_breaker_block":bull_breaker,"bearish_breaker_block":bear_breaker,
            "support_zone":support,"resistance_zone":resistance,
            "premium_discount":premium_discount,"equilibrium":equilibrium,
            "swing_high":swing_high,"swing_low":swing_low}

def inspect_tf(c: list[dict[str,Any]]) -> dict[str,Any]:
    close=[x["close"] for x in c]; e20=ema(close,20)[-1];e50=ema(close,50)[-1];e200=ema(close,200)[-1] if len(close)>=200 else None
    m,ms,mh=macd(close); rv=rsi(close); av=atr(c); dx=adx(c); last=close[-1]
    bias="BULLISH" if last>e20 and e20>e50 and (e200 is None or last>e200) else "BEARISH" if last<e20 and e20<e50 and (e200 is None or last<e200) else "NEUTRAL"
    return {"bias":bias,"close":last,"ema20":e20,"ema50":e50,"ema200":e200,"macd":m,"macd_signal":ms,
            "macd_histogram":mh,"rsi":rv,"atr":av,"adx":dx,"structure":structure(c)}

async def build_signal(
    settings: dict[str, Any], symbol: str = "XAUUSD", *,
    candles_override: dict[str, list[dict[str, Any]]] | None = None,
    execution_context_override: dict[str, Any] | None = None,
    order_flow_override: dict[str, Any] | None = None,
    replay_as_of: datetime | None = None,
) -> dict[str, Any]:
    symbol = str(symbol).upper()
    as_of = replay_as_of or datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    if symbol != "XAUUSD":
        if not symbol.isalnum() or len(symbol) > 30:
            raise MarketDataError("Unsupported market symbol format.")
        # Historical replay is an offline, caller-supplied dataset. Do not make
        # a live exchangeInfo request while evaluating a deterministic replay.
        if candles_override is None and not await is_binance_spot_symbol(symbol):
            raise MarketDataError("Unsupported market. Choose a currently tradable Binance Spot pair or XAUUSD.")
    enabled=[str(x) for x in settings.get("enabled",["60","30","15","5","1"])]
    if not enabled: enabled=["60","30","15","5","1"]
    needed=set(enabled+[str(settings.get("primary","5")),str(settings.get("trend","60"))])
    if "50" in needed: needed.add("1")
    candles = {}
    providers = set()
    errors = []
    if candles_override is None:
        tasks = {}
        for tf in needed:
            if tf in INTERVALS:
                tasks[tf] = fetch_candles_with_provider(
                    INTERVALS[tf], 3200 if tf == "1" and "50" in needed else 320, symbol
                )
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for tf, result in zip(tasks, results):
            if isinstance(result, Exception):
                errors.append(f"{tf}m: {str(result)}")
            else:
                try:
                    rows, provider = result
                    if not isinstance(rows, list) or not provider:
                        raise ValueError("Market-data provider returned an invalid candle result.")
                    candles[tf] = rows
                    providers.add(str(provider))
                except (TypeError, ValueError) as exc:
                    errors.append(f"{tf}m: {str(exc)}")
    else:
        for tf in needed:
            if tf == "50" and "1" in candles_override:
                continue
            rows = candles_override.get(tf)
            if not isinstance(rows, list):
                errors.append(f"{tf}m: historical replay candles are missing.")
                continue
            candles[tf] = [dict(row) for row in rows]
        providers.add("Historical Binance Spot replay")
    if "50" in needed and "1" in candles:
        candles["50"] = closed_candles(aggregate_minutes(candles["1"], 50), "50min")
        if len(candles["50"]) < 50:
            raise MarketDataError("Not enough fully closed M50 candles for stable indicator calculations.")
    if errors: raise MarketDataError("; ".join(errors))
    if candles_override is None:
        freshness_errors = []
        for tf, rows in candles.items():
            interval = "50min" if tf == "50" else INTERVALS[tf]
            try:
                validate_candle_freshness(rows, interval)
            except MarketDataError as exc:
                freshness_errors.append(f"{tf}m: {exc}")
        if freshness_errors:
            raise MarketDataError("; ".join(freshness_errors))
    else:
        for tf, rows in candles.items():
            if len(rows) < (50 if tf == "50" else 210):
                raise MarketDataError(f"Not enough historical {tf}m candles for replay.")
            times = [str(row.get("time") or "") for row in rows]
            if times != sorted(times) or len(times) != len(set(times)):
                raise MarketDataError(f"Historical {tf}m candles must be unique and chronological.")
    analysis={tf:inspect_tf(candles[tf]) for tf in needed if tf in candles and len(candles[tf])>=(50 if tf=="50" else 210)}
    primary=str(settings.get("primary","5")); trend=str(settings.get("trend","60"))
    if primary not in analysis or trend not in analysis: raise MarketDataError("Selected primary/trend timeframe does not have enough candles.")
    p=analysis[primary]; t=analysis[trend]; side=None
    # Score ten transparent rule checks, rather than claiming a probability of winning.
    close=p["close"]; st=p["structure"]; buy=[];sell=[]
    for tf in ["60","30","15"]:
        if tf in analysis:
            (buy if analysis[tf]["bias"]=="BULLISH" else sell if analysis[tf]["bias"]=="BEARISH" else []).append(f"{tf}m EMA trend")
    (buy if p["macd_histogram"]>0 else sell if p["macd_histogram"]<0 else []).append("Primary MACD momentum")
    if 50<=p["rsi"]<=70: buy.append("RSI bullish range")
    elif 30<=p["rsi"]<=50: sell.append("RSI bearish range")
    if p["adx"]>=18: (buy if p["macd_histogram"]>0 else sell if p["macd_histogram"]<0 else []).append("ADX trend strength")
    if st["bos_mss"]=="BULLISH":buy.append("Bullish BOS / MSS")
    elif st["bos_mss"]=="BEARISH":sell.append("Bearish BOS / MSS")
    if st["liquidity_sweep"]=="BULLISH":buy.append("Sell-side liquidity sweep")
    elif st["liquidity_sweep"]=="BEARISH":sell.append("Buy-side liquidity sweep")
    zone=(st["bullish_fvg"] or st["bullish_order_block"] or st["bullish_breaker_block"] or st["bullish_ifvg"]) if p["macd_histogram"]>0 else (st["bearish_fvg"] or st["bearish_order_block"] or st["bearish_breaker_block"] or st["bearish_ifvg"])
    in_zone=bool(zone and zone["low"]<=close<=zone["high"])
    discount_buy=st.get("premium_discount")=="DISCOUNT" and p["macd_histogram"]>0
    premium_sell=st.get("premium_discount")=="PREMIUM" and p["macd_histogram"]<0
    if in_zone or discount_buy or premium_sell:
        (buy if p["macd_histogram"]>0 else sell).append("OB / FVG / breaker or premium-discount zone")
    # Count directional timeframe alignment as the tenth confluence.
    if t["bias"]=="BULLISH":buy.append("Trend timeframe aligned")
    elif t["bias"]=="BEARISH":sell.append("Trend timeframe aligned")
    bscore=min(10,len(buy));sscore=min(10,len(sell))
    threshold=int(settings.get("min_score",7))
    if bscore>=threshold and bscore>sscore: side="BUY";checks=buy;score=bscore
    elif sscore>=threshold and sscore>bscore: side="SELL";checks=sell;score=sscore
    else: checks=buy if bscore>=sscore else sell;score=max(bscore,sscore)
    # Directional quality gate: no signal against the selected primary/trend bias,
    # with weak ADX or an overextended RSI. Enabled higher timeframes must broadly agree.
    quality_filters={"primary_bias_aligned":False,"trend_bias_aligned":False,"adx_strength":False,
                     "rsi_not_extreme":False,"macd_direction":False,"timeframe_consensus":False}
    if side:
        primary_aligned=p["bias"]==("BULLISH" if side=="BUY" else "BEARISH")
        trend_aligned=t["bias"]==("BULLISH" if side=="BUY" else "BEARISH")
        adx_ok=p["adx"]>=18
        rsi_ok=(45<=p["rsi"]<=68) if side=="BUY" else (32<=p["rsi"]<=55)
        macd_ok=(p["macd_histogram"]>0) if side=="BUY" else (p["macd_histogram"]<0)
        directional=[analysis[x]["bias"] for x in enabled if x in analysis and x!=primary]
        aligned=sum(x==("BULLISH" if side=="BUY" else "BEARISH") for x in directional)
        consensus_ok=not directional or aligned/len(directional)>=0.60
        quality_filters={"primary_bias_aligned":primary_aligned,"trend_bias_aligned":trend_aligned,
                         "adx_strength":adx_ok,"rsi_not_extreme":rsi_ok,"macd_direction":macd_ok,
                         "timeframe_consensus":consensus_ok}
        if not all(quality_filters.values()):
            side=None
    price_precision = 2 if symbol == "XAUUSD" else 8
    signal = None
    entry_rejection_reason = None
    entry_choice = None
    execution = None
    execution_quality = None
    tick_size = "0.01" if symbol == "XAUUSD" else "0.00000001"
    if side and symbol == "XAUUSD":
        entry_choice = {
            "entry_type": "REFERENCE",
            "entry_price": close,
            "reason": "Gold provider reference price; Binance execution routing is not applicable.",
        }
    elif side:
        execution = execution_context_override or await get_binance_spot_execution_context(symbol)
        entry_choice = select_binance_entry(side, close, p["atr"], zone, execution, settings)
        if not entry_choice:
            side = None
            quality_filters["execution_quality"] = False
            filter_detail = execution.get("order_filter_rejection_reason")
            entry_rejection_reason = (
                "No safe MARKET entry or technically justified LIMIT retracement met the spread, "
                "liquidity, order-type, exchange-filter and price-distance rules."
                + (f" Exchange filter detail: {filter_detail}." if filter_detail else "")
            )
            execution_quality = {
                "spread_bps": round(float(execution["spread_bps"]), 3),
                "bid_depth_usd": round(float(execution.get("bid_depth_usd", 0.0)), 2),
                "ask_depth_usd": round(float(execution.get("ask_depth_usd", 0.0)), 2),
                "quote_asset": execution.get("quote_asset"),
                "quote_asset_usd_rate": execution.get("quote_asset_usd_rate"),
                "accepted": False,
                "rejection_reason": entry_rejection_reason,
            }
        else:
            tick_size = str(execution["tick_size"])
            price_precision = max(0, -Decimal(tick_size).normalize().as_tuple().exponent)
            round_entry_up = (side == "BUY" and entry_choice["entry_type"] == "MARKET") or (
                side == "SELL" and entry_choice["entry_type"] == "LIMIT"
            )
            entry_choice["entry_price"] = round_price_to_tick(
                float(entry_choice["entry_price"]), tick_size, round_up=round_entry_up
            )

    order_flow_payload: dict[str, Any] = {"status": "NOT_EVALUATED"}
    if symbol == "XAUUSD":
        order_flow_payload = {
            "status": "NOT_APPLICABLE",
            "note": "XAUUSD uses its configured Gold feed; Binance Spot order-flow is not applied.",
        }
    elif side and entry_choice:
        order_flow_mode = "DETERMINISTIC_FIXTURE" if order_flow_override is not None else "PUBLIC_REST_SNAPSHOT"
        try:
            if order_flow_override is not None:
                order_flow_snapshot = order_flow_override
            elif candles_override is None:
                max_order_flow_age = float(settings.get("max_order_flow_trade_age_seconds", 15.0))
                if not math.isfinite(max_order_flow_age) or max_order_flow_age <= 0:
                    raise MarketDataError("Order-flow freshness setting must be finite and positive.")
                async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=3.0)) as client:
                    order_flow_snapshot = await fetch_spot_order_flow(
                        client,
                        symbol,
                        tick_size=tick_size,
                        max_trade_age_seconds=max_order_flow_age,
                    )
                order_flow_mode = (
                    "DETERMINISTIC_FIXTURE"
                    if order_flow_snapshot.get("feed_mode") == "DETERMINISTIC_FIXTURE"
                    else "PUBLIC_REST_SNAPSHOT"
                )
            else:
                order_flow_snapshot = None
                order_flow_mode = "CANDLE_ONLY_REPLAY_BASELINE"

            if order_flow_snapshot is None:
                order_flow_payload = {
                    "status": "NOT_AVAILABLE_CANDLE_ONLY_REPLAY",
                    "accepted": None,
                    "note": "Historical candle replay has no historical aggressor trades or synchronized L2 data; this result is a candle-only baseline.",
                }
            else:
                decision = evaluate_order_flow_confirmation(
                    side,
                    order_flow_snapshot,
                    max_trade_age_seconds=float(settings.get("max_order_flow_trade_age_seconds", 15.0)),
                    max_depth_age_seconds=float(settings.get("max_order_book_snapshot_age_seconds", 5.0)),
                    now=as_of if candles_override is not None else datetime.now(timezone.utc),
                )
                order_flow_payload = summarize_order_flow_snapshot(order_flow_snapshot, decision)
                order_flow_payload["data_mode"] = order_flow_mode
                quality_filters["order_flow_confirmation"] = bool(decision["accepted"])
                if not decision["accepted"]:
                    status = str(decision["status"]).lower()
                    entry_rejection_reason = (
                        f"Order Flow did not confirm {side}: {status}. "
                        "Recent aggressor delta and L2 depth must provide net directional support."
                    )
                    side = None
        except (BinanceOrderFlowFeedError, OrderFlowDataError, httpx.HTTPError,
                MarketDataError, ValueError, TypeError, KeyError, OverflowError) as exc:
            order_flow_payload = {
                "status": "ERROR",
                "accepted": False,
                "data_mode": order_flow_mode,
                "error": f"{type(exc).__name__}: {exc}",
            }
            quality_filters["order_flow_confirmation"] = False
            entry_rejection_reason = (
                "Order Flow data was unavailable, malformed or stale; the live Spot signal was rejected."
            )
            side = None
    elif symbol != "XAUUSD" and candles_override is not None:
        order_flow_payload = {
            "status": "NOT_AVAILABLE_CANDLE_ONLY_REPLAY",
            "accepted": None,
            "note": "Historical candle replay has no historical aggressor trades or synchronized L2 data; this result is a candle-only baseline.",
        }
    elif symbol != "XAUUSD":
        order_flow_payload = {
            "status": "NOT_EVALUATED_NO_DIRECTIONAL_SETUP",
            "accepted": None,
        }

    if side and entry_choice:
        entry = round(float(entry_choice["entry_price"]), price_precision)
        swing = st["swing_low"] if side == "BUY" else st["swing_high"]
        risk = max(p["atr"] * 1.5, abs(entry - swing), p["atr"] * 0.8)
        if symbol != "XAUUSD":
            risk = max(risk, float(Decimal(tick_size)) * 2)
        sign = 1 if side == "BUY" else -1
        if symbol == "XAUUSD":
            sl = round(entry - sign * risk, price_precision)
            tp1 = round(entry + sign * risk, price_precision)
            tp2 = round(entry + sign * risk * 2, price_precision)
            tp3 = round(entry + sign * risk * 3, price_precision)
            execution_quality = None
            expiry_seconds = None
        else:
            sl = round_price_to_tick(entry - sign * risk, tick_size, round_up=side == "SELL")
            tp1 = round_price_to_tick(entry + sign * risk, tick_size, round_up=side == "BUY")
            tp2 = round_price_to_tick(entry + sign * risk * 2, tick_size, round_up=side == "BUY")
            tp3 = round_price_to_tick(entry + sign * risk * 3, tick_size, round_up=side == "BUY")
            fee_bps = float(settings.get(
                "estimated_maker_fee_bps_per_side" if entry_choice["entry_type"] == "LIMIT"
                else "estimated_taker_fee_bps_per_side", 8.0 if entry_choice["entry_type"] == "LIMIT" else 10.0
            ))
            slippage_bps = float(settings.get(
                "estimated_slippage_bps_per_side", 1.0 if entry_choice["entry_type"] == "LIMIT" else 2.5
            ))
            if not all(math.isfinite(value) and value >= 0 for value in (fee_bps, slippage_bps)):
                raise MarketDataError("Execution cost assumptions must be finite and non-negative.")
            spread_bps = float(execution["spread_bps"])
            estimated_round_trip_cost_bps = spread_bps + 2 * (fee_bps + slippage_bps)
            tp1_reward_bps = abs(tp1 - entry) / entry * 10000 if entry > 0 else 0
            reward_cost_ratio = tp1_reward_bps / max(estimated_round_trip_cost_bps, 0.01)
            minimum_reward_cost_ratio = float(settings.get("min_reward_to_cost_ratio", 1.25))
            execution_quality = {
                "spread_bps": round(spread_bps, 3),
                "quote_asset": execution.get("quote_asset"),
                "quote_asset_usd_rate": execution.get("quote_asset_usd_rate"),
                "quote_asset_usd_rate_source": execution.get("quote_asset_usd_rate_source"),
                "bid_depth_usd": round(float(execution.get("bid_depth_usd", execution["bid_depth_quote"])), 2),
                "ask_depth_usd": round(float(execution.get("ask_depth_usd", execution["ask_depth_quote"])), 2),
                "estimated_round_trip_cost_bps": round(estimated_round_trip_cost_bps, 3),
                "estimated_fee_bps_per_side": fee_bps,
                "estimated_slippage_bps_per_side": slippage_bps,
                "fee_assumption": "Estimated only; replace with the user's actual Binance fee tier.",
                "tick_size": tick_size,
                "step_size": execution["step_size"],
                "min_quantity": execution["min_quantity"],
                "min_notional": execution["min_notional"],
                "order_types": execution.get("order_types", []),
                "base_asset_precision": execution.get("base_asset_precision"),
                "quote_asset_precision": execution.get("quote_asset_precision"),
                "quote_precision": execution.get("quote_precision"),
                "quote_order_qty_market_allowed": execution.get("quote_order_qty_market_allowed", False),
                "price_filter": execution.get("price_filter"),
                "limit_lot_size": execution.get("limit_lot_size"),
                "market_lot_size": execution.get("market_lot_size"),
                "notional_filter": execution.get("notional_filter"),
                "limit_order_constraints_valid": execution.get("limit_order_constraints_valid"),
                "market_order_constraints_valid": execution.get("market_order_constraints_valid"),
                "quantity_validation_status": "NOT_CHECKED_NO_ORDER_QUANTITY_IN_SIGNAL",
                "quote_observed_at": execution["observed_at"],
                "provider": execution["provider"],
                "data_mode": "HISTORICAL_REPLAY_ASSUMED" if execution.get("is_replay") else "LIVE_ORDER_BOOK",
                "tp1_reward_to_cost_ratio": round(reward_cost_ratio, 2),
            }
            if reward_cost_ratio < minimum_reward_cost_ratio:
                quality_filters["execution_quality"] = False
                entry_rejection_reason = (
                    "Expected TP1 reward is too small relative to estimated spread, fees and slippage "
                    f"({reward_cost_ratio:.2f}x; minimum {minimum_reward_cost_ratio:.2f}x)."
                )
                side = None
                entry_choice = None
                execution_quality = {**execution_quality, "accepted": False}
            else:
                quality_filters["execution_quality"] = True
                execution_quality["accepted"] = True
                expiry_seconds = 900 if entry_choice["entry_type"] == "LIMIT" else 60

        if side and entry_choice:
            signal = {
                "symbol": symbol,
                "market_type": "BINANCE_SPOT" if symbol != "XAUUSD" else "XAUUSD_FEED",
                "side": side,
                "timeframe": primary,
                "trend_timeframe": trend,
                "entry_type": entry_choice["entry_type"],
                "entry": entry,
                "entry_price": entry,
                "limit_price": entry if entry_choice["entry_type"] == "LIMIT" else None,
                "entry_selection_reason": entry_choice["reason"],
                "entry_expires_at": (as_of + timedelta(seconds=expiry_seconds)).isoformat()
                    if expiry_seconds else None,
                "signal_candle_time": candles[primary][-1]["time"],
                "stop_loss": round(sl, price_precision),
                "tp1": round(tp1, price_precision),
                "tp2": round(tp2, price_precision),
                "tp3": round(tp3, price_precision),
                "score": score,
                "out_of": 10,
                "confirmations": checks,
                "risk_distance": round(risk, price_precision),
                "execution_quality": execution_quality,
                "exchange_filters": execution_quality.get("price_filter") if False else {
                    "order_types": execution.get("order_types", []) if execution else [],
                    "price_filter": execution.get("price_filter") if execution else None,
                    "limit_lot_size": execution.get("limit_lot_size") if execution else None,
                    "market_lot_size": execution.get("market_lot_size") if execution else None,
                    "notional_filter": execution.get("notional_filter") if execution else None,
                    "base_asset_precision": execution.get("base_asset_precision") if execution else None,
                    "quote_asset_precision": execution.get("quote_asset_precision") if execution else None,
                    "quote_precision": execution.get("quote_precision") if execution else None,
                    "quote_order_qty_market_allowed": execution.get("quote_order_qty_market_allowed", False) if execution else False,
                    "quantity_validation_status": "NOT_CHECKED_NO_ORDER_QUANTITY_IN_SIGNAL",
                },
                "order_flow": order_flow_payload,
            }
    if symbol != "XAUUSD" and side is None and score >= threshold and not entry_rejection_reason:
        entry_rejection_reason = "Directional setup passed, but execution quality did not produce a valid entry."

    provider_label = " + ".join(sorted(providers)) if providers else "Unknown"
    generated_at = as_of.isoformat()
    message = (
        "Signal setup and entry-quality filters passed."
        if signal else
        "WAIT — " + entry_rejection_reason
        if entry_rejection_reason else
        "WAIT — confluence threshold or directional quality filters not met."
    )
    return {"symbol":symbol,"provider":provider_label,"generated_at":generated_at,
            "signal":signal,"execution_quality":execution_quality,
            "confluence_score":score,"score_out_of":10,"score_note":"Rule-based confluence count, not a measured win probability.",
            "timeframes":{tf:{"bias":v["bias"],"close":round(v["close"],price_precision),"ema20":round(v["ema20"],price_precision),
                "ema50":round(v["ema50"],price_precision),"ema200":round(v["ema200"],price_precision) if v["ema200"] is not None else None,"macd_histogram":round(v["macd_histogram"],price_precision),
                "rsi":round(v["rsi"],1),"adx":round(v["adx"],1),"atr":round(v["atr"],price_precision),
                "structure":v["structure"]} for tf,v in analysis.items()},
            "quality_filters":quality_filters,"order_flow":order_flow_payload,
            "status":"SIGNAL" if signal else "WAIT","message":message}
