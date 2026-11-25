# QUANTNEX Automated Engineering Progress

This file is the durable continuation point for the automated phase-by-phase engineering workflow. Update it in every work session so progress survives conversation/context changes.

## Milestone

Deliver a reliable, end-to-end automatic signal-generation workflow using the strategies and safety rules already documented in the repository. Keep broker execution disabled; validate through read-only market data and paper/demo workflows only. Do not describe the tool as perfect or production-safe without evidence.

## 2026-11-16 — Phase 1: MT5 Gold signal-feed availability

### Finding

The signal engine already supports XAUUSD candles through either the configured local read-only MT5 terminal or Twelve Data. However, several higher-level paths checked only `TWELVE_DATA_API_KEY` and therefore rejected or silently skipped XAUUSD when MT5 was enabled without a Twelve Data key.

Affected paths:
- Signal engine status reported Gold as unconfigured unless Twelve Data was configured.
- Manual `/api/v1/signals/scan` rejected XAUUSD before the existing MT5 candle provider could run.
- Telegram Auto Signals settings rejected XAUUSD when MT5 was configured without Twelve Data.
- Telegram's recurring auto-scan loop skipped XAUUSD under the same valid MT5-only configuration.

### Changes in branch `fix/mt5-gold-signal-availability`

- Added shared `gold_feed_provider()` and `gold_feed_configured()` helpers to the signal engine.
- Updated signal status and scan endpoint gates to recognize either MT5 or Twelve Data.
- Updated Auto Signals settings/status and the Telegram recurring scan gate to use the shared provider check.
- Added regression tests for provider selection, MT5-only Gold scan, and MT5-only Auto Signals settings.
- Preserved the existing local MT5 read-only integration and did not enable broker execution.

### Verification

