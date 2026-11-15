# QUANTNEX Full Tool Audit

**Audit refreshed:** 2026-11-16  
**Product scope:** Android APK + Web workspace + supporting local Backend.  
**Method:** Trace each user-facing Web/Android tool through UI, API/service/provider and persistence. Static inventory is not proof that an external provider is reachable from a user's device.

## Product inventory

- **Web workspace:** Overview, QUANTNEX VIEW, Position Calculator, Trade Journal, Account & Wallet, Signal Lab, Updates, Market Intelligence, Data Reliability, AI Signal Center, Order Flow & Liquidity, News Intelligence, Paper Trading, Paper Autopilot, Performance Lab, Risk Management, Watchlist, Forex/Crypto/Gold desks, Price Alerts, Economic Calendar, Trade History, Strategy Library, Portfolio Monitor, Integrations, Goals & Certificates, AI Strategy Laboratory, Prop Firm Challenge, System Security and Support.
- **Android:** native shell for the hosted Web workspace, Overview, Chart, Trading Room, Journal and Updates; release updater verifies APK SHA256 before opening Android's package installer.
- **Backend:** loopback-only FastAPI service for local Web persistence, wallet ledger, preferences, signal tools, paper trading, market data, Telegram integration, backup and maintenance.
- **Windows is a supported host environment for the Web + Backend launcher only. The current source and workflows contain no Windows desktop application, executable build or installer pipeline.**

## Tool audit matrix

| Tool / flow | Current evidence | Status | Remaining verification |
|---|---|---|---|
| Web Overview | BTC/USD, XAU/USD and USD/LKR provider-backed estimates with explicit source/status fields | Implemented; provider-dependent | Verify user's network/provider reachability and freshness on device |
| QUANTNEX VIEW | First-party chart UI; Binance candles and Coinbase fallback for supported crypto; Gold history via configured MT5 or Twelve Data | Implemented; provider-dependent | Test all symbol/timeframe combinations, stale/empty/error states and overlays on device |
| Web journal CRUD | Browser recovery cache plus local SQLite GET/POST/PUT/DELETE API; offline creates import idempotently; edits reconcile an existing linked wallet P&L row | **PARTIAL** — backend API lifecycle and UI wiring regression tests; physical browser/restart path not yet exercised | Verify real browser add/edit/delete, offline recovery, reload/restart and multi-tab behavior |
| Journal CSV export | Spreadsheet-safe CSV serializer and download action | **PARTIAL** — formula-injection, quoting, newline and numeric-P&L unit tests pass; actual spreadsheet interoperability is unverified | Open a downloaded CSV in supported spreadsheet apps on a user device |
| Wallet ledger | Local Web form, shared USD formatter, safe transaction-history renderer, summary/history/POST APIs, SQLite ledger and journal-linked P&L | **PARTIAL** — API boundary/history tests, atomic concurrent-withdrawal test and file-backed database-engine restart test; Web renderer/action contracts covered in CI | Real browser deposit/withdraw, history rendering, reload and full backend process restart on the user's Windows host; this is not a bank/payment rail |
| Signal Lab / Signal Center | Signal settings and scan APIs; rule-based confluence score | Implemented; not a win probability | Exercise valid/invalid scans, settings persistence and unavailable market feeds |
| Market Intelligence / Order Flow / News | Market, order-book, signal and news APIs | Partial/provider-dependent | Gold depth needs local MT5 + broker DOM; Forex depth needs a configured provider; Finnhub news needs a valid key |
| Paper Trading / Autopilot | Manual open/close, paper ledger, provider freshness gate, risk settings, autopilot worker and event/performance views | **PARTIAL** — mocked-provider API lifecycle, stale-quote rejection, concurrent-close guard, SQLite engine-restart persistence and worker cancellation covered by backend tests; Web exit/P&L rendering contract covered by CI | Real provider key/quota, browser UI, full Windows process restart and an enabled live-data paper-worker session remain device/provider verification |
| Risk Management / Portfolio | Position sizing, guardian, stress, portfolio and smart-open routes | Implemented in code | Verify boundary cases and ensure no broker-order side effects |
| Strategy Laboratory | Replay, backtest, optimize, forward evaluation and walk-forward routes | Implemented in code | Test deterministic fixtures, invalid parameters and result persistence |
| Performance Analytics | Intelligence and advanced performance routes | Implemented; ledger-derived estimates | Verify calculations, time boundaries and empty states |
| Prop Firm Challenge | Virtual challenge routes and optional MT5 DEMO monitoring | Implemented with external MT5 dependency | Verify daily/overall/trailing drawdown; DEMO-only terminal testing remains device-level |
| Web + Backend source updater | Pinned-main source download, bounded archive, staging, backups, startup confirmation and rollback | Implemented; automated tests present | Verify real install/restart/rollback on the user's Windows host |
| Launcher / startup | Batch launcher, virtual environment creation, dependency install, Backend preflight, API/Web health checks | Maintenance fix in this branch: persistent log + keep-open error handling | Confirm first-run dependency install and launch on the user's device |
| Android APK updater | Latest GitHub Release check, APK download, SHA256 manifest validation and Android package installer | Implemented in Android shell | Verify a signed production update on a physical Android device |
| Android release pipeline | Signed APK + SHA256-only release workflow; stable PKCS#12 signing key required | Pipeline updated in this branch | Confirm required signing secrets and perform a tagged release build |
| Telegram bot / alerts | Connect/test/send, Auto Signal and report APIs; encrypted local credentials | Implemented; destination/provider-dependent | Requires a valid bot token, correct destination ID, permissions and live provider access |
| Telegram release notifications | GitHub Actions announcement workflow | Optional; external secret-dependent | Verify the repository destination secret and actual Telegram delivery |

