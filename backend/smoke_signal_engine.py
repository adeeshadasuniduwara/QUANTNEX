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

import httpx

from app.binance_public import get_binance_public_json
from app.binance_order_flow_manager import get_binance_spot_order_flow_manager
from app.signal_engine import (
    MarketDataError, build_signal, get_binance_spot_symbol_info, get_binance_spot_symbols,
)
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


def select_order_flow_probe_symbols(
    universe: list[str], ticker_rows: list[dict], *, limit: int = 1
) -> list[str]:
    """Choose a small live-feed health sample from current eligible USDT Spot pairs.

    Ranking uses Binance's 24-hour quoteVolume, not a hard-coded coin shortlist.
    This is a feed-health sentinel only; it does not limit the signal universe.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("Order Flow probe limit must be a positive integer.")
    if not isinstance(ticker_rows, list):
        raise ValueError("Binance 24-hour ticker response must be a list.")

    eligible = {
        str(symbol).strip().upper()
        for symbol in universe
        if isinstance(symbol, str) and str(symbol).strip()
    }
    volume_by_symbol: dict[str, float] = {}
    for row in ticker_rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        if symbol not in eligible or not symbol.endswith("USDT"):
            continue
        try:
            quote_volume = float(row.get("quoteVolume"))
        except (TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(quote_volume) or quote_volume <= 0:
            continue
        volume_by_symbol[symbol] = max(volume_by_symbol.get(symbol, 0.0), quote_volume)

    ranked = sorted(volume_by_symbol, key=lambda symbol: (-volume_by_symbol[symbol], symbol))
    return ranked[:limit]


async def _load_spot_order_flow_probe_symbols(
    universe: list[str], *, limit: int = 1
) -> list[str]:
    """Rank eligible USDT pairs by live Binance 24-hour quote volume."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=3)) as client:
        tickers, _source = await get_binance_public_json(
            client, "/api/v3/ticker/24hr"
        )
    return select_order_flow_probe_symbols(universe, tickers, limit=limit)