- Changes and regression tests were reviewed in PR [#146](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/146) and merged to `main` as commit `da54f6e16c0d202436a87d26de30f58cbc73a1af`.
- PR CI passed: Backend CI, Backend/Web CI on Python 3.12 and 3.14, and Web CI.
- Post-merge CI also passed: `backend-tests (3.12)`, `backend-tests (3.14)`, `test`, and `web-check` on the merge commit.
- The optional Telegram `announce` workflow failed because the repository's `TELEGRAM_CHAT_ID` secret resolves to the bot itself. This does not affect build/test checks or the merged code; correct the repository secret only if Telegram update announcements are desired.
- A physical Windows MT5 terminal smoke test remains separate and must not be inferred from CI.

### Remaining limitation / follow-up

The Telegram TP/SL level monitor currently obtains its XAUUSD monitoring price through the Twelve Data-specific path. This phase fixes MT5-backed signal generation and automatic scan eligibility, but does not claim MT5-backed TP/SL level monitoring is implemented. Audit and test that separately before declaring Gold alert lifecycle complete.

## Next steps

1. Phase 1 is complete and merged; the next phase is MT5-backed XAUUSD TP/SL level monitoring in Telegram, with fresh-provider validation and Twelve Data fallback.
2. Add regression tests for fresh MT5 quotes, stale/missing quotes and Twelve Data fallback before merging that change.
3. Continue auditing Telegram signal delivery/idempotency and market-data freshness/closed-candle handling.
4. Keep this file current with exact commits, PRs, check results, blockers and next steps.


## 2026-11-16 — Phase 2: MT5-backed Telegram Gold level monitoring (in progress)

### Finding

The Telegram XAUUSD TP/SL level monitor was gated on the Twelve Data API key and fetched a raw Twelve Data price directly. It did not use the already-supported local MT5 quote feed, and it did not apply the shared quote-freshness assessment before sending level notifications.

### Changes in branch `fix/mt5-gold-telegram-level-monitor`

- Prefer the local MT5 quote when enabled and accept it only when the tick is not stale and its age is at most 30 seconds.
- Fall back to Twelve Data when MT5 is unavailable/stale and Twelve Data is configured.
- Use the existing quote-health assessment for Twelve Data and reject unsafe/stale quotes.
- Enable the existing Gold level-monitor loop whenever either historical Gold provider is configured.
- Add regression tests for fresh MT5 preference, Twelve Data fallback, and stale MT5/Twelve Data rejection.

### Verification

- Implementation and regression tests were reviewed in PR [#148](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/148) and merged to `main` as commit `e89a997eb58b727921143934a41c62c5e3640f85`.
- PR CI passed: Backend CI, Backend/Web CI on Python 3.12 and 3.14, and Web CI.
- Post-merge CI passed: `backend-tests (3.12)`, `backend-tests (3.14)`, `test`, and `web-check` on the merge commit.
- The optional Telegram `announce` workflow again failed because the repository's `TELEGRAM_CHAT_ID` secret resolves to the bot itself. This does not affect build/test checks or the merged code.
- A real Windows MT5 terminal and broker-symbol smoke test remains device-level verification.

### Next steps

1. Phase 2 is complete and merged; next audit candle freshness so automatic signals cannot be generated from stale-but-closed market data.
2. Add timeframe-aware freshness checks and regression tests for stale, future-dated, and fresh candles.
3. Continue auditing signal delivery/idempotency and end-to-end automatic signal generation.


## 2026-11-16 — Phase 3: reject stale signal candles (in progress)

### Finding

The candle ingestion path removed still-forming candles, but the signal engine did not reject old, fully closed candles. A provider could therefore return an old historical snapshot and the engine could calculate and publish a signal from it.

### Changes in branch `fix/reject-stale-signal-candles`

- Add timeframe-aware freshness validation based on the latest candle's close time.
- Reject future-dated and stale candles before indicator/confluence analysis.
- Apply the freshness check to every selected timeframe, including derived M50 candles.
- Add tests for fresh, stale, future-dated candles and stale provider data reaching `build_signal`.

### Verification

- Implementation and regression tests were reviewed in PR [#150](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/150) and merged to `main` as commit `c56a0518c8ce0d43839ea0ba30b2465c277815e5`.
- PR CI passed on Python 3.12 and 3.14, plus the schema and web checks.
- Post-merge CI passed: `backend-tests (3.12)`, `backend-tests (3.14)`, `test`, and `web-check`.
- Provider outage and weekend/market-closure behavior still need real-device/provider validation.

### Next steps

1. Inspect CI and review the complete PR diff.
2. Merge only if all checks pass; verify post-merge CI.
3. Continue auditing duplicate signal delivery and end-to-end automatic signal generation.


## 2026-11-16 — Phase 4: preserve low-price crypto signal precision (in progress)

### Finding

The signal engine rounded every instrument's entry, stop loss, targets, ATR and EMA values to two decimal places. That destroys valid price levels for low-priced supported markets such as PEPEUSDT and SHIBUSDT, often collapsing entry/SL/TP to zero. The Signal Lab plan display also forced all levels to two decimals.

### Changes in branch `fix/crypto-signal-price-precision`

- Keep two decimal places for XAUUSD and eight decimal places for crypto signal levels and price-derived indicators.
- Format Signal Lab levels according to price magnitude so small crypto prices remain readable.
- Add an end-to-end mocked PEPEUSDT signal test proving Entry, SL, TP1-TP3 and ATR remain non-zero and correctly ordered.

### Verification

- Implementation and regression tests were reviewed in PR [#151](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/151) and merged to `main` as commit `eb4499b21a2a7a4ec534f2bf0907b8335bdb945e`.
- PR CI passed: Backend CI on Python 3.12 and 3.14, schema checks, and both web checks.
- Post-merge CI passed: `backend-tests (3.12)`, `backend-tests (3.14)`, `test`, and `web-check`.
- The optional Telegram `announce` workflow still fails because the repository's `TELEGRAM_CHAT_ID` secret resolves to the bot itself; code and test checks pass.

### Next steps

1. Phase 4 is complete and merged; next review duplicate signal delivery and worker recovery across network failures/restarts.
2. Add deterministic tests for the automatic Telegram signal loop and persistent fingerprint behavior.
3. Complete a paper-mode end-to-end smoke test when a real local runtime and data feed are available.


## 2026-11-16 — Phase 5: harden automatic signal worker settings (in progress)

### Finding

The Telegram automatic-signal worker parsed persisted preference JSON and immediately called dictionary methods and integer conversions. A valid JSON scalar/null value, malformed interval, malformed timeframe list, or out-of-range minimum score could raise an uncaught exception and interrupt the worker loop. The worker also only enforced a lower bound for the score, so a corrupt value above the maximum could silently prevent every signal.

### Changes in branch `fix/guard-auto-signal-worker-settings`

- Normalize auto-signal settings to a safe typed dictionary before scanning.
- Normalize primary/trend/enabled timeframes and clamp automatic-signal score to the supported 8–10 range.
- Fall back to safe defaults for invalid persisted values without enabling automatic signals unless the stored enabled value is exactly true.
- Add tests for malformed JSON values, invalid intervals, symbols and score bounds.

### Verification

- Implementation and regression tests were reviewed in PR [#153](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/153) and merged to `main` as commit `ee3d68b5ce2e5b69bdf63eb39fbce59515923710`.
- PR CI passed on Python 3.12 and 3.14, plus web and schema checks.
- Post-merge CI passed: `backend-tests (3.12)`, `backend-tests (3.14)`, `test`, and `web-check`.
- The optional Telegram `announce` workflow continues to fail because the repository's `TELEGRAM_CHAT_ID` secret resolves to the bot itself; this is separate from code checks.

### Next steps

1. Phase 6 is in progress: verify automatic signal fingerprint deduplication across database sessions/restarts and Telegram send failures.
2. Review any ambiguous Telegram delivery outcomes; do not claim exactly-once delivery where the Bot API cannot guarantee it.
3. Complete an end-to-end paper-mode signal generation and delivery smoke test when the local runtime is available.


## 2026-11-16 — Phase 6: automatic signal deduplication and delivery persistence (in progress)

### Finding

The automatic worker already stores a per-symbol signal fingerprint in the persistent preferences table after Telegram accepts a message. However, the fingerprint creation, send, and persistence path was inline and had no direct regression tests proving that duplicates are suppressed after a worker restart or that a failed send does not mark an undelivered signal as delivered.

### Changes in branch `test/automatic-signal-deduplication`

- Extract deterministic fingerprint and delivery helpers used by the worker.
- Treat symbol, side, timeframe and signal-candle timestamp as the signal identity; changed levels on the same candle do not produce a duplicate alert.
- Persist the fingerprint only after Telegram send succeeds.
- Add SQLite-backed tests for persistence across sessions, duplicate suppression and send-failure behavior.

### Verification

- Implementation and regression tests were reviewed in PR [#154](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/154) and merged to `main` as commit `a48bfe0cf61dc3099daa66cfe3a4c2d3612157b6`.
- PR CI passed on Python 3.12 and 3.14, plus web and schema checks.
- Post-merge CI passed: `backend-tests (3.12)`, `backend-tests (3.14)`, `test`, and `web-check`.
- Telegram Bot API cannot provide a general idempotency key for sendMessage; an ambiguous network/server failure may still have an uncertain delivery outcome.
- The optional Telegram `announce` workflow failed because the repository's `TELEGRAM_CHAT_ID` secret resolves to the bot itself; code and test checks passed.

### Next steps

1. Phase 7: add an end-to-end synthetic market-data test that exercises the real indicator/structure/confluence pipeline and proves a valid signal can be generated.
2. Verify the signal output is delivered through the tested Telegram fingerprint path in paper mode.
3. Complete a local Windows/MT5 smoke test when the user's runtime is available; never infer it from CI.


## 2026-11-16 — Phase 7: end-to-end signal generation verification (in progress)

### Goal and implementation

A new parameterized end-to-end test now creates deterministic, timestamp-fresh synthetic bullish and bearish OHLC series. Only the market-data fetch is mocked; the actual EMA, RSI, MACD, ATR, ADX, swing structure, BOS/MSS, liquidity sweep, confluence scoring, quality filters, and signal-level calculations execute.

Each generated signal is then passed through the Telegram delivery helper with a fake sender and an isolated SQLite database. The test verifies the fingerprint is persisted and a second delivery attempt after reopening the database is suppressed.

### Verification boundary

- Tests use synthetic data and a fake Telegram sender; no external message or broker order is sent.
- Keep real market-data providers and a real MT5 terminal smoke test separate from synthetic CI tests.
- Passing synthetic tests prove the pipeline can generate signals under controlled conditions, not that the strategy has a positive live expectancy.

### Verification

- PR [#156](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/156) merged to `main` as commit `5822d99a5f89251e19097997a72e37606fe2079f`.
- End-to-end synthetic BUY and SELL cases passed using the actual indicator, structure, confluence, quality-filter and signal-level implementations.
- The generated signals passed through a fake Telegram sender and SQLite fingerprint persistence; duplicate sends were suppressed after reopening the database.
- PR CI and post-merge CI passed on Python 3.12 and 3.14, plus schema and web checks.
- No live provider, MT5 terminal, external Telegram destination or broker order was used.

### Next steps

1. Phase 8: preserve and report the actual market-data provider used for each signal timeframe (MT5, Twelve Data, Binance or Coinbase fallback).
2. Add provider-fallback and provider-attribution tests.
3. Perform a real Windows/MT5 and public crypto-feed smoke test when the user's local runtime is available.


## 2026-11-16 — Phase 8: actual market-data provider attribution (in progress)

### Finding

The candle provider function already returned the provider actually used, including MT5, Twelve Data, Binance Spot and Coinbase fallback. The signal engine discarded that information and hard-coded the result label to Binance Spot for every crypto signal and Twelve Data for every Gold signal. Telegram automatic alerts therefore could misreport the source when a fallback or MT5 feed was used.

### Changes in branch `fix/signal-market-provider-attribution`

- Build signals from provider-aware candle fetch results and aggregate the distinct sources used across selected timeframes.
- Report the actual source(s) in the scan response and Signal Lab's existing Source field.
- Include the actual market-data source in Telegram automatic signal alerts.
- Update the feed status description to document the Coinbase fallback.
- Add provider attribution coverage for Binance, Coinbase fallback, MT5, Twelve Data and mixed-source timeframes.

### Verification

- Implementation and provider tests were reviewed in PR [#158](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/158) and merged to `main` as commit `a85ea1fb7439e6cced21ab520cfe2b3e9dd88e53`.
- PR CI and post-merge CI passed on Python 3.12 and 3.14, plus schema and web checks.
- Provider tests cover Binance Spot, Coinbase fallback, local MT5, Twelve Data and mixed timeframe sources.
- The optional Telegram `announce` workflow failed because the repository's `TELEGRAM_CHAT_ID` secret resolves to the bot itself; this does not affect code or test checks.

### Next steps

1. Phase 9: add Twelve Data provider/fallback tests and a safe local live-feed smoke-test script.
2. Inspect CI and the smoke-test script; merge only after all relevant checks pass.
3. The local Windows/MT5 smoke test must be run on the user's actual machine; CI cannot verify their terminal connection.


## 2026-11-16 — Phase 9: Twelve Data fallback and local live-feed smoke test (in progress)

### Changes in branch `test/gold-provider-fallback-smoke-script`

- Add tests for Twelve Data candle normalization/source attribution and MT5-disconnect fallback to Twelve Data.
- Add `backend/smoke_signal_engine.py`, a read-only live-provider scan for BTCUSDT, ETHUSDT, SOLUSDT and XAUUSD.
- Add `docs/LOCAL-SIGNAL-SMOKE-TEST.md` with Windows PowerShell instructions and interpretation of SIGNAL, WAIT and ERROR results.
- The script never sends Telegram messages or places broker orders.

### Verification

- Implementation and tests were reviewed in PR [#159](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/159) and merged to `main` as commit `43a83c2ce965c9e7d4d93cc1fe8a32ce226f23ae`.
- PR CI and post-merge CI passed on Python 3.12 and 3.14, plus schema and web checks.
- Twelve Data tests cover direct provider use and fallback after an MT5 disconnect.
- The read-only local smoke script and PowerShell instructions are now in the repository.
- The optional Telegram `announce` workflow failed because the repository's `TELEGRAM_CHAT_ID` secret resolves to the bot itself; code and test checks passed.
- The actual Windows/MT5 smoke test has not been run here; it requires the user's local terminal and configured symbol.

### Next steps

1. Phase 10: audit Twelve Data rate limits and concurrent XAUUSD scans, then improve cache reuse/single-flight behavior without serving stale candles.
2. Add deterministic tests for concurrent scans and cache expiry/freshness.
3. Continue local feed verification using the new smoke script when the Windows runtime is available.


## 2026-11-16 — Phase 10: market-data cache and rate-limit resilience (in progress)

### Finding

The Twelve Data Gold candle cache currently has a 15-second TTL. Each signal scan can request five timeframes concurrently. Multiple users/scans arriving together can miss the cache simultaneously and issue duplicate requests for the same symbol/timeframe, increasing the chance of provider rate limits. Any cache extension must remain within the signal engine's timeframe-aware candle freshness limits.

### Changes in branch `fix/twelvedata-singleflight-cache`

- Add per-event-loop, per-cache-key single-flight locking for Twelve Data Gold candle requests.
- Recheck the cache after acquiring the lock so concurrent scans for the same timeframe share one provider request.
- Increase the bounded cache TTL from 15 to 45 seconds; the signal engine still validates every returned timeframe's candle age before signal generation.
- Add tests for concurrent same-key requests, cache expiry/refetch and rejection of stale cached candles.

### Verification boundary

- Implementation and tests were reviewed in PR [#161](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/161) and merged to `main` as commit `69ff1d84a87daea057985e309a485567dc3bc82f`.
- PR CI and post-merge CI passed on Python 3.12 and 3.14, plus schema and web checks.
- Tests verify concurrent same-key scans share one Twelve Data request, expired cache entries trigger a refetch, and stale cached candles are rejected by the signal freshness gate.
- The optional Telegram `announce` workflow failed because the repository's `TELEGRAM_CHAT_ID` secret resolves to the bot itself; code and test checks passed.
- Live provider quota behavior and local MT5 availability still require the real environment.

### Next steps

1. Phase 11: add a scheduled, read-only GitHub Actions smoke workflow for public crypto feeds using the local smoke script.
2. Verify workflow output and ensure WAIT results are not treated as provider failures.
3. Continue auditing provider outages, rate limits and market-closure handling.


## 2026-11-16 — Phase 11: scheduled live crypto smoke verification (in progress)

### Changes in branch `ci/live-crypto-signal-smoke`

- Add `.github/workflows/live-signal-smoke.yml` with a daily schedule at 01:17 UTC and a manual workflow-dispatch option.
- Run the read-only smoke script for BTCUSDT, ETHUSDT and SOLUSDT on Python 3.12.
- Grant only `contents: read`; no API secrets, Telegram destination, broker credentials or write permissions are used.
- A `WAIT` scan exits successfully; provider/data errors fail the workflow.

### Verification boundary

- PR [#163](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/163) merged to `main` as commit `c1ff57e1f6071500e44aedbece93b60ce989db11`.
- PR CI and post-merge CI passed on Python 3.12 and 3.14, plus web checks.
- The workflow is present on `main`, scheduled daily at 01:17 UTC, and can also be started manually from GitHub Actions.
- The first scheduled live run is pending; this session has no workflow-dispatch action to start it immediately.
- The workflow checks public crypto feeds only; Gold/MT5 remains a separate local smoke test.
- Passing the workflow does not establish profitability or verify the user's local terminal.
- The optional Telegram `announce` workflow failed because the repository's `TELEGRAM_CHAT_ID` secret resolves to the bot itself; this is separate from signal-smoke and code CI.

### Next steps

1. Phase 12: inspect the first scheduled live crypto smoke run and diagnose any actual Binance/Coinbase data or validation failures.
2. Review output semantics for SIGNAL vs WAIT vs ERROR; do not treat a WAIT as failure.
3. Continue local Windows/MT5 verification using the smoke script when the user's terminal is available.


## 2026-11-16 — Phase 12: dynamic Binance Spot signal universe (PR validation pending)

### User priority

Automatic, high-quality market signals are the primary product milestone. Binance pair coverage must not be limited to a release-time hard-coded shortlist. For every valid setup, the signal engine must eventually choose MARKET versus LIMIT entry based on market conditions and execution costs, while retaining the existing documented setup rules and paper/read-only safety boundary.

### Finding

The current signal pipeline used a static `CRYPTO_SYMBOLS` allowlist (20 symbols). The candle provider, signal scan API, chart API, Telegram scan settings, auto-signal preferences and smoke-test validation all inherited this limitation. Newly listed or otherwise valid Binance Spot pairs could not be scanned even when Binance provided their candles. Automatic entry type was also not yet represented in the signal payload; the current entry is the latest closed candle price.

### Changes in branch `feat/dynamic-binance-spot-universe`

- Added cached, five-minute Binance Spot `exchangeInfo` discovery with filtering for `TRADING` status and Spot permission.
- Kept the legacy symbol set as a compatibility fast-path while allowing additional pairs after live exchange metadata validation.
- Updated signal and candle fetching to accept dynamically discovered Spot pairs.
- Added `GET /api/v1/signals/markets` to expose the current Binance Spot universe for a market selector.
- Updated chart and manual signal scan API validation to use dynamic exchange metadata.
- Relaxed Auto Signals schema/Telegram normalization from a four-symbol static allowlist to validated symbol syntax, with final market eligibility checked by the signal engine.
- Updated the read-only smoke script to validate requested pairs against live Binance exchange metadata.
- Added searchable Binance-pair inputs to Signal Lab and Auto Signals; populated suggestions and the chart symbol list from the dynamic market endpoint.
- Increased Auto Signals selection capacity to 50 pairs and validate selected symbols against current Binance Spot metadata before enabling alerts.
- Added tests for newly listed Spot pair discovery, inactive/non-Spot filtering, and fetching candles for a dynamic pair.

### Verification and merge result

- PR #165 was merged to `main` as commit `43d787c6c13441f5225b49d509baa0a0c4fda113`.
- Backend CI, Backend-and-Web CI, and Web CI passed after merge, including Python 3.12/3.14 and frontend checks.
- The separate Telegram Update Notifications workflow failed because the configured `TELEGRAM_CHAT_ID` resolves to the bot itself; this is a notification-secret configuration blocker, not a signal-engine test failure.
- This phase covers Binance Spot only. USDⓈ-M and COIN-M Futures require separate exchange metadata, candle endpoints, contract filters and explicit market-type handling.
- No live order placement is enabled. The work remains read-only signal analysis and paper/demo validation.

### Next steps

1. Implement and test adaptive MARKET versus LIMIT entry selection using fresh Binance bookTicker/depth, price movement relative to the confirmed close, OB/FVG retracement zones, spread, liquidity and estimated costs.
2. Apply exact exchange tick/lot/notional filters and include explicit entry type, price, expiry and execution-quality evidence in the signal payload and Telegram/UI alerts.
3. Add deterministic end-to-end long/short tests proving both MARKET and LIMIT decisions, plus rejection of poor execution conditions.
4. Run realistic chronological/out-of-sample paper validation with fees and slippage before treating the signal engine as reliable.
5. Plan Futures coverage only after Spot signal execution quality is verified.


## 2026-11-16 — Phase 13: adaptive MARKET/LIMIT entry (implementation and CI pending)

### User priority

After dynamic Binance pair coverage, the next core requirement is to generate an entry price suited to current market movement: use MARKET when current spread/liquidity and price drift make immediate execution acceptable; use LIMIT at a technically justified OB/FVG retracement when price has moved away from the signal candle. Do not force an entry when neither method meets the execution-quality gates.

### Implementation started on branch `feat/adaptive-market-limit-entry`

- Extended Binance Spot exchange metadata cache to retain symbol filters, including price tick size, quantity step and minimum notional.
- Added fresh Binance Spot best-bid/best-ask and order-book depth retrieval for a selected pair.
- Normalized order-book depth into USD-equivalent liquidity using stablecoin parity assumptions or a live quote-asset/USDT conversion pair; unknown/unconvertible quote assets fail the execution-liquidity gate rather than being treated as USD.
- Exposed execution diagnostics and rejection reasons when no safe entry qualifies.
- Added transparent entry selection thresholds for spread, side-specific top-10 depth, deviation from the confirmed candle and a valid OB/FVG limit zone.
- Added tick-aware price rounding for MARKET/LIMIT entry, stop-loss and take-profit prices.
- Added explicit `entry_type`, `entry_price`, optional `limit_price`, entry rationale, expiry and execution-quality evidence to signal payloads.
- Added estimated spread/fee/slippage cost checks. Fee assumptions are clearly marked as estimates because the user's Binance fee tier is not available to this local signal engine.
- Updated manual/automatic Telegram alerts and Signal Lab UI to display entry type, limit price and execution quality.
- Displayed the MARKET/LIMIT entry expiry in the UI and Telegram alerts so a limit signal is not mistaken for an indefinitely valid instruction.
- Added unit and end-to-end tests for MARKET selection, LIMIT retracement selection, wide-spread rejection, exchange filters and low-price precision.
- Added deterministic bearish LIMIT selection, dynamic newly listed pair signal coverage, quote-asset USD conversion tests, and an end-to-end WAIT case proving poor spreads do not produce a forced signal.

### Verification and merge result

- PR [#166](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/166) merged to `main` as commit `9b420315b3222c12bfb4800fb6bb13e09aade474`.
- Backend CI, Backend-and-Web CI and Web CI passed before merge; post-merge Backend and Web checks also passed.
- The separate Telegram Update Notifications workflow failed because the configured `TELEGRAM_CHAT_ID` resolves to the bot itself; this remains a notification-secret configuration blocker, not a signal-engine CI failure.
- Binance Spot only. SELL signals are analytical Spot sell signals; this does not create a short position or submit a Binance order.
- No real orders are submitted. Market/limit values are signal guidance only; actual fills may differ and LIMIT signals may expire unfilled.
- The quality gates are explicit engineering thresholds and need historical/out-of-sample evaluation before any profitability claim.

### Next steps

1. Add chronological historical replay of the same signal engine, with no look-ahead and explicit fill/expiry assumptions.
2. Compare training and unseen out-of-sample metrics, including fees, slippage, spread, win rate, expectancy, profit factor and drawdown.
3. Do not tune parameters on the holdout or loosen filters simply to increase signal count.
4. Then evaluate Binance USDⓈ-M Futures support for native short signals and broader pair coverage, with explicit market-type separation.


## 2026-11-16 — Phase 14: signal-engine historical walk-forward validation (implementation and CI pending)

### User priority

A signal is not considered good merely because the engine emits it. Validate the actual multi-timeframe QUANTNEX signal rules against historical Binance Spot candles, with chronological training and unseen out-of-sample results. No parameter fitting on the holdout, no future-candle look-ahead, and no live orders.

### Implementation started on branch `feat/signal-engine-walk-forward-backtest`

- Added a bounded, paginated Binance Spot historical kline fetcher (1m base data, 1–30 day bounds, closed candles only).
- Improved minute aggregation to discard incomplete/duplicate buckets before constructing 5m/15m/30m/M50/1h candles.
- Added historical minute-gap checks; reject replay ranges with excessive missing bars rather than silently interpolating or inventing candles.
- Added deterministic historical candle and execution-context overrides to the same `build_signal` engine used by live scans; replay timestamps and signal expiry are anchored to the historical replay time.
- Added a chronological walk-forward runner that uses only candles closed by the next primary bar open, splits usable history into training and unseen holdout slices, and simulates MARKET fills, 15-minute LIMIT expiry/fills, SL/TP1 exits, and conservative stop-first same-candle ambiguity.
- Execution fills and exits are replayed on 1m candles even when the signal timeframe is 15m/30m/M50/1h, so the 15-minute LIMIT expiry cannot accidentally extend to a whole higher-timeframe candle.
- Includes spread/depth/fee/slippage assumptions, net PnL, win rate, profit factor, expectancy in R, max drawdown, expired limit counts and a buy-and-hold reference.
- Added a `POST /api/v1/signals/backtest` API and Signal Lab UI action to show training versus out-of-sample results.
- Backtest limitations are surfaced: no historical order book, no partial TP2/TP3 exits, no position sizing, no funding, and no actual user fee-tier confirmation.

### Verification status

- Code and deterministic tests are in progress on the feature branch; GitHub Actions must verify all tests before merge.
- Backtest MARKET/LIMIT execution uses explicit assumptions for historical spread and depth because Binance public klines do not provide historical order-book snapshots.
- No live orders are submitted; this is a research-only replay.
- A positive holdout result is not proof of future profitability.

### Next steps

1. Run Backend CI and Web CI; fix all test, schema and UI regressions.
2. Review the no-look-ahead boundary and fill/exit simulation against edge cases (gaps, unfilled limits, stop/target in one candle, missing minute buckets).
3. Merge only after checks pass and verify post-merge CI.
4. Run the walk-forward tool on several liquid and lower-liquidity Binance Spot pairs; record real outputs and limitations without inventing performance claims.
5. Perform cost sensitivity tests before treating any strategy settings as reliable.


## 2026-11-17 — Phase 15: order-flow data integrity and rotating Binance Spot coverage (merged PR #187; post-merge checks passed)

### User priority

Automatic, high-quality Binance signals remain the primary objective. Order-flow is now a core signal-quality requirement, not a secondary dashboard feature. Continue through end-to-end data ingestion, strategy evaluation, entry choice and evidence-backed replay; do not treat WAIT or a single green test as proof of completion.

### Latest verified main state

- PR #168 merged deterministic Binance Spot order-flow analytics as `7fff80e39ed4aa7694c49cf9984a11dc643989ae`.
- PR #169 merged a read-only public REST collector as `6a380e4c257d48e1188aeb3557e12581cb0a4b49`. Its four PR checks passed.
- Post-merge CI for PR #169 exposed eight signal-lifecycle failures in the then-current main: the recovery guard rejected the first normal post-signal candle because it opened one timeframe after `signal_time`.
- PR #186 fixed the first-candle boundary and the subsequent-worker-cycle continuity check. It merged as `91585d4584bfe01d730e1d4569b3bb46e4ff4017`.
- Post-merge Backend CI (Python 3.12/3.14), Backend/Web CI and Web checks passed for PR #186. The separate Telegram `announce` job failed because the configured `TELEGRAM_CHAT_ID` resolves to the bot itself; this is an external notification configuration issue, not a code-test failure.

### Implementation in branch `feat/binance-dynamic-orderflow-coverage`

- Corrected order-flow semantics so a bounded recent aggTrade response is not mislabeled as full UTC-session delta or persistent CVD.
- Added a Binance UTC-session-start aggregate-trade probe. Full `session_delta` is exposed only when the response starts at the session's first trade ID and IDs are contiguous; otherwise the engine returns a sample and marks coverage incomplete.
- Exposed `window_cumulative_delta` and an explicit unavailable CVD state until continuous trade state exists.
- Removed the legacy static `CRYPTO_SYMBOLS` bypass from Spot eligibility. All symbols, including legacy known symbols, must now pass current exchangeInfo validation.
- Replaced the fixed BTCUSDT/ETHUSDT/SOLUSDT scheduled smoke list with a rotating, deterministic 20-pair sample from the full eligible Binance Spot universe. The smoke run remains a subset, not a claim that every pair was scanned.
- Added tests for complete/incomplete session coverage, ID gaps, static-shortlist rejection and rotating-universe coverage.

### Verification status and blockers

- Initial CI on commit `6b6f81586ae09aa0dc5c9a891d48546ba7320a6a` failed: 13 tests failed and 290 passed on Python 3.12/3.14; Web syntax checks passed. Failures were caused by legacy test transports not modeling the newly required `/api/v3/exchangeInfo` validation request, plus historical replay unnecessarily consulting live exchange metadata.
- Corrective commits now mock Spot eligibility explicitly in candle/signal tests while retaining dedicated real-metadata tests, and make `build_signal(candles_override=...)` an offline replay path that validates symbol syntax without making live exchangeInfo calls. A regression test asserts that replay never performs the live symbol lookup.
- PR #187 merged to `main` as `3666519818fb20ded9c1be9259c7e004e8f06dda`; `main` was verified to point to that commit.
- Post-merge Backend CI passed: 303 tests. Backend/Web CI passed: 303 tests on Python 3.12 and 3.14; `web-check` passed.
- The optional Telegram `announce` job failed because the repository's `TELEGRAM_CHAT_ID` resolves to the bot itself. This is a repository secret/configuration issue and does not affect build, test or web checks.
- Scheduled live smoke run `43827596155` on 2026-11-16 failed before scanning: the GitHub runner could not retrieve Binance Spot `exchangeInfo` metadata. The error was a provider reachability failure, not a WAIT or a fabricated signal.
- A separate read-only Binance connector check on 2026-11-17 returned 3,703 exchangeInfo symbol records and 1,373 pairs matching the current Spot eligibility filter; BTCUSDT aggregate trades and depth were also returned. This does not prove GitHub Actions runner reachability.
- Binance Spot is the only verified crypto market type. USDⓈ-M/COIN-M Futures are not yet wired into the signal engine.
- REST depth is still a snapshot, not a sequence-validated book. Persistent CVD, reconnect/backfill and historical order-flow replay remain incomplete.
- No claim of improved win rate or profitability is made.


## 2026-11-17 — Phase 16: Binance public REST host failover (merged PR #188)

### Finding and changes

- The scheduled live smoke run on 2026-11-16 failed before scanning because the GitHub runner could not retrieve Spot `exchangeInfo` from the single configured REST host.
- Added `backend/app/binance_public.py`: HTTPS-only, public `/api/v3` routes; prefers `data-api.binance.vision`, then official Binance REST hosts; bounded 3.5-second host attempts (1.5-second connect timeout); four concurrent requests per event loop; successful-host reuse.
- Failover retries transport, invalid JSON, HTTP 408/425 and server failures. It stops on 418/429 rate limits, 403/451 WAF or geo restrictions, and ordinary client validation errors.
- Routed Spot exchange metadata, bookTicker, depth, klines, historical klines and order-flow requests through the helper. Provider host provenance is preserved.

### Verification

- PR [#188](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/188) merged to `main` as `a8fc002b214a037fd4e1ba63e9c68223444684b1`.
- Post-merge Backend CI and Backend/Web CI passed on the current main commit; the separate Telegram Update Notifications workflow failed because the repository's configured Telegram chat target is invalid/self-directed. This does not affect backend/web test results.
- The only verified crypto signal market remains Binance Spot. USDⓈ-M and COIN-M Futures are not wired into the signal engine.
- The latest visible live smoke run remains the 2026-11-16 run, which failed before symbol discovery. The post-failover scheduled runner reachability has not yet been demonstrated; do not treat CI unit tests as live-provider verification.

## 2026-11-17 — Phase 17: order-flow-aware Binance Spot signal gate (merged PR #189; post-merge checks passed)

### User priority

Automatic, high-quality Binance signals remain the primary objective. Order-flow must influence signal eligibility, not merely appear in a dashboard. WAIT is preferred over a candidate whose live order-flow evidence is missing, stale, neutral or contradictory.

### Changes on branch `feat/orderflow-aware-signal-gate`

- Added `evaluate_order_flow_confirmation()` to `backend/app/order_flow.py`.
- The evaluator checks two non-duplicated directional observations: Binance aggregate-trade aggressor `delta_ratio` and quote-notional L2 depth imbalance. It reports supporting, conflicting and neutral evidence separately.
- A live Spot candidate now requests the read-only public AggTrade + depth snapshot after the existing candle/confluence and execution-entry gates pass. The signal is rejected to WAIT unless at least one observation supports the direction and support count exceeds conflict count.
- Stale, malformed, unproven or unavailable trade/order-flow data fails closed. No candle-volume-derived bid/ask delta is accepted.
- Signal payloads include compact trade-side delta, buy/sell volume, window-delta scope, full-session delta only when ID coverage is complete, explicit persistent-CVD unavailable state, L2 spread/depth/microprice, footprint summary, source hosts and snapshot continuity state. The gate also validates the depth snapshot's local receive timestamp (five-second maximum); Binance REST does not supply an exchange event timestamp here.
- Historical candle-only backtest remains an explicitly labeled baseline; no historical trade/depth data is invented. Deterministic order-flow fixtures are labeled separately from live public REST data.

### Tests added

- Hand-controlled BUY and SELL order-flow confirmation cases.
- CONTRADICTED, MIXED, NEUTRAL, stale and invalid-provenance cases.
- End-to-end synthetic long/short signal fixtures now require aligned order-flow evidence.
- End-to-end negative cases verify contradictory and stale order-flow returns WAIT.
- Existing historical replay test asserts that candle-only replay reports order flow unavailable rather than claiming it was validated.

### Verification status

- PR [#189](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/189) merged from `feat/orderflow-aware-signal-gate` to `main` as `c94aa41e72121500656aac584ad8b4406b887ad6`; main was verified to point at that merge commit. PR and post-merge Backend CI passed 319 tests on Python 3.12 and 319 tests on Python 3.14. Backend schema/test and web-check jobs passed. The optional Telegram announce workflow failed because the configured Telegram chat target is invalid/self-directed; this does not affect code or signal tests. The full diff was reviewed; no secrets or unrelated changes were found.
- This sign-confluence evaluator is not calibrated as a win probability. It has not yet demonstrated incremental expectancy or win-rate improvement.
- The current REST depth is one snapshot, not a continuous sequence-validated book. Persistent CVD, reconnect-safe backfill and historical trade/depth replay remain incomplete.
- The scheduled live smoke runner has not yet been observed succeeding after PR #188's endpoint failover.

### Exact next steps

1. Separately verify a live read-only smoke run on the GitHub runner after the REST failover merge; the latest visible scheduled run is still the 2026-11-16 pre-failover failure.
2. Implement bounded WebSocket AggTrade state, ID-gap detection, reconnect/backfill and persistent/reconstructable UTC-session CVD.
3. Implement the depth snapshot + diff-stream sequence bridge; invalidate/resync on every update-ID gap.
4. Add synchronized historical trade/depth capture and replay before evaluating order-flow's incremental value.
5. Only then add further strategy-registry methods (VWAP, volume profile, regime/pullback/continuation variants) with causal fixtures and ablation evidence.


## 2026-11-17 — Phase 18: deterministic Binance Spot stream state (merged PR #191; post-merge checks passed)

### Purpose

The merged PR #189 adds a conservative live REST order-flow gate. The next critical gap is maintaining CVD and a valid order book across streaming updates, reconnects and missing sequence IDs. This phase builds the deterministic state layer before adding network sockets.

### Changes on branch `feat/binance-orderflow-stream-state`

- Added `backend/app/binance_order_flow_state.py`.
- `AggTradeCvdState` supports known UTC-session first-trade anchoring, exact Decimal aggressor delta and quote delta, duplicate/out-of-order handling, ID-gap invalidation, paged REST-backfill recovery and explicit CVD/session coverage states.
- UTC rollover keeps cumulative delta's since-seed scope but marks the new session delta incomplete until a new session anchor is established. Backfill across midnight cannot incorrectly restore new-session completeness.
- `BinanceSpotDepthBook` loads REST snapshots, bridges buffered diff events, applies zero-quantity deletes, checks crossed/locked books and rejects sequence gaps. Invalid books clear all stored levels and require a new snapshot before further diffs can be applied.
- No WebSocket connection or live state persistence is added in this phase.

### Deterministic tests

13 tests cover:
- Session-start seed and hand-computed BUY/SELL delta/CVD.
- Duplicate and out-of-order aggregate trades.
- ID gaps, pending state, partial backfill and complete recovery.
- UTC midnight rollover and backfill across a session boundary.
- Incomplete stream-start state when no session anchor is available.
- REST depth snapshot + buffered diff bridge, zero-quantity deletion, sequence gap/resync, crossed book and malformed snapshot.
- Stale depth levels are cleared on invalidation.
- Malformed/non-monotonic trade events invalidate CVD until a valid contiguous backfill restores it.

### Verification status

- PR [#191](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/191) merged from `feat/binance-orderflow-stream-state` to `main` as `1f953140f18af5555abf4ed7d008789824a96bd2`; main was verified to point at the merge commit. PR and post-merge Backend CI passed 332 tests on Python 3.12 and 332 tests on Python 3.14; schema/test and web-check passed.
- The optional Telegram announce workflow failed because the configured Telegram chat target is invalid/self-directed; this does not affect code or tests.
- This state layer is not yet connected to Binance WebSocket feeds or the live signal engine. It does not yet establish live persistent CVD, live sequence-validated L2, or order-flow out-of-sample performance.

### Exact next steps

1. Add an explicit WebSocket dependency and build a bounded Binance Spot public-stream adapter.
2. Implement reconnect/backoff and REST aggTrade backfill from the last contiguous aggregate-trade ID.
3. Connect REST depth snapshot + buffered diff events to the sequence state; resync on every gap.
4. Integrate state completeness into signal eligibility and capture synchronized historical trade/depth replay.
5. Measure combined order-flow value against the candle-only baseline using chronological replay and ablation.


## 2026-11-17 — live public Binance validation and next verified gap

- At 2026-11-17 08:39 UTC, the read-only Binance connector returned Spot exchangeInfo with 3,703 symbols; 1,373 passed TRADING, isSpotTradingAllowed and Spot permission-set filters, while 2,330 were BREAK.
- All 1,373 active eligible Spot symbols had PRICE_FILTER, LOT_SIZE, MARKET_LOT_SIZE and NOTIONAL; legacy MIN_NOTIONAL was absent but not needed because NOTIONAL existed.
- BTCUSDT public AggTrades, 20-level REST depth and 1m klines returned successfully. This proves sample endpoint access only; it is not a full-universe scan and does not prove a live signal.
- The latest visible GitHub Live Crypto Signal Smoke run remains the 2026-11-16 pre-failover failure; no post-PR #188 scheduled smoke success is visible yet.
- Code audit found a remaining core gap: the Spot symbol cache stores only symbol/base/quote/filter data, and the execution context uses PRICE_FILTER, LOT_SIZE and NOTIONAL but not orderTypes, MARKET_LOT_SIZE, base/quote precision or market-specific min/max quantity. The entry selector therefore does not yet verify that MARKET or LIMIT is allowed for the selected pair.
- Next phase must fix exchange metadata/order-type/filter handling before WebSocket integration. Keep all trading read-only/paper-only.

## 2026-11-19 — Automation run 4: dynamic Spot rotation merged; retracement-zone correctness fix in review

### Latest repository audit

- Repository: `adeeshadasuniduwara/QUANTNEX`; default branch: `main`.
- Main head at start of this run: `bb1b27b480d5a715429c5087db99ebc044a45cdf`.
- PR [#220](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/220) merged on 2026-11-19. Auto Signals now rotates through the full authoritative eligible Binance Spot universe in bounded batches instead of using a BTC/ETH/SOL default.
- PR #220 checks passed: Backend CI, Backend/Web CI on Python 3.12 and 3.14, and Web CI. Post-merge main Backend CI, Backend/Web CI (Python 3.12/3.14) and Web CI passed.
- Latest scheduled `QUANTNEX Live Crypto Signal Smoke` run found in Actions: 2026-11-18 08:32 UTC on commit `cf29930a1759d92122fd390818643bfb3a24d851`. It discovered 1,373 eligible Spot pairs, scanned 20 rotating symbols, returned 20 WAIT results, and recorded 0 provider errors / 0 insufficient-history skips. This run predates PR #220 and is only a 20-pair read-only sample; it does not prove a qualifying live signal or profitability.
- Latest main Backend CI, Backend/Web CI and Web CI on `bb1b27b` passed. The optional Telegram Update Notifications workflow failed in its `announce` step; no signal code test failed. The known Telegram chat-target/secret configuration issue is not changed here.
- Open PRs were audited; none was a pending core signal-engine PR. Binance Spot remains the only verified crypto signal market; USDⓈ-M and COIN-M Futures are not integrated into the signal engine.

### Confirmed entry-selection defect

The signal engine selected the first non-empty FVG/order-block/breaker/inverse-FVG zone. A distant or wrong-side FVG could therefore hide a nearer valid order block or breaker and cause an otherwise valid LIMIT retracement candidate to be rejected. The same shortcut could hide a current-price confluence in another valid zone.

### Changes on branch `fix/select-nearest-valid-retracement-zone`

Branch created from main `bb1b27b480d5a715429c5087db99ebc044a45cdf`.

- `backend/app/signal_engine.py`:
  - Added finite, positive, ordered zone validation.
  - Current-price confluence now checks every valid zone in the directional family.
  - Entry selection evaluates all favorable FVG, order-block, breaker and inverse-FVG candidates, then chooses the nearest valid midpoint within the configured ATR distance and actual Binance PRICE_FILTER.
  - Existing spread, depth, order-type, distance and execution-cost gates remain unchanged.
  - LIMIT rationale identifies the chosen zone source.
- `backend/tests/test_signal_engine.py`:
  - Added BUY and SELL fixtures where a distant first FVG must not hide a nearer valid order block.
  - Added malformed, non-finite, reversed and wrong-side zone rejection coverage.
- `docs/ORDER-FLOW-ROADMAP.md`:
  - Replaced the stale pre-PR-220 checkpoint with the current main state and exact Spot/Futures, order-flow, strategy and historical-replay limitations.
  - Added Phase C3 status and next steps.

### Verification and merge status

- Feature branch code commits: `89fbbc36add0cd1c5226542985559b3aef9a34f6`, `b962835994650d2f4fdcfb4d9fd8192fb359f76d`, `69e501a0e4d4f7fb854acaf2cb81a418960afef0`; roadmap update: `b9ee0e5ce7fdce52e9821f55aa1a91d65f1d800c`.
- Deterministic tests were added but have not yet run in this environment. PR CI is the next verification gate.
- No merge has been attempted. Do not merge unless all Backend/Web CI checks pass and the complete diff is reviewed for scope and regressions.

### Exact next steps

1. Create PR against main and wait for Backend CI (Python 3.12/3.14), Backend/Web CI and Web CI.
2. Review the full diff and merge only if all relevant checks pass; then verify post-merge main and checks.
3. Add a modular strategy registry and evidence attribution. Avoid double-counting correlated EMA/RSI/MACD/ADX features as independent confluence.
4. Capture synchronized historical Spot AggTrade/depth data with provenance and bounded retention, then implement chronological replay/ablation before claiming order-flow improves expectancy.
5. Expand live smoke evidence after PR #220; a rotating 20-pair smoke sample is not proof of same-cycle all-pair coverage.
6. Keep USDⓈ-M/COIN-M Futures marked unsupported until independent metadata, market data, execution filters and deterministic signal tests exist.


### Final Phase C3 verification — 2026-11-19 07:41 UTC

- PR [#221](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/221) passed all required checks and was squash-merged to main as 5c911554325b3c91f2b727fbfba0d1a7450d8a9c.
- PR-head results: 424 tests passed on Python 3.12, 424 on Python 3.14, schema/preflight passed, and Web CI passed.
- Full diff review confirmed four intended files only; no secrets or unrelated changes. PR base was latest main and mergeability was clean.
- Post-merge main was verified at the merge commit. Backend CI passed 424 tests; Backend/Web CI passed 424 tests on Python 3.12 and 3.14; Web check passed.
- Optional Telegram Update Notifications failed only in the announce step; it does not affect the code/test checks.
- Phase C3 is complete. Next core phase: modular strategy evidence registry and correlated-feature control, followed by synchronized historical trade/depth capture and order-flow ablation. See docs/ORDER-FLOW-ROADMAP.md for exact boundaries and steps.


## 2026-11-19 — Phase C4: modular strategy evidence registry (merged PR #223)

- PR [#223](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/223) merged to main as 0ee25ab7f259af6f690d2583f083d994aae76636.
- Added backend/app/signal_methods.py with typed MethodEvidence/StrategyMethod and a registry for the existing EMA, MACD, RSI, ADX, BOS/MSS, sweep, zone-location and trend-timeframe rules.
- Integrated the registry into signal_engine.py without changing legacy BUY/SELL reason order, raw score or min_score threshold.
- Signal payload now reports supporting and conflicting baseline evidence with method ID, category, side, timeframe, candle-derived source, as-of timestamp and unweighted calibration status.
- Unique category counts are diagnostic only; they are not statistical independence, a probability, or a live decision gate.
- PR CI passed: 430 tests on Python 3.12 and 430 on Python 3.14, schema/preflight passed, Web CI passed. Post-merge main Backend CI, Backend/Web CI on Python 3.12/3.14 and Web check all passed 430 tests.
- Initial CI exposed one incorrect test expectation in the contradictory SELL fixture (TREND plus STRUCTURE means two categories); the fixture was corrected and the final PR/post-merge runs passed.
- No profitability or accuracy improvement is claimed. This phase establishes explainable method architecture and baseline parity.

## 2026-11-19 — Phase C5: rolling VWAP diagnostic method (implementation on branch)

### Purpose and data boundary

Add a first value-area method to the strategy registry without changing the live score. The data source is candle OHLCV only, so this is explicitly a proxy, not trade-level VWAP or bid/ask order flow.

### Changes on branch feat/vwap-diagnostic-evidence

- Add a rolling 50-closed-bar VWAP proxy using typical price (high + low + close) / 3 weighted by total candle volume.
- Compare the current 50-bar VWAP with the prior shifted 50-bar VWAP; emit diagnostic BUY/SELL evidence only when close position and VWAP slope align.
- Exclude any candle whose close time is after the signal as-of time; require 51 valid, unique, contiguous, closed bars with non-negative candle volume and positive total volume.
- Label provenance OHLCV_TYPICAL_PRICE_PROXY and include lookback, current/previous VWAP, close, price basis, volume basis and scope in evidence details.
- Mark the method DIAGNOSTIC_ONLY and counts_for_baseline=false. It is not added to the legacy confirmation count or live signal threshold.
- Add bullish/bearish, baseline-score-preservation, incomplete/future-candle and zero-volume fixtures.
- CI and full diff review are pending. No VWAP performance uplift is claimed.

### Next exact steps

1. Validate the new VWAP proxy and ensure diagnostic-only evidence never changes BUY/SELL score or thresholds.
2. After merge and post-merge checks, add further methods only with explicit data provenance and causal tests.
3. Prioritize synchronized historical Spot AggTrade/depth capture and replay so order-flow evidence can be evaluated out of sample.
4. Keep USDⓈ-M and COIN-M Futures unsupported until separate adapters, metadata, execution constraints and deterministic fixtures are verified.


## 2026-11-19 — Phase C5 merged and Phase C6 observed trade volume profile

### Repository audit at run start
- Main was `0473937ca0e649f7ff0d50f3aaf9f169e1c73706`.
- PR #223 strategy evidence registry was merged; PR #224 rolling OHLCV VWAP diagnostic was merged as `0473937ca0e649f7ff0d50f3aaf9f169e1c73706`.
- Main Backend CI and Backend/Web CI passed on that exact commit. Backend tests: 433 passed on Python 3.12 and 433 passed on Python 3.14; Web check passed.
- Optional Telegram Update Notifications failed only in its announce job. It is separate from backend/web signal-engine checks.
- Latest scheduled Live Crypto Signal Smoke run found: 2026-11-18 08:32 UTC, commit `cf29930a1759d92122fd390818643bfb3a24d851`. It discovered 1,373 eligible Spot pairs, scanned a rotating 20-pair sample, returned 20 WAIT, 0 provider errors and 0 insufficient-history skips. This is live provider/scan-health evidence only; it does not prove signal generation quality or profitability.
- Open issues search returned none. Remaining open PRs were reviewed; none was a pending core signal-engine PR.

### Phase C5 — merged PR #224
- Added rolling 50-closed-bar OHLCV typical-price VWAP proxy to the strategy evidence registry as diagnostic-only evidence.
- Explicit provenance: total candle volume weighted by typical price; not observed aggressor delta, not transaction-level VWAP and not volume-at-price.
- Added bullish/bearish fixtures and incomplete/future/gapped/zero-volume rejection tests.
- PR and post-merge main checks passed; main has 433 backend tests passing on Python 3.12 and 3.14.
- It does not alter the live score or threshold.

### Phase C6 — merged PR #225
- Add POC/VAH/VAL from actual validated Binance Spot aggTrades, tick-bucketed using the exchange symbol's tick size; quote notional is summed from each original execution price, not the rounded bucket price.
- Define 70% value area with deterministic lower-price tie-breaks; expose base quantity and quote notional.
- Explicitly scope to the bounded latest aggTrade input window, not a full UTC session or historical profile.
- Surface profile metrics in the signal-safe order-flow summary without changing score/gates.
- Add deterministic hand-calculated POC/value-area/tie-break/summary tests.
- PR #225 merged as `50b5c0cc8cb324fb9e24b71d95a0c8e86511de48` after complete diff review and passing checks.
- CI: 436 backend tests passed on Python 3.12 and 436 on Python 3.14; backend schema CI and Web checks passed. Post-merge main checks also passed.
- No performance uplift claimed; profile remains diagnostic only.

### Next exact steps
1. Phase C6 PR #225 is merged and post-merge checks passed.
2. Phase C7 now fixes a replay safety gap: historical replay must enforce the same authoritative Binance PRICE_FILTER tick and bounds as the live entry validator.
3. Next priority after C7 is synchronized historical Spot AggTrade/depth capture with bounded retention and chronological order-flow replay/ablation. Current historical replay remains candle-only and cannot measure order-flow uplift.
4. Keep strategy additions diagnostic until replay demonstrates incremental out-of-sample value; do not inflate the current legacy confluence score with correlated methods.
5. Keep USDⓈ-M/COIN-M Futures unsupported until independent market adapters, metadata, filters, data feeds and deterministic signal tests are implemented.


### Phase C7 — fix branch `fix/replay-enforces-binance-price-filter`
- Audit found that candle-only replay defaulted missing symbol tick size to `0.00000001` and did not pass the symbol's `PRICE_FILTER` into the simulated execution context. As a result, the price-filter validator could accept a replay price without checking the actual exchange tick/min/max.
- Changed replay to require finite, positive authoritative `PRICE_FILTER.tickSize`, validate min/max bounds, and pass normalized `price_filter` metadata into `build_signal`.
- Added deterministic tests for missing/zero/non-finite tick fail-closed behavior and correct propagation of authoritative tick/min/max.
- PR #226 code/test checks passed: 439 backend tests on Python 3.12 and 439 on Python 3.14; backend schema CI and Web checks passed. Full diff review and mergeability verification remain before merge.


## 2026-11-20 — Automation run 5: historical order-flow capture foundation

### Latest repository audit

- Repository: `adeeshadasuniduwara/QUANTNEX`; default branch: `main`.
- Main at run start: `70c3700cc7564167befa874f56e918c8eae67b24` (merge of PR #238).
- Open issues: none. Open PRs included #239 (GitHub updater rate-limit cache) and older UI/reporting/MT5 PRs; none was a pending Binance signal-engine PR.
- PR #226 (replay exchange-filter enforcement) is closed/merged as `9309185290224d8998f1b994e43c87da03aba912`. Its PR-head Backend CI and Backend/Web CI passed; the recorded test count was 439 on Python 3.12 and 439 on Python 3.14.
- Latest scheduled `QUANTNEX Live Crypto Signal Smoke` run: [run 44490651872](https://github.com/adeeshadasuniduwara/QUANTNEX/actions/runs/44490651872), 2026-11-19 08:47 UTC, on the PR #226 merge commit. Binance exchangeInfo returned 1,380 eligible Spot pairs; the workflow scanned a rotating 20-pair sample and returned 20 WAIT, 0 provider errors and 0 insufficient-history skips. This proves the sampled public data paths loaded; it does not prove a qualifying signal, full-universe same-cycle coverage or profitability.
- Latest main commit `70c3700` contains Telegram multi-coin performance reporting (PR #238). The latest Backend CI and Backend/Web CI results in the visible run list were successful on its immediate parent `bed113a`; the PR #226 signal-core checks and scheduled smoke evidence are separately recorded above. The optional Telegram update-notification workflow failed on its announce job; that is not a backend signal-engine test result.

### Confirmed core boundary before this phase

- Binance Spot is the only verified crypto signal market; USDⓈ-M and COIN-M Futures are not integrated. XAUUSD is a separate MT5/Twelve Data feed.
- Spot pair discovery is dynamic from authoritative exchangeInfo; Auto Signals rotates through the full eligible universe in bounded batches rather than scanning every pair simultaneously.
- Live Spot signals require fresh sequence-validated public WebSocket AggTrade/depth state. Aggressor delta is inferred from Binance buyer-is-maker semantics; it is not consolidated quoted bid/ask volume.
- CVD is complete only since a bounded stream bootstrap seed. Full UTC-session delta is reported only when the session-start anchor is proven.
- Strategy registry currently reports the existing EMA/MACD/RSI/ADX, BOS/MSS, sweep, zone and timeframe rules; the legacy raw confluence score remains uncalibrated. Rolling OHLCV VWAP is diagnostic-only; observed AggTrade volume profile is diagnostic-only.
- Historical walk-forward still uses candles and assumed spread/depth/fees. Before this phase, synchronized live order-flow observations were not persisted, so no order-flow incremental-value replay was possible.

### Phase C8 — branch `feat/orderflow-feature-snapshot-capture`

- Add a bounded `order_flow_observations` table and recorder for verified Binance Spot stream snapshots.
- Sample at most once per symbol per UTC minute, only while the stream is fresh, AggTrade-contiguous, CVD-complete since seed, and L2 sequence-validated.
- Persist compact metrics and provenance: delta/CVD/session scope, spread/depth imbalance, update IDs, latest volume profile, up to 32 active footprint buckets and up to 20 book levels.
- Capture persistence runs in a worker thread so SQLite/Postgres writes do not block WebSocket event handling. The manager reports capture errors without weakening signal eligibility.
- Retain seven days and prune at most hourly. The loader filters on millisecond timestamps in a strict `[start, end)` window to avoid look-ahead.
- This is a feature-snapshot recorder, not raw AggTrade/depth-diff archival. It is not yet connected to walk-forward replay, and it does not change live scoring or thresholds.

### Changed files

- `backend/app/models.py`: add `OrderFlowObservation`.
- `backend/app/main.py`: register the model before `Base.metadata.create_all`.
- `backend/app/order_flow_recorder.py`: add strict validation, compact snapshot persistence, idempotent minute bucketing, retention pruning and chronological loading.
- `backend/app/binance_order_flow_manager.py`: sample ready snapshots off the WebSocket callback and expose capture diagnostics.
- `backend/tests/test_order_flow_recorder.py` and `backend/tests/test_binance_order_flow_manager.py`: add deterministic persistence/lifecycle tests.
- `docs/ORDER-FLOW-ROADMAP.md` and this file: update the verified checkpoint and exact replay boundary.

### Verification status

- Branch created from main `70c3700cc7564167befa874f56e918c8eae67b24`.
- GitHub Actions verified implementation/test head `120c7508ddcf1b9824a497e106d306d19c0f160f`: Backend CI passed 464 tests; Backend/Web CI passed 464 tests on Python 3.12 and 464 on Python 3.14; automatic startup preflight, backend compile, schema test and Web CI all passed.
- Full PR diff reviewed: exactly the eight intended files listed above, no unrelated changes, and no credential/private-key patterns in added lines. Final PR head `4420ee5ec42ea896eee86adf5256378234277034` passed Backend CI (464 tests), Backend/Web CI (464 tests on Python 3.12 and 464 on Python 3.14), startup preflight, compile, schema test and Web CI. PR #240 merged to `main` as `1b9d14ced78209cfe74de56f779ae2d3210043eb` on 2026-11-20 07:06:58 UTC.
- Post-merge main Backend CI, Backend/Web CI on Python 3.12/3.14 and Web check passed on that exact commit. The optional Telegram Update Notifications workflow failed only in its announce job because of the configured self-directed/invalid chat target; this is separate from signal-engine tests.
- Main contains the new `order_flow_observations` model, bounded recorder, and off-event-loop manager capture. No API keys or live-money execution were introduced.

### Exact next steps

1. Add chronological replay alignment that selects only the latest feature snapshot captured at or before each signal decision timestamp.
2. Recompute trade/depth age at the historical decision time; stale, missing, future, gapped or unsequenced snapshots must fail closed.
3. Compare the candle-only baseline with the existing order-flow gate on the same chronological training/holdout windows, while reporting sparse snapshot coverage.
4. Collect enough aligned sessions before making any claim about order-flow's incremental value.
5. Keep Futures unsupported until separate market adapters, metadata, filters and deterministic tests exist.


## 2026-11-20 — Automation run 5 continued: Phase C9 historical order-flow replay (merged PR #241)

### Start-of-phase repository audit

- Latest `main`: `1b9d14ced78209cfe74de56f779ae2d3210043eb`, containing merged PR #240.
- PR #240 was verified merged on 2026-11-20 07:06:58 UTC. Backend CI, Backend/Web CI (Python 3.12 and 3.14) and Web check passed on the exact main commit. The optional Telegram announce job failed independently due the configured chat target.
- Open PRs at audit: #239 updater API rate-limit cache, #206 Telegram Gold reports, #201 mobile cloud gateway, #185 signal ledger/reporting, #172 layout, #170 MT5 Gold, #110 workspace polling, #76 Android parity and #57 Telegram UI polish. No open core Binance signal-engine PR or open repository issue was found.
- PR #169 public Spot REST collector is merged; live Spot signal eligibility uses the sequence-validated public WebSocket stream. REST depth snapshots are not treated as continuous books.
- Binance Spot remains the only verified crypto signal market. USDⓈ-M and COIN-M Futures are unsupported. The live strategy score remains an uncalibrated confluence count; VWAP and volume profile remain diagnostic; no profitability uplift is established.
- Latest main push CI on 2026-11-20: Backend CI and Backend/Web CI passed. Optional Telegram Update Notifications failed in the announce job.

### Confirmed Phase C8 checkpoint

- PR #240 merged to main as `1b9d14ced78209cfe74de56f779ae2d3210043eb`.
- It adds the bounded version-1 compact feature snapshot recorder, one sample per active symbol per UTC minute, seven-day retention, and a strict `[start,end)` loader.
- It does not archive raw AggTrades or every depth diff. Only symbols with active manager streams (maximum eight at once) are captured.
- The latest visible live smoke evidence remains a rotating 20-pair sample from 1,380 eligible Spot symbols; no new live smoke run was confirmed in this phase. Do not describe it as full-universe same-cycle coverage.

### Phase C9 implementation on branch `feat/historical-orderflow-replay`

- Upgrade recorder payload to capture version 2 and persist explicit `coverage_complete` and `gap_detected` flags. Recorder rejects snapshots unless coverage is explicitly complete and the gap flag is explicitly false.
- Add strict snapshot alignment helpers in `backend/app/signal_backtest.py`: validate matching symbol/Spot market and strictly increasing capture times; select the latest observation at or before each decision; recompute trade age from `last_trade_at` and book age from `depth_observed_at` against the historical decision time.
- Require capture version 2, no-gap trade state, sequence-validated depth, matching depth update IDs, complete-since-seed CVD, public WebSocket provenance and no candle-volume substitution.
- Missing/stale/future/invalid observations pass an empty override into the existing gate and therefore reject candidate setups; no stale forward-fill or candle-only fallback is allowed within the order-flow-gated replay.
- Preserve top-level `training` and `out_of_sample` as candle-only baseline metrics. Add a separate order-flow-gated train/OOS replay with snapshot coverage counts and descriptive OOS deltas for trade count, expectancy, win rate and drawdown.
- Integrate the saved-snapshot loader into `POST /api/v1/signals/backtest`; it is enabled by default and can be disabled with `include_order_flow_replay=false`. Empty capture windows are reported explicitly instead of inventing performance data.

### Changed files

- `backend/app/order_flow_recorder.py`: version-2 capture payload and strict explicit no-gap recording gate.
- `backend/app/signal_engine.py`: allow an explicit historical replay data-mode label for supplied order-flow observations.
- `backend/app/signal_backtest.py`: causal snapshot selection, freshness recomputation, fail-closed gating, coverage counters and separate baseline/Order Flow ablation output.
- `backend/app/main.py`: load same-symbol persisted observations for the requested candle window; guard empty candle responses; expose capture status/count.
- `backend/tests/test_order_flow_recorder.py` and `backend/tests/test_signal_backtest.py`: deterministic continuity, no-lookahead, stale/future/gap, order and mode-provenance tests.
- `docs/ORDER-FLOW-ROADMAP.md` and this file: update the durable continuation checkpoint.

### Verification status

- PR [#241](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/241) merged to `main` as `388e30e885621e0c74ed2f8e3183f6a66a94e945`. The final PR head `b6c49a62b305631dd46bb6721fe98131c133f1a1` passed Backend CI and Backend/Web CI (Python 3.12 and 3.14 plus Web CI).
- No live scan, trade signal, performance uplift or profitability result is claimed by this code change.
- No live orders or private Binance API credentials are introduced.

### Verified outcome

- Full PR diff reviewed: eight intended files only (backtest API, recorder, replay engine, signal-engine replay mode, two test files and two progress documents); no API credentials or live-order code were added.
- PR #241 merged against its latest main base. Backend CI and Backend/Web CI passed on the final PR head; the exact main merge commit then passed Backend CI and Backend/Web CI. The optional Telegram Update Notifications workflow failed only in its separate `announce` step due the repository's configured chat target.
- No live signal, stored-observation count, performance uplift or profitability result is claimed. A live endpoint exercise against a database containing recent recorded rows is still required.

### Exact next steps

1. Improve snapshot timing so observations are available immediately before historical candle decision boundaries while still passing the same source-age limits.
2. Preserve the candle-only baseline and fail-closed order-flow replay; do not loosen freshness limits to inflate coverage.
3. Collect and inspect actual aligned observations before interpreting any out-of-sample comparison.



## 2026-11-20 — Automation run 5 continued: Phase C10 decision-aligned order-flow capture (merged PR #242)

### Finding

Phase C9 replays only the latest snapshot captured at or before each candle decision time and recomputes source ages. The recorder stored one sample per UTC minute, but the manager captured it at an arbitrary point in that minute. A sample captured just after a 1m/5m/15m/30m/50m/1h boundary is correctly excluded as future data; the prior minute's sample is often older than the 5-second depth freshness limit. This can make replay coverage unnecessarily sparse even when the live stream is healthy.

### Change on branch `feat/align-orderflow-replay-capture`

- Capture only during the final two seconds before the next UTC minute boundary, so the sample is available to decisions at that boundary without look-ahead.
- Before scheduling the database write, project trade and depth source ages forward to the next minute boundary and reject the sample if either would exceed its existing 15-second/5-second freshness limit.
- Preserve the one-sample-per-symbol-per-minute uniqueness, seven-day retention, bounded async write queue, sequence-validation requirement and eight-stream cap.
- Expose the capture alignment policy in manager diagnostics.
- Add deterministic tests for boundary timing, source-age projection, invalid/non-finite ages and skipping off-window capture.

### Verification status

- PR [#242](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/242) merged to main as `0780e71fa5aa60dc67cb14398f07c4af770eb19d`.
- Final PR head `fa8e83c22dc0dc2b8bf5ecd1ca61e1f99c1da5ab` passed Backend CI and Backend/Web CI; Python 3.12 and Python 3.14 each passed 478 tests, and Web CI passed.
- Post-merge main Backend CI and Backend/Web CI passed on the exact merge commit (478 tests on Python 3.12 and 478 on Python 3.14, plus Web check).
- Full diff reviewed: four intended files only; no secret patterns, private credentials or order-placement code. The optional Telegram announce job failed separately due its configured chat target.
- No actual stored-snapshot coverage or trading-performance uplift has been measured yet.
- This change does not modify signal thresholds, live scoring, execution selection or order-flow confirmation rules.

### Exact next steps

1. Compare actual stored-snapshot coverage at 1m/5m/15m/30m/50m/1h decision timestamps against the previous arbitrary-minute capture, using unchanged strict source-age limits.
2. Verify the backtest endpoint returns real observation counts and separate baseline/order-flow-gated metrics for a symbol with active streams; zero observations must remain an explicit no-data result.
3. Collect representative chronological out-of-sample sessions before interpreting expectancy, profit factor, win rate or drawdown changes.


## 2026-11-21 — Automation run 6: end-to-end historical Order Flow long/short fixtures (PR pending)

### Start-of-run repository audit

- Latest verified `main` before this phase: `cc3437c56a35bf0c59ccdf61c522803b38fe3d30`.
- Open repository issues: none.
- Open PRs: #239 (GitHub updater rate-limit cache), #206 (Telegram Gold reports), #201 (mobile cloud gateway), #185 (signal ledger/reporting), #172 (layout), #170 (MT5 Gold), #110 (workspace polling), #76 (Android parity), and #57 (Telegram UI polish). No open PR directly targeted the Binance signal/replay core. PR #239's recorded base SHA predates the current main head, so it is not merge-ready without a fresh-base review.
- Latest scheduled `QUANTNEX Live Crypto Signal Smoke`: [run #44703341723](https://github.com/adeeshadasuniduwara/QUANTNEX/actions/runs/44703341723), created 2026-11-20 08:32:20 UTC, completed successfully. All workflow steps completed; this run's inspected metadata does not expose per-symbol console output, so no new WAIT/signal counts are claimed here.
- The smoke workflow still uses a rotating 20-symbol sample from the dynamic Binance Spot exchangeInfo universe. It is not a same-cycle full-universe scan and does not persist order-flow observations into the user's local database.
- Binance Spot remains the only verified crypto signal market. USDⓈ-M and COIN-M Futures remain unsupported by the signal engine.

### Phase C11 — deterministic historical replay signal proof (merged PR #244)

Branch: `test/orderflow-replay-long-short-fixtures`.

- Extend the persisted order-flow replay fixture builder to support both directional sides with correctly signed aggressor delta and L2 depth imbalance.
- Add deterministic multi-timeframe candle scenarios containing a qualifying trend, confirmed liquidity sweep and BOS/MSS event, then pass them through the actual `_simulate_slice` replay path and the actual `build_signal` engine.
- Supply a prior, fresh, sequence-validated feature snapshot with complete-since-seed CVD provenance; replay recomputes source age at the decision timestamp.
- Assert that one BUY and one SELL replay signal are generated, the order-flow gate confirms each, and the modeled MARKET entry is filled by the next execution candle.
- These are deterministic synthetic replay fixtures only. They are not live signals, historical-market performance results, or evidence of profitability.

### Changed files

- `backend/tests/test_signal_backtest.py`: directional snapshot fixture, synthetic multi-timeframe setup generator, replay execution bars, and parameterized long/short tests through the real signal engine.
- This progress document and `docs/ORDER-FLOW-ROADMAP.md`: record the new acceptance test and remaining live-data blocker.

### Verification status

- Initial replay fixtures exposed a real historical-execution modeling defect: synthetic bid/ask prices were derived from candle open plus an assumed spread but were not rounded to the symbol tick. The entry selector correctly enforced `PRICE_FILTER` before the later entry-price rounding, so both otherwise-valid replay setups were rejected.
- `backend/app/signal_backtest.py` now rounds the modeled bid down and ask up to the authoritative tick, enforces at least one tick of separation for a zero-spread/locked synthetic book, and recalculates the effective spread after rounding. Cost estimates therefore use the effective tick-aware spread, which can be wider than the requested assumption.
- Added a focused test proving modeled quotes are tick-aligned, uncrossed and never narrower than the requested spread, including the zero-spread edge case.
- PR [#244](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/244) passed Backend CI and Backend/Web CI: 481 tests passed on Python 3.12, 481 on Python 3.14, schema checks passed and Web CI passed.
- The earlier failing attempts were not merged. The failure was retained as evidence, diagnosed and corrected before merge.
- No signal thresholds, production scoring, order-flow freshness limits, live execution settings, or order-placement behavior were changed.
- No API keys or live-money execution were introduced.

### Exact next steps (updated after merge)

1. Add negative end-to-end replay fixtures for contradictory, stale and gapped Order Flow snapshots.
2. Inspect real local order_flow_observations counts for active streams through the backtest endpoint; GitHub smoke success does not prove local recorder coverage.
3. Keep baseline candle replay separate from order-flow-gated replay; collect representative chronological out-of-sample observations before interpreting any performance delta.


## 2026-11-21 — Automation run 6: fail-closed historical replay negative fixtures (PR pending)

### Start-of-run audit

- Latest main at the start of this phase: ef702a2e77a66bae6fcd5362a08e1e480668d594, containing merged PR #244.
- Open issues: none. Open PRs at audit were #239, #206, #201, #185, #172, #170, #110, #76 and #57; none targeted the Binance signal/replay core.
- Latest available scheduled Live Crypto Signal Smoke was [run #44703341723](https://github.com/adeeshadasuniduwara/QUANTNEX/actions/runs/44703341723), created 2026-11-20 08:32:20 UTC. It discovered 1,375 eligible Spot pairs and scanned a rotating 20-pair slice. All 20 scans completed with Binance Spot data, zero insufficient-history skips and zero provider errors; all 20 returned WAIT. The highest displayed confluence values were 7/10 and 8/10, but the runner did not expose per-candidate Order Flow rejection details. This is a healthy provider smoke run, not evidence of a live setup or strategy profitability.
- Latest main CI for PR #244 merge commit: Backend CI and Backend/Web CI passed; the separate Telegram Update Notifications workflow failed in its announce job because of the configured chat target.

### Phase C12 — end-to-end negative replay proof (merged PR #245)

- Refactor the deterministic replay fixture into one shared runner so positive and negative scenarios use the same 1m/5m/15m/30m/1h candles, symbol filters, assumed execution costs and actual _simulate_slice + build_signal path.
- Preserve the two positive acceptance cases: aligned BUY and SELL AggTrade-derived delta plus sequence-validated L2 depth must each generate exactly one synthetic replay signal and one modeled paper MARKET fill.
- Add both-direction negative fixtures where trade delta and depth imbalance oppose the otherwise valid candle setup. These must remain WAIT with zero signals/trades.
- Add both-direction stale-depth fixtures. The replay must count the stale snapshot, reject the candidate and produce no trade.
- Add a trade-ID gap fixture. The replay must classify the snapshot invalid, reject the candidate and produce no trade.
- No strategy threshold, signal score, market/limit selection, freshness limit, feed state or live order permission is changed.

### Evidence boundary

- These fixtures prove the replay's fail-closed behavior on deterministic synthetic candle and stored-snapshot inputs. They are not historical-market performance evidence, not live signals and not a win-rate/expectancy improvement claim.
- The latest GitHub smoke runner scans only a rotating subset (20 of 1,375 eligible Spot pairs in the last observed run); it does not inspect the user's local database or prove that order-flow snapshots were persisted locally.
- The backtest API already exposes order_flow_capture.status and observation_count; a local run with an active stream is still required to establish real recorder coverage and compare candle-only versus Order-Flow-gated OOS metrics.
- Binance Spot remains the only verified crypto signal market. USDⓈ-M and COIN-M Futures remain unsupported by the signal engine.

### Changed files

- backend/tests/test_signal_backtest.py: shared actual-engine replay runner plus stale-depth, contradictory delta/depth and trade-gap negative fixtures for the signal replay path.
- docs/AUTOMATION-PROGRESS.md and docs/ORDER-FLOW-ROADMAP.md: record the verified smoke output, merged C11 checkpoint, C12 scope, evidence boundary and exact next steps.

### Verification

- PR [#245](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/245) merged to main as 43029441a672929c104466452ff32dfe6c6231e5. Backend CI passed; Backend/Web CI passed with 486 tests on Python 3.12 and 486 on Python 3.14, plus Web CI. Post-merge checks passed on the exact merge commit. The separate Telegram announce job failed because of the configured chat target. No live order placement or private API credentials were introduced.

### Exact next steps (updated after merge)

1. Improve the read-only smoke output so WAIT results expose the Order Flow gate status and key freshness/delta/depth metrics.
2. Inspect actual local order_flow_observations coverage via the backtest endpoint while one of the managed Spot streams is active; record the returned count and train/OOS coverage counters without inferring local data from GitHub smoke logs.
3. If local coverage is sparse, diagnose the eight-stream cap, capture-window timing, stream readiness and recorder errors without relaxing 15-second trade / 5-second depth freshness limits.
4. Collect real chronological order-flow sessions before reporting win rate, expectancy, profit factor, drawdown or any incremental edge.


## 2026-11-21 — Automation run 6 continued: live smoke Order Flow diagnostics (merged PR #246)

### Purpose

The last scheduled live smoke run successfully scanned 20 dynamically selected Binance Spot pairs, but its output printed only WAIT and the legacy confluence count. That did not show whether a WAIT came from no directional candle setup, an unready sequence-validated stream, contradictory aggressor delta, stale depth or another Order Flow gate outcome. The signal API already returns a compact Order Flow summary, so the smoke runner can expose the decision without changing the strategy.

### Changes

- Add a safe scalar formatter and a compact Order Flow diagnostic line for every successful symbol scan, whether the result is WAIT or SIGNAL.
- Show status, accepted/not-applicable, feed mode, stream readiness, trade count, aggressor delta/ratio, CVD value/status, UTC session delta/completeness, trade age, spread and L2 depth imbalance when present.
- Do not print raw WebSocket URLs, raw footprint arrays, complete book levels, or full source payloads.
- Add tests proving contradictory status/metrics appear in output and non-finite/missing values are omitted.

### Evidence boundary

- This improves diagnosis only. It does not change live signal eligibility, scoring, freshness thresholds, symbol coverage, or order execution.
- A WAIT with status NOT_EVALUATED_NO_DIRECTIONAL_SETUP means no directional candle candidate reached the Order Flow gate; it is not a stream failure.
- A WAIT with accepted=false and a stream/decision status identifies an Order Flow veto or data-readiness problem. The smoke runner still does not persist the user's local database observations.
- No live signal or performance improvement is claimed.

### Changed files

- backend/smoke_signal_engine.py
- backend/tests/test_smoke_signal_engine.py
- docs/AUTOMATION-PROGRESS.md
- docs/ORDER-FLOW-ROADMAP.md

### Verification

- PR [#246](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/246) merged to main as 9d951d18e547cca260378d3c5903870c6da64dab. Backend CI passed; Backend/Web CI passed with 487 tests on Python 3.12 and 487 on Python 3.14, plus Web CI. Post-merge checks passed on the exact merge commit. The separate Telegram announce job failed because of the configured chat target.

### Exact next steps

1. Inspect the next scheduled read-only smoke run and use the new diagnostics to distinguish no-setup WAIT from Order Flow readiness/confirmation vetoes.
2. Verify actual local recorder coverage through the backtest endpoint while a managed Spot stream is active.
3. Use local backtest API diagnostics to establish actual recorder row coverage and keep the candle-only baseline separate from Order Flow replay.
4. Only after representative real chronological observations exist, calculate comparative OOS expectancy, win rate, profit factor and drawdown.


## 2026-11-21 — QUANTNEX VIEW Order Flow & Liquidity Toolkit (implementation branch)

### User request

Consolidate the existing standalone Order Flow & Liquidity page and its Bookmap-style liquidity heatmap into QUANTNEX VIEW as a distinct integrated tool package. Keep the existing native chart as the primary chart and share its selected symbol/timeframe.

### Repository audit

- Existing UI had a separate sidebar route `#orderflow-liquidity` with a Binance Spot `<symbol>@depth20@100ms` partial-depth stream, a rolling heatmap and top-12 bid/ask tables.
- The heatmap retained at most 120 snapshots (approximately 12 seconds at 100ms) and explicitly showed resting liquidity, not executed volume.
- The stream is partial-depth snapshots, not a sequence-validated full depth-diff reconstruction. No full footprint or trade-side Delta/CVD browser widget was present.
- QUANTNEX VIEW is a first-party native canvas chart with its own market and timeframe selectors. The UI can share these selectors without introducing a second chart.
- Existing source auto-updater downloads verified main-branch Web/Backend source with backup and rollback; cache keys must be advanced when Web assets change.

### Implementation on branch `feat/quantnex-view-orderflow-toolkit`

- Remove the standalone sidebar navigation entry and old standalone page.
- Add an Order Flow & Liquidity Toolkit package below the QUANTNEX VIEW chart intelligence section.
- Add three tool tabs: Liquidity Bookmap, Depth Ladder and Trade Flow diagnostics.
- Reuse the existing live Spot partial-depth heatmap and bid/ask tables; add best bid/ask, quoted spread in price/bps, top-20 displayed quantity totals and depth imbalance.
- Bind the toolkit to QUANTNEX VIEW's selected symbol/timeframe. Do not request Binance depth for XAUUSD/non-USDT chart symbols.
- Preserve browser visibility/active-view socket lifecycle. Show the package only on QUANTNEX VIEW; stop the depth socket when leaving the view.
- Explicitly disclose that browser Trade-side Delta/CVD is not connected and that the Bookmap visual is partial-depth resting liquidity, not a sequence-validated full book or executed footprint.

### Verification boundary

- Web CI contract tests cover placement/navigation, selected chart market linkage, tab structure, capability disclosures and lifecycle wiring.
- The source diff must not change signal scoring, backend order-flow validation, broker execution, API credentials or live-money settings.
- Real browser rendering and live WebSocket verification still require a running local QUANTNEX instance. The UI cannot be declared device-verified from static CI alone.

### Next steps

1. Run Web CI and inspect the complete diff/security surface before merging.
2. Verify the next main-branch source update installs the new assets and cache keys; the user can restart the local launcher if they want the update immediately.
3. On the user's local app, select BTCUSDT/ETHUSDT/SOLUSDT in QUANTNEX VIEW and verify heatmap/depth metrics; switch to XAUUSD and confirm the UI reports Binance Spot depth unavailable.
4. Implement browser-side AggTrade Delta/CVD only after exposing the existing validated backend observations through a read-only API with provenance, freshness and gap status; do not infer it from candles or partial depth.


### CI correction

- Initial Web CI correctly caught a defect in the new contract test (the regex omitted the leading `if(` token); the application code itself passed syntax and preceding contract assertions. Corrected the assertion to match the actual active-view conditional. Re-run all Web CI checks before merge.

- Follow-up safety hardening: clear the previous symbol's heatmap, depth tables and metrics before opening a new stream or returning early for Gold/non-USDT instruments, preventing stale BTC/ETH/SOL depth from remaining visible after a chart-market switch.

- CI found the existing app.js cache-key contract in `live-terminal.test.cjs`; updated it to the new app asset version. Added a regression assertion and code guard ensuring a BTC/ETH/SOL heatmap, ladder and metrics are cleared before switching to Gold/non-USDT instruments, so old crypto liquidity is never left on screen as if it belonged to the new market.


### Final merge and post-merge verification — PR #248

- Compare review confirmed the feature branch was 4 commits ahead / 0 behind latest main, mergeable, with 8 intended files only and no private-key/API-secret pattern in the diff.
- PR [#248](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/248) was squash-merged as `177ddecc0d5104b2bfd324fa03b607271f8d70d5` on 2026-11-21.
- PR-head checks passed: Web CI, Backend/Web CI Web check, Backend tests on Python 3.12 (487 passed) and Python 3.14 (487 passed).
- Post-merge checks passed on the exact merge commit: Web CI and Backend/Web CI Web check; Python 3.12: 487 passed; Python 3.14: 487 passed.
- The separate Telegram `announce` workflow failed independently; backend tests and web checks passed. This does not verify Telegram update delivery.
- Verified `main` ref points to merge commit `177ddecc0d5104b2bfd324fa03b607271f8d70d5`.
- Confirmed source supervisor uses `UPDATE_INTERVAL_SECONDS = 300` (5 minutes), checks for automatic source updates, installs the pinned source snapshot and restarts services with health-check rollback. The user does not need to click the Web install button for supervisor-managed source updates. The local supervisor must be running; if QUANTNEX is closed, it will update when launched.
- Local browser rendering/live Binance stream has not been verified on the user's machine.

### Remaining limitations / next phase

1. The browser Bookmap remains Binance Spot `depth20@100ms` partial snapshots only; it is not a sequence-validated full depth-diff order book.
2. Trade-side Delta/CVD is deliberately marked unavailable in the browser until validated backend observations are exposed through a read-only endpoint with provenance, freshness and gap state.
3. USDⓈ-M/COIN-M Futures, Gold and Forex depth are not claimed as supported.
4. Next UI/order-flow phase: expose validated Spot AggTrade-derived delta/CVD and session coverage to QUANTNEX VIEW; keep partial-depth and executed-trade metrics distinct.
5. Independently continue the primary signal-engine milestone: dynamic Binance symbol universe, deterministic long/short replay and chronological OOS validation.


## 2026-11-21 — Phase C14: validated Spot Order Flow API (implementation branch)

- Main baseline: 450194b8a750273cf8734e4d5f2a81bd629d4c41; branch feat/quantnex-view-sequence-validated-orderflow.
- Backend already owns a bounded Binance Spot AggTrade + diff-depth manager with trade-ID gap backfill, sequence-validated L2, CVD since stream seed and explicit UTC session coverage. The previous browser Bookmap bypassed it and opened an unsequenced depth20@100ms partial stream.
- Add a local read-only API to expose the validated manager snapshot and replace the browser partial-depth socket with bounded polling.
- Trade Flow UI consumes actual AggTrade-derived delta/CVD/footprint with provenance; full UTC session delta remains unavailable until independently anchored.
- Depth readiness and trade-flow readiness are separate; no stale/unsequenced depth fallback is rendered.
- Pending PR checks and post-merge local device/live stream verification.

- Follow-up C14 integration: the chart symbol selector now refreshes all current eligible Binance Spot symbols on entry and every 15 minutes while the chart is active; the Bookmap uses the backend sequence-validated L2 stream and the Trade Flow panel displays AggTrade delta/CVD, footprint, volume-profile POC/VAH/VAL, microprice and honest UTC session coverage. Price formatting follows each pair's exchange tick size.

- CI caught a test-only cache-key mismatch: the stylesheet version correctly remains sequence-orderflow1 (its CSS last changed in the first toolkit merge), while app.js is sequence-orderflow3. Updated the toolkit contract test to check each asset's actual version; no application behavior changed by this correction.

- CI caught a stale legacy assertion in live-terminal.test.cjs that required the old browser-side @depth20@100ms stream. Replaced it with assertions for the validated local Order Flow API and no partial-depth fallback; this reflects the intended architecture change.

- CI caught a malformed regex escape in the updated legacy live-terminal contract assertion. Replaced it with a direct source-string assertion; the new Order Flow toolkit contract suite itself passed.

- CI found additional legacy live-terminal assertions for the removed browser-side Bookmap WebSocket reconnect logic. Replaced them with checks for the validated backend polling lifecycle, sequence/staleness veto and absence of browser depth sockets.

- Updated the legacy live-terminal contract to assert that backend-provided freshness/sequence rejection reasons are surfaced, rather than expecting the backend enum string to be hard-coded in the browser.


### Phase C14 merge record — PR #250

- PR [#250](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/250) squash-merged into main as d5758744c61ccedabc6fc71eb70b1c07798cf7c6 on 2026-11-21.
- Compare before merge: 11 commits ahead, 0 behind; mergeable; 9 intended files; no private-key/API-secret pattern detected.
- Pre-merge CI: Web CI passed; Backend CI and Backend/Web CI passed. Python 3.12 and Python 3.14 suites each reported 491 passed.
- Post-merge CI on exact merge commit d5758744c61ccedabc6fc71eb70b1c07798cf7c6: Web CI passed; Backend CI and Backend/Web CI passed; Python 3.12 and Python 3.14 each reported 491 passed.
- Verified main ref equals d5758744c61ccedabc6fc71eb70b1c07798cf7c6.
- Live public crypto smoke run 44884113669 was triggered by this main update; its final scan output was still in progress at the time of this documentation record. It is the existing three-symbol smoke subset, not full-universe coverage.
- Telegram update-notification workflow failed at the announce step because TELEGRAM_CHAT_ID resolves to the bot itself. Exact blocker: the repository secret must be changed to a private chat ID or a group/channel ID where the bot can post. The token itself was not inspected or changed.
- Source supervisor auto-update interval remains 300 seconds. While the local supervisor is running, it checks, downloads and applies verified main source automatically with backup/rollback; if QUANTNEX is closed, update applies on next launch.
- User-device browser rendering and live Binance Spot stream verification remain pending.

### C14 capability status

- Binance Spot only is exposed in the QUANTNEX VIEW Order Flow package. The selector dynamically refreshes the active Spot symbol universe from exchangeInfo at chart entry and every 15 minutes while active.
- Bookmap and Depth Ladder now consume the backend's sequence-validated Spot diff-depth book through a local read-only API. The browser no longer opens an unsequenced depth20 partial stream.
- Trade Flow shows observed AggTrade-derived buy/sell volume, delta, delta ratio, CVD since stream seed, footprint, volume profile and microprice with provenance.
- UTC session delta is displayed as complete only when the stream reports complete UTC-session coverage; otherwise the sample is explicitly labelled incomplete.
- USDⓈ-M Futures, COIN-M Futures, Gold and Forex depth are not claimed as supported. No real orders or live-money execution are enabled.

### Next steps

1. Confirm the triggered live smoke result and distinguish live WAIT from provider/engine errors.
2. Run the local app after automatic source update and verify BTCUSDT plus a non-USDT Spot pair, then XAUUSD unavailable state.
3. Extend deterministic API/replay coverage for reconnects, trade gaps, book sequence gaps and stale snapshots at the UI boundary.
4. Continue primary signal-engine validation: dynamic universe end-to-end scans, valid long/short replay, walk-forward OOS and paper execution costs.
5. Resolve Telegram notification destination by setting a valid private/group chat ID; do not expose bot token in chat.


### Live smoke result after PR #250 — run 44884113669

- Workflow completed successfully on the updated main commit.
- Binance Spot exchangeInfo reported 1,376 eligible pairs.
- The rotating read-only sample scanned 20 pairs, including non-USDT quote pairs (for example XRPIDR, XRPJPY and XRPUSDC).
- Result: 20 successful scans, 0 insufficient-history skips, 0 provider/error failures.
- All 20 returned WAIT with reason NOT_EVALUATED_NO_DIRECTIONAL_SETUP. This means no directional strategy setup qualified; it is not evidence of a generated signal or profitability.
- Order Flow was correctly marked NOT_EVALUATED_NO_DIRECTIONAL_SETUP / accepted=n/a because no directional candidate reached the Order Flow gate. This run therefore does not validate the new UI stream or prove Order Flow confirmation behavior.
- This remains a 20-pair rotating smoke subset, not full-universe coverage. Full dynamic-universe scan scheduling and realistic long/short replay remain separate acceptance items.


### Phase C15 — QUANTNEX VIEW Binance USDⓈ-M Futures chart

- Added a separate dynamic USDⓈ-M perpetual universe sourced from Binance `/fapi/v1/exchangeInfo`; only `status=TRADING` and `contractType=PERPETUAL` are eligible. Delivery contracts and COIN-M are excluded.
- Added read-only USDⓈ-M historical candles from `/fapi/v1/klines`, with closed-candle validation, malformed OHLC filtering, minimum 210 bars, and explicit stale-data status.
- Added live Futures chart kline WebSocket using `wss://fstream.binance.com/ws/{symbol}@kline_{interval}`.
- QUANTNEX VIEW now has separate market-type and pair selectors. Tickers use `[EX-BTCUSDT]` for Spot and `[EX-BTCUSDT.P]` for USDⓈ-M perpetual Futures. Pair universe refreshes every 15 minutes while chart is active.
- Futures selection is persisted independently from the pair. Switching market type cannot accidentally send a Spot symbol to the Futures feed or vice versa.
- Important boundary: this phase adds chart market data only. Futures order-flow, Futures signal generation, funding/OI/liquidation confluence, and order execution are not enabled. Spot signal/order-flow engine remains Spot-only. No COIN-M support is claimed.
- Deterministic tests are added for metadata filtering, closed candle parsing and invalid symbols; local browser/live WebSocket verification remains pending.

- Additional safety review: QUANTNEX VIEW's intelligence controller previously auto-called the Spot analyze/replay/backtest endpoints for any selected symbol. Added an explicit USDⓈ-M Futures guard so Futures charts cannot silently show Spot signals/ledger/backtests for the same raw ticker. Futures chart selection now displays a clear "Futures chart only" status and clears the Spot trade plan.

- Chart history accepts any non-empty set of valid closed Futures candles (rather than requiring 210), so recently listed eligible perpetual contracts can still display; indicator warm-up is disclosed by the existing chart renderer.


### Phase C15 merge and post-merge verification — PR #254

- PR [#254](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/254) squash-merged to main as `28071b133d02169f1391ae7b8823d45a3a0cd632` on 2026-11-21.
- Branch was 21 commits ahead and 0 behind main at final review; PR was mergeable; 11 changed files were within the Futures chart, tests and documentation scope; secret-pattern review found no credentials or private keys.
- Pre-merge CI passed on head `3e98caa56f8cf94834290e56aad365ee75f416aa`: Backend Python 3.12 (500 passed), Python 3.14 (500 passed), Web CI and Backend/Web CI all successful.
- Post-merge CI passed on exact main commit `28071b133d02169f1391ae7b8823d45a3a0cd632`: Backend Python 3.12, Python 3.14 and Web CI successful. Each Python suite reported 500 passed.
- Main ref verified equal to the merge SHA.
- Telegram update notification workflow failed at the separate announce step; previously identified `TELEGRAM_CHAT_ID` points to the bot itself. Source deployment and code CI are unaffected.
- Futures endpoint tests are deterministic/mocked; no external live Binance Futures endpoint check or user-device browser rendering has been claimed.

### Phase C15 final capability boundary

- QUANTNEX VIEW now charts Binance Spot and Binance USDⓈ-M PERPETUAL instruments with dynamically refreshed exchange metadata.
- Display labels: `[EX-BTCUSDT]` for Spot and `[EX-BTCUSDT.P]` for USDⓈ-M perpetual. The raw symbol sent to Binance remains `BTCUSDT`.
- Futures candles: `/fapi/v1/klines`; live stream: `wss://fstream.binance.com/ws/{symbol}@kline_{interval}`. Only valid closed candles are used; non-empty short histories are allowed and chart indicators show warm-up.
- Futures chart selection is isolated from Spot signal analysis, Spot replay, Spot backtest and Spot signal ledger. It is chart-only and read-only.
- COIN-M, Futures Order Flow, Futures signal generation, funding/open-interest/liquidation confluence and execution remain unsupported. No live orders or margin actions.
- Next: add independent USDⓈ-M Order Flow state/stream validation and Futures signal engine only after market-type-specific historical replay and execution-cost tests exist; keep Spot and Futures semantics separate.



### Phase C16 — QUANTNEX VIEW compact chart workspace and position table

- Moved Signal Timeframe Preferences into a compact Settings control at the top of QUANTNEX VIEW. The existing setting IDs, local persistence, Telegram sync and apply-to-chart actions are retained.
- Added one consolidated Technical Indicators table for RSI, MACD, ADX, ATR, Stochastic and CCI. It starts collapsed to preserve chart height; indicator calculations and live values continue to update from chart candles while collapsed, and mini charts redraw at their expanded dimensions.
- Made the Live Structure / Confirmation sheet and Signal Outcomes / Results sheet independently collapsible. Their existing live analysis, lifecycle reconciliation and periodic refresh paths remain active while the sheets are hidden. The Signal Outcomes data model and result logic were intentionally not changed pending the user's next instructions.
- Added a dedicated Live Signals table directly below the chart. It is populated by the existing selected-market analysis cycle (60-second active-view refresh), includes entry type/reference price, SL, TP1–TP3, confluence and status, and explicitly refuses to apply Spot signals to a USDⓈ-M Futures chart.
- Placed the Sri Lanka / New York market-session clock and session table below the Live Signals table.
- Removed the unused Live Trade Results Calculator UI and its browser-side market-tick listeners.
- Removed the separate Live Strategy Engine / catalogue / backtest panel from QUANTNEX VIEW. The existing read-only chart analysis path remains in place only to feed the Live Signals table, chart sheet and lifecycle history; this UI cleanup does not claim a new strategy or improve signal accuracy.
- Upgraded the manual Position Tool's calculated summary from separate metric cards to a readable table with side, entry, stop distance, targets, equity, risk amount, estimated lots and gross target-profit estimates. Broker contract/tick value assumptions still require user verification; estimates exclude execution costs.
- Pre-merge validation: Web CI and Backend/Web CI passed on PR #256 head fac7ef3a4c804d30edb1c236383989bca3ddfd99; the web contract suite and Python 3.12 / 3.14 backend suites passed. Post-merge Web CI and Backend/Web CI also passed on main commit a77f57107bb936b4e3b884059f5b80311c13fc77. Browser/device visual rendering was not independently verified in this run. No live-money execution, order placement, Futures signals or Futures Order Flow were added.


### Phase C16 merge record — PR #256

- Squash-merged PR #256 into main: a77f57107bb936b4e3b884059f5b80311c13fc77.
- Post-merge verification: QUANTNEX Web CI passed; QUANTNEX Backend and Web CI passed, including Python 3.12, Python 3.14 and the Web check.
- Separate Telegram Update Notifications workflow did not send: its configured TELEGRAM_CHAT_ID resolves to the bot itself. This is a notification configuration issue and did not affect the merge or CI results; the notification workflow correctly reported the configuration error.
- Local supervisor auto-update will apply the merged version on its next normal update cycle / next app launch. Browser-device rendering still needs user-side confirmation.


## 2026-11-22 — Phase C18 follow-up: dynamic smoke isolation and CI regression fix (PR #278)

- Main at run start: `b4daeb862f90ad142f485035d5eb9422724edc70`, following merged PR #277 for separate dynamic Binance Spot and USDⓈ-M smoke samples.
- PR #277 exposed a test-fixture defect: the mocked USDⓈ-M analyzer accepted positional arguments only, while production calls it with keyword `min_score`. The resulting `TypeError` was incorrectly counted as a Futures provider failure. Main CI therefore had 1 failing test (540 passed) on both Python 3.12 and 3.14.
- PR #278 fixes the stub signature and adds a regression test. It also keeps the independent USDⓈ-M smoke sample running if Spot `exchangeInfo` discovery fails, while preserving a non-zero overall exit code for the Spot provider error. Invalid sample configuration remains a distinct exit code.
- PR #278 CI on head `62afa85e39072113277e6b8f3eb6763ca3dd0190`: Backend CI **542 passed**; Backend/Web CI **542 passed on Python 3.12**, **542 passed on Python 3.14**, and Web check passed. Full diff contains only the smoke runner and its tests; no credentials or order-placement paths were added. Merge and post-merge verification are pending.
- Scheduled Spot smoke run [#45000648674](https://github.com/adeeshadasuniduwara/QUANTNEX/actions/runs/45000648674), 2026-11-22 07:58 UTC, main SHA `f47f9c5399ac46572d7d856604f1687e913aa4e3`: discovered **1,376** eligible Spot pairs and scanned a rotating sample of **20**; **20 WAIT**, **0 provider errors**, **0 insufficient-history skips**. All candidates reported `NOT_EVALUATED_NO_DIRECTIONAL_SETUP`; Order Flow was not evaluated because no directional candidate passed. This validates live Spot data/scan health only, not signal generation quality or profitability.
- USDⓈ-M live smoke attempt [#45002095522](https://github.com/adeeshadasuniduwara/QUANTNEX/actions/runs/45002095522), 2026-11-22 08:17 UTC, returned HTTP **451** from the public `/fapi/v1/exchangeInfo` request on the GitHub-hosted runner. The Spot leg still discovered 1,376 pairs and completed 20 WAIT scans. The Futures provider error is intentionally not suppressed; this is an environment/access blocker, not proof that the Futures endpoint is unavailable everywhere. The exact local-network check remains outstanding.
- Open PR #275 contains an earlier copy of the dynamic USDⓈ-M smoke expansion and its PR-triggered live smoke workflow; its live run also hit HTTP 451. Do not merge a failing live-provider check or mask the status code. PR #278 is the focused main-based correction for the regression and independent scan behavior.

### Current core state and next exact steps

- Phase C18 is merged: PR #277 (`b4daeb862f90ad142f485035d5eb9422724edc70`) and PR #278 (`ad3c190ae2ce60280dcba60ef943d3bfb1ce9333`). Dynamic Spot/USDⓈ-M exchangeInfo discovery and bounded rotating samples are in main. Spot is sampled over its complete eligible universe across rotations; USDⓈ-M remains a separate candle-only monitor. COIN-M is unsupported.
- The most recent scheduled smoke run remains [#45000648674](https://github.com/adeeshadasuniduwara/QUANTNEX/actions/runs/45000648674), 2026-11-22 07:58:53 UTC, before the USDⓈ-M smoke change was merged: 1,376 eligible Spot pairs, 20 sampled, 20 WAIT, 0 provider errors, 0 insufficient-history skips. No scheduled smoke run for 2026-11-23 was visible at this checkpoint. The current workflow supports `workflow_dispatch`, but the connected GitHub actions tools in this run expose no dispatch action.
- The separate USDⓈ-M runner attempt [#45002095522](https://github.com/adeeshadasuniduwara/QUANTNEX/actions/runs/45002095522) returned HTTP 451 from `/fapi/v1/exchangeInfo` on GitHub-hosted infrastructure. Treat this as a provider/access failure, not WAIT or proof of global endpoint unavailability.
- Phase C19 PR #299 is merged to main as `518d27817447e3a02413ae7fb44e630be55b54e3`. Post-merge Backend CI passed **598 tests on Python 3.12** and **598 on Python 3.14**; Backend/Web CI's web-check passed; Telegram update notification workflow passed. The final Spot MARKET/LIMIT selector now requires both observed aggressor delta and sequence-validated L2 depth to support MARKET urgency; a neutral component prefers a valid favorable LIMIT, otherwise WAIT.
- Old PR #281 (stale duplicate of C19), #284 (duplicate raw recorder), and #275 (superseded dynamic smoke implementation) were reviewed, commented and closed. PR #270/#266/#265/#262/#259 and other unrelated work remain open; do not mix them into signal-engine phases.
- A read-only Binance connector sanity check on 2026-11-23 returned Spot exchangeInfo at serverTime **07:05:58.950 UTC**: 3,711 total symbols, **1,376** active `TRADING` Spot pairs, **526** active USDT-quote pairs. BTCUSDT metadata reported tick size 0.01, LOT_SIZE step/minQty 0.00001 and min notional 5 USDT.
- A 1,000-row BTCUSDT aggregate-trade sample from 07:04:45.119–07:06:16.135 UTC had contiguous aggregate-trade IDs 4,128,697,563–4,128,698,562; buyer-aggressor volume 5.01330 BTC, seller-aggressor volume 2.59346 BTC, delta +2.41984 BTC and delta ratio +0.31812. Binance `m=false` means buyer is taker; `m=true` means buyer is maker/seller is taker. This is a recent bounded sample, not full-session CVD or a consolidated bid/ask footprint.
- A parallel REST top-20 BTCUSDT book snapshot showed about 20,181.50 USDT bid notional vs 753,314.96 USDT ask notional (imbalance -0.94782), but it was **not sequence-validated continuous depth** and must not enter the live flow gate. The trade and REST book samples are not a synchronized signal snapshot; no trade is inferred.
- The Binance connector's USDⓈ-M exchangeInfo response carried serverTime **02:35:56.128 UTC**, roughly 4h30m older than the Spot response. Treat that connector result as stale/cached; do not use its 956-symbol/567-perpetual/522-USDT-margined counts for live Futures validation.
- Exact next steps: finish the C20 raw-event coverage audit, validate truncation/trade-ID/depth-sequence/session/backfill diagnostics, run Backend CI + Backend/Web CI on Python 3.12/3.14, review the focused PR and merge only if clean. Then add event-level chronological replay and candle-only / aggressor-only / L2-only / combined ablations with fees, spread, slippage and realistic LIMIT fills. No performance uplift claim from sparse/non-random capture.
- Spot remains the only market type with sequence-validated live Order Flow. USDⓈ-M is candle-only monitor mode; Futures Order Flow/funding/OI/liquidation-aware entries and COIN-M remain unsupported. No real orders or real-money mode.

## 2026-11-23 — Phase C19: Spot Order-Flow-aware final entry selection (merged)

- PR #299 merged to main as `518d27817447e3a02413ae7fb44e630be55b54e3`.
- Final Spot entry selection now occurs after the accepted live/replay Order Flow decision. MARKET requires both observed aggregate-trade aggressor delta and sequence-validated L2 quote-notional depth imbalance to support the candidate direction, plus the existing spread/depth/drift/order-type/exchange-filter gates. If one component is neutral, MARKET is disabled and a valid favorable LIMIT retracement may be selected; otherwise WAIT.
- The signal and Order Flow payload expose entry-selection evidence, freshness, depth update ID and provenance. No new score/threshold or signal-frequency relaxation was introduced.
- Post-merge Backend CI: 598 passed on Python 3.12 and 598 passed on Python 3.14; Backend/Web web-check and Telegram update notification workflow passed. The initial missing pytest import was fixed before the final green run.
- Stale duplicate PRs #281, #284 and #275 were reviewed, commented and closed. No live order or real-money capability was added.

## 2026-11-23 — Phase C20: bounded raw-event coverage audit (feature branch)

### Implemented on `feat/spot-raw-event-coverage-audit`
- Extend `summarize_order_flow_candles` to count the total events in the requested range before trusting its bounded sample; expose total vs loaded events and an explicit `TRUNCATED_EVENT_WINDOW` status when the 5,000-row/200-events-per-minute cap is reached.
- Audit observed aggregate-trade IDs across minute boundaries, depth-update U/u continuity across minute and query-window boundaries, REST snapshot-to-first-diff bridge validity, session changes, REST gap-backfill sources and explicit capture-queue-overflow markers.
- A review found the initial per-minute baseline check would incorrectly require a new REST snapshot every minute. The implementation now carries the latest prior validated depth update into a mid-session query, propagates sequence invalidity until a new snapshot re-anchors the stream, and distinguishes an unanchored session from a sequence-invalid one.
- Report source counts, session counts, depth sessions, stream-session count/transition count (a reconnect/restart proxy, not a verified socket-close cause), trade-ID range/gaps, depth sequence gaps, baseline validation, gap reasons and `coverage_is_complete=false`.
- Preserve the key safety rule: even a contiguous observed event sample is `OBSERVED_PARTIAL_NOT_PROVEN_COMPLETE`; no event summary is labelled a complete candle or a full-session feed.
- Deterministic tests cover aggTrade ID gaps within and across minute buckets, depth diff gaps across minute boundaries, valid depth continuity across minute and query-window boundaries, invalid snapshot bridge, persistent invalidity after a sequence gap, multi-session boundary with REST backfill, bounded-window truncation and invalid summary limits. Existing raw recorder persistence/idempotency/capture-gap tests remain.

### Verification boundary
- Branch base: `518d27817447e3a02413ae7fb44e630be55b54e3` (C19 post-merge main).
- Code commits: `3e5984f056e4bd07cfb6e2231a1b05801ec602de` (coverage audit), `2c144263caaae930341cbd96b1a87b0186521bbb` (invalid bridge flag), `0369b31276530cc29249caedfbb34bc844afdbe1` (initial tests), `27dbb513017cf84cfd5e9236c46635b3f28ba6ec`, `8678da6ae290337e5d35c07de1937f3a2b458bd7`, `2189d8f51e7741392836bda326fedb815cf953ec`, `68a84657c5328a85af82584ced72d67b7f62cfad` (cross-window sequence-state corrections), `d7210b793391ea67ea5e18bd45bcb15a92d965a3` and `8505fe1721288b7340abc46691900c6ab8831326` (boundary fixtures), and `1409dd4bfdc925872212089cd914fa20c9a3d531` (snapshot-bridge classification), and `c8d917f1cbfd699d7d5df167d9956c1a2a366d5a` (capture-gap recovery fixture).
- Corrected-head CI passed on `c8d917f1cbfd699d7d5df167d9956c1a2a366d5a`: Backend CI **607 passed on Python 3.12**; Backend/Web CI **607 passed on Python 3.12 and 607 passed on Python 3.14**; schema test and Web check passed. Added a capture-gap invalidation/re-snapshot re-anchor fixture and tightened the mid-window baseline assertion. Earlier attempts exposed snapshot-bridge classification and fixture-ordering issues; those were corrected before this green head.
- No raw replay performance result, win-rate improvement or profitability claim is made by this coverage diagnostic.

### Merge and post-merge verification
1. PR #300 was squash-merged to main as `b5b3eb609fdeff005536345cb406882a3cef3215` on 2026-11-23 07:53:19 UTC.
2. The exact main merge SHA passed [Backend CI #45134362671](https://github.com/adeeshadasuniduwara/QUANTNEX/actions/runs/45134362671) and [Backend/Web CI #45134362665](https://github.com/adeeshadasuniduwara/QUANTNEX/actions/runs/45134362665), including Python 3.12, Python 3.14 and Web checks.
3. PR #300 changed only the raw-event recorder, its tests and the two progress documents. It adds bounded-window/truncation diagnostics, cross-minute trade/depth sequence checks, reconnect/session indicators, backfill provenance and capture-gap invalidation. No profitability uplift was claimed.
4. Next: validate the audit against retained local capture, reject truncated/unanchored/gapped windows from raw replay, then compare candle-only, delta-only, L2-only and combined methods on identical chronological folds with fees, spread, slippage and realistic LIMIT fills.

### 2026-11-23 live read-only Binance Spot provider sanity check
- Binance Spot `exchangeInfo` at serverTime `2026-11-23T07:43:44.586Z`: 3,711 total symbols, 1,376 `TRADING` and `isSpotTradingAllowed=true` symbols, including 526 USDT-quoted pairs. Metadata returned symbol-specific PRICE_FILTER, LOT_SIZE and NOTIONAL filters; BTCUSDT tick 0.01, step/minQty 0.00001, minNotional 5 USDT.
- BTCUSDT and NEOUSDT each returned 210 valid 5m kline rows. The final row was still forming at the observation time; the engine must continue to exclude it from closed-candle decisions.
- A bounded BTCUSDT aggregate-trade sample contained 1,000 contiguous IDs (4,128,724,112–4,128,725,111): buyer-taker quantity 6.13503 BTC, seller-taker quantity 10.72028 BTC, inferred aggressor delta −4.58525 BTC (`m=false` buyer taker; `m=true` seller taker).
- A separate REST top-20 book snapshot had 20 bid and 20 ask levels, 0.001626 bps best spread and −0.98062 quote-notional imbalance. This snapshot was not sequence-validated or synchronized to the aggregate-trade sample; it is not eligible for the live Order Flow gate. No live signal was inferred from these independent samples.

### 2026-11-23 latest-main smoke audit
- Latest completed QUANTNEX Live Crypto Signal Smoke run: [#45000648674](https://github.com/adeeshadasuniduwara/QUANTNEX/actions/runs/45000648674), 2026-11-22 07:58:53 UTC, commit `f47f9c5399ac46572d7d856604f1687e913aa4e3` (older than current main). It discovered 1,376 eligible Spot pairs, scanned a rotating 20-symbol sample, and completed 20/20 scans with 0 history skips and 0 provider errors. All 20 returned WAIT; every row reported `NOT_EVALUATED_NO_DIRECTIONAL_SETUP`, so this run did not exercise the Order Flow confirmation gate and is not evidence of a live trade setup.
- The current main smoke workflow now configures both a 20-pair Spot sample and a separate 20-contract USDⓈ-M sample. The latest completed run above predates that workflow version and its job command only invoked the Spot sample; no completed smoke run on the current main head was found. USDⓈ-M remains monitor-only and the prior GitHub-hosted fapi exchangeInfo HTTP 451 remains a provider-access limitation.

## 2026-11-24 — Automation run: Phase C21 causal raw-event Spot replay (implementation branch)

### Start-of-run repository audit
- Default branch at start: `b5b3eb609fdeff005536345cb406882a3cef3215` (PR #300 merged).
- Inspected current README, `AUTOMATION-PROGRESS.md`, `ORDER-FLOW-ROADMAP.md`, the live smoke workflow/runner, raw recorder, Spot order-flow state/stream, signal engine/method registry, walk-forward harness and relevant tests.
- No open repository issues were returned. Open PRs include #270, #266, #265, #262, #259, #239 and older unrelated UI/Telegram/Android work; none was folded into this signal-engine branch.
- Mainline post-merge Backend CI and Backend/Web CI for #300 passed on exact main SHA. The latest scheduled Live Crypto Signal Smoke run [#45143589597](https://github.com/adeeshadasuniduwara/QUANTNEX/actions/runs/45143589597) completed with **failure** at the combined Spot/USDⓈ-M scan step. The job summary exposed no provider exception or per-symbol output, so the precise cause is **not verified**. A previous GitHub-hosted USDⓈ-M `/fapi/v1/exchangeInfo` attempt returned HTTP 451, but that prior error must not be assumed to explain this newer run. The smoke failure is not a WAIT result and is not counted as a successful live scan.

### Phase C21 implementation on `feat/spot-raw-event-chronological-replay`
- Add `backend/app/order_flow_replay.py`: deterministic replay of archived Binance Spot aggregate trades, REST depth bootstrap snapshots, sequence-applied diff-depth events and raw-capture gap markers.
- Use receive-time buckets as the replay information clock; emit only completed buckets. Exchange event timestamps remain separate for trade/depth freshness. Later-arriving backfill cannot change a checkpoint that was already emitted.
- Reuse `AggTradeCvdState` for buyer-is-maker aggressor-side inference, contiguous aggregate-trade IDs, CVD since the first captured seed and delayed REST gap recovery. Backfill and bootstrap volumes are reported separately from live receive-bucket delta.
- Reuse `BinanceSpotDepthBook` for snapshot/diff reconstruction. A stream-session change invalidates the old book until a new snapshot and bridging diff validate the new session. Sequence gaps keep depth unusable until re-snapshot.
- A raw capture-gap marker permanently vetoes replay eligibility for the archive window. Full UTC session delta remains null without an explicit session-start trade-ID anchor. `coverage_is_complete=false` is retained even for internally contiguous captured windows.
- Expose data provenance, delta/quote delta, CVD scope/status, trade/depth ages, L2 metrics, sequence state and explicit replay eligibility. This module is research-only; it is not wired into live signal generation and does not place orders or relax quality gates.

### Deterministic coverage added
- BUY and SELL taker-delta/CVD fixtures with hand-computed expected deltas.
- L2 snapshot/diff reconstruction and directionally opposite depth-imbalance fixtures.
- Exclusion of incomplete receive-time buckets.
- Trade-ID gap veto, delayed REST backfill recovery, and proof that the earlier pre-backfill checkpoint remains invalid.
- Depth sequence-gap veto and stream-reconnect invalidation until a fresh snapshot/diff bridge.
- Persistent capture-gap veto even after later depth re-anchoring.
- Stale trade/depth age rejection, market-type/symbol isolation, future receive-time and naive-clock rejection.
- These are deterministic replay fixtures, not live signals or a profitability sample.

### Changed files and branch commits
- `backend/app/order_flow_replay.py` — `dbdc42253bcc98b840a4e6fc1e525b7a6d7ca698`, `efdbd24ac3ee0dcee76bcffa3a8b95266f9d9c9c`, `7dc1b2a268c38b9eaa3e85da1f88de0286a1f86f`.
- `backend/tests/test_order_flow_replay.py` — `cf1c108ceecfff2d41f8e044caba76485809cc94`, `96f3ebe8ca10ff82a83666ea289988a7dc836e52`.
- `docs/ORDER-FLOW-ROADMAP.md` — `84cdb3e98e47ccc411b6db844ad189ae0ea88d7b`.
- CI-verified code/test head: `01ec41ca69001f50c81cbc7a273058a97a0997ee`.

### Verification / PR #301
1. PR #301: https://github.com/adeeshadasuniduwara/QUANTNEX/pull/301, based on main SHA `b5b3eb609fdeff005536345cb406882a3cef3215`, is open and GitHub reports it mergeable/clean at head `01ec41ca69001f50c81cbc7a273058a97a0997ee`.
2. Backend CI passed. Backend/Web CI passed: **621 tests on Python 3.12**, **621 tests on Python 3.14**, plus the Web check. The standalone schema/compile Backend CI also passed.
3. Full PR diff is limited to `order_flow_replay.py`, its deterministic tests and the two progress documents. Secret-pattern scan found no matches; no order-placement references or live-order paths were added.
4. No local Python execution or retained Windows raw-archive replay was performed. GitHub CI verifies deterministic fixtures only; the user's local SQLite archive and WebSocket capture remain unverified.
5. Merge only after refreshing the exact head/base and all checks, then verify the merge commit on main and run post-merge checks.
6. Next core work: adapt the chronological walk-forward harness to consume only validated replay checkpoints, then run candle-only / aggressor-only / L2-only / combined ablations with fee, spread, slippage and conservative LIMIT expiry/fill assumptions. No OOS metrics or predictive uplift are available yet.
7. Binance Spot remains the only market type with sequence-validated live Order Flow. USDⓈ-M remains candle-only monitor mode; COIN-M remains unsupported. Never place live orders or enable real-money trading.

### 2026-11-23 latest-main dynamic Binance smoke run (log-verified)
- [QUANTNEX Live Crypto Signal Smoke #45143589597](https://github.com/adeeshadasuniduwara/QUANTNEX/actions/runs/45143589597) ran on main SHA `b5b3eb609fdeff005536345cb406882a3cef3215`.
- Binance Spot discovery returned **1,376 eligible Spot pairs**; the rotating sample scanned **20/20 successfully**, with **0 history skips** and **0 Spot provider errors**. This verifies a successful bounded live Spot scan, not a same-run scan of every eligible pair.
- All 20 returned WAIT. Every row reported `NOT_EVALUATED_NO_DIRECTIONAL_SETUP`; therefore the live Order Flow confirmation gate was not exercised. WAIT is not a test of the signal's predictive quality.
- USDⓈ-M discovery failed with the explicit provider response **HTTP 451** from the public exchangeInfo endpoint. It produced **0 successful USDⓈ-M scans** and one provider/error failure; the workflow correctly exited non-zero. This is a provider-access failure, not a Futures WAIT.
- The prior note about 451 is now confirmed by the latest run log. A local-network USDⓈ-M access check remains required. Do not claim USDⓈ-M live signal coverage from the GitHub runner.


## 2026-11-24 C22 — Raw Binance Spot event replay integrated into walk-forward (PR pending)

### Starting checkpoint and repository audit
- Latest main at run start: 347b992245c9a5fdde8e3bb4ce8647cdcfbf1baf, merge commit for PR #301. PR #301 is confirmed closed/merged.
- The prior C21 replay module existed but was only a deterministic replay library. The walk-forward harness consumed the older minute feature-snapshot format; it did not consume raw archived aggTrade and depth-diff events.
- Existing main CI immediately before this branch had passed 621 tests on Python 3.12, 621 tests on Python 3.14, and the Web check. The latest scheduled smoke metadata still points to the earlier main SHA b5b3eb609fdeff005536345cb406882a3cef3215; no post-C21 smoke result is available yet.
- Open PR review and latest workflow history were inspected. No open core signal/order-flow PR superseded this checkpoint.

### C22 implementation
- backend/app/signal_backtest.py
  - Added raw checkpoint provenance validation and a selector that only chooses the latest receive-time checkpoint at or before each candle decision.
  - Recomputes trade/depth freshness from exchange event timestamps at the decision boundary; rejects future event timestamps relative to the checkpoint, stale sources, trade-ID gaps, depth sequence gaps, capture-gap markers, missing live-bucket trades and false full-coverage declarations.
  - Adapts eligible raw replay checkpoints to the existing fail-closed order-flow confirmation and entry-selection path. Missing/ineligible latest checkpoints do not fall back to older valid checkpoints.
  - run_signal_walk_forward now accepts raw_order_flow_events, reconstructs checkpoints once against the closed-candle replay horizon, and reports raw event/checkpoint/eligibility counts separately from feature snapshots.
  - OOS fold aggregation now preserves raw-checkpoint match counters. Candle-only baseline and order-flow variant retain the same chronological folds and modeled execution assumptions.
- backend/app/order_flow.py
  - Recognizes RAW_EVENT_REPLAY as a sequence-validated Spot depth source and describes its bounded-archive and receive-time limitations accurately; it is not mislabeled as a single REST snapshot.
- backend/app/order_flow_raw_recorder.py
  - Added a separate receive-time archive query. It returns the latest bounded events in chronological receive order and explicitly reports total count/truncation. The existing event-time query remains unchanged for event-time research endpoints.
- backend/app/main.py
  - The signal walk-forward API now supports order_flow_replay_source=AUTO|RAW_EVENTS|FEATURE_SNAPSHOTS. Default AUTO prefers raw events when any are present and falls back to feature snapshots only when the raw archive is empty. A non-empty but invalid/incomplete raw archive is never hidden by fallback.
  - API response/audit metadata reports the actual source, receive-time clock, event/checkpoint counts and archive truncation.
- Deterministic tests added: raw-event BUY and SELL signal fixtures, contradictory delta/depth veto, capture-gap no-fallback, stale/future checkpoint handling, event-time-ahead-of-checkpoint rejection, bounded-coverage validation, full walk-forward raw-event wiring, receive-time inclusion of late REST backfill, and explicit truncation behavior (11 parametrized/test cases).

### Verification boundary
- The new branch has not yet been run through GitHub CI at the time of this note. Local git clone/Python execution was unavailable because the runner could not resolve github.com; no test pass is claimed.
- Raw replay is still Binance Spot only. It uses aggressor delta plus sequence-validated L2 directional sign confluence; CVD is surfaced with bounded-seed provenance but is not yet a calibrated divergence score. No predictive uplift or profitability claim is made.
- AUTO uses at most the latest 5,000 retained raw events for the requested receive-time window; truncation is explicit. Raw event archives remain bounded and coverage_is_complete=false. The feature-snapshot path remains available.
- USDⓈ-M is still candle-only monitor coverage on the GitHub runner due HTTP 451 on exchangeInfo; COIN-M remains unsupported. No live orders or real-money routing were added.

### C22 changed files
- backend/app/signal_backtest.py
- backend/app/order_flow.py
- backend/app/order_flow_raw_recorder.py
- backend/app/main.py
- backend/tests/test_signal_backtest.py
- backend/tests/test_order_flow_raw_recorder.py
- docs/AUTOMATION-PROGRESS.md
- docs/ORDER-FLOW-ROADMAP.md

### Next steps
1. Run Backend CI on the C22 PR; fix any failures before considering merge.
2. Review the full diff and secret scan; verify PR base/head and mergeability, then merge only if every required check passes.
3. Verify post-merge main and run the backend suite again.
4. Use the local retained raw archive through the new AUTO path; report archive truncation, eligible checkpoint count, coverage and OOS sample size. Do not interpret sparse/seeded CVD as a full session.
5. Add aggressor-only / L2-only / combined ablations and CVD-divergence features only after deterministic causal definitions and tests; retain the current quality gate.


## 2026-11-24 C22 — Raw Binance Spot event replay merged

### Merge and verification
- PR [#302](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/302) merged to `main` as squash commit `c69a0589ce1b0effdf1e9b893330f38d135b38fb`.
- The PR head `94b2f65b8750e670beadc24b347fa7679c7d1346` passed `test`, `backend-tests (3.12)`, `backend-tests (3.14)`, and `web-check`.
- Post-merge checks on the merge commit also passed: `test`, `backend-tests (3.12)`, `backend-tests (3.14)`, and `web-check`. The Telegram announce workflow also completed successfully.
- The merge only connects archived raw Binance Spot events to the causal walk-forward harness. It does not establish live predictive value or profitability.

### C22 evidence boundary clarification
- The receive-time archive query returns the newest bounded 5,000 events and exposes `total_count` and `truncated`.
- A truncated archive is not automatically equivalent to a sequence gap: a recent bounded segment may still be internally contiguous from its captured trade seed and sequence-valid depth bridge. Such a checkpoint may be used only as a bounded observation; `coverage_is_complete=false`, CVD remains since-seed, and UTC full-session delta is not inferred.
- Any actual trade-ID gap, capture-gap marker, stale/future source, invalid depth bridge or malformed latest checkpoint remains fail-closed. The walk-forward response must retain the archive truncation flag beside any replay metrics.

## 2026-11-24 C23 — Order Flow directional-vote ablations (PR pending)

### Goal
Measure whether observed Binance Spot aggressor-side delta, sequence-validated L2 depth imbalance, or their combined directional confirmation changes the same candle strategy's historical decisions. This is a controlled research ablation, not a live-strategy threshold change.

### Changes on branch `feat/order-flow-evidence-ablation-replay`
- Added explicit `COMBINED`, `AGGRESSOR_ONLY` and `L2_ONLY` evidence modes to the existing order-flow confirmation function.
- Applied the same evidence mode to MARKET-versus-LIMIT urgency selection, so the directional vote is consistently isolated through both confirmation and entry selection.
- Kept both underlying feeds subject to existing freshness, provenance and feed-specific integrity checks in every variant. AGGRESSOR_ONLY does not bypass depth sequence integrity; L2_ONLY does not bypass trade-side provenance or freshness.
- Extended chronological walk-forward replay to run the three variants on identical training/OOS windows and execution assumptions, alongside the existing candle-only baseline.
- Added per-variant OOS summaries and deltas for trade count, win rate, expectancy, net PnL, estimated costs and max drawdown, plus order-flow coverage/confirmation counters. Existing combined result fields remain available for compatibility.
- Added deterministic tests for conflicting aggressor/L2 votes, invalid ablation modes, entry-urgency mode consistency and raw-event walk-forward variant wiring.

### Merge and verification
- PR [#303](https://github.com/adeeshadasuniduwara/QUANTNEX/pull/303) merged to `main` as squash commit `f986dbae4d3012e6fbb43d5613d5d028adc74337`.
- The PR head `a99d29cb0b09a11f7fe7c99585176161172bf7df` passed `test`, `backend-tests (3.12)`, `backend-tests (3.14)`, and `web-check`.
- Post-merge checks on `f986dbae4d3012e6fbb43d5613d5d028adc74337` also passed: `test`, both backend Python versions, `web-check`, and the Telegram announce workflow.
- The live/default signal path remains `COMBINED`; the ablation modes are invoked only by the historical walk-forward harness. No live order or real-money path was added.
- The comparison is a descriptive experiment. No local retained archive was run and no predictive uplift, win-rate improvement or profitability is claimed.

### Current limitations
- Both trade and L2 streams remain required to pass their existing freshness, provenance and feed-specific integrity gates in every ablation. The experiment does not prove either feed can operate safely when the other is absent.
- Binance Spot is the only market type with sequence-validated live/raw Order Flow. USDⓈ-M remains candle-only monitor coverage because the latest GitHub-runner exchangeInfo request returned HTTP 451; COIN-M remains unsupported.
- The latest recorded dynamic smoke run is still the 2026-11-23 run: 20/20 rotating Spot sample requests succeeded and all were WAIT with no directional setup; USDⓈ-M discovery failed with HTTP 451. There is no post-C23 live smoke result in this checkpoint.
- The user's local retained SQLite raw-event archive has not been exercised. Real OOS metrics remain unavailable until its eligible checkpoint coverage and truncation are measured.

### Next steps
1. Run the walk-forward API against the retained local Binance Spot archive. Record total events, truncation, completed/eligible checkpoints, OOS bars, matched decisions and all three variant metrics before interpreting results.
2. Verify the stored minute series carries a causally valid CVD value and status at each closed UTC M1 boundary. If it does not, extend the recorder with explicit seed/gap/reset provenance first.
3. Add a causal CVD-divergence classifier only from confirmed price pivots and same-boundary CVD observations; use hand-computed LONG/SHORT, false-divergence, gap, reset and stale-data fixtures.
4. Measure CVD divergence and existing absorption/exhaustion patterns as separate ablations against the same candle-only baseline. Do not stack them as independent votes without incremental-value evidence.
5. Continue Binance Spot signal-quality validation; keep USDⓈ-M and COIN-M capability claims restricted to verified support. Paper/replay only.


## C24 — Causal confirmed-pivot CVD divergence research (in progress)

### Checkpoint and scope
- Started from latest main d32d7108902fb5c28718b74acb739fc14869b846, which already contains C22 raw-event walk-forward integration and C23 aggressor-only / L2-only / combined ablations.
- Branch: feat/causal-cvd-divergence-walk-forward.
- This phase is Binance Spot raw-event replay research only. It does not change the live default Order Flow gate (still COMBINED), alter strategy thresholds, create live signals, or place orders.

### Implementation on the branch
- AggTradeCvdState now records cvd_seed_trade_id in every state snapshot. A CVD comparison must use one stable stream seed; a changed seed cannot be mistaken for a continuous CVD series.
- Added a causal divergence classifier using strict local price pivots. The default pivot window is two bars left and two bars right; the pivot is not known until both right-side candles have closed.
- CVD is aligned to the latest eligible raw receive-time checkpoint at or before each pivot candle close (maximum two-second boundary age). The full interval between the two compared pivots must have eligible one-minute checkpoints, sequence-validated depth, contiguous trade state, no capture-gap marker, and the same CVD seed.
- Bullish divergence is a confirmed lower price low with a higher same-boundary CVD low. Bearish divergence is a confirmed higher price high with a lower same-boundary CVD high. Equal pivots, missing boundaries, stale/ineligible checkpoints, seed changes, and incomplete captures do not create a vote.
- The classifier explicitly reports UNAVAILABLE, NO_DIVERGENCE, BULLISH_DIVERGENCE, BEARISH_DIVERGENCE, or CONFLICTING_DIVERGENCE. It never labels a bounded stream-seeded series as full-session CVD.
- Added research-only walk-forward variants CVD_DIVERGENCE_ONLY and COMBINED_CVD alongside the existing three variants. COMBINED_CVD requires aggressor delta, L2 depth and CVD divergence all to support the candidate. CVD_DIVERGENCE_ONLY can only choose a favorable LIMIT retracement; swing divergence is not treated as immediate MARKET urgency.
- These modes require raw Spot receive-time checkpoints. Feature snapshots and candle-only history cannot silently supply a CVD time series. Live signal generation remains unchanged.

### Tests added / verification status
- Deterministic fixtures cover bullish and bearish divergence, no divergence, unconfirmed pivots, missing/ineligible minute boundaries, CVD seed changes, future checkpoint exclusion, malformed candle timestamps, symbol mismatch, unavailable CVD as neutral WAIT, CVD-only LIMIT behavior, combined-vote hard requirements, future-dated divergence rejection, and stable CVD seed provenance.
- The C24 tests have been added but have NOT yet been executed in this checkpoint. Do not mark the phase verified until GitHub Actions runs the complete relevant backend matrix and post-merge checks.
- No walk-forward performance result is claimed. The user's local retained raw archive is not available to this automation runtime; synthetic fixtures validate code paths only, not profitability or incremental predictive value.

### Current blockers and exact next steps
1. Review the complete branch diff and run backend CI / Python 3.12 and 3.14 tests; fix every regression before merge.
2. Create a PR against latest main, verify mergeability and all required checks, inspect the final diff and secret scan, then merge only if all checks pass. Verify main and post-merge CI.
3. Run the raw-event walk-forward on a retained local Spot archive. Report raw event count separately from eligible checkpoint count, pivot/CVD coverage, fold trade count, win rate, expectancy, profit factor, drawdown and estimated costs. If coverage is sparse, report no performance conclusion.
4. Investigate the 2026-11-24 main smoke workflow run #45379203111: the dynamic Spot/USDⓈ-M scan step failed. The accessible run summary identifies the failed step but does not expose its provider error text, so the exact cause is not asserted here.
5. Keep USDⓈ-M in candle-only monitor scope until live provider access and its own order-flow adapter are verified; GitHub-hosted requests previously returned HTTP 451. COIN-M remains unsupported.
