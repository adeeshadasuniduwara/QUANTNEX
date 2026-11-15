"""Read-only smoke test for live QUANTNEX signal data providers.

Run from the backend directory after activating the project's Python environment:
    python smoke_signal_engine.py
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from app.signal_engine import CRYPTO_SYMBOLS, MarketDataError, build_signal


DEFAULT_SETTINGS = {
    "primary": "5",
    "trend": "60",
    "enabled": ["60", "30", "15", "5", "1"],
    "risk_percent": 1,
    "min_score": 8,
}


def _format_price(symbol: str, value: float) -> str:
    return f"{float(value):.{2 if symbol == 'XAUUSD' else 8}f}"


async def _run(symbols: list[str], min_score: int) -> int:
    settings = {**DEFAULT_SETTINGS, "min_score": max(8, min(10, min_score))}
    failures = 0
    print("QUANTNEX read-only signal smoke test")
    print("No Telegram messages are sent and no broker orders are placed.")
    print("-" * 72)

    for symbol in symbols:
        try:
            result = await build_signal(settings, symbol)
            provider = result.get("provider", "Unknown")
            signal = result.get("signal")
            if not signal:
                print(
                    f"[WAIT] {symbol} | source={provider} | "
                    f"confluence={result.get('confluence_score', 0)}/10"
                )
                continue

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
        except (MarketDataError, ValueError, TypeError, KeyError) as exc:
            failures += 1
            print(f"[ERROR] {symbol} | {type(exc).__name__}: {exc}")
        except Exception as exc:  # keep checking other symbols if one provider fails
            failures += 1
            print(f"[ERROR] {symbol} | unexpected {type(exc).__name__}: {exc}")

    print("-" * 72)
    print(f"Finished: {len(symbols) - failures} successful scan(s), {failures} provider/error failure(s).")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only QUANTNEX signal/provider smoke test.")
    parser.add_argument(
        "--symbols",
        default="BTCUSDT,ETHUSDT,SOLUSDT,XAUUSD",
        help="Comma-separated supported markets (default: BTCUSDT,ETHUSDT,SOLUSDT,XAUUSD).",
    )
    parser.add_argument("--min-score", type=int, default=8, help="Signal threshold, clamped to 8–10.")
    args = parser.parse_args()

    symbols = list(dict.fromkeys(part.strip().upper() for part in args.symbols.split(",") if part.strip()))
    allowed = set(CRYPTO_SYMBOLS) | {"XAUUSD"}
    invalid = [symbol for symbol in symbols if symbol not in allowed]
    if not symbols or invalid:
        print("Invalid or empty symbol list. Supported markets: " + ", ".join(sorted(allowed)), file=sys.stderr)
        return 2
    return asyncio.run(_run(symbols, args.min_score))


if __name__ == "__main__":
    raise SystemExit(main())
