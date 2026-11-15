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

### Goal

Run the read-only signal smoke script against public Binance Spot/Coinbase fallback data on a daily GitHub Actions schedule, with a manual workflow-dispatch option. This adds a real-provider integration check without credentials, Telegram sends or broker orders.

### Verification boundary

- The workflow checks only BTCUSDT, ETHUSDT and SOLUSDT; Gold/MT5 remains a separate local smoke test.
- A `WAIT` result is a successful data/engine scan, not a failure.
- A provider/data validation error should fail the workflow and remain visible in Actions logs.
- Passing the workflow does not establish profitability or verify the user's local terminal.

### Next steps

1. Add the scheduled/manual workflow with read-only repository permissions.
2. Validate workflow syntax and script invocation.
3. Merge only after CI passes and verify the workflow is present on main.
