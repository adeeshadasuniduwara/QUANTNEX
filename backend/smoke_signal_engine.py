"""Read-only smoke test for live QUANTNEX signal data providers.

Run from the backend directory after activating the project's Python environment:
    python smoke_signal_engine.py --universe-sample-size 20
"""
from __future__ import annotations

import argparse
import asyncio
import math
from datetime import datetime, timezone
import sys

from app.signal_engine import MarketDataError, build_signal, get_binance_spot_symbols


DEFAULT_SETTINGS = {
    "primary": "5",
    "trend": "60",
    "enabled": ["60", "30", "15", "5", "1"],
    "risk_percent": 1,
    "min_score": 8,
}


def rotating_symbol_sample(
    symbols: list[str], sample_size: int, *, day_index: int | None = None
) -> list[str]:
    """Return a deterministic daily slice that rotates through the live Spot universe."""
    if isinstance(sample_size, bool) or not isinstance(sample_size, int) or sample_size < 1:
        raise ValueError("universe sample size must be a positive integer.")
    if day_index is None:
        day_index = datetime.now(timezone.utc).date().toordinal()
    if isinstance(day_index, bool) or not isinstance(day_index, int) or day_index < 0:
        raise ValueError("sample day index must be a non-negative integer.")
    universe = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
    if not universe:
        return []
    if len(universe) <= sample_size:
        return universe
    start = (day_index * sample_size) % len(universe)
    return [universe[(start + offset) % len(universe)] for offset in range(sample_size)]


def _format_price(symbol: str, value: float) -> str:
    return f"{float(value):.{2 if symbol == 'XAUUSD' else 8}f}"


