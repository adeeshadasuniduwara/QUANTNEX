"""Transparent, causal strategy-method evidence registry.

The registry initially mirrors the existing signal-engine checks.  It does not
change the legacy decision threshold or assign calibrated win probabilities.
Evidence is grouped into broad categories so correlated indicators can be
reported without pretending each is an independent confirmation.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Callable


@dataclass(frozen=True)
class MethodEvidence:
    method_id: str
    category: str
    side: str
    timeframe: str | None
    reason: str
    source: str = "CANDLE_DERIVED"
    observed_at: str | None = None
    strength: float = 1.0
    calibration: str = "UNWEIGHTED_RULE_EVIDENCE"
    counts_for_baseline: bool = True
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "method_id": self.method_id,
            "category": self.category,
            "side": self.side,
            "timeframe": self.timeframe,
            "reason": self.reason,
            "source": self.source,
            "observed_at": self.observed_at,
            "strength": self.strength,
            "calibration": self.calibration,
            "decision_role": "BASELINE_SCORE" if self.counts_for_baseline else "DIAGNOSTIC_ONLY",
            "counts_for_baseline": self.counts_for_baseline,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class StrategyMethod:
    method_id: str
    category: str
    evaluator: Callable[[dict[str, Any]], list[MethodEvidence]]


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _side_for_bias(value: Any) -> str | None:
    bias = str(value or "").upper()
    if bias == "BULLISH":
        return "BUY"
    if bias == "BEARISH":
        return "SELL"
    return None


def _ema_trend(context: dict[str, Any]) -> list[MethodEvidence]:
    analysis = context["analysis"]
    evidence = []
    for timeframe in ("60", "30", "15"):
        snapshot = analysis.get(timeframe)
        if not isinstance(snapshot, dict):
            continue
        side = _side_for_bias(snapshot.get("bias"))
        if side:
            evidence.append(MethodEvidence(
                "ema_trend", "TREND", side, timeframe,
                f"{timeframe}m EMA trend",
            ))
    return evidence


def _macd_momentum(context: dict[str, Any]) -> list[MethodEvidence]:
    primary = context["analysis"].get(context["primary"], {})
    histogram = _finite(primary.get("macd_histogram"))
    if histogram == 0:
        return []
    side = "BUY" if histogram > 0 else "SELL"
    return [MethodEvidence(
        "macd_momentum", "MOMENTUM", side, context["primary"],
        "Primary MACD momentum",
    )]


def _rsi_range(context: dict[str, Any]) -> list[MethodEvidence]:
    primary = context["analysis"].get(context["primary"], {})
    rsi_value = _finite(primary.get("rsi"), float("nan"))
    if not math.isfinite(rsi_value):
        return []
    if 50 <= rsi_value <= 70:
        side, reason = "BUY", "RSI bullish range"
    elif 30 <= rsi_value <= 50:
        side, reason = "SELL", "RSI bearish range"
    else:
        return []
    return [MethodEvidence(
        "rsi_range", "MOMENTUM", side, context["primary"], reason,
    )]


def _adx_strength(context: dict[str, Any]) -> list[MethodEvidence]:
    primary = context["analysis"].get(context["primary"], {})
    histogram = _finite(primary.get("macd_histogram"))
    if _finite(primary.get("adx")) < 18 or histogram == 0:
        return []
    side = "BUY" if histogram > 0 else "SELL"
    return [MethodEvidence(
        "adx_strength", "MOMENTUM", side, context["primary"],
        "ADX trend strength",
    )]


def _structure_break(context: dict[str, Any]) -> list[MethodEvidence]:
    structure = context["analysis"].get(context["primary"], {}).get("structure", {})
    direction = str(structure.get("bos_mss") or "").upper()
    if direction == "BULLISH":
        side, reason = "BUY", "Bullish BOS / MSS"
    elif direction == "BEARISH":
        side, reason = "SELL", "Bearish BOS / MSS"
    else:
        return []
    return [MethodEvidence(
        "market_structure_break", "STRUCTURE", side, context["primary"], reason,
    )]


def _liquidity_sweep(context: dict[str, Any]) -> list[MethodEvidence]:
    structure = context["analysis"].get(context["primary"], {}).get("structure", {})
    direction = str(structure.get("liquidity_sweep") or "").upper()
    if direction == "BULLISH":
        side, reason = "BUY", "Sell-side liquidity sweep"
    elif direction == "BEARISH":
        side, reason = "SELL", "Buy-side liquidity sweep"
    else:
        return []
    return [MethodEvidence(
        "liquidity_sweep", "LIQUIDITY", side, context["primary"], reason,
    )]


def _zone_location(context: dict[str, Any]) -> list[MethodEvidence]:
    primary = context["analysis"].get(context["primary"], {})
    structure = primary.get("structure", {})
    histogram = _finite(primary.get("macd_histogram"))
    discount_buy = structure.get("premium_discount") == "DISCOUNT" and histogram > 0
    premium_sell = structure.get("premium_discount") == "PREMIUM" and histogram < 0
    if not context.get("in_zone") and not discount_buy and not premium_sell:
        return []
    # Preserve the legacy rule: when in_zone is true and MACD is exactly zero,
    # the previous decision path assigned this location confirmation to SELL.
    side = "BUY" if histogram > 0 else "SELL"
    return [MethodEvidence(
        "zone_location", "LOCATION", side, context["primary"],
        "OB / FVG / breaker or premium-discount zone",
    )]


def _parse_candle_timestamp(value: Any) -> datetime | None:
    try:
        stamp = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except (TypeError, ValueError, OverflowError):
        return None
    if stamp.tzinfo is None:
        return None
    return stamp.astimezone(timezone.utc)


def _weighted_typical_price_vwap(rows: list[dict[str, float]]) -> float | None:
    total_volume = sum(row["volume"] for row in rows)
    if not math.isfinite(total_volume) or total_volume <= 0:
        return None
    total_value = sum(
        ((row["high"] + row["low"] + row["close"]) / 3) * row["volume"]
        for row in rows
    )
    value = total_value / total_volume
    return value if math.isfinite(value) and value > 0 else None


def _rolling_vwap_proxy(context: dict[str, Any]) -> list[MethodEvidence]:
    """Emit a diagnostic rolling VWAP from closed OHLCV bars, never aggressor flow."""
    timeframe = str(context["primary"])
    seconds = {"1": 60, "5": 300, "15": 900, "30": 1800,
               "50": 3000, "60": 3600, "240": 14400}.get(timeframe)
    as_of = context.get("as_of")
    if seconds is None or not isinstance(as_of, datetime) or as_of.tzinfo is None:
        return []
    as_of = as_of.astimezone(timezone.utc)
    closed: list[tuple[datetime, dict[str, float]]] = []
    for row in context.get("candles") or []:
        if not isinstance(row, dict):
            continue
        stamp = _parse_candle_timestamp(row.get("time"))
        if stamp is None or stamp + timedelta(seconds=seconds) > as_of:
            continue
        high = _finite(row.get("high"), float("nan"))
        low = _finite(row.get("low"), float("nan"))
        close = _finite(row.get("close"), float("nan"))
        volume = _finite(row.get("volume"), float("nan"))
        if not all(math.isfinite(value) for value in (high, low, close, volume)):
            continue
        if low <= 0 or high < low or not low <= close <= high or volume < 0:
            continue
        closed.append((stamp, {
            "high": high, "low": low, "close": close, "volume": volume,
        }))
    closed.sort(key=lambda item: item[0])
    if len(closed) < 51 or len({stamp for stamp, _row in closed}) != len(closed):
        return []
    if any(
        (current_stamp - previous_stamp).total_seconds() != seconds
        for (previous_stamp, _previous_row), (current_stamp, _current_row)
        in zip(closed, closed[1:])
    ):
        return []

    previous_rows = [row for _stamp, row in closed[-51:-1]]
    current_rows = [row for _stamp, row in closed[-50:]]
    previous_vwap = _weighted_typical_price_vwap(previous_rows)
    current_vwap = _weighted_typical_price_vwap(current_rows)
    if previous_vwap is None or current_vwap is None:
        return []
    last_close = current_rows[-1]["close"]
    if last_close > current_vwap and current_vwap > previous_vwap:
        side, direction = "BUY", "bullish"
    elif last_close < current_vwap and current_vwap < previous_vwap:
        side, direction = "SELL", "bearish"
    else:
        return []

    return [MethodEvidence(
        "rolling_vwap_proxy", "VALUE", side, timeframe,
        f"50-bar OHLCV typical-price VWAP proxy {direction} alignment",
        source="OHLCV_TYPICAL_PRICE_PROXY",
        calibration="UNWEIGHTED_DIAGNOSTIC_ONLY",
        counts_for_baseline=False,
        details={
            "lookback_bars": 50,
            "current_vwap": round(current_vwap, 12),
            "previous_vwap": round(previous_vwap, 12),
            "last_close": round(last_close, 12),
            "price_basis": "OHLCV typical price (high + low + close) / 3",
            "volume_basis": "total candle volume; no bid/ask or aggressor-side inference",
            "scope": "ROLLING_50_CLOSED_BARS",
        },
    )]


def _trend_timeframe_alignment(context: dict[str, Any]) -> list[MethodEvidence]:
    snapshot = context["analysis"].get(context["trend"], {})
    side = _side_for_bias(snapshot.get("bias"))
    if not side:
        return []
    return [MethodEvidence(
        "trend_timeframe_alignment", "TREND", side, context["trend"],
        "Trend timeframe aligned",
    )]


STRATEGY_METHOD_REGISTRY: tuple[StrategyMethod, ...] = (
    StrategyMethod("ema_trend", "TREND", _ema_trend),
    StrategyMethod("macd_momentum", "MOMENTUM", _macd_momentum),
    StrategyMethod("rsi_range", "MOMENTUM", _rsi_range),
    StrategyMethod("adx_strength", "MOMENTUM", _adx_strength),
    StrategyMethod("market_structure_break", "STRUCTURE", _structure_break),
    StrategyMethod("liquidity_sweep", "LIQUIDITY", _liquidity_sweep),
    StrategyMethod("zone_location", "LOCATION", _zone_location),
    StrategyMethod("trend_timeframe_alignment", "TREND", _trend_timeframe_alignment),
    StrategyMethod("rolling_vwap_proxy", "VALUE", _rolling_vwap_proxy),
)


def evaluate_strategy_registry(
    analysis: dict[str, dict[str, Any]],
    primary: str,
    trend: str,
    *,
    in_zone: bool,
    observed_at: str | None = None,
    candles: list[dict[str, Any]] | None = None,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate all registered methods and return baseline + category evidence.

    The ordered reason lists intentionally match the legacy confluence count.
    Category counts are a diagnostic only and are not yet used as live gates.
    """
    context = {
        "analysis": analysis,
        "primary": str(primary),
        "trend": str(trend),
        "in_zone": bool(in_zone),
        "candles": candles or [],
        "as_of": as_of,
    }
    evidence: list[MethodEvidence] = []
    for method in STRATEGY_METHOD_REGISTRY:
        for item in method.evaluator(context):
            if item.method_id != method.method_id or item.category != method.category:
                raise ValueError(
                    f"Strategy registry metadata mismatch for method {method.method_id}."
                )
            evidence.append(replace(item, observed_at=observed_at))

    buy = [
        item.reason for item in evidence
        if item.side == "BUY" and item.counts_for_baseline
    ]
    sell = [
        item.reason for item in evidence
        if item.side == "SELL" and item.counts_for_baseline
    ]
    categories = {
        side: sorted({item.category for item in evidence if item.side == side})
        for side in ("BUY", "SELL")
    }
    category_methods = {
        side: {
            category: [
                item.method_id for item in evidence
                if item.side == side and item.category == category
            ]
            for category in categories[side]
        }
        for side in ("BUY", "SELL")
    }
    return {
        "registry_version": 1,
        "evidence": [item.as_dict() for item in evidence],
        "diagnostic_only": [
            item.as_dict() for item in evidence if not item.counts_for_baseline
        ],
        "buy_reasons": buy,
        "sell_reasons": sell,
        "baseline_raw_counts": {"BUY": len(buy), "SELL": len(sell)},
        "unique_category_counts": {
            "BUY": len(categories["BUY"]),
            "SELL": len(categories["SELL"]),
        },
        "categories": categories,
        "category_methods": category_methods,
        "category_score_status": "DIAGNOSTIC_ONLY_NOT_USED_FOR_LIVE_DECISIONS",
    }
