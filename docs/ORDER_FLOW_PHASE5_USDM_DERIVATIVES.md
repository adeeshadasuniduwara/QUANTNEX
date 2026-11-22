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

## Remaining Phase 5

1. Futures mark-price WebSocket event capture and persistence.
2. Force-order/liquidation WebSocket adapter with side, observed quantity and price context.
3. Liquidation flow aggregation with explicit sampled/partial coverage.
4. Persist funding and OI snapshots with bounded retention and idempotency.
5. Futures-only replay fixtures for funding/OI/mark/liquidation context.
6. UI panels for funding countdown, basis, OI change and liquidation observations.
7. Validate rate limits, endpoint availability and freshness under reconnect/load tests.

## Integrity requirements

- Use USDⓈ-M Futures endpoints and schemas only; never borrow Spot data.
- Funding and open interest are context, not standalone buy/sell instructions.
- Liquidation stream events are observed public force-order messages, not the full set of all leveraged liquidations across venues.
- No participant identity, hidden order intent, guaranteed liquidation total, or profitability claim.
- No order execution, account credentials or signed endpoints.