def _format_diagnostic_value(value: object) -> str | None:
    """Format a small, safe scalar for smoke diagnostics."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        numeric = float(value)
        return f"{numeric:.4g}" if math.isfinite(numeric) else None
    if isinstance(value, str):
        normalized = " ".join(value.split())
        return normalized[:100] if normalized else None
    return None


def _format_order_flow_diagnostics(result: dict) -> str:
    """Expose the live Order Flow gate outcome without dumping raw feed payloads."""
    flow = result.get("order_flow")
    if not isinstance(flow, dict):
        return "  Order Flow: UNAVAILABLE"

    status = _format_diagnostic_value(flow.get("status")) or "UNKNOWN"
    accepted_value = flow.get("accepted")
    accepted = (
        "n/a" if accepted_value is None
        else "yes" if accepted_value is True
        else "no" if accepted_value is False
        else _format_diagnostic_value(accepted_value) or "unknown"
    )
    fields = [f"status={status}", f"accepted={accepted}"]
    for key in (
        "feed_mode", "stream_ready", "trade_count", "delta", "delta_ratio",
        "cvd_status", "trade_data_age_seconds", "session_delta_coverage_complete",
    ):
        formatted = _format_diagnostic_value(flow.get(key))
        if formatted is not None:
            fields.append(f"{key}={formatted}")

    book = flow.get("order_book")
    if isinstance(book, dict):
        for key in ("spread_bps", "depth_imbalance"):
            formatted = _format_diagnostic_value(book.get(key))
            if formatted is not None:
                fields.append(f"{key}={formatted}")
    return "  Order Flow: " + " | ".join(fields)


async def _run(
    symbols: list[str] | None,
    min_score: int,
    *,
    universe_sample_size: int = 20,
    sample_day: int | None = None,
) -> int:
    settings = {**DEFAULT_SETTINGS, "min_score": max(8, min(10, min_score))}
    try:
        universe = await get_binance_spot_symbols()
    except MarketDataError as exc:
        print(f"[ERROR] Binance Spot symbol discovery failed: {exc}", file=sys.stderr)
        return 1

    if not universe:
        print("No eligible Binance Spot pairs were returned by exchangeInfo.", file=sys.stderr)
        return 1

    if symbols is None:
        try:
            symbols = rotating_symbol_sample(
                universe, universe_sample_size, day_index=sample_day
            )
        except ValueError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 2
        print(f"Eligible Binance Spot pairs from exchangeInfo: {len(universe)}")
        print(
            f"Rotating smoke sample: {len(symbols)} pairs "
            f"(sample day={sample_day if sample_day is not None else datetime.now(timezone.utc).date().toordinal()})"
        )
    else:
        symbols = list(dict.fromkeys(str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()))
        if not symbols:
            print("Invalid or empty symbol list.", file=sys.stderr)
            return 2
        allowed = set(universe) | {"XAUUSD"}
        invalid = [symbol for symbol in symbols if symbol not in allowed]
        if invalid:
            print("Unsupported/non-tradable market symbol(s): " + ", ".join(invalid), file=sys.stderr)
            return 2

    failures = 0
    skipped = 0
    print("QUANTNEX read-only signal smoke test")
    print("No Telegram messages are sent and no broker orders are placed.")
    print("-" * 72)

    for index, symbol in enumerate(symbols):
        try:
            result = await build_signal(settings, symbol)
            provider = result.get("provider", "Unknown")
            signal = result.get("signal")
            if not signal:
                print(
                    f"[WAIT] {symbol} | source={provider} | "
                    f"confluence={result.get('confluence_score', 0)}/10"
                )
            else:
                print(
                    f"[SIGNAL] {symbol} {signal['side']} | source={provider} | "
                    f"score={signal['score']}/10"
                )
                print(
                    f"  Entry={_format_price(symbol, signal['entry'])} "
                    f"SL={_format_price(symbol, signal['stop_loss'])} "
                    f"TP1={_format_price(symbol, signal['tp1'])} "
                    f"TP2={_format_price(symbol, signal['tp2'])} "
                    f"TP3={_format_price(symbol, signal['tp3'])}"
                )
                print(f"  Candle={signal['signal_candle_time']}")
            print(_format_order_flow_diagnostics(result))
        except MarketDataError as exc:
            detail = str(exc)
            if any(marker in detail for marker in (
                "Not enough CLOSED", "Not enough valid CLOSED", "Not enough fully closed"
            )):
                skipped += 1
                print(f"[SKIP] {symbol} | insufficient closed history for current indicators: {detail}")
            else:
                failures += 1
                print(f"[ERROR] {symbol} | {type(exc).__name__}: {exc}")
        except (ValueError, TypeError, KeyError) as exc:
            failures += 1
            print(f"[ERROR] {symbol} | {type(exc).__name__}: {exc}")
        except Exception as exc:  # keep checking other symbols if one provider fails
            failures += 1
            print(f"[ERROR] {symbol} | unexpected {type(exc).__name__}: {exc}")
        if index + 1 < len(symbols):
            await asyncio.sleep(0.1)

    print("-" * 72)
    print(
        f"Finished: {len(symbols) - failures - skipped} successful scan(s), "
        f"{skipped} insufficient-history skip(s), {failures} provider/error failure(s)."
    )
    print(
        "Coverage note: this is a rotating read-only smoke subset, not a claim that "
        "every Binance pair was scanned in this run."
    )
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only QUANTNEX signal/provider smoke test.")
    parser.add_argument(
        "--symbols",
        default=None,
        help="Optional explicit comma-separated supported markets; omit to use the rotating live Spot universe.",
    )
    parser.add_argument(
        "--universe-sample-size",
        type=int,
        default=20,
        help="Number of dynamically discovered Binance Spot pairs to scan when --symbols is omitted.",
    )
    parser.add_argument(
        "--sample-day",
        type=int,
        default=None,
        help="Optional deterministic non-negative day index for repeatable sample selection.",
    )
    parser.add_argument("--min-score", type=int, default=8, help="Signal threshold, clamped to 8–10.")
    args = parser.parse_args()

    symbols = None if args.symbols is None else [
        part.strip().upper() for part in args.symbols.split(",") if part.strip()
    ]
    if symbols is not None and not symbols:
        print("Invalid or empty symbol list.", file=sys.stderr)
        return 2
    return asyncio.run(_run(
        symbols, args.min_score,
        universe_sample_size=args.universe_sample_size,
        sample_day=args.sample_day,
    ))


if __name__ == "__main__":
    raise SystemExit(main())
