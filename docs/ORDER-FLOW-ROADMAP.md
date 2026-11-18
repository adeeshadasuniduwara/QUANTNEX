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

A scheduled live smoke run failed at Binance Spot `exchangeInfo` discovery before any pair was scanned. The implementation adds a shared public-only REST helper that prefers `data-api.binance.vision`, then falls back to official Binance REST hosts. It retries transport/invalid-JSON/server/408/425 failures, but stops on 403/451 WAF or geo restrictions, 418/429 rate limits and ordinary client validation errors. The helper is restricted to HTTPS origins and public `/api/v3` routes, caps each host attempt at 3.5 seconds (1.5-second connect timeout), limits concurrency per event loop, and records the successful source host and remembers the last successful host per event loop. It is wired into symbol discovery, execution context, candle/history requests and order-flow REST reads. Mocked host-failover tests passed on PR #188 head `e2114a0076875646707188f8d6c5882030e7f4df`: 314 backend tests on Python 3.12 and 3.14 plus Web checks. PR #188 is mergeable; the next scheduled smoke run must still verify actual GitHub-runner reachability.

## Phase B3 — continuous ingestion (next)

Use Binance's public market-data WebSocket host `data-stream.binance.vision` for Spot AggTrade and diff-depth streams; User Data Streams are not available on that host. Bridge each depth stream to a REST snapshot and invalidate/resync on any update-ID gap. Plan for 24-hour connection expiry/serverShutdown, 20-second ping frames (reply with pong within 60 seconds), a 1,024-stream connection cap, five incoming messages per second, and 300 connection attempts per five minutes. Use combined streams and bounded/on-demand subscriptions rather than blindly subscribing every eligible pair.

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


## Capability matrix (verified current state)

| Capability | Binance Spot | USDⓈ-M Futures | COIN-M Futures | XAUUSD feed |
|---|---|---|---|---|
| Dynamic symbol/instrument metadata | Yes: `/api/v3/exchangeInfo`, active Spot permission/status, orderTypes, asset precision and full symbol filters | Not wired | Not wired | MT5/Twelve Data configuration, not Binance metadata |
| OHLCV signal candles | Yes; public klines with closed-candle freshness checks | Not wired | Not wired | MT5 or Twelve Data |
| Adaptive MARKET/LIMIT decision | Yes; analytical choice only, with spread/depth/ATR/zone gates plus orderTypes and validated exchange filters; quantity still not calculated | Not wired | Not wired | Reference price only; Binance execution not applicable |
| Aggressor-side trade delta | Yes; recent `aggTrades`, buyer-is-maker semantics | Not wired | Not wired | Not available from current Gold candle/quote adapters |
| UTC session delta | Only when the current response begins at the UTC session's first aggregate-trade ID and every subsequent ID is contiguous; otherwise unavailable/sample only | Not wired | Not wired | Not available |
| Persistent CVD | Deterministic state machine exists; not wired to live WebSocket or persistence | Not wired | Not wired | Not available |
| Footprint buckets / imbalance | Recent-window price buckets from observed aggTrades | Not wired | Not wired | Not available |
| Order-book depth | Live REST L2 snapshot; sequence-validated diff state machine exists but is not connected to live stream | Not wired | Not wired | Not available |
| Funding / open interest / liquidations | Not applicable to Spot | Not wired | Not wired | Not available |
| Historical trade/depth replay | Not yet; current walk-forward uses candles and assumed execution costs | Not wired | Not wired | Not available |
| Exchange order constraints | PRICE_FILTER, LOT_SIZE, MARKET_LOT_SIZE (including disabled sub-rules), NOTIONAL/MIN_NOTIONAL and orderTypes preserved; quantity itself is not validated because no size is emitted | Not wired | Not wired | Not applicable |

The current supported crypto signal market is Binance Spot only. A Spot SELL is not a Futures short. The current order-flow feed does not claim true consolidated quoted bid/ask volume: it infers aggressor side from Binance aggregate trades. The REST depth response's local receive timestamp is not an exchange event timestamp and does not replace a WebSocket sequence bridge. The live gate rejects snapshots whose local receive age exceeds five seconds, but this is not a substitute for exchange-event sequencing.

## Phase C0 — order-flow-aware live signal gate (merged PR #189)

