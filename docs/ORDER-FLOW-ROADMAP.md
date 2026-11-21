# QUANTNEX Advanced Order-Flow Roadmap

## Current verified boundary

- The signal engine supports Binance Spot pair discovery from `exchangeInfo`, candle-based multi-timeframe confluence, confirmed market-structure/SMC zones, sequence-validated public WebSocket trade/depth streams for live Spot order-flow confirmation, adaptive MARKET/LIMIT selection, exchange filter checks, estimated spread/fee/slippage gates, and chronological Binance Spot candle replay. Telegram Auto Signals now has a full dynamic Spot-universe mode with fair rotating batches.
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


## Phase B2.1 — public REST endpoint failover (merged PR #188)

Branch: `fix/binance-public-data-endpoint-failover`.

A scheduled live smoke run failed at Binance Spot `exchangeInfo` discovery before any pair was scanned. The implementation adds a shared public-only REST helper that prefers `data-api.binance.vision`, then falls back to official Binance REST hosts. It retries transport/invalid-JSON/server/408/425 failures, but stops on 403/451 WAF or geo restrictions, 418/429 rate limits and ordinary client validation errors. The helper is restricted to HTTPS origins and public `/api/v3` routes, caps each host attempt at 3.5 seconds (1.5-second connect timeout), limits concurrency per event loop, and records the successful source host and remembers the last successful host per event loop. It is wired into symbol discovery, execution context, candle/history requests and order-flow REST reads. Mocked host-failover tests passed on PR #188 head `e2114a0076875646707188f8d6c5882030e7f4df`: 314 backend tests on Python 3.12 and 3.14 plus Web checks. PR #188 merged to main as `a8fc002b214a037fd4e1ba63e9c68223444684b1`. The latest scheduled Live Crypto Signal Smoke run observed in this audit was successful on 2026-11-17 09:12:45 UTC; it scans a rotating sample, not every eligible pair.

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
| Persistent CVD | In-memory stream-seeded CVD is available from the bounded bootstrap; scope is only since the seed, it is not persisted, and full UTC-session delta remains unavailable without an independent session anchor | Not wired | Not wired | Not available |
| Observed trade volume profile (POC/VAH/VAL) | Yes: tick-bucketed base-quantity profile over the latest bounded aggTrade input window; not full-session or historical | Not wired | Not wired | Not available |
| Footprint buckets / imbalance | Recent-window price buckets from observed aggTrades | Not wired | Not wired | Not available |
| Order-book depth | Sequence-validated Spot WebSocket stream is required by the live signal gate; on-demand manager owns at most eight active symbol streams. Auto scanner rotates across the dynamic pair universe; it does not subscribe to every pair simultaneously | Not wired | Not wired | Not available |
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
- Candidate entries are checked against enabled PRICE_FILTER min/max and tick alignment; rounded entry, SL and TP1–TP3 are checked again before a signal can be emitted. A rounded level outside exchange price bounds produces WAIT.

Deterministic regression tests cover order-type restrictions, zero-disabled market lot sub-rules, effective MARKET constraints, missing/zero tick rejection, price bounds/tick alignment, and complete exchange metadata. These tests prove filter handling only; they do not make the signal payload an order ticket.

