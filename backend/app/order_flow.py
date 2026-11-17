"""Causal Binance Spot order-flow analytics.

Binance aggregate-trade buyer-is-maker semantics:
- m=False: buyer was taker (aggressive buy volume)
- m=True: seller was taker (aggressive sell volume)

This is exchange-reported aggressor-side inference, not consolidated bid/ask
volume across venues. OHLCV candles are never used as a substitute.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
import math
from typing import Any


class OrderFlowDataError(ValueError):
    """Raised when order-flow input is malformed, stale, or unsafe."""


def _aware_utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise OrderFlowDataError(f"{name} must be a timezone-aware datetime.")
    return value.astimezone(timezone.utc)


def _positive_decimal(value: Any, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise OrderFlowDataError(f"{name} must be a valid decimal.") from None
    if not result.is_finite() or result <= 0:
        raise OrderFlowDataError(f"{name} must be finite and positive.")
    return result


def normalize_agg_trades(rows: list[dict[str, Any]], *, now: datetime | None = None,
                         max_age_seconds: float = 15.0,
                         future_tolerance_seconds: float = 2.0) -> list[dict[str, Any]]:
    """Validate, de-duplicate and chronologically sort Binance aggTrade rows."""
    if not isinstance(rows, list) or not rows:
        raise OrderFlowDataError("Binance aggregate-trade data is empty.")
    if not math.isfinite(max_age_seconds) or max_age_seconds <= 0:
        raise OrderFlowDataError("max_age_seconds must be finite and positive.")
    if not math.isfinite(future_tolerance_seconds) or future_tolerance_seconds < 0:
        raise OrderFlowDataError("future_tolerance_seconds must be finite and non-negative.")
    clock = _aware_utc(now or datetime.now(timezone.utc), "now")
    normalized: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise OrderFlowDataError("Aggregate-trade rows must be objects.")
        try:
            trade_id = int(row["a"])
            price = _positive_decimal(row["p"], "trade price")
            quantity = _positive_decimal(row["q"], "trade quantity")
            timestamp_ms = int(row["T"])
            buyer_is_maker = row["m"]
        except (KeyError, TypeError, ValueError, OverflowError):
            raise OrderFlowDataError("Binance aggregate-trade row has invalid required fields.") from None
        if trade_id < 0 or timestamp_ms <= 0 or not isinstance(buyer_is_maker, bool):
            raise OrderFlowDataError("Aggregate-trade identifiers, timestamp or maker flag are invalid.")
        stamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        age = (clock - stamp).total_seconds()
        if age < -future_tolerance_seconds:
            raise OrderFlowDataError("Aggregate-trade data contains a future-dated trade.")
        item = {
            "aggregate_trade_id": trade_id, "price": price, "quantity": quantity,
            "timestamp": stamp, "buyer_is_maker": buyer_is_maker,
            "aggressor_side": "SELL" if buyer_is_maker else "BUY",
            "signed_quantity": -quantity if buyer_is_maker else quantity,
        }
        previous = normalized.get(trade_id)
        if previous is not None and any(
            previous[key] != item[key]
            for key in ("price", "quantity", "timestamp", "buyer_is_maker")
        ):
            raise OrderFlowDataError(
                f"Aggregate-trade ID {trade_id} has conflicting duplicate payloads."
            )
        normalized[trade_id] = item
    result = sorted(normalized.values(), key=lambda item: (item["timestamp"], item["aggregate_trade_id"]))
    latest_age = (clock - result[-1]["timestamp"]).total_seconds()
    if latest_age > max_age_seconds:
        raise OrderFlowDataError(
            f"Binance aggregate-trade stream is stale ({latest_age:.1f}s; limit {max_age_seconds:.1f}s)."
        )
    return result


def calculate_order_book_metrics(bids: list[list[Any]], asks: list[list[Any]], *,
                                  depth_levels: int = 10) -> dict[str, float | int | str]:
    """Calculate metrics from one validated Binance L2 depth snapshot."""
    if not isinstance(bids, list) or not isinstance(asks, list) or not bids or not asks:
        raise OrderFlowDataError("Order-book snapshot must contain bids and asks.")
    if not isinstance(depth_levels, int) or depth_levels < 1:
        raise OrderFlowDataError("depth_levels must be a positive integer.")

    def parse_levels(rows: list[list[Any]], side: str) -> list[tuple[Decimal, Decimal]]:
        parsed = []
        for row in rows[:depth_levels]:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                raise OrderFlowDataError(f"Invalid {side} order-book level.")
            parsed.append((_positive_decimal(row[0], f"{side} price"),
                           _positive_decimal(row[1], f"{side} quantity")))
        if not parsed:
            raise OrderFlowDataError(f"Order book has no {side} levels.")
        prices = [price for price, _ in parsed]
        if prices != sorted(prices, reverse=(side == "bid")):
            raise OrderFlowDataError(f"{side.capitalize()} levels are not price-sorted.")
        return parsed

    bid_levels = parse_levels(bids, "bid")
    ask_levels = parse_levels(asks, "ask")
    best_bid, best_bid_qty = bid_levels[0]
    best_ask, best_ask_qty = ask_levels[0]
    if best_bid >= best_ask:
        raise OrderFlowDataError("Order book is crossed or locked; refresh the snapshot.")
    bid_notional = sum((price * qty for price, qty in bid_levels), Decimal(0))
    ask_notional = sum((price * qty for price, qty in ask_levels), Decimal(0))
    total_depth = bid_notional + ask_notional
    imbalance = float((bid_notional - ask_notional) / total_depth) if total_depth else 0.0
    mid = (best_bid + best_ask) / Decimal(2)
    spread_bps = (best_ask - best_bid) / mid * Decimal(10000)
    microprice = (best_ask * best_bid_qty + best_bid * best_ask_qty) / (best_bid_qty + best_ask_qty)
    return {
        "best_bid": float(best_bid), "best_ask": float(best_ask), "mid_price": float(mid),
        "spread_bps": float(spread_bps), "bid_depth_quote": float(bid_notional),
        "ask_depth_quote": float(ask_notional), "depth_imbalance": imbalance,
        "microprice": float(microprice),
        "microprice_displacement_bps": float((microprice - mid) / mid * Decimal(10000)),
        "bid_levels": len(bid_levels), "ask_levels": len(ask_levels),
        "source": "BINANCE_SPOT_L2_SNAPSHOT",
    }


def calculate_order_flow(agg_trades: list[dict[str, Any]], bids: list[list[Any]],
                         asks: list[list[Any]], *, now: datetime | None = None,
                         max_trade_age_seconds: float = 15.0,
                         tick_size: str | Decimal = "0.00000001",
                         depth_levels: int = 10,
                         footprint_imbalance_ratio: float = 3.0,
                         session_start_trade_id: int | None = None) -> dict[str, Any]:
    """Return recent-window aggressor delta and L2 metrics with honest session coverage.

    A complete UTC session delta is emitted only when the caller supplies the
    exchange-reported first aggTrade ID for the current UTC day and every
    aggregate trade from that ID through the latest trade is present.
    """
    clock = _aware_utc(now or datetime.now(timezone.utc), "now")
    tick = _positive_decimal(tick_size, "tick_size")
    if not math.isfinite(footprint_imbalance_ratio) or footprint_imbalance_ratio <= 1:
        raise OrderFlowDataError("footprint_imbalance_ratio must be greater than one.")
    trades = normalize_agg_trades(agg_trades, now=clock, max_age_seconds=max_trade_age_seconds)
    book = calculate_order_book_metrics(bids, asks, depth_levels=depth_levels)
    buy_volume = sum((x["quantity"] for x in trades if x["aggressor_side"] == "BUY"), Decimal(0))
    sell_volume = sum((x["quantity"] for x in trades if x["aggressor_side"] == "SELL"), Decimal(0))
    delta = buy_volume - sell_volume
    total_volume = buy_volume + sell_volume
    quote_delta = sum((x["signed_quantity"] * x["price"] for x in trades), Decimal(0))
    session_date = trades[-1]["timestamp"].date()
    session_trades = [x for x in trades if x["timestamp"].date() == session_date]
    session_delta_sample = sum((x["signed_quantity"] for x in session_trades), Decimal(0))
    if session_start_trade_id is not None and (
        isinstance(session_start_trade_id, bool) or not isinstance(session_start_trade_id, int)
        or session_start_trade_id < 0
    ):
        raise OrderFlowDataError("session_start_trade_id must be a non-negative integer.")
    session_ids = [x["aggregate_trade_id"] for x in session_trades]
    session_coverage_complete = bool(
        session_start_trade_id is not None
        and session_ids
        and session_ids[0] == session_start_trade_id
        and session_ids == list(range(session_start_trade_id, session_ids[-1] + 1))
    )
    session_delta = session_delta_sample if session_coverage_complete else None
    footprint: dict[Decimal, dict[str, Decimal]] = defaultdict(
        lambda: {"buy_volume": Decimal(0), "sell_volume": Decimal(0)}
    )
    for item in trades:
        bucket = (item["price"] / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
        footprint[bucket]["buy_volume" if item["aggressor_side"] == "BUY" else "sell_volume"] += item["quantity"]
    footprint_rows = []
    for price in sorted(footprint):
        buy, sell = footprint[price]["buy_volume"], footprint[price]["sell_volume"]
        ratio = float(max(buy, sell) / min(buy, sell)) if min(buy, sell) > 0 else (
            float("inf") if max(buy, sell) > 0 else 1.0
        )
        footprint_rows.append({
            "price": float(price), "buy_volume": float(buy), "sell_volume": float(sell),
            "delta": float(buy - sell),
            "dominant_side": "BUY" if buy > sell else "SELL" if sell > buy else "BALANCED",
            "imbalance_ratio": ratio if math.isfinite(ratio) else None,
            "is_imbalanced": ratio >= footprint_imbalance_ratio,
        })
    age = max(0.0, (clock - trades[-1]["timestamp"]).total_seconds())
    return {
        "market_type": "BINANCE_SPOT",
        "data_provenance": {
            "trade_source": "Binance Spot aggregate trades; buyer-is-maker flag infers aggressor side",
            "book_source": book["source"],
            "bid_ask_semantics": "Aggressor-side inferred trade delta; not consolidated quoted bid/ask volume.",
            "candle_volume_used": False,
        },
        "trade_count": len(trades), "unique_aggregate_trade_ids": len({x["aggregate_trade_id"] for x in trades}),
        "first_trade_at": trades[0]["timestamp"].isoformat(),
        "last_trade_at": trades[-1]["timestamp"].isoformat(), "trade_data_age_seconds": round(age, 3),
        "buy_volume": float(buy_volume), "sell_volume": float(sell_volume), "delta": float(delta),
        "delta_ratio": float(delta / total_volume) if total_volume else 0.0,
        "window_cumulative_delta": float(delta), "window_delta_scope": "LATEST_AGGTRADE_RESPONSE_WINDOW",
        "cvd_value": None, "cvd_status": "NOT_AVAILABLE_WITHOUT_CONTINUOUS_TRADE_STATE",
        "quote_delta": float(quote_delta),
        "session_timezone": "UTC", "session_date_utc": session_date.isoformat(),
        "session_delta": float(session_delta) if session_coverage_complete else None,
        "session_delta_sample": float(session_delta_sample),
        "session_delta_coverage_complete": session_coverage_complete,
        "session_delta_scope": "FULL_UTC_SESSION" if session_coverage_complete else "RECENT_WINDOW_SAMPLE_ONLY",
        "session_start_trade_id": session_start_trade_id,
        "footprint": footprint_rows,
        "order_book": book, "quality": "OBSERVED_AGGRESSOR_DELTA_AND_L2_SNAPSHOT",
    }