## Backend and API verification

The repository contains dedicated tests for API routes, schemas, local workspace security, events, application lifespan, market data, MT5 feed handling, signal engine, paper trading, risk/prop challenge, strategy phases, Telegram integration, worker lifecycle, maintenance and updater behavior.

The latest main-branch CI run observed during this audit passed:
- Backend CI on Python 3.12 and Python 3.14, including dependency installation, startup preflight, compilation and the full pytest suite.
- Backend/Web CI on Python 3.12 and 3.14, including backend tests and Web syntax/contract checks.
- Web CI, including JavaScript syntax, Web regression tests, Python updater compilation and unittest discovery.

These CI results establish that the tested code passed in GitHub's runner. They do not prove that the user's local Python installation, internet connection, API keys, MT5 terminal, Telegram destination or Android package installer will work on their device.

## Confirmed external prerequisites and safety boundaries

- Market feeds depend on provider uptime, connectivity, symbol coverage, quotas and API configuration. Never fabricate prices or candles when a provider fails.
- Gold/Forex historical feeds may require a valid Twelve Data key or a local read-only MT5 terminal. MT5 requires an installed terminal and a DEMO account for challenge monitoring.
- Telegram delivery requires a valid bot token and correct destination chat ID. Never request or expose token values in chat.
- Stable Android upgrades require the same private signing keystore for every production APK. Never commit the keystore or passwords.
- CI artifacts are temporary test downloads; they are not the same as a published GitHub Release.
- The Backend remains loopback-only and login-free. Do not expose it to a LAN or public internet.
- No broker order placement or verified win-rate calculation is enabled by this audit.

## Maintenance PR #137 — Android + Web only

- Removed the Windows desktop source tree and Windows EXE build workflow; the Android release workflow now builds and publishes only the signed APK plus SHA256 manifest.
- Reduced the Windows batch launcher to Web + Backend, Backend-only and source-folder options. Failed startup now keeps the CMD window open and writes diagnostics to `logs/launcher.log`.
- Added regression tests for launcher exit-code handling, persistent log output, Android-only release assets, signing requirements and ignored local data/secrets.
- Backend CI passed on Python 3.12 and 3.14; the Python 3.12 suite reported 196 passed. Backend/Web CI and Web CI passed. Android debug APK build and artifact upload passed.
- A real Windows first-run install and physical Android signed-release update still require device-level verification. The historical v0.6.0 GitHub Release retains its old EXE asset until manually removed; no current workflow builds another one.

## Update 020 — Web Journal edit and wallet reconciliation

- Added a visible date field, per-row Edit action, and Cancel edit control. Existing entries can be edited without creating a duplicate; unsynced browser-recovery rows can be corrected locally before their first import.
- Added `PUT /api/v1/journal/{trade_id}`. The route validates the full replacement payload, normalizes timestamps to UTC, writes the journal row and audit event in one database transaction, and publishes the journal change event.
- If the journal row already has a linked `trade_pnl` wallet transaction, its amount and description are reconciled atomically. Legacy imported history with no wallet transaction remains excluded from the wallet; editing old history does not create a cash movement.
- Delete continues to remove an existing linked P&L transaction; the create/update/delete test checks the balance returns to its starting value. Invalid non-finite P&L is rejected without mutating either record.
- Web contract tests cover date/edit/cancel controls, PUT wiring, matching-row cache replacement, startup/offline recovery wiring and distinction between HTTP validation errors and offline queuing.
- Evidence level: backend TestClient exercises API create/list/update/delete, timestamp normalization, wallet linkage, legacy no-wallet behavior and invalid-input rollback. Web CI exercises syntax and static UI/API contract tests. A real browser download, browser storage failure, browser restart, Excel/LibreOffice opening and user's device persistence remain **PARTIAL / device-level verification required**.

