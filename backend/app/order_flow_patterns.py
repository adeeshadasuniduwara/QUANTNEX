"""Candle-context interpretation of verified Binance Spot order flow.

The classifiers are deterministic research labels, not probabilities. They
require observed aggressor-side trades and sequence-validated L2 depth; OHLCV
candle volume is never treated as bid/ask volume.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


def detect_order_flow_patterns(
    side: str,
    candle: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    baseline_trade_count: float | None = None,
) -> dict[str, Any]:
    """Detect absorption/exhaustion patterns and report whether they oppose a setup."""
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL.")
    if not isinstance(candle, dict) or not isinstance(snapshot, dict):
        raise ValueError("A candle and verified order-flow snapshot are required.")
    if snapshot.get("market_type") != "BINANCE_SPOT":
        raise ValueError("Order-flow patterns require Binance Spot provenance.")
    feed_mode = str(snapshot.get("feed_mode") or "")
    if feed_mode not in {"PUBLIC_WEBSOCKET_STREAM", "RAW_EVENT_REPLAY"} or snapshot.get("depth_is_continuous") is not True:
        raise ValueError("Order-flow patterns require sequence-validated public Spot depth.")
    provenance = snapshot.get("data_provenance")
    if not isinstance(provenance, dict) or provenance.get("candle_volume_used") is not False:
        raise ValueError("Order-flow pattern input is missing verified trade-side provenance.")
    order_book = snapshot.get("order_book")
    if not isinstance(order_book, dict):
        raise ValueError("Order-flow pattern input is missing L2 book metrics.")
    if feed_mode == "RAW_EVENT_REPLAY":
        if (
            snapshot.get("eligible_for_order_flow_replay") is not True
            or snapshot.get("coverage_is_complete") is not False
            or snapshot.get("coverage_status") != "OBSERVED_CONTIGUOUS_CAPTURE_NOT_FULL_SESSION"
            or snapshot.get("capture_gap_detected") is not False
            or provenance.get("decision_clock") != "RECEIVED_AT_MS"
            or order_book.get("source") != "BINANCE_SPOT_SEQUENCE_VALIDATED_DEPTH_REPLAY"
        ):
            raise ValueError("Raw replay patterns require an eligible bounded receive-time checkpoint and validated depth.")
    pattern_metadata = {
        "method": "AGGRESSOR_DELTA_L2_CANDLE_RESPONSE_ABSORPTION_EXHAUSTION",
        "method_version": 1,
        "market_type": "BINANCE_SPOT",
        "symbol": str(snapshot.get("symbol") or "").upper() or None,
        "feed_mode": feed_mode,
        "coverage_status": snapshot.get("coverage_status"),
        "coverage_is_complete": snapshot.get("coverage_is_complete"),
        "data_provenance": {
            "candle_volume_used": provenance.get("candle_volume_used"),
            "bid_ask_semantics": provenance.get("bid_ask_semantics"),
            "decision_clock": provenance.get("decision_clock"),
            "capture_scope": provenance.get("capture_scope"),
        },
    }

    def finite(value: Any, label: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{label} must be finite numeric data.")
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            raise ValueError(f"{label} must be finite numeric data.") from None
        if not math.isfinite(number):
            raise ValueError(f"{label} must be finite numeric data.")
        return number

    opening = finite(candle.get("open"), "candle open")
    high = finite(candle.get("high"), "candle high")
    low = finite(candle.get("low"), "candle low")
    close = finite(candle.get("close"), "candle close")
    if min(opening, high, low, close) <= 0 or high < max(opening, close, low) or low > min(opening, close, high):
        raise ValueError("Candle OHLC geometry is invalid.")
    candle_range = high - low
    if candle_range <= 0:
        return {
            **pattern_metadata,
            "status": "NO_PATTERN", "direction": None, "accepted_for_side": True,
            "reason": "Zero-range candle cannot establish absorption or exhaustion.",
        }

    flow = snapshot
    delta_ratio = finite(flow.get("delta_ratio"), "aggressor delta ratio")
    depth_imbalance = finite(order_book.get("depth_imbalance"), "L2 depth imbalance")
    trade_count = finite(flow.get("trade_count"), "aggregate trade count")
    trade_age = finite(flow.get("trade_data_age_seconds"), "trade age")
    depth_age = finite(flow.get("depth_data_age_seconds", flow.get("depth_age_seconds", 0)), "depth age")
    if trade_count < 1 or not -1 <= delta_ratio <= 1 or not -1 <= depth_imbalance <= 1:
        raise ValueError("Order-flow pattern metrics are outside validated ranges.")
    if trade_age < 0 or trade_age > 15 or depth_age < 0 or depth_age > 5:
        raise ValueError("Order-flow pattern input is stale.")

    candle_stamp = candle.get("time") or candle.get("open_time")
    trade_stamp = flow.get("last_trade_at")
    depth_stamp = flow.get("depth_observed_at")
    try:
        candle_time = datetime.fromisoformat(str(candle_stamp or "").replace("Z", "+00:00"))
        trade_time = datetime.fromisoformat(str(trade_stamp or "").replace("Z", "+00:00"))
        depth_time = datetime.fromisoformat(str(depth_stamp or "").replace("Z", "+00:00"))
        if any(value.tzinfo is None or value.utcoffset() is None for value in (candle_time, trade_time, depth_time)):
            raise ValueError("Order-flow and candle timestamps must carry an explicit UTC offset.")
        candle_time = candle_time.astimezone(timezone.utc)
        trade_time = trade_time.astimezone(timezone.utc)
        depth_time = depth_time.astimezone(timezone.utc)
        if candle_time.second != 0 or candle_time.microsecond != 0:
            raise ValueError("The M1 candle timestamp must be aligned to a UTC minute.")
        candle_minute = int(candle_time.timestamp()) // 60
        trade_minute = int(trade_time.timestamp()) // 60
        depth_minute = int(depth_time.timestamp()) // 60
    except (TypeError, ValueError, OverflowError):
        return {
            **pattern_metadata,
            "status": "NOT_ALIGNED", "direction": None, "accepted_for_side": True,
            "candle_minute": None, "trade_observed_at": None, "depth_observed_at": None,
            "reason": "The closed M1 candle, exchange trade and depth timestamps must all be present, timezone-aware and valid; pattern confirmation is skipped.",
            "evidence": [],
        }
    if candle_minute != trade_minute or candle_minute != depth_minute:
        return {
            **pattern_metadata,
            "status": "NOT_ALIGNED", "direction": None, "accepted_for_side": True,
            "candle_minute": candle_time.isoformat(),
            "trade_observed_at": trade_time.isoformat(),
            "depth_observed_at": depth_time.isoformat(),
            "reason": "The closed M1 candle, observed aggressor trades and sequence-validated depth do not belong to the same UTC minute; no pattern is inferred.",
            "evidence": [],
        }

    close_location = (close - low) / candle_range
    upper_wick_ratio = (high - max(opening, close)) / candle_range
    lower_wick_ratio = (min(opening, close) - low) / candle_range

    pattern = None
    evidence: list[str] = []
    # Aggressive buying absorbed by passive asks: positive delta, weak close,
    # and ask-heavy resting liquidity. This is a bearish (SELL) clue.
    if delta_ratio >= 0.35 and close_location <= 0.60 and depth_imbalance <= -0.10:
        pattern = "SELL_ABSORPTION"
        evidence = [
            f"Aggressive buy delta is elevated ({delta_ratio:+.3f})",
            f"Price failed to hold the upper candle range (close location {close_location:.2f})",
            f"Ask-side L2 liquidity dominates ({depth_imbalance:+.3f})",
        ]
    # Aggressive selling absorbed by passive bids: negative delta, resilient
    # close, and bid-heavy resting liquidity. This is a bullish (BUY) clue.
    elif delta_ratio <= -0.35 and close_location >= 0.40 and depth_imbalance >= 0.10:
        pattern = "BUY_ABSORPTION"
        evidence = [
            f"Aggressive sell delta is elevated ({delta_ratio:+.3f})",
            f"Price held above the lower candle range (close location {close_location:.2f})",
            f"Bid-side L2 liquidity dominates ({depth_imbalance:+.3f})",
        ]

    baseline = None
    if baseline_trade_count is not None:
        baseline = finite(baseline_trade_count, "baseline trade count")
        if baseline <= 0:
            raise ValueError("baseline trade count must be positive.")
    if pattern is None and baseline is not None and trade_count >= baseline * 1.75:
        if delta_ratio >= 0.40 and upper_wick_ratio >= 0.35 and close_location <= 0.55:
            pattern = "SELL_EXHAUSTION"
            evidence = [
                f"Trade activity expanded to {trade_count:.0f} vs {baseline:.1f} baseline",
                f"Aggressive buying failed to hold the high (upper wick {upper_wick_ratio:.2f})",
                f"Close location is {close_location:.2f}",
            ]
        elif delta_ratio <= -0.40 and lower_wick_ratio >= 0.35 and close_location >= 0.45:
            pattern = "BUY_EXHAUSTION"
            evidence = [
                f"Trade activity expanded to {trade_count:.0f} vs {baseline:.1f} baseline",
                f"Aggressive selling failed to hold the low (lower wick {lower_wick_ratio:.2f})",
                f"Close location is {close_location:.2f}",
            ]

    if pattern is None:
        status = "NO_PATTERN"
        direction = None
        reason = (
            "No absorption/exhaustion threshold was met."
            if baseline is not None else
            "No absorption threshold was met; exhaustion awaits a stored trade-count baseline."
        )
    else:
        status = pattern
        direction = "BUY" if pattern.startswith("BUY_") else "SELL"
        reason = "Pattern is a deterministic context clue, not a standalone entry signal."

    return {
        "status": status,
        "direction": direction,
        "accepted_for_side": direction is None or direction == side,
        "evidence": evidence,
        "candle_metrics": {
            "close_location": round(close_location, 4),
            "upper_wick_ratio": round(upper_wick_ratio, 4),
            "lower_wick_ratio": round(lower_wick_ratio, 4),
        },
        "order_flow_metrics": {
            "delta_ratio": delta_ratio,
            "depth_imbalance": depth_imbalance,
            "trade_count": int(trade_count),
            "baseline_trade_count": baseline,
        },
        **pattern_metadata,
        "candle_minute": candle_time.isoformat(),
        "trade_observed_at": trade_time.isoformat(),
        "depth_observed_at": depth_time.isoformat(),
        "reason": reason,
        "limitations": [
            "Binance Spot venue only; not consolidated multi-venue flow.",
            "L2 depth is observed resting liquidity and can be cancelled; it is not proof of execution.",
            "Exhaustion requires at least one stored trade-count baseline; otherwise it is not classified.",
            "No candle volume is used as a substitute for aggressor-side volume.",
        ],
    }
