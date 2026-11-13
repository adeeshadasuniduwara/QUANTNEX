# QUANTNEX Gold Feed Integration Architecture

## Current state

QUANTNEX VIEW currently retrieves crypto OHLC candles from Binance Spot and XAUUSD candles from Twelve Data when a local `TWELVE_DATA_API_KEY` is configured. The current chart refresh is polling-based; it is not a tick-level institutional feed.

The existing Gold-API integration in `backend/app/market_data.py` is a keyless indicative XAU/USD spot-price source. It does not provide the historical OHLC candle contract required by the chart analysis engine, so it must not be silently substituted for candle data.

## QVeris clarification

The supplied QVeris instruction connects QVeris to ChatGPT through a hosted MCP authorization flow. That authorizes the ChatGPT host to call QVeris tools; it does **not** by itself provide QUANTNEX's local Python backend with a documented REST/WebSocket OHLC endpoint, credentials, or a data entitlement.

Therefore this phase does not claim that QVeris is connected, does not copy OAuth credentials into QUANTNEX, and does not scrape or proxy ChatGPT's MCP session. A QVeris feed adapter can be implemented only after QVeris documents a backend-compatible API, authentication method, supported symbols/timeframes, rate limits, and licensing.

## Provider adapter contract

A production Gold candle provider must normalize every response to this internal candle shape:

- `time`: UTC ISO-8601 timestamp for the candle open time
- `open`, `high`, `low`, `close`: finite positive numeric prices
- `volume`: optional numeric value; null/zero when the provider does not publish volume

The provider adapter must:
1. Validate symbol and timeframe against an explicit allow-list.
2. Normalize all timestamps to UTC and sort ascending.
3. Reject duplicate timestamps, malformed OHLC, non-positive prices, and impossible high/low ranges.
4. Report provider name, source timestamp, fetch timestamp, and stale-data status.
5. Enforce timeouts, bounded retries, cache limits, and provider rate limits.
6. Keep API keys on the local backend in the user's local secret configuration; never return them to the browser or Telegram.
7. Never treat indicative spot prices as executable quotes or route them to broker order execution.

## Planned provider order

1. **Local MT5 demo/market-data bridge** — preferred for broker-specific XAUUSD candles and quote conventions, with read-only data permission by default.
2. **Twelve Data** — existing configured OHLC provider.
3. **QVeris** — optional future adapter only after a documented server-side API and explicit user authorization are available.

The provider interface should remain separate from strategy logic. All providers feed the same normalized OHLC validator before RSI, MACD, ADX, structure, or signal calculations run.

## Security and execution boundaries

- QUANTNEX remains local-only and login-free.
- No QVeris OAuth token or API key is committed to Git.
- No provider can place a broker order.
- Live execution remains disabled unless a separate, explicit authorization flow is designed and approved.
- Provider failures must show a clear stale/unavailable status; they must never silently fall back to a different symbol or fabricate candles.

## Acceptance criteria for a future QVeris adapter

- Official API documentation and endpoint are available.
- The user's QVeris plan includes the requested market data.
- Authentication can be performed from the local backend without reusing ChatGPT-host OAuth session tokens.
- XAUUSD OHLC coverage exists for the required timeframes and sufficient history.
- Unit tests cover authentication failure, rate limiting, malformed data, stale timestamps, and provider outage.
- A live smoke test confirms symbol mapping, timezone, candle boundaries, and source timestamp.
