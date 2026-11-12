# QUANTNEX Phase 10 — Market Data Reliability Engine

## Purpose
Validate source timestamps, quote values and OHLCV candle integrity before market data is treated as suitable for paper execution.

## Included controls
- Provider-origin timestamp parsing and age checks (crypto: 180 seconds; Gold/Forex: 1800 seconds).
- Quote validation for missing/future timestamps and invalid prices.
- Candle checks for missing/duplicate/out-of-order timestamps, invalid OHLC/volume values, stale series and large interval gaps.
- Unified HEALTHY / DEGRADED / UNSAFE health result.
- Execution gate integrated with paper-entry routes: unsafe quote data blocks new paper positions.
- Dashboard market-by-market reliability scan and last-check status.

## Important assumptions
Provider timestamp availability differs by API. If the source does not return a timestamp, QUANTNEX marks the quote unsafe rather than substituting local receipt time. This may conservatively block a provider until it exposes a verifiable source time.
Candle gaps are warnings because FX market closures and provider omissions can be legitimate; malformed, stale, duplicate or non-monotonic candles are unsafe.
This phase validates data quality; it does not guarantee exchange uptime, broker execution prices or profitability. Existing open positions are not forcibly closed by a data warning; only new paper entries are blocked. No broker/live order routing is added.

## Local-only boundary
All checks run in the local QUANTNEX API. No login, remote data relay, new credential store or public listener is introduced.
