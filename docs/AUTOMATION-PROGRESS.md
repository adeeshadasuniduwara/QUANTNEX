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
