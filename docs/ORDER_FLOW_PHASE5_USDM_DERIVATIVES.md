# QUANTNEX Order Flow — Phase 5: USDⓈ-M Derivatives Context

## Started in this PR

- Read-only Binance USDⓈ-M premium-index adapter for mark price, index price, funding rate and next funding timestamp.
- Read-only current open-interest adapter.
- Bounded open-interest history adapter with supported interval and 1–30 point limits.
- Derived mark/index basis and percentage, plus first-to-last open-interest change percentage.
- Explicit endpoint provenance, timestamps, observed-data coverage and non-execution disclaimer.
- API: `GET /api/v1/order-flow/futures/{symbol}/derivatives`.
- Advanced Footprint UI panel shows funding rate, mark/index basis, current open interest and bounded OI change when USDⓈ-M Futures is selected.
- Deterministic tests for valid calculations, invalid symbol/interval/limit, symbol mismatch and non-finite price data.

## Phase 5.1 — mark-price and liquidation event capture (this PR)

- Subscribe each bounded USDⓈ-M symbol stream to its own `@markPrice@1s` and `@forceOrder` channels alongside aggTrade and diff-depth.
- Validate symbol, event type, exchange/receive timestamps, finite mark/index/funding values, next-funding time, liquidation side, quantity and price fields before accepting events.
- Persist mark-price and force-order observations in the existing isolated USDⓈ-M event archive with deterministic event keys, idempotency and seven-day retention.
- Expose the latest mark-price sample and observed 60-second force-order side quantities through the existing read-only Futures snapshot.
- Label liquidation observations as sampled public force-order messages, not total market liquidations. No order placement or account data is used.

## Remaining Phase 5

1. Persist funding and open-interest snapshots with bounded retention and idempotency (current REST values are fetched on demand).
2. Futures-only replay fixtures for funding/OI/mark/liquidation context.
3. Dedicated UI panels for funding countdown, basis, OI change and observed liquidation flow.
4. Validate rate limits, endpoint availability and freshness under reconnect/load tests.

## Integrity requirements

- Use USDⓈ-M Futures endpoints and schemas only; never borrow Spot data.
- Funding and open interest are context, not standalone buy/sell instructions.
- Liquidation stream events are observed public force-order messages, not the full set of all leveraged liquidations across venues.
- No participant identity, hidden order intent, guaranteed liquidation total, or profitability claim.
- No order execution, account credentials or signed endpoints.
