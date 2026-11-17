# Binance Public Market-Data Failover

## Purpose

Keep Binance Spot signal generation from depending on a single REST hostname while preserving strict data provenance and fail-closed behavior.

## Official public hosts

The client prefers the dedicated unauthenticated public-market-data host, then uses the official Spot REST alternatives:

1. `https://data-api.binance.vision`
2. `https://api.binance.com`
3. `https://api-gcp.binance.com`
4. `https://api1.binance.com`
5. `https://api2.binance.com`
6. `https://api3.binance.com`
7. `https://api4.binance.com`

Binance documents the alternative REST base URLs and recommends the market-data-only host for public market data. It also notes that api1–api4 can be less stable. See the [Spot REST API documentation](https://developers.binance.com/en/docs/products/spot/rest-api) and [Market Data Only URLs](https://developers.binance.me/en/docs/products/spot/faqs/market_data_only).

## Retry policy

- Try the next official host for connection/timeout failures, invalid JSON, server errors and host-level access/geo responses (403/451).
- Stop on HTTP 418 or 429. Preserve `Retry-After`; do not fan out across hosts after an IP ban or rate limit.
- Stop on ordinary client errors such as HTTP 400 invalid symbol; another hostname cannot repair invalid request parameters.
- Cap each host attempt at 3.5 seconds (1.5-second connect timeout) and limit concurrent requests to four per event loop, bounding worst-case failover latency.
- Restrict the helper to HTTPS origins and public `/api/v3` paths. No signed/private endpoints, API keys or trading routes are allowed.
- Return the successful base URL so execution and order-flow payloads can record data provenance.
- Remember the last successful host per event loop and try it first on the next request, avoiding repeated timeouts when one documented host is unavailable.

## Integrated routes

- `/api/v3/exchangeInfo` — dynamic Spot universe and exchange filters.
- `/api/v3/ticker/bookTicker` and `/api/v3/depth` — execution context.
- `/api/v3/klines` — live candles and historical candle replay.
- `/api/v3/aggTrades` — recent trade delta and UTC session-start probe.

## Limitations

Failover improves host availability but cannot bypass an account/IP restriction, an exchange-wide outage or an IP-wide rate limit. The client stops on 418/429 and does not retry with stale cached metadata. The next scheduled live smoke run must verify that the GitHub Actions runner can reach the public market-data host. Binance USDⓈ-M/COIN-M Futures remain outside this Spot client.
