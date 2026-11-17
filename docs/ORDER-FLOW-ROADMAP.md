# QUANTNEX Advanced Order-Flow Roadmap

## Current verified boundary

- The signal engine supports Binance Spot pair discovery from `exchangeInfo`, candle-based multi-timeframe confluence, confirmed market-structure/SMC zones, fresh best-bid/ask and REST depth, adaptive MARKET/LIMIT selection, exchange tick rounding, estimated spread/fee/slippage gates, and chronological Binance Spot candle replay.
- Binance USDⓈ-M Futures and COIN-M Futures are **not verified as supported signal markets**. A Binance Spot SELL is an analytical Spot sell signal, not a Futures short.
- Historical order-book depth, historical aggressor-side footprint and historical CVD are not currently available to the walk-forward engine.
- A successful smoke scan or WAIT result does not establish profitability. Signal quality remains unproven until realistic out-of-sample and paper evidence is accumulated.

Order-flow is measured evidence, not a promise of higher win rate. All calculations must be causal, time-stamped, source-attributed and fail closed when data is malformed, incomplete or stale.

## Phase A — deterministic Spot order-flow analytics (merged PR #168)

Implemented in `backend/app/order_flow.py`:

- Binance Spot aggregate-trade aggressor-side inference using buyer-is-maker semantics (`m=False` aggressive buyer; `m=True` aggressive seller).
- De-duplication by aggregate-trade ID, chronological ordering, future-time rejection and configurable latest-trade freshness.
- Base-volume delta, signed quote-volume delta and recent-response-window cumulative delta.
- Price-bucket footprint summaries and configurable buy/sell imbalance ratio.
- Validated L2 snapshot metrics: best bid/ask, spread bps, depth imbalance, microprice and displacement.
- Explicit provenance: aggressor-side inferred trade delta is not consolidated quoted bid/ask volume; OHLCV candle volume is never used as a substitute.