async def _run_spot_order_flow_probe(
    universe: list[str], *, wait_seconds: float = 8.0
) -> tuple[int, int]:
    """Independently verify live Spot aggTrade + sequence-valid L2 readiness.

    A candle WAIT does not prevent this probe. It never creates a trading signal
    and never places an order. A not-ready stream is reported as a probe failure,
    not as a signal WAIT.
    """
    if (
        isinstance(wait_seconds, bool)
        or not isinstance(wait_seconds, (int, float))
        or not math.isfinite(float(wait_seconds))
        or not 0 < float(wait_seconds) <= 30
    ):
        print("[ORDER FLOW PROBE ERROR] wait_seconds must be between 0 and 30.", file=sys.stderr)
        return 0, 1

    try:
        symbols = await _load_spot_order_flow_probe_symbols(universe, limit=1)
        if not symbols:
            raise MarketDataError(
                "No eligible USDT-quoted Spot pair with positive 24-hour quote volume was found."
            )
    except Exception as exc:
        print(
            f"[ORDER FLOW PROBE ERROR] Could not select a live Spot feed sample: "
            f"{type(exc).__name__}: {str(exc)[:180]}",
            file=sys.stderr,
        )
        return 0, 1

    manager = get_binance_spot_order_flow_manager()
    ready = 0
    failures = 0
    try:
        for symbol in symbols:
            try:
                info = await get_binance_spot_symbol_info(symbol)
                filters = info.get("filters") if isinstance(info, dict) else None
                price_filter = filters.get("PRICE_FILTER") if isinstance(filters, dict) else None
                tick_size = price_filter.get("tickSize") if isinstance(price_filter, dict) else None
                if not tick_size:
                    raise MarketDataError(f"{symbol} has no exchangeInfo PRICE_FILTER tick size.")

                result = await manager.get_snapshot(
                    symbol, str(tick_size), wait_seconds=float(wait_seconds)
                )
                flow = result.get("order_flow") if isinstance(result, dict) else None
                book = flow.get("order_book") if isinstance(flow, dict) else None
                provenance = flow.get("data_provenance") if isinstance(flow, dict) else None
                is_ready = bool(
                    isinstance(result, dict)
                    and result.get("market_type") == "BINANCE_SPOT"
                    and result.get("signal_ready") is True
                    and isinstance(flow, dict)
                    and flow.get("feed_mode") == "PUBLIC_WEBSOCKET_STREAM"
                    and flow.get("depth_is_continuous") is True
                    and isinstance(book, dict)
                    and isinstance(provenance, dict)
                    and provenance.get("candle_volume_used") is False
                )
                if is_ready:
                    fields = [
                        f"trades={_format_diagnostic_value(flow.get('trade_count')) or 'n/a'}",
                        f"delta_ratio={_format_diagnostic_value(flow.get('delta_ratio')) or 'n/a'}",
                        f"spread_bps={_format_diagnostic_value(book.get('spread_bps')) or 'n/a'}",
                        f"depth_imbalance={_format_diagnostic_value(book.get('depth_imbalance')) or 'n/a'}",
                        f"cvd={_format_diagnostic_value(flow.get('cvd_value')) or 'n/a'}",
                        f"cvd_scope={_format_diagnostic_value(flow.get('cvd_scope')) or 'n/a'}",
                    ]
                    print(f"[ORDER FLOW READY] {symbol} | " + " | ".join(fields))
                    ready += 1
                else:
                    status = _format_diagnostic_value(result.get("status")) if isinstance(result, dict) else None
                    reason = None
                    if isinstance(result, dict):
                        reason = (
                            _format_diagnostic_value(result.get("last_error"))
                            or _format_diagnostic_value(result.get("order_flow_error"))
                        )
                    print(
                        f"[ORDER FLOW NOT READY] {symbol} | status={status or 'UNKNOWN'}"
                        + (f" | reason={reason}" if reason else "")
                    )
                    failures += 1
            except Exception as exc:
                print(
                    f"[ORDER FLOW PROBE ERROR] {symbol} | {type(exc).__name__}: {str(exc)[:180]}",
                    file=sys.stderr,
                )
                failures += 1
    finally:
        try:
            await manager.stop()
        except Exception as exc:
            print(
                f"[ORDER FLOW PROBE CLEANUP ERROR] {type(exc).__name__}: {str(exc)[:160]}",
                file=sys.stderr,
            )
            failures += 1

    print(
        f"Spot Order Flow probe complete: {ready} ready, {failures} not-ready/error."
    )
    return ready, failures


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
    include_order_flow_probe: bool = False,
    order_flow_probe_wait_seconds: float = 8.0,
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


    order_flow_ready = 0
    order_flow_failures = 0
    if include_order_flow_probe and spot_universe:
        order_flow_ready, order_flow_failures = await _run_spot_order_flow_probe(
            spot_universe, wait_seconds=order_flow_probe_wait_seconds
        )


    usdm_successful = 0
    usdm_skipped = 0
    usdm_failures = 0
    if include_usdm:
        usdm_successful, usdm_skipped, usdm_failures = await _run_usdm(
            universe_sample_size=usdm_universe_sample_size,
            min_score=settings["min_score"],
            sample_day=sample_day,
        )

    total_failures = spot_failures + usdm_failures + order_flow_failures
    total_skipped = spot_skipped + usdm_skipped
    print("-" * 72)
    print(
        f"Finished: {spot_successful} successful Spot scan(s), "
        f"{usdm_successful} successful USDⓈ-M scan(s), "
        f"{order_flow_ready} ready Spot Order Flow probe(s), "
        f"{order_flow_failures} Order Flow probe failure(s), "
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
        "--skip-order-flow-probe",
        action="store_true",
        help="Skip the independent live Spot aggTrade and sequence-validated depth health probe.",
    )
    parser.add_argument(
        "--order-flow-probe-wait-seconds",
        type=float,
        default=8.0,
        help="Maximum time to wait for the live Spot Order Flow stream to become sequence-valid (1–30 seconds).",
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
        include_order_flow_probe=not args.skip_order_flow_probe,
        order_flow_probe_wait_seconds=args.order_flow_probe_wait_seconds,
    ))


if __name__ == "__main__":
    raise SystemExit(main())
