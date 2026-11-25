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
from app.binance_usdm_market_data import BinanceUsdMDataError, get_binance_usdm_symbols
from app.binance_usdm_signal_engine import BinanceUsdMSignalError, analyze_usdm_futures_signal


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
        "cvd_value", "cvd_status", "session_delta", "trade_data_age_seconds",
        "session_delta_coverage_complete",
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


async def _run_usdm(
    *,
    universe_sample_size: int,
    min_score: int,
    sample_day: int | None = None,
) -> tuple[int, int, int]:
    """Run a separate, read-only rotating sample of active USDⓈ-M perpetuals.

    Futures currently has a candle-only monitor engine. This smoke path must
    never imply Spot Order Flow, adaptive execution, or order placement.
    """
    try:
        universe = await get_binance_usdm_symbols()
    except BinanceUsdMDataError as exc:
        if exc.status_code == 451:
            print(
                "[FUTURES UNAVAILABLE] Binance USDⓈ-M returned HTTP 451 from this runner; "
                "the Futures universe was not scanned. This is provider access restriction, "
                "not a WAIT or a successful Futures validation. Spot checks continue independently."
            )
            return 0, 0, 0
        print(f"[ERROR] Binance USDⓈ-M symbol discovery failed: {exc}", file=sys.stderr)
        return 0, 0, 1

    if not universe:
        print("No eligible Binance USDⓈ-M perpetual contracts were returned by exchangeInfo.", file=sys.stderr)
        return 0, 0, 1

    try:
        symbols = rotating_symbol_sample(
            universe, universe_sample_size, day_index=sample_day
        )
    except ValueError as exc:
        print(f"[ERROR] Invalid USDⓈ-M smoke sample: {exc}", file=sys.stderr)
        return 0, 0, 1

    day_label = sample_day if sample_day is not None else datetime.now(timezone.utc).date().toordinal()
    print()
    print("QUANTNEX Binance USDⓈ-M Futures read-only candle smoke test")
    print(f"Eligible TRADING PERPETUAL contracts from exchangeInfo: {len(universe)}")
    print(f"Rotating USDⓈ-M smoke sample: {len(symbols)} contracts (sample day={day_label})")
    print("Futures scope: closed 5m candles only; no Futures Order Flow, no adaptive execution and no orders.")

    successful = 0
    skipped = 0
    failures = 0
    provider_unavailable = False
    for index, symbol in enumerate(symbols):
        try:
            result = await analyze_usdm_futures_signal(
                symbol, "5m", min_score=max(6, min(10, int(min_score)))
            )
            signal = result.get("signal")
            if result.get("status") == "SIGNAL" and isinstance(signal, dict):
                print(
                    f"[FUTURES CANDLE SIGNAL] {symbol}.P {signal.get('side', 'UNKNOWN')} | "
                    f"score={_format_diagnostic_value(signal.get('score')) or _format_diagnostic_value(result.get('confluence_score')) or 'n/a'}"
                )
                levels = []
                for label, key in (("reference", "entry"), ("SL", "stop_loss"), ("TP1", "tp1")):
                    value = _format_diagnostic_value(signal.get(key))
                    if value is not None:
                        levels.append(f"{label}={value}")
                if levels:
                    print("  " + " | ".join(levels))
            else:
                reason = _format_diagnostic_value(result.get("message")) or "No qualifying closed-candle setup."
                print(
                    f"[FUTURES WAIT] {symbol}.P | "
                    f"confluence={_format_diagnostic_value(result.get('confluence_score')) or 'n/a'} | {reason}"
                )
            print("  Execution: DISABLED | Order Flow: NOT AVAILABLE | Market type: BINANCE_USDM_FUTURES")
            successful += 1
        except BinanceUsdMSignalError as exc:
            if exc.status_code == 451:
                provider_unavailable = True
                print(
                    "[FUTURES UNAVAILABLE] Binance USDⓈ-M returned HTTP 451 during candle retrieval; "
                    f"stopping the Futures sample after {successful} completed scan(s). "
                    "This is provider access restriction, not a WAIT."
                )
                break
            detail = str(exc)
            if any(marker in detail for marker in (
                "At least 210 fully closed", "No closed valid", "insufficient closed"
            )):
                skipped += 1
                print(f"[FUTURES SKIP] {symbol}.P | insufficient closed history: {detail}")
            else:
                failures += 1
                print(f"[FUTURES ERROR] {symbol}.P | {type(exc).__name__}: {exc}")
        except (ValueError, TypeError, KeyError) as exc:
            failures += 1
            print(f"[FUTURES ERROR] {symbol}.P | {type(exc).__name__}: {exc}")
        except Exception as exc:  # continue checking the remaining dynamic universe sample
            failures += 1
            print(f"[FUTURES ERROR] {symbol}.P | unexpected {type(exc).__name__}: {exc}")
        if index + 1 < len(symbols):
            await asyncio.sleep(0.1)

    print(
        f"USDⓈ-M sample complete: {successful} successful scan(s), "
        f"{skipped} insufficient-history skip(s), {failures} provider/error failure(s)."
    )
    if provider_unavailable:
        print("USDⓈ-M coverage is incomplete because the public provider returned HTTP 451.")
    return successful, skipped, failures