Branch: `feat/orderflow-aware-signal-gate`. PR [#189](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/189) merged to `main` as `c94aa41e72121500656aac584ad8b4406b887ad6`. PR and post-merge Backend CI passed 319 tests on Python 3.12 and 319 tests on Python 3.14; schema/test and web-check jobs passed. The optional Telegram announce workflow failed because the configured chat target is invalid/self-directed; it does not affect signal code or CI tests.

- Add a deterministic order-flow evaluator that uses two non-duplicated observations: recent aggressor `delta_ratio` and L2 quote-notional depth imbalance. Microprice is included in the report but is not counted as a third independent vote because it is derived from top-of-book quantities.
- A live Binance Spot candidate is eligible only when order-flow data is present, provenance confirms no candle-volume substitution, trade data is fresh, the L2 snapshot's local receive age is at most five seconds, and directional support count exceeds conflict count with at least one supporting observation.
- CONTRADICTED, MIXED, NEUTRAL, malformed, stale or unavailable order-flow data produces WAIT; no threshold is relaxed to manufacture signals.
- Include compact per-signal evidence: trade count/age, buy/sell volumes, delta and delta ratio, window-delta scope, UTC session-delta value/coverage, explicit persistent-CVD unavailable status, L2 spread/depth imbalance/microprice, footprint bucket summary, source hosts and depth snapshot continuity state.
- Historical candle-only walk-forward remains a baseline and explicitly reports order flow unavailable. Deterministic fixtures can inject order-flow snapshots to prove long/short pipeline behavior, but they are not historical-market performance evidence.
- This gate is a transparent sign-confluence rule, not a calibrated probability or proven win-rate improvement. Its incremental value must be measured later against candle-only baseline and ablation variants.

## Phase C1 — deterministic Spot order-flow stream state (merged PR #191)

PR [#191](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/191) merged to `main` as `1f953140f18af5555abf4ed7d008789824a96bd2`. PR and post-merge CI passed 332 tests on Python 3.12 and 332 tests on Python 3.14; schema/test and web-check jobs passed. The optional Telegram announce workflow failed due the invalid/self-directed chat target, unrelated to application code.

Implemented in `backend/app/binance_order_flow_state.py`:
- `AggTradeCvdState`: UTC-session seed, Decimal aggressor delta and quote delta, duplicate/out-of-order handling, aggregate-trade ID gap invalidation, paged backfill recovery, and explicit CVD/session completeness.
- UTC rollover preserves CVD's `SINCE_STATE_SEED` scope but marks the new session delta incomplete. Backfill spanning midnight cannot incorrectly restore new-session completeness.
- `BinanceSpotDepthBook`: REST snapshot loading, buffered diff bridge, zero-quantity deletion, update-ID gap detection, crossed/locked-book rejection, and clearing levels on invalidation.
- Thirteen deterministic tests cover hand-computed delta/CVD, duplicates, ID gaps, partial/full backfill, UTC rollover, depth snapshot bridge, deletes, sequence gaps, resync and malformed/crossed books.

Limitations: these are pure state machines only. No WebSocket client, reconnect/backoff, REST backfill network loop, persistent storage or live signal integration is included. The live signal gate remains REST-snapshot based; do not describe persistent CVD or continuous sequence-validated L2 as live-enabled yet.

## Phase C2 — read-only WebSocket adapter and live state integration (next)

- Add an explicit WebSocket dependency and bounded per-symbol subscription manager using Binance public Spot streams; do not subscribe to every eligible symbol at once.
- On reconnect, REST-backfill aggTrades from the last contiguous ID and keep CVD/session state incomplete until every missing ID is recovered.
- Buffer depth diffs while obtaining a REST snapshot, bridge the first valid event, and invalidate/resync on every update-ID gap.
- Add bounded queues, stream/request limits, exponential backoff with jitter, cancellation and shutdown tests.
- Feed validated state into signal eligibility and distinguish live-complete, incomplete, gap and REST-snapshot-only data states.
- Capture synchronized historical trade/depth replay before measuring order-flow incremental value against the candle-only baseline.


## Live Binance public-data verification — 2026-11-17 08:39 UTC

A read-only Binance connector check succeeded independently of GitHub Actions:
- Spot exchangeInfo returned 3,703 symbols. Applying status == TRADING, isSpotTradingAllowed == true and Spot permission-set eligibility yielded 1,373 active Spot pairs; 2,330 returned symbols were in BREAK status.
- All 1,373 eligible pairs contained PRICE_FILTER, LOT_SIZE, MARKET_LOT_SIZE and NOTIONAL; none required the legacy MIN_NOTIONAL filter because NOTIONAL was present.
- BTCUSDT returned recent Spot aggregate trades, a 20-level L2 REST snapshot and five 1-minute candles. This verifies current public endpoint access and sample payloads, not a full 1,373-pair scan or a live signal.

### Execution-filter correction — implemented on branch `fix/binance-spot-exchange-order-filters`

The exchange-filter gap identified above is now addressed in this PR:

- Dynamic symbol metadata retains `orderTypes`, base/quote precision, `quotePrecision`, `quoteOrderQtyMarketAllowed`, status/permissions and the complete symbol filter map.
- `PRICE_FILTER.tickSize` is no longer replaced with an invented 1e-8 fallback. A missing/invalid tick makes both entry types ineligible.
- LIMIT selection requires `LIMIT` in `orderTypes`, a valid `PRICE_FILTER`, `LOT_SIZE` and valid `NOTIONAL`/`MIN_NOTIONAL`.
- MARKET selection requires `MARKET` in `orderTypes`, valid `MARKET_LOT_SIZE`, the general `LOT_SIZE`, price metadata and notional metadata.
- Live BTCUSDT `exchangeInfo` was checked directly during this run. Its `MARKET_LOT_SIZE` reports `stepSize=0` and `minQty=0`, while `maxQty` is positive. The implementation records those two sub-rules as disabled and derives effective market quantity step/minimum from `LOT_SIZE`, while intersecting the maximum with `MARKET_LOT_SIZE.maxQty`. This avoids incorrectly disabling MARKET for BTCUSDT and does not invent quantity precision.
- Signals expose the raw/effective exchange constraints, order types, asset precision and whether quote-order-quantity MARKET is allowed. The payload explicitly says quantity validation was not performed because this signal engine does not yet calculate an order quantity; no actual order is placed.
- Entry selection refuses unsupported or incomplete MARKET/LIMIT paths rather than silently assuming the order type is available.

Deterministic regression tests cover order-type restrictions, zero-disabled market lot sub-rules, effective MARKET constraints, missing/zero tick rejection, and complete exchange metadata. These tests prove filter handling only; they do not make the signal payload an order ticket.

Source references: [Binance Spot filters](https://github.com/binance/binance-spot-api-docs/blob/master/filters.md) and [live BTCUSDT exchangeInfo](https://data-api.binance.vision/api/v3/exchangeInfo?symbol=BTCUSDT).

Next core phase: implement the read-only WebSocket adapter around the existing `AggTradeCvdState` and `BinanceSpotDepthBook` state machines, then feed only sequence-validated stream state into the signal gate.

## Phase C1.1 — Binance Spot order-filter-aware entry selection (PR in progress)

Branch: `fix/binance-spot-exchange-order-filters`, based on main `5876b9cda4596bad0309574019da5b1d762b9878`.

Changed files:
- `backend/app/signal_engine.py`: preserve exchangeInfo order/precision fields; parse PRICE_FILTER, LOT_SIZE, MARKET_LOT_SIZE and NOTIONAL/MIN_NOTIONAL; stop inventing tick-size fallbacks; gate MARKET/LIMIT selection against the actual orderTypes and valid symbol filters; include raw/effective constraints in signal metadata.
- `backend/tests/test_signal_engine.py`: add order-type gating, zero-disabled MARKET lot sub-rule, no-fallback tick and live-shaped exchangeInfo fixtures.
- `backend/tests/test_signal_pipeline_e2e.py`: make deterministic execution fixtures explicitly declare the exchange order/filter capabilities they assume.
- This roadmap: update verified capabilities and next step.

Validation pending: run Backend CI, Backend/Web CI, inspect the full diff and added-line secret scan, then merge only if every required check passes. Post-merge CI and the next scheduled dynamic-universe live smoke are still required.

Important boundary: a signal carries the applicable constraints but not a computed base/quote order quantity. It must not be described as an exchange-valid order ticket until position sizing is implemented and every min/max/step/notional filter is checked against the actual quantity.
