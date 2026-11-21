"""Independent candle-validated Binance USDⓈ-M perpetual signal engine.

This engine reuses QUANTNEX's transparent confluence catalogue against strictly
validated, fully closed USDⓈ-M candles. It is read-only: no leverage selection,
account access, order placement, or Spot order-flow substitution is performed.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from .binance_usdm_market_data import (
    BinanceUsdMDataError,
    fetch_binance_usdm_candles,
)

INTERVAL_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900,
    "30m": 1800, "1h": 3600, "4h": 14400,
}


class BinanceUsdMSignalError(RuntimeError):
    pass


async def analyze_usdm_futures_signal(
    symbol: str, interval: str, min_score: int = 6,
) -> dict[str, Any]:
    """Analyze one active perpetual using closed, fresh Futures candles only."""
    normalized = str(symbol or "").strip().upper()
    if not normalized.isalnum() or not 1 <= len(normalized) <= 30:
        raise BinanceUsdMSignalError("Choose a valid Binance USDⓈ-M perpetual symbol.")
    if interval not in INTERVAL_SECONDS:
        raise BinanceUsdMSignalError("Choose a supported USDⓈ-M timeframe.")
    if not isinstance(min_score, int) or isinstance(min_score, bool) or not 4 <= min_score <= 20:
        raise BinanceUsdMSignalError("Confluence threshold must be between 4 and 20.")

    try:
        candles = await fetch_binance_usdm_candles(normalized, interval, 1000)
    except BinanceUsdMDataError as exc:
        raise BinanceUsdMSignalError(str(exc)) from exc
    if not isinstance(candles, list) or len(candles) < 210:
        raise BinanceUsdMSignalError(
            f"At least 210 fully closed {interval} USDⓈ-M candles are required; "
            f"received {len(candles) if isinstance(candles, list) else 0}."
        )

    # Re-validate chronology/OHLC at the signal boundary. Never silently sort
    # or repair malformed rows supplied by a provider adapter.
    previous = None
    parsed_times = []
    for row in candles:
        try:
            stamp = datetime.fromisoformat(str(row["time"]).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            stamp = stamp.astimezone(timezone.utc)
            values = [float(row[key]) for key in ("open", "high", "low", "close", "volume")]
            op, high, low, close, volume = values
            if (not all(math.isfinite(value) for value in values)
                    or min(op, high, low, close) <= 0 or volume < 0
                    or high < max(op, close, low) or low > min(op, close, high)):
                raise ValueError
            if previous is not None and stamp <= previous:
                raise ValueError
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise BinanceUsdMSignalError("Futures candles failed OHLC, timestamp or ordering validation.") from exc
        previous = stamp
        parsed_times.append(stamp)

    now = datetime.now(timezone.utc)
    age = max(0.0, (now - parsed_times[-1]).total_seconds())
    stale_after = INTERVAL_SECONDS[interval] * 2 + 60
    if age > stale_after:
        raise BinanceUsdMSignalError(
            f"Latest closed Futures candle is stale ({int(age)}s old; limit {stale_after}s)."
        )

    from .quantnex_view_intelligence import analyze_candles, MarketDataError
    try:
        result = analyze_candles(candles, normalized, interval, min_score)
    except (MarketDataError, ValueError, KeyError, IndexError) as exc:
        raise BinanceUsdMSignalError(f"Futures confluence analysis failed closed: {exc}") from exc

    result["market_type"] = "BINANCE_USDM_FUTURES"
    result["provider"] = "Binance USDⓈ-M Futures"
    result["data_mode"] = "PUBLIC_READ_ONLY_CLOSED_CANDLES"
    result["signal_engine"] = "QUANTNEX_USDM_CANDLE_CONFLUENCE_V1"
    result["data_health"] = "FRESH"
    result["latest_candle_age_seconds"] = round(age, 2)
    result["score_note"] = (
        "USDⓈ-M Futures candle-confluence ranking only; not a measured win probability. "
        "Futures Order Flow is not included in this engine."
    )
    result["execution_enabled"] = False
    result["order_flow_enabled"] = False
    result["display_symbol"] = normalized + ".P"
    if result.get("signal"):
        signal = result["signal"]
        signal["symbol"] = normalized + ".P"
        signal["display_symbol"] = normalized + ".P"
        signal["exchange_symbol"] = normalized
        signal["market_type"] = "BINANCE_USDM_FUTURES"
        signal["entry_reference_note"] = (
            "Last fully closed USDⓈ-M candle reference; not a broker fill. "
            "Futures signals are monitor-only; no order was placed."
        )
    return result