async def _run(
    symbols: list[str] | None,
    min_score: int,
    *,
    universe_sample_size: int = 20,
    sample_day: int | None = None,
    include_usdm: bool = False,
    usdm_universe_sample_size: int = 20,
) -> int:
    settings = {**DEFAULT_SETTINGS, "min_score": max(8, min(10, min_score))}
    spot_successful = 0
    spot_skipped = 0
    spot_failures = 0
    config_error = False
    spot_universe: list[str] = []

    try:
        spot_universe = await get_binance_spot_symbols()
        if not spot_universe:
            raise MarketDataError("No eligible Binance Spot pairs were returned by exchangeInfo.")
    except MarketDataError as exc:
        # Keep the independent Futures monitor running when only Spot metadata
        # is unavailable. The Spot failure still makes the overall run fail.
        spot_failures += 1
        print(f"[ERROR] Binance Spot symbol discovery failed: {exc}", file=sys.stderr)

    spot_symbols: list[str] = []
    if spot_universe:
        if symbols is None:
            try:
                spot_symbols = rotating_symbol_sample(
                    spot_universe, universe_sample_size, day_index=sample_day
                )
                print(f"Eligible Binance Spot pairs from exchangeInfo: {len(spot_universe)}")
                print(
                    f"Rotating smoke sample: {len(spot_symbols)} pairs "
                    f"(sample day={sample_day if sample_day is not None else datetime.now(timezone.utc).date().toordinal()})"
                )
            except ValueError as exc:
                config_error = True
                spot_failures += 1
                print(f"[ERROR] Invalid Spot smoke sample: {exc}", file=sys.stderr)
        else:
            spot_symbols = list(dict.fromkeys(
                str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()
            ))
            if not spot_symbols:
                config_error = True
                spot_failures += 1
                print("Invalid or empty Spot symbol list.", file=sys.stderr)
            else:
                allowed = set(spot_universe) | {"XAUUSD"}
                invalid = [symbol for symbol in spot_symbols if symbol not in allowed]
                if invalid:
                    config_error = True
                    spot_failures += 1
                    print(
                        "Unsupported/non-tradable Spot or Gold symbol(s): " + ", ".join(invalid),
                        file=sys.stderr,
                    )
                    spot_symbols = []

    print("QUANTNEX read-only signal smoke test")
    print("No Telegram messages are sent and no broker orders are placed.")
    print("-" * 72)

    for index, symbol in enumerate(spot_symbols):
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
            spot_successful += 1
        except MarketDataError as exc:
            detail = str(exc)
            if any(marker in detail for marker in (
                "Not enough CLOSED", "Not enough valid CLOSED", "Not enough fully closed"
            )):
                spot_skipped += 1
                print(f"[SKIP] {symbol} | insufficient closed history for current indicators: {detail}")
            else:
                spot_failures += 1
                print(f"[ERROR] {symbol} | {type(exc).__name__}: {exc}")
        except (ValueError, TypeError, KeyError) as exc:
            spot_failures += 1
            print(f"[ERROR] {symbol} | {type(exc).__name__}: {exc}")
        except Exception as exc:  # keep checking other symbols if one provider fails
            spot_failures += 1
            print(f"[ERROR] {symbol} | unexpected {type(exc).__name__}: {exc}")
        if index + 1 < len(spot_symbols):
            await asyncio.sleep(0.1)

    usdm_successful = 0
    usdm_skipped = 0
    usdm_failures = 0
    if include_usdm:
        usdm_successful, usdm_skipped, usdm_failures = await _run_usdm(
            universe_sample_size=usdm_universe_sample_size,
            min_score=settings["min_score"],
            sample_day=sample_day,
        )

    total_failures = spot_failures + usdm_failures
    total_skipped = spot_skipped + usdm_skipped
    print("-" * 72)
    print(
        f"Finished: {spot_successful} successful Spot scan(s), "
        f"{usdm_successful} successful USDⓈ-M scan(s), "
        f"{total_skipped} insufficient-history skip(s), {total_failures} provider/error failure(s)."
    )
    print(
        "Coverage note: Spot and USDⓈ-M each use independent rotating smoke subsets. "
        "Neither sample means every eligible contract was scanned in this run."
    )
    if config_error:
        return 2
    return 1 if total_failures else 0


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
    parser.add_argument(
        "--usdm-universe-sample-size",
        type=int,
        default=20,
        help="Number of dynamically discovered active USDⓈ-M perpetuals to scan in candle-only monitor mode.",
    )
    parser.add_argument(
        "--skip-usdm",
        action="store_true",
        help="Skip the separate USDⓈ-M Futures candle-only smoke sample.",
    )
    parser.add_argument("--min-score", type=int, default=8, help="Spot threshold, clamped to 8–10; also bounded for Futures.")
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
        include_usdm=not args.skip_usdm,
        usdm_universe_sample_size=args.usdm_universe_sample_size,
    ))


if __name__ == "__main__":
    raise SystemExit(main())
