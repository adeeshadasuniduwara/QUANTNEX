"""Deterministic Binance Spot trade-footprint aggregation from archived aggTrade events.

Reports observed aggressor-side volume only. It does not infer missing trades,
candle OHLC, hidden liquidity, or complete market coverage.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
import math
from typing import Any

MAX_FOOTPRINT_EVENTS = 5000
MAX_FOOTPRINT_LEVELS = 1000

class OrderFlowFootprintError(ValueError):
    """Raised when footprint inputs or limits are invalid."""

def _positive_decimal(value: Any, name: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise OrderFlowFootprintError(f"{name} must be a positive decimal.") from None
    if not number.is_finite() or number <= 0:
        raise OrderFlowFootprintError(f"{name} must be a positive decimal.")
    return number

def build_order_flow_footprint(events: list[dict[str, Any]], *, price_step: str | float | Decimal, interval_ms: int = 60_000, max_levels: int = 250, imbalance_ratio: float = 3.0) -> dict[str, Any]:
    """Aggregate archived aggTrade rows into UTC time/price footprints.

    Binance aggTrade m is buyer-is-maker: True means seller aggressor; False
    means buyer aggressor. Prices are floored to explicit exchange tick size.
    """
    step = _positive_decimal(price_step, "price_step")
    if not isinstance(events, list) or len(events) > MAX_FOOTPRINT_EVENTS:
        raise OrderFlowFootprintError(f"events must be a list of at most {MAX_FOOTPRINT_EVENTS} rows.")
    if isinstance(interval_ms, bool) or not isinstance(interval_ms, int) or interval_ms not in {60_000, 300_000, 900_000}:
        raise OrderFlowFootprintError("interval_ms must be 60000, 300000 or 900000.")
    if isinstance(max_levels, bool) or not isinstance(max_levels, int) or not 1 <= max_levels <= MAX_FOOTPRINT_LEVELS:
        raise OrderFlowFootprintError(f"max_levels must be between 1 and {MAX_FOOTPRINT_LEVELS}.")
    if isinstance(imbalance_ratio, bool) or not isinstance(imbalance_ratio, (int, float)) or not math.isfinite(float(imbalance_ratio)) or imbalance_ratio < 1.0:
        raise OrderFlowFootprintError("imbalance_ratio must be a finite number greater than or equal to 1.")
    buckets: dict[int, dict[Decimal, dict[str, Any]]] = defaultdict(dict)
    accepted = ignored = 0
    for event in events:
        if not isinstance(event, dict) or event.get("event_type") != "aggTrade":
            ignored += 1
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            raise OrderFlowFootprintError("aggTrade payload must be an object.")
        try:
            event_ms = int(event["event_time_ms"])
            price = _positive_decimal(payload["p"], "trade price")
            quantity = _positive_decimal(payload["q"], "trade quantity")
            buyer_is_maker = payload["m"]
        except (KeyError, TypeError, ValueError, OverflowError):
            raise OrderFlowFootprintError("aggTrade row is missing valid time, price or quantity.") from None
        if event_ms <= 0 or not isinstance(buyer_is_maker, bool):
            raise OrderFlowFootprintError("aggTrade timestamp or aggressor side is invalid.")
        level = (price / step).to_integral_value(rounding=ROUND_FLOOR) * step
        bucket = (event_ms // interval_ms) * interval_ms
        row = buckets[bucket].setdefault(level, {"buy_volume": Decimal("0"), "sell_volume": Decimal("0"), "trade_count": 0})
        row["sell_volume" if buyer_is_maker else "buy_volume"] += quantity
        row["trade_count"] += 1
        accepted += 1
    candles = []
    for bucket in sorted(buckets):
        levels = buckets[bucket]
        ordered = sorted(levels, reverse=True)[:max_levels]
        rows = []
        for price in ordered:
            data = levels[price]
            buy, sell = data["buy_volume"], data["sell_volume"]
            next_lower = levels.get(price - step, {}).get("sell_volume", Decimal("0"))
            next_higher = levels.get(price + step, {}).get("buy_volume", Decimal("0"))
            rows.append({"price": format(price, "f"), "buy_volume": format(buy, "f"), "sell_volume": format(sell, "f"),
                         "delta": format(buy - sell, "f"), "total_volume": format(buy + sell, "f"),
                         "trade_count": data["trade_count"],
                         "buy_imbalance": bool(next_lower > 0 and buy >= next_lower * Decimal(str(imbalance_ratio))),
                         "sell_imbalance": bool(next_higher > 0 and sell >= next_higher * Decimal(str(imbalance_ratio)))})
        candles.append({"open_time_ms": bucket, "interval_ms": interval_ms, "levels": rows, "level_count": len(rows),
                        "trades_aggregated": sum(levels[p]["trade_count"] for p in ordered), "levels_truncated": len(levels) > len(ordered)})
    return {"market_type": "BINANCE_SPOT", "source": "ARCHIVED_AGG_TRADE_EVENTS", "price_step": format(step, "f"),
            "imbalance_ratio": float(imbalance_ratio), "accepted_trade_events": accepted, "ignored_non_trade_events": ignored,
            "candles": candles, "coverage": "OBSERVED_EVENTS_ONLY_NOT_PROVEN_COMPLETE"}
