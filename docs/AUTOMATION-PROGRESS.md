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


## 2026-11-17 — Phase 18: deterministic Binance Spot stream state (PR pending)

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

- Feature branch contains the state module and deterministic tests; CI and PR review are pending.
- This state layer is not yet connected to Binance WebSocket feeds or the live signal engine. It does not yet establish live persistent CVD, live sequence-validated L2, or order-flow out-of-sample performance.

### Exact next steps

1. Run Backend CI (Python 3.12/3.14), schema/test and web-check; fix any failures.
2. Review the full diff and merge PR only if all relevant checks pass and latest-main mergeability is confirmed.
3. Add an explicit WebSocket dependency and build a bounded Binance Spot public-stream adapter.
4. Implement reconnect/backoff and REST aggTrade backfill from the last contiguous aggregate-trade ID.
5. Connect REST depth snapshot + buffered diff events to the sequence state; resync on every gap.
6. Integrate state completeness into signal eligibility and capture synchronized historical trade/depth replay.