## Update 021 — Wallet ledger lifecycle and UI recovery

- Fixed two missing Web functions in the main app bundle: the shared USD formatter used by journal metrics and the wallet transaction-history renderer. Without these definitions, the initial journal render could stop `app.js` before the wallet controls and refresh lifecycle were registered; wallet refresh also referenced a renderer that did not exist.
- Added a safe DOM-only wallet history renderer using `textContent`, UTC-aware timestamp parsing and explicit Deposit / Withdrawal / Trading P&L labels. The Web wallet now requests the latest 500 ledger rows and documents that older entries remain stored locally.
- Wallet writes now ignore repeated clicks while a request is pending. A successful API write is reported as saved even if the subsequent display refresh fails, avoiding ambiguous failure feedback after a committed transaction.
- Made withdrawal balance enforcement atomic: the balance predicate is part of a single conditional SQL INSERT with RETURNING, so concurrent withdrawals cannot both spend the same available balance. A SQLite busy-snapshot is rolled back and retried once; persistent contention returns a clear HTTP 503. Insufficient funds remains HTTP 409 and no row is written.
- Backend TestClient coverage now includes withdrawal rejection without balance mutation, newest-first history, the 1–500 history limit, simultaneous withdrawals against a $1,000 fixture (one succeeds, one receives 409), and a file-backed SQLite database-engine dispose/reopen with deposit, withdrawal, journal P&L reconciliation and deletion.
- Web CI checks the shared formatter, visible history renderer, safe text insertion, duplicate-submit guard, saved-vs-refresh error distinction and 500-row request contract. These are source/contract checks, not a real browser run.
- Evidence level: backend tests exercise API and controlled file-backed persistence. CI does not launch the user's browser or restart their Windows process. Wallet remains a local bookkeeping ledger; no bank transfer, card payment, exchange transfer or broker funding is performed. Real browser and full-device restart verification remain **PARTIAL / device-level verification required**.

## Update 022 — Paper Trading lifecycle and close safety

- Manual paper positions now close only when the provider quote passes the same Market Data Guardian freshness/price checks used for entry. Stale, missing-timestamp or invalid quotes return a clear HTTP 503 and leave the position OPEN.
- Manual close and the autopilot worker now use conditional database UPDATEs constrained to the same user, trade ID and OPEN status. A second/concurrent close cannot create another realized result or close event; manual close returns HTTP 409 when already closed, or a safe HTTP 503 if SQLite remains busy while the current state is unresolved. The worker now schedules its first scan immediately after process startup, even when the system monotonic clock has not yet reached one full configured interval.
- Paper engine integer controls now reject NaN/Infinity, booleans and fractional values rather than leaking OverflowError/500 responses. The existing scan interval clamp remains 60–3600 seconds.
- The Web Paper Trading ledger now displays exit price and realized P&L per closed position. If a close request fails (including a concurrent close), the page reloads the ledger to reconcile the current server state.
- Backend TestClient uses isolated file-backed SQLite and a mocked provider to cover invalid quantity, stale open rejection, valid manual open, stale close rejection without mutation, valid close/P&L, duplicate close, status/limit validation, saved engine settings, paper event/position persistence across database-engine dispose/reopen, and unchanged wallet balance. A separate concurrent-close test asserts exactly one MANUAL_CLOSED event; a worker-cycle test verifies an AUTO_OPENED position reaches one persisted TAKE_PROFIT close event. Engine tests cover finite/integer settings and actual autopilot task cancellation through its start/stop helpers.
- Web CI contract tests cover the Exit / Realized P&L columns, per-trade result rendering and close-error reconciliation. These are not a real browser test.
- Evidence level: controlled API/provider mocks and SQLite engine restart are verified in CI. The test does not run an enabled live provider-driven autopilot loop or restart the user's Windows process. Paper Trading remains simulated; no broker orders are sent. Status remains **PARTIAL** pending browser/device and provider verification.

## Audit status vocabulary

- **PASS:** relevant automated and/or controlled end-to-end test passed with evidence.
- **FAIL:** test or real flow failed; include root cause and repair issue/PR.
- **PARTIAL:** some layers work, but UI/service/provider/persistence path is incomplete.
- **EXTERNAL BLOCKER:** code path exists but a required key, account, permission, terminal or service is unavailable.
- **NOT IMPLEMENTED:** no functional implementation found.

Do not convert static code inspection or CI success into a claim that a real external feed, Telegram message, APK install or local-device startup was verified.