PR [#168](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/168) merged to main after Python 3.12, Python 3.14, backend and web checks passed.

## Phase B1 — read-only REST collector (merged PR #169)

Implemented in `backend/app/binance_order_flow_feed.py`:

- Fetches Binance Spot public `aggTrades` and `depth` endpoints with no API key.
- Requires the caller to supply the symbol's current exchange `PRICE_FILTER.tickSize`; does not infer tick size from candles.
- Validates symbol syntax, request limits, latest trade freshness and order-book shape.
- Preserves `lastUpdateId`, but marks the depth as an independent REST snapshot (`depth_is_continuous=false`). A snapshot update ID alone does not establish a continuous sequence.
- Includes mocked HTTP tests for observed aggressor delta, provenance, invalid symbols and stale trades.

PR [#169](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/169) merged as `6a380e4c257d48e1188aeb3557e12581cb0a4b49`. All four PR checks passed. Post-merge Backend/Web checks were subsequently blocked by eight pre-existing signal-lifecycle tests, not by this collector; those lifecycle failures were traced and fixed in PR #186.

## Phase B2 — session coverage and dynamic universe smoke rotation (merged PR #187)

Merged to `main` as `3666519818fb20ded9c1be9259c7e004e8f06dda`. PR CI passed (303 tests on Python 3.12 and 3.14 plus Web checks); post-merge CI also passed (303 tests on Python 3.12 and 3.14 plus Web checks).

### Order-flow correctness changes

- Query the first aggregate-trade ID at the current UTC session start.
- Report `session_delta` only when the recent trade response begins at that first session trade ID and contains every sequential aggregate-trade ID through the latest trade.
- If the last-1000 trade window starts mid-session or contains an ID gap, return `session_delta=null`, expose only `session_delta_sample`, and set `session_delta_coverage_complete=false`.
- Rename the short-window accumulator to `window_cumulative_delta`. Persistent CVD remains explicitly unavailable (`cvd_value=null`) until a continuous/reconnect-safe trade state exists.
- Preserve the distinction between observed aggressor-side trade flow and quoted bid/ask liquidity.

### Dynamic Spot universe smoke coverage

- Remove the legacy `CRYPTO_SYMBOLS` fast-path from `is_binance_spot_symbol`; every pair must be present in the current cached Binance Spot `exchangeInfo` universe.
- Replace the workflow's fixed BTC/ETH/SOL smoke list with a deterministic rotating sample of 20 dynamically discovered eligible Spot pairs.
- The sample rotates daily, is rate-conscious and sequential, and reports that it is only a smoke subset—not a full-universe scan.
- Explicit user-selected symbols still validate against the full dynamic universe; XAUUSD remains a separate feed path.

### Limitations

- This is not yet wired into `build_signal` as a live confluence/veto input.
- REST depth remains a one-time snapshot, not a sequence-validated local book.
- The latest 1000 aggregate trades are a bounded response window; window delta is not session delta or persistent CVD unless full session ID coverage is proven.
- No persistent cache, WebSocket reconnect/backoff, historical order-flow replay, or all-symbol continuous scanner yet.


## Phase B2.1 — public REST endpoint failover (in progress)

Branch: `fix/binance-public-data-endpoint-failover`.

A scheduled live smoke run failed at Binance Spot `exchangeInfo` discovery before any pair was scanned. The implementation adds a shared public-only REST helper that prefers `data-api.binance.vision`, then falls back to official Binance REST hosts. It retries transport/invalid-JSON/server/host-access failures, but stops on 418/429 and ordinary client validation errors. The helper is restricted to HTTPS origins and public `/api/v3` routes, caps each host attempt at 3.5 seconds (1.5-second connect timeout), limits concurrency per event loop, and records the successful source host. It is wired into symbol discovery, execution context, candle/history requests and order-flow REST reads. Mocked host-failover tests are in progress; the next scheduled smoke run must verify runner reachability.

## Phase B3 — continuous ingestion (next)

- Add bounded per-symbol rolling trade state with aggregate-trade ID tracking, deduplication, REST backfill and reconnect recovery.
- Add WebSocket depth snapshot bridging using Binance's documented update-ID sequence procedure; invalidate and resync immediately on any gap.
- Persist or safely reconstruct UTC-session delta and cumulative delta; expose explicit data-quality states for gaps, resets, reconnects and stale data.
- Respect request weights, stream connection limits, subscription limits and backpressure. Avoid a per-symbol request storm.

## Phase C — order-flow-aware entry engine

- Integrate order-flow as a separately visible evidence component, with positive, negative and unavailable states.
- Hard-veto stale trade data, invalid/crossed books, wide spreads, inadequate liquidity and sequence gaps.
- Explain window delta, full-session delta only when complete, footprint imbalance, depth imbalance, spread and microprice evidence in each eligible signal.
- Keep MARKET/LIMIT selection grounded in current execution data. Order-flow score must not override execution or risk vetoes.
- Until historical trade/order-book replay exists, keep candle-only walk-forward results clearly labeled as a baseline, not as evidence for the combined order-flow model.

## Phase D — derivatives and advanced methods

Only after Spot order-flow is stable:

- Verify USDⓈ-M and COIN-M metadata, trades, depth, funding, open interest and liquidation-feed availability independently.
- Build separate market-type adapters and tests; never mix Spot and Futures semantics.
- Add absorption/exhaustion only when synchronized trade flow and book updates support a defensible definition; label proxies explicitly.
- Add VWAP/anchored VWAP, volume profile, session profiles, supply/demand, breaker/mitigation, liquidity sweeps, Fibonacci and regime/momentum/mean-reversion/breakout methods only with causal definitions, fixtures and measurable incremental value.

## Validation and safety

- Deterministic fixtures must prove correct calculations and qualifying long/short replay signals.
- Negative fixtures must cover stale data, missing trade IDs, false sweeps, wide spreads, low liquidity, reconnects and depth sequence gaps.
- Replay must include realistic fees, spread, slippage, latency, partial/unfilled LIMIT behavior and chronological out-of-sample splits.
- Compare baseline, each method and combinations using sample size, trade count, win rate, expectancy, profit factor, max drawdown and cost sensitivity. Higher win rate alone is not success.
- Never invent data, force live signals, place real orders or enable live-money execution. Public feeds remain read-only; paper mode only.
- Binance Spot is the only currently verified crypto signal market. Futures and true historical footprint/order-book replay remain unsupported/unverified.