Source references: [Binance Spot filters](https://github.com/binance/binance-spot-api-docs/blob/master/filters.md) and [live BTCUSDT exchangeInfo](https://data-api.binance.vision/api/v3/exchangeInfo?symbol=BTCUSDT).

Completed by PRs #203 and #204: the read-only WebSocket adapter now bridges those state machines, and the live Spot signal gate consumes only sequence-validated stream state.

## Phase C1.1 — Binance Spot order-filter-aware entry selection (merged PR #202)

Branch: `fix/binance-spot-exchange-order-filters`, based on main `5876b9cda4596bad0309574019da5b1d762b9878`.

Changed files:
- `backend/app/signal_engine.py`: preserve exchangeInfo order/precision fields; parse PRICE_FILTER, LOT_SIZE, MARKET_LOT_SIZE and NOTIONAL/MIN_NOTIONAL; stop inventing tick-size fallbacks; gate MARKET/LIMIT selection against the actual orderTypes and valid symbol filters; include raw/effective constraints in signal metadata.
- `backend/tests/test_signal_engine.py`: add order-type gating, zero-disabled MARKET lot sub-rule, no-fallback tick and live-shaped exchangeInfo fixtures.
- `backend/tests/test_signal_pipeline_e2e.py`: make deterministic execution fixtures explicitly declare the exchange order/filter capabilities they assume.
- This roadmap: update verified capabilities and next step.

PR [#202](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/202) merged to main as `b4fba45301e3c456e3dba741e369354650a08a8d`. PR-head Backend CI, Backend/Web CI, Python 3.12, Python 3.14 and web-check all passed. Post-merge Backend CI and Backend/Web CI both passed on main. The optional Telegram update-notification workflow failed because its configured chat target is invalid/self-directed; it is unrelated to signal code and required checks.

Important boundary: a signal carries the applicable constraints but not a computed base/quote order quantity. It must not be described as an exchange-valid order ticket until position sizing is implemented and every min/max/step/notional filter is checked against the actual quantity.


## Live Binance public sample — 2026-11-18 06:57 UTC

A separate read-only Binance connector check verified current Spot public data for BTCUSDT (not a QUANTNEX-generated signal):
- Exchange metadata: `TRADING`, Spot enabled, `LIMIT` and `MARKET` allowed, tick `0.01`, LOT_SIZE step `0.00001`, min notional `5 USDT`.
- MARKET_LOT_SIZE: `stepSize=0`, `minQty=0`, `maxQty=158.28000225`; effective market step/min therefore inherit LOT_SIZE while the market-specific max remains capped.
- 20 recent aggregate trades were returned; latest trade age was about 0.9 seconds at the sampled exchange server time. In that small window aggressive buy base volume was `0.00501 BTC`, aggressive sell volume `0.04784 BTC`, and inferred base delta `-0.04283 BTC`.
- Top-10 L2 quote-notional imbalance was about `-0.978` (ask-heavy) and best spread about `0.00155 bps`. This is a short sample and can change immediately; it is not a directional signal or a backtest result.

The daily GitHub smoke run is a separate rotating 20-pair sample from the dynamic Spot universe. Its latest observed scheduled run succeeded on 2026-11-17, but no same-day full-universe run was available in this audit. The live connector check above validates current BTCUSDT data only.


## Phase C2 — sequence-validated single-symbol Spot WebSocket adapter (merged PR #203)

Branch: `feat/binance-spot-orderflow-websocket`. PR [#203](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/203) merged to `main` on 2026-11-18 as `b88f11237ab0791b261b46139ff3f56cd201d4cd`.

Implemented in `backend/app/binance_order_flow_stream.py`:
- One read-only Binance Spot combined stream per symbol (`@aggTrade` and `@depth@100ms`); it does not open a connection for every exchangeInfo pair.
- Connect-before-seed bootstrap buffers live events while fetching recent aggregate trades and a REST depth snapshot, then bridges buffered depth events by Binance update IDs.
- Trade ID gaps trigger bounded REST `fromId` backfill; unrecoverable gaps leave CVD unavailable.
- Depth sequence gaps, crossed books, invalid messages and buffer overflow invalidate the book and force reconnect/resnapshot.
- CVD is scoped to the bounded bootstrap seed, not a full historical series. UTC session delta remains unavailable unless an independent session-start anchor proves coverage.
- Reconnect backoff/jitter, bounded recent-trade and event buffers, ping/pong, max message/queue sizes, callback isolation and graceful stop are implemented.
- Tests cover combined-stream routing, bootstrap buffering/bridge, trade-gap recovery and depth-gap invalidation.

PR-head Backend CI and Backend/Web CI passed; post-merge main Backend CI and Backend/Web CI passed on commit `b88f112` (Python 3.12, Python 3.14 and web checks). The optional Telegram update-notification workflow failed because its configured chat target is invalid/self-directed; it is not a signal-engine test.

PR #204 subsequently resolved this integration gap: FastAPI lifespan owns the bounded stream manager, and live Binance Spot `build_signal` requires sequence-validated WebSocket state. The eight-stream capacity limit still means all-pair simultaneous streaming is not supported.

## Phase C2.1 — bounded stream manager and signal-pipeline integration (merged PR #204)

Branch: `feat/spot-orderflow-manager-signal-integration`, based on main `b88f11237ab0791b261b46139ff3f56cd201d4cd`. PR [#204](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/204) merged to main as `5fcc8ce16d6fdc2f896dd0751e0c34535c509c38`.

Implemented:
- `backend/app/binance_order_flow_manager.py`: FastAPI-lifespan-owned, shared HTTP client and bounded on-demand LRU manager with at most eight active symbol streams.
- A stream is requested only after the candle setup and execution gates pass; the manager validates symbol tick size/freshness and shuts down cleanly.
- Live Binance Spot `build_signal` now requires a ready stream snapshot with contiguous aggTrade coverage and sequence-validated depth. A bootstrapping, reconnecting, evicted, stale or invalid stream returns WAIT; it never falls back to REST-only depth or candle volume.
- Deterministic end-to-end tests retain injected order-flow fixtures for long/short setup behavior and prove WAIT while the live stream is bootstrapping.
- Backend CI, Python 3.12/3.14 and Web checks passed on PR head; post-merge Backend CI and Backend/Web CI passed. The optional Telegram update-notification workflow failure is unrelated to signal correctness.

Important capacity boundary:
- Eight simultaneous active symbol streams per application process; this is not simultaneous order-flow coverage of all eligible pairs.
- The manager uses LRU eviction. The automatic scanner must revisit a bootstrapping candidate before admitting too many new candidates, otherwise a stream could be evicted before it becomes ready. The next phase below adds that scheduling discipline.

## Phase C2.2 — full-universe automatic signal scanning (merged PR #220)

Branch: `feat/dynamic-auto-signal-universe`. PR [#220](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/220) merged to main as `bb1b27b480d5a715429c5087db99ebc044a45cdf` on 2026-11-19.

- Telegram Auto Signals now defaults to the authoritative eligible Binance Spot universe rather than a fixed BTC/ETH/SOL shortlist.
- It scans a configurable bounded batch of up to 20 pairs per cycle and persists a fair rotation cursor across cycles.
- It retries order-flow stream warm-up candidates before moving on, respecting the manager's eight-stream cap.
- This is full-universe *rotation over time*, not simultaneous candle+order-flow coverage of every pair in one pass.
- PR checks passed: Backend CI, Backend/Web CI (Python 3.12 and 3.14), and Web CI. Post-merge main Backend CI, Backend/Web CI and Web CI passed on the merge commit.
- The latest scheduled live smoke run is still the 2026-11-18 run on the prior core commit: it discovered 1,373 eligible Spot pairs, scanned a rotating 20-pair sample, and returned 20 WAIT results with zero provider errors and zero insufficient-history skips. This is provider/scan-health evidence only; it is not proof of valid signal generation or profitability.

## Latest core checkpoint — 2026-11-19 07:35 UTC

- Main: `bb1b27b480d5a715429c5087db99ebc044a45cdf`.
- The latest main push-triggered Backend CI, Backend/Web CI (Python 3.12 and 3.14) and Web CI all passed. The optional Telegram Update Notifications workflow failed in its single `announce` step; this is a notification-secret/chat-target configuration issue, not a signal-engine check.
- PR #220's dynamic all-eligible-Spot rotation is merged and verified.
- Binance Spot is the only verified crypto signal market. USDⓈ-M Futures and COIN-M Futures are not connected to the signal engine. XAUUSD is a separate MT5/Twelve Data feed, not Binance order flow.
- Live Spot candidates require a sequence-validated public WebSocket AggTrade + diff-depth stream. Trade-side delta is inferred from Binance buyer-is-maker semantics; depth is sequence checked; no candle-volume-derived bid/ask delta is used.
- Persistent full-history CVD and full UTC-session delta are not claimed: current stream state is bounded to the bootstrap/backfill window, and session delta is only complete when a session-start anchor is proven.
- The current strategy rules are still a compact rule-based engine: EMA/RSI/ATR/ADX/MACD, multi-timeframe bias, confirmed swing BOS/MSS, sweep, FVG/IFVG, order block, breaker, support/resistance and premium/discount. VWAP, volume profile, Fibonacci, explicit supply/demand, mitigation blocks and a general strategy registry are not yet integrated. The displayed score is a confluence count, not a calibrated probability.
- Historical replay remains candle-only. It cannot test whether order flow improves expectancy because synchronized historical aggressor trades and depth are not retained. Walk-forward cost assumptions are estimates; no profitability or accuracy uplift is established.
- The latest scheduled live smoke run (2026-11-18 08:32 UTC) scanned 20/1,373 eligible Spot pairs: 20 WAIT, 0 provider errors, 0 insufficient-history skips. It ran before PR #220 and is not a full-universe scan.
- No open PR at this checkpoint is dedicated to the core signal engine; the current work branch below addresses a confirmed entry-zone selection bug.

## Phase C3 — nearest valid directional retracement zone (merged PR #221)

Branch: fix/select-nearest-valid-retracement-zone, based on main bb1b27b480d5a715429c5087db99ebc044a45cdf. PR #221 merged to main as 5c911554325b3c91f2b727fbfba0d1a7450d8a9c on 2026-11-19.

### Finding

The signal engine previously selected the first non-empty zone in a fixed order (FVG, order block, breaker, inverse FVG). If that first zone was too far away or on the wrong side of price, it prevented a nearer valid order-block/breaker zone from being considered. The same first-zone shortcut could also hide a current-price confluence in another available zone.

### Changes

- Validate structure-zone bounds and finite positive prices before scoring or entry use.
- Score current-price zone confluence against every valid directional zone, rather than only the first populated zone.
- Evaluate every favorable directional FVG/order-block/breaker/inverse-FVG candidate and choose the nearest valid midpoint within the configured ATR distance and actual Binance PRICE_FILTER.
- Preserve the existing distance, spread, depth, order-type and exchange-filter gates; no thresholds are loosened.
- Include the selected zone source in the LIMIT-entry rationale.
- Add deterministic BUY and SELL fixtures where a distant first FVG must not hide a nearer valid order block, plus invalid/wrong-side zone rejection.

### Verification

- PR #221 full diff reviewed: four intended files only (signal_engine.py, test_signal_engine.py, AUTOMATION-PROGRESS.md, ORDER-FLOW-ROADMAP.md); no secrets or unrelated changes.
- PR checks passed: 424 backend tests on Python 3.12 and 424 on Python 3.14; schema/preflight job passed; Web CI passed.
- PR mergeability was clean, base was latest main, and PR was squash-merged with expected head SHA.
- Post-merge main was verified at 5c911554325b3c91f2b727fbfba0d1a7450d8a9c. Post-merge Backend CI passed 424 tests, Backend/Web CI passed 424 tests on Python 3.12 and 3.14, and Web check passed.
- The optional Telegram Update Notifications workflow again failed in its announce step. It is a notification configuration issue and not a code/test failure.
- This change fixes zone selection correctness only; no win-rate, expectancy or profitability uplift is claimed.

## Latest verified checkpoint — 2026-11-19 07:41 UTC

- Main: 5c911554325b3c91f2b727fbfba0d1a7450d8a9c; PR #221 is merged and post-merge checks pass.
- Dynamic all-eligible Binance Spot Auto Signals rotation from PR #220 is merged; the eight-stream cap still means coverage is rotated/on-demand, not simultaneous for all symbols.
- Latest available scheduled live smoke run remains 2026-11-18 08:32 UTC on the pre-PR-220 main commit: 1,373 eligible Spot symbols discovered, 20 scanned, 20 WAIT, zero provider errors and zero insufficient-history skips. A newer post-PR-220 live scan was not available in this run.
- Verified crypto signal market: Binance Spot only. USDⓈ-M Futures and COIN-M Futures are not integrated. XAUUSD is separate MT5/Twelve Data.
- Live Spot candidate gate requires sequence-validated WebSocket AggTrade and depth. Trade-side delta is aggressor-side inferred, not a consolidated quoted bid/ask footprint. CVD is bounded to the bootstrap/backfill seed; full UTC-session delta only when anchored. Historical replay remains candle-only.
- Existing methods: EMA/RSI/ATR/ADX/MACD, multi-timeframe bias, BOS/MSS, liquidity sweep, FVG/IFVG, order block, breaker, support/resistance, premium/discount. Still not integrated: general strategy registry, VWAP, volume profile, Fibonacci, explicit supply/demand and mitigation-block methods. Confluence is a rule count, not a calibrated probability.
- No independent out-of-sample evidence yet shows that the live order-flow gate or additional methods improve expectancy. Do not claim performance gains until synchronized historical trade/depth replay and ablation tests exist.

## Next core phase — strategy evidence registry and correlated-feature control

1. Extract existing rules into a modular registry without changing their semantics initially.
2. Emit typed evidence with method, category, side, timeframe, source/provenance, observation time, strength and conflicts.
3. Group correlated observations (EMA trend across timeframes; MACD/RSI/ADX momentum) so they cannot inflate confluence as independent evidence.
4. Preserve current score/decision as a baseline; introduce category-capped alternatives behind replay/ablation evaluation.
5. Add causal tests for each method and explicit unsupported-data states. Add VWAP/volume profile only with clear candle-volume proxy provenance; do not fabricate aggressor delta.
6. Add synchronized historical Spot AggTrade/depth capture and chronological replay so order-flow and strategy-method uplift can be measured out of sample.
7. Keep USDⓈ-M/COIN-M Futures unsupported until independent adapters and fixtures are verified.


## Phase C4 — strategy evidence registry and correlated-feature reporting (merged PR #223)

Branch: feat/strategy-evidence-registry. PR [#223](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/223) merged to main as 0ee25ab7f259af6f690d2583f083d994aae76636 on 2026-11-19.

- Existing EMA trend, MACD, RSI, ADX, BOS/MSS, liquidity sweep, zone location and trend-timeframe checks now emit typed evidence through a modular registry.
- Evidence contains method ID, category, side, timeframe, reason, candle-derived source, as-of observation timestamp and unweighted calibration status.
- Supporting and conflicting baseline evidence are exposed in signal payloads.
- Unique category counts are diagnostic only. They do not mean methods are statistically independent and do not alter live decisions.
- Legacy BUY/SELL reason order, raw confluence counts and min_score threshold are preserved.
- PR CI and post-merge main passed 430 backend tests on Python 3.12 and 3.14; schema/preflight and Web CI passed.
- No accuracy, win-rate or profitability improvement is claimed.

## Phase C5 — rolling VWAP proxy as diagnostic-only registry evidence (PR validation pending)

Branch: feat/vwap-diagnostic-evidence, created from main 0ee25ab7f259af6f690d2583f083d994aae76636.

### Method definition and provenance

- Calculate a rolling 50-closed-bar VWAP proxy using each bar's typical price (H + L + C) / 3 weighted by total OHLCV candle volume.
- Compare the latest 50-bar value with the previous shifted 50-bar value. Emit bullish diagnostic evidence only when close is above the current value and current VWAP is rising; emit bearish evidence only when close is below current VWAP and current VWAP is falling.
- Require at least 51 unique, contiguous, valid closed bars; per-bar volume may be zero but must be non-negative, and each 50-bar window must have positive total volume. A bar is eligible only when its open timestamp plus the primary timeframe duration is no later than the signal as-of timestamp.
- Provenance is explicitly OHLCV_TYPICAL_PRICE_PROXY. The volume is total candle volume, not bid/ask volume, aggressor delta or a true transaction-level volume-at-price profile.
- This is rolling 50-bar VWAP, not session VWAP or anchored VWAP.
- The method is marked DIAGNOSTIC_ONLY and counts_for_baseline=false. It is exposed separately from supporting/conflicting baseline evidence and cannot alter the legacy signal score or thresholds.

### Tests and validation gates

- Deterministic rising and falling candle fixtures verify bullish and bearish diagnostic evidence.
- Tests verify that the legacy baseline raw count remains unchanged, and that incomplete/future candles, timestamp gaps and all-zero-volume inputs produce no VWAP evidence.
- PR and post-merge Backend CI on Python 3.12 and 3.14, schema/preflight and Web CI must pass.
- Review the complete diff to confirm no diagnostic-only method changes the live score or threshold. Do not merge if any relevant check fails.

### Next

1. Add further value methods (session VWAP, volume profile and Fibonacci) only after each has precise causal definitions, data provenance and deterministic fixtures.
2. Build synchronized historical Spot AggTrade/depth capture and replay to evaluate order-flow and method ablations out of sample.
3. Keep USDⓈ-M/COIN-M Futures unsupported until separate market adapters and deterministic fixtures are verified.


## Phase C6 — observed trade volume profile (merged PR #225)

Merged 2026-11-19 as `50b5c0cc8cb324fb9e24b71d95a0c8e86511de48` (PR #225), based on main `0473937ca0e649f7ff0d50f3aaf9f169e1c73706`.

### Implementation

- Calculate volume-at-price from Binance Spot aggregate trades already validated by the order-flow pipeline. Each observed execution is assigned to the exact symbol tick-size bucket; OHLCV candle volume is never used.
- Expose Point of Control (POC), Value Area High (VAH), Value Area Low (VAL), base-asset volume, exact quote notional summed from original execution prices, bucket count and current mid-price location.
- POC is the bucket with the greatest base-asset quantity; equal-volume POC ties select the lower price.
- Value area target is 70% of the observed window's base volume. Expand from POC by selecting the larger adjacent bucket; equal adjacent-volume ties expand toward the lower price.
- The profile is explicitly scoped to `LATEST_AGGTRADE_INPUT_WINDOW` (bounded recent trades, up to the stream/REST input limit). It is not a complete UTC session profile, not a persistent historical profile, and not a cross-venue consolidated profile.
- Include the profile in the signal-safe order-flow summary so it is visible alongside delta, CVD scope, footprint and L2 evidence. It is diagnostic only and does not add score points, override the order-flow gate, or change BUY/SELL thresholds.

### Deterministic validation

- Hand-computed four-price fixture verifies POC=100, VAL=100, VAH=101, base volume=11, exact quote volume=1111.2 and 70% value-area coverage.
- Equal-volume fixture verifies lowest-price POC tie-break and lower-price-first value-area expansion.
- Summary fixture verifies the observed profile scope/provenance survives into the signal payload.
- PR CI passed: 436 backend tests on Python 3.12 and 436 on Python 3.14; backend schema CI and Web checks passed. Post-merge main checks passed with the same 436-test counts.

### Remaining boundary and next phase

- This adds a genuine recent trade-derived volume profile, but not session-anchored or historical profile replay.
- No performance uplift is claimed; profile location is not yet a live scoring factor.
- Next priority remains synchronized historical Spot AggTrade + diff-depth capture with bounded retention and chronological order-flow replay/ablation. Keep the current live score as the baseline until out-of-sample evidence justifies any change.
- USDⓈ-M and COIN-M Futures remain unsupported by the signal engine.


## Phase C7 — replay exchange-filter enforcement (merged PR #226)

PR [#226](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/226) merged to `main` on 2026-11-19 as `9309185290224d8998f1b994e43c87da03aba912`.

- Historical replay now requires the authoritative Binance Spot `PRICE_FILTER` and passes exact tick/min/max values into the same validator used by live entry selection.
- Missing, malformed, zero/negative and non-finite tick metadata fails closed; the generic `1e-8` replay fallback was removed.
- PR-head Backend CI and Backend/Web CI passed; the recorded suite count was 439 tests on Python 3.12 and 439 on Python 3.14.
- The scheduled read-only live smoke run on the merge commit succeeded (see the 2026-11-20 automation checkpoint below). It is provider/scan-health evidence, not strategy-performance evidence.

## Phase C8 — bounded live order-flow feature snapshot capture (merged PR #240)

### Purpose

The live Spot stream already maintains contiguous aggregate-trade state and a sequence-validated L2 book, but the data was discarded when a stream was evicted or the application restarted. That made it impossible to replay the same observed order-flow features chronologically or measure their incremental value against the candle-only baseline.

### Implementation

- Add `order_flow_observations`, a dedicated SQLAlchemy table for public Binance Spot feature snapshots.
- Capture at most one observation per symbol per UTC minute, only after the stream reports fresh contiguous AggTrade coverage, complete CVD since its bounded bootstrap seed, and a bridged sequence-valid depth book.
- Persist aggressor-side delta, CVD scope/status, UTC session-delta completeness, spread/depth imbalance, trade/depth IDs, source provenance, the latest volume profile, the 32 most active footprint buckets, and up to 20 bid/ask levels.
- Keep capture writes off the WebSocket event loop using `asyncio.to_thread`; storage failures are surfaced in manager diagnostics and do not corrupt stream state or force a signal.
- Retain seven days and prune at most hourly. Unique `(market_type, symbol, UTC-minute bucket)` keys make reconnect/eviction retries idempotent.
- Add a strict chronological loader using millisecond capture timestamps and a half-open `[start, end)` interval so a replay cannot include an observation captured after its decision time.

### Scope and limitations

- This is a compact **feature-snapshot recorder**, not a raw tick archive. It does not retain every AggTrade or every depth diff, and it does not claim historical full-session CVD.
- Only active, on-demand streams are sampled. The manager remains capped at eight simultaneous symbols; a full-universe scanner rotates candidates over time.
- Binance Spot only. USDⓈ-M and COIN-M Futures remain unsupported by the signal engine.
- Captured snapshots are not yet wired into walk-forward evaluation. No win-rate, expectancy or profitability uplift is claimed. The next phase must align these snapshots to closed 1m candles and compare candle-only baseline, order-flow gate and ablation variants on chronological out-of-sample windows.

### Verification

- New deterministic tests cover provenance/sequence/freshness rejection, future-dated source rejection, one-per-minute idempotency, strict no-look-ahead time filtering, retention pruning and manager off-loop capture scheduling.
- Implementation/test head `120c7508ddcf1b9824a497e106d306d19c0f160f` passed 464 tests on Python 3.12 and 464 on Python 3.14; backend schema test, automatic startup preflight, compile and Web CI passed. The full diff contains only the eight intended files and no credential/private-key patterns.
- Final PR head `4420ee5ec42ea896eee86adf5256378234277034` passed Backend CI (464 tests), Backend/Web CI (464 tests on Python 3.12 and 464 on Python 3.14), startup preflight, compile, schema test and Web CI. PR #240 merged to `main` as `1b9d14ced78209cfe74de56f779ae2d3210043eb` on 2026-11-20 07:06:58 UTC; post-merge Backend CI, Backend/Web CI on Python 3.12/3.14 and Web check passed on that exact commit. The optional Telegram announce job failed separately due the configured chat target.


## Phase C9 — causal historical replay of captured Spot order-flow snapshots (merged PR #241)

### Purpose

Phase C8 now persists bounded, sequence-validated feature snapshots, but the historical walk-forward endpoint still evaluated a candle-only baseline. This phase adds a separate order-flow-gated replay without changing the live strategy score or the candle-only baseline.

### Implementation on branch `feat/historical-orderflow-replay`

- Upgrade the compact capture payload to version 2 and persist explicit `coverage_complete` and `gap_detected` trade-state flags. The recorder now refuses to store a snapshot unless the trade stream explicitly reports complete coverage and no known gap.
- Load stored observations for the same symbol and requested historical candle window from the local database. The API enables this replay by default and accepts `include_order_flow_replay=false` to disable the additional comparison.
- For each historical decision timestamp, select only the latest observation captured at or before the decision. Recompute trade age from `last_trade_at` and depth age from `depth_observed_at` against the historical decision time; never trust the age measured at capture time.
- Require capture version 2, exact symbol/Spot market, explicit no-gap trade coverage, sequence-validated L2, matching depth update IDs, complete-since-seed CVD, public WebSocket provenance and no candle-volume substitution.
- Missing, stale, future-dated, malformed or non-sequenced snapshots pass an empty override to the existing order-flow gate so a technical candidate becomes WAIT. No candle-only fallback is allowed inside the order-flow-gated variant, and no older snapshot is carried forward across a stale interval.
- Keep the existing `training` and `out_of_sample` fields as the candle-only baseline. Add separate order-flow-gated training/OOS metrics, snapshot coverage counters and descriptive OOS deltas for trade count, expectancy, win rate and drawdown.

### Validation and limitations

- Add deterministic tests for latest-prior selection, source-age recomputation, future exclusion, stale depth, gapped streams, unordered snapshots, historical mode provenance and fail-closed behavior when no snapshot exists.
- Add recorder coverage for version-2 continuity flags and rejection when gap state is unknown.
- This is a descriptive ablation, not a calibrated causal estimate. Snapshots are sparse/non-random because only active managed streams are sampled; at most one is stored per symbol per minute and the manager has an eight-stream cap.
- The seven-day recorder retains compact feature snapshots, not raw AggTrades/depth diffs. CVD remains bounded since the stream seed; full UTC-session delta may be unavailable. Historical execution spread/depth, fees and slippage remain assumed values, not reconstructed from the stored book.
- No win-rate, expectancy, profit-factor or profitability uplift is claimed. Keep the live gate and legacy score unchanged until adequate independent out-of-sample evidence exists.

### Verification

- PR [#241](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/241) merged to main as `388e30e885621e0c74ed2f8e3183f6a66a94e945`.
- Final PR head `b6c49a62b305631dd46bb6721fe98131c133f1a1` passed Backend CI and Backend/Web CI (Python 3.12/3.14 and Web check). Post-merge main Backend CI and Backend/Web CI passed on the merge commit.
- Full diff reviewed: eight intended files only; no secrets, private API credentials or order-placement code.
- The separate Telegram Update Notifications announce job failed due its configured chat target; backend and web checks were successful.
- No live stored-row coverage or order-flow profitability uplift has yet been demonstrated.

### Next steps

1. Align the once-per-minute feature sample with the next UTC candle-decision boundary without relaxing the existing source-age checks.
2. Inspect real stored-row coverage and keep the candle-only baseline separate from the order-flow-gated replay.
3. Keep USDⓈ-M and COIN-M Futures unsupported until their market metadata, feed adapters, filters and deterministic tests are independently implemented.



## Phase C10 — decision-aligned order-flow feature capture (merged PR #242)

### Problem

Historical replay selects only a snapshot captured at or before a candle decision timestamp and recomputes source age at that decision. The prior once-per-minute capture could happen anywhere in the minute. If it occurred after a candle boundary, it was correctly excluded; the previous sample was then commonly older than the 5-second L2 freshness limit. This could suppress replay coverage without indicating a broken live stream.

### Implementation on branch `feat/align-orderflow-replay-capture`

- Sample in the final two seconds before each UTC minute boundary. All currently supported replay timeframes are minute multiples, so a sample captured before that boundary can be used causally at the next 1m/5m/15m/30m/50m/1h decision.
- Project the latest AggTrade and depth source ages to the boundary before accepting the sample. Reject if projected trade age exceeds the existing 15-second limit or projected depth age exceeds the existing 5-second limit.
- Keep at most one row per symbol per UTC minute, existing seven-day retention and bounded background persistence. The sample is still accepted only when trade continuity/CVD and L2 sequence validation pass.
- Expose the alignment window in stream-manager diagnostics.

### Tests and limitations

- Deterministic tests cover the final-two-second window, UTC-aware timestamps, projected freshness at the boundary, non-finite/negative ages and no capture outside the window.
- This improves sampling alignment only; it does not create historical raw trades/depth, increase the eight-stream cap or prove that stored data exists for a given symbol.
- No signal score, threshold, entry rule or execution behavior changes. No win-rate or profitability uplift is claimed.

### Verification

- PR [#242](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/242) merged to main as `0780e71fa5aa60dc67cb14398f07c4af770eb19d`.
- Final PR head `fa8e83c22dc0dc2b8bf5ecd1ca61e1f99c1da5ab` passed Backend CI and Backend/Web CI; Python 3.12 and 3.14 each passed 478 tests, and Web CI passed.
- Post-merge main Backend CI passed and Backend/Web CI passed on the exact merge commit (478 tests on Python 3.12 and 478 on Python 3.14, plus Web check).
- Full diff reviewed: four intended files only (manager, deterministic manager tests and two progress documents); no secret patterns, API credentials or order-placement code.
- The optional Telegram Update Notifications announce workflow failed separately because of the configured chat target. It does not change the successful backend/web test result.

### Next steps

1. Compare actual stored-snapshot coverage at 1m/5m/15m/30m/50m/1h decision timestamps against the previous arbitrary-minute capture, using unchanged strict source-age limits.
2. Verify the backtest endpoint returns real observation counts and separate baseline/order-flow-gated metrics for a symbol with active streams; zero observations must remain an explicit no-data result.
3. Collect representative chronological out-of-sample sessions before interpreting expectancy, profit factor, win rate or drawdown changes.


## Phase C11 — deterministic end-to-end long/short replay fixtures (PR pending)

### Purpose

The prior replay tests verified causal snapshot selection, freshness recomputation, fail-closed behavior and mode provenance, while the live pipeline tests separately verified synthetic long/short setups. This phase closes the gap between those two layers: prove that the historical replay loop can select a prior stored-style order-flow snapshot and generate a real directional signal through the existing `build_signal` engine.

### Implementation

- Make the deterministic replay observation fixture side-aware: BUY scenarios carry positive aggressor delta and positive L2 quote-notional depth imbalance; SELL scenarios carry negative values.
- Build deterministic, timestamped multi-timeframe candle contexts with a confirmed trend, liquidity sweep and BOS/MSS breakout.
- Run both directions through `signal_backtest._simulate_slice` without monkeypatching `build_signal`; use a prior snapshot with fresh source timestamps, sequence-validated depth and complete-since-seed CVD status.
- Include next-minute execution candles so the existing replay fill simulator evaluates the generated MARKET entry.
- Assert exactly one replay signal/trade, matching direction, a prior snapshot match and explicit order-flow confirmation.

### Evidence boundary

- The scenarios are synthetic fixtures designed to prove engine capability and chronological wiring. They are not downloaded historical trades, not live market signals and not an out-of-sample performance sample.
- Passing this test does not establish win rate, expectancy, profit factor, drawdown improvement or profitability.
- Live stored-row coverage remains a separate operational check. The GitHub smoke workflow runs a rotating read-only pair sample and does not inspect the local app database.

### Verification

- The first replay-test run failed on both directions. The test exposed that the historical execution model generated off-tick synthetic bid/ask prices; the live entry selector correctly rejected them at its `PRICE_FILTER` check.
- The replay model now rounds bid down and ask up to the symbol tick, keeps the synthetic book uncrossed (minimum one tick when the assumed spread is zero), and recalculates the effective spread used in fee/slippage evaluation.
- The long and short replay tests now pass through the real `build_signal` path, match a prior fresh snapshot, receive explicit order-flow confirmation and produce one paper MARKET fill each.
- PR [#244](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/244) final head `a7b16c9d155867bfb9816d1a07277437ed230a6c` passed Backend CI and Backend/Web CI: 481 tests passed on Python 3.12 and 481 on Python 3.14; schema checks and Web CI passed.
- No live scoring thresholds, entry rules, freshness limits, data provenance rules or order execution permissions are changed.
