# QUANTNEX Full Tool Audit

**Audit refreshed:** 2026-11-16  
**Product scope:** Android APK + Web workspace + supporting local Backend.  
**Method:** Trace each user-facing Web/Android tool through UI, API/service/provider and persistence. Static inventory is not proof that an external provider is reachable from a user's device.

## Product inventory

- **Web workspace:** Overview, QUANTNEX VIEW (including signal analysis, strategy intelligence and trade planning), Position Calculator, Trade Journal, Account & Wallet, Telegram Bot, Updates, Market Intelligence, Data Reliability, Order Flow & Liquidity, News Intelligence, Paper Trading, Paper Autopilot, Performance Lab, Risk Management, Watchlist, Forex/Crypto/Gold desks, Price Alerts, Economic Calendar, Trade History, Strategy Library, Portfolio Monitor, Integrations, Goals & Certificates, AI Strategy Laboratory, Prop Firm Challenge, System Security and Support.
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
| QUANTNEX VIEW signal analysis | Multi-timeframe signal scan, configurable timeframes, walk-forward validation, chart intelligence, 100-variant strategy engine and trade-plan levels | **PARTIAL** — API and Web contract coverage; provider and physical-browser verification remain outstanding | Verify chart and signal flows together on-device across supported symbols/timeframes and provider failure states |
| Market Intelligence / Order Flow / News | Market, order-book and news APIs | Partial/provider-dependent | Gold depth needs local MT5 + broker DOM; Forex depth needs a configured provider; Finnhub news needs a valid key |
| Paper Trading / Autopilot | Manual open/close, paper ledger, provider freshness gate, risk settings, autopilot worker and event/performance views | **PARTIAL** — mocked-provider API lifecycle, stale-quote rejection, concurrent-close guard, SQLite engine-restart persistence and worker cancellation covered by backend tests; Web exit/P&L rendering contract covered by CI | Real provider key/quota, browser UI, full Windows process restart and an enabled live-data paper-worker session remain device/provider verification |
| Risk Management / Portfolio | Position sizing, guardian, stress, portfolio and smart-open routes | Implemented in code | Verify boundary cases and ensure no broker-order side effects |
| Strategy Laboratory | Replay, backtest, optimize, forward evaluation and walk-forward routes | Implemented in code | Test deterministic fixtures, invalid parameters and result persistence |
| Performance Analytics | Intelligence and advanced performance routes | Implemented; ledger-derived estimates | Verify calculations, time boundaries and empty states |
| Prop Firm Challenge | Virtual challenge routes and optional MT5 DEMO monitoring | Implemented with external MT5 dependency | Verify daily/overall/trailing drawdown; DEMO-only terminal testing remains device-level |
| Web + Backend source updater | Pinned-main source download, bounded archive, staging, backups, startup confirmation and rollback; update restarts suppress browser re-open and the existing tab performs a cache-busted same-tab refresh preserving its workspace hash | **PARTIAL** — restart/browser suppression and same-tab refresh contracts covered by regression tests; real browser/device install remains unverified | Verify live update in the existing browser tab on the user's Windows host, confirm no extra tab and Telegram/update details after refresh |
| Launcher / startup | Batch launcher, virtual environment creation, dependency install, Backend preflight, API/Web health checks | Maintenance fix in this branch: persistent log + keep-open error handling | Confirm first-run dependency install and launch on the user's device |
| Android APK updater | Latest GitHub Release check, APK download, SHA256 manifest validation and Android package installer | Implemented in Android shell | Verify a signed production update on a physical Android device |
| Android release pipeline | Signed APK + SHA256-only release workflow; stable PKCS#12 signing key required | Pipeline updated in this branch | Confirm required signing secrets and perform a tagged release build |
| Telegram Bot / signal delivery | Dedicated sidebar tool owns connect/test/disconnect, Auto Signals, PDF reports and setup guide; QUANTNEX VIEW owns signal analysis and manual plan alerts, with mirrored connection/delivery status | **PARTIAL** — shared API wiring and navigation contracts covered by Web CI; actual Telegram account delivery remains unverified | Requires a valid bot token, private chat/channel destination, bot membership/posting permissions and live local API; verify in a real browser and Telegram account |
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
- Latest verified code-commit checks (b7d1faa7): Backend CI run 43761633039 — 211 passed; Backend/Web run 43761633096 — 211 passed on Python 3.12 and 3.14 plus Web job passed; Web CI run 43761632978 passed. An earlier worker test exposed delayed first scan on a fresh low-uptime clock; the worker now runs its first scan immediately and the rerun passed.
- Evidence level: controlled API/provider mocks and SQLite engine restart are verified in CI. The test does not run an enabled live provider-driven autopilot loop or restart the user's Windows process. Paper Trading remains simulated; no broker orders are sent. Status remains **PARTIAL** pending browser/device and provider verification.


## Update 023 — Dedicated Telegram Bot workspace tool (historical; superseded by Update 025)

- At that stage of development, the Telegram credential/configuration panel was moved from the then-existing signal workspace into a dedicated **Telegram Bot** sidebar page. The existing bot token, chat ID, display name, connect/test/disconnect actions, Auto Signals market/interval settings, daily PDF report settings and setup guide are retained in the new page.
- At that time, the signal workspace retained timeframe configuration, market scans, historical validation and manual XAUUSD plan / TP1 alerts, with a **Manage Telegram bot** shortcut and mirrored connection status. Update 025 later consolidated these functions into QUANTNEX VIEW.
- Connections & Integrations was changed to open the dedicated Telegram Bot page rather than scrolling to the former signal workspace. Existing local API routes and encrypted backend credential storage are unchanged; no bot token is copied into browser storage or exposed to the UI.
- The original regression coverage asserted unique section IDs, a valid dedicated sidebar target, relocated credential panel, signal-workspace shortcut/status, status synchronization observer and Connections & Integrations navigation.
- Evidence level: source-contract tests and Web CI can verify DOM/navigation wiring only. No real browser, local backend, Telegram account, bot token, destination ID or posting permission was available in this run. Actual bot connection and message delivery remain **PARTIAL / EXTERNAL BLOCKER** until a valid user-owned bot and destination are configured and exercised. Signal delivery still depends on the local API running; broker execution remains disabled.


## Update 024 — Keep automatic updates in the existing browser tab

- Root cause: `run_quantnex_services.py` unconditionally called `webbrowser.open()` every time the supervisor started. A source update safely restarted the supervisor, but the restarted process opened a second QUANTNEX browser tab.
- Fix: every supervisor restart now passes a one-shot `QUANTNEX_SUPPRESS_BROWSER_OPEN=1` flag to the child. The restarted process consumes the flag and skips `webbrowser.open()`; ordinary first launch still opens the workspace normally. The flag does not leak into later restarts or child processes.
- First-update handoff hardening: the still-running pre-update launcher also sets the one-shot flag when the updater reports a source-changing restart. Its existing child-process inheritance passes the flag into the newly installed launcher, so the very first update that introduces this fix does not open a duplicate tab either.
- Legacy first-install bootstrap: the newly installed launcher also detects the updater's existing pending rollback manifest (`data/updates/last_update.json`) before confirming the update. This covers an already-installed older launcher that cannot yet set the environment flag; the new process skips browser launch, then confirms and clears the marker after API/Web health checks pass.
- Existing browser update watchers still wait for the installed revision to match GitHub main. They now call one same-tab refresh helper that uses the current full URL, preserves the active workspace hash/route and existing query parameters, adds a cache-busting update nonce, and uses `location.replace` (not `window.open`). The local Web server already sends no-store/no-cache headers for HTML, JS and CSS, so the refreshed tab requests current assets.
- The existing post-refresh completion flow continues to show the installed-update toast and send the update details through the already-configured local Telegram integration when available. Wallet, Journal and Settings persistence is unchanged.
- Regression tests cover pre-update launcher flag handoff, pending rollback-marker detection for the first upgraded process, restart environment propagation, one-shot flag consumption, same-tab navigation, hash preservation, cache-busting and absence of `window.open` in the update client.
- Evidence level: automated launcher and source-contract tests can verify the fix's control flow; they do not operate a real Windows browser. Real browser tab count, hard refresh, actual update notification and data survival through a live Windows restart remain **PARTIAL / DEVICE VERIFICATION REQUIRED**.

## Audit status vocabulary

- **PASS:** relevant automated and/or controlled end-to-end test passed with evidence.
- **FAIL:** test or real flow failed; include root cause and repair issue/PR.
- **PARTIAL:** some layers work, but UI/service/provider/persistence path is incomplete.
- **EXTERNAL BLOCKER:** code path exists but a required key, account, permission, terminal or service is unavailable.
- **NOT IMPLEMENTED:** no functional implementation found.

Do not convert static code inspection or CI success into a claim that a real external feed, Telegram message, APK install or local-device startup was verified.


## Sidebar readability update — 2026-11-16

- Reduced expanded sidebar navigation labels to 9.5px with tighter line-height and spacing. Labels and captions now stay on one line; constrained labels use ellipsis rather than wrapping into stacked words. Icons retain their existing compact size and collapsed/mobile icon-only navigation is unchanged.
- Added a CSS contract regression test and cache-busted the workspace stylesheet URL.
- Status: **PARTIAL** pending visual verification in the user's browser at desktop and mobile widths; CI/static checks do not prove physical rendering.


## Update 025 — Consolidate signal workspaces into QUANTNEX VIEW

- Removed the empty Signal Lab navigation/page heading and the duplicate AI Signal Center navigation/page and its separate market-scan UI.
- QUANTNEX VIEW is now the single signal workspace: configurable multi-timeframe settings, signal scan, historical walk-forward validation, chart-based strategy intelligence, the 100-variant strategy catalogue, Entry/SL/TP levels and manual trade planning are grouped before the Telegram Bot page.
- Moved the existing QUANTNEX VIEW Live Strategy Engine panel out of the Telegram Bot view and into QUANTNEX VIEW. Telegram Bot remains focused on credentials, connection, Auto Signals delivery settings and reports; existing encrypted credentials and saved preferences are unchanged.
- Retained the Phase 07 cross-market scanner and its `/api/v1/intelligence/signals/scan` route, moving its controls, timeframe results and Paper Trading ticket handoff into QUANTNEX VIEW. The established `/api/v1/signals/scan` and `/api/v1/quantnex-view/analyze` routes also remain available.
- Kept the cross-market scanner's frontend renderer, paper-ticket handoff and styling as an integrated QUANTNEX VIEW panel. Market Intelligence, Order Flow, News, Paper Trading and the existing QUANTNEX VIEW signal engines remain intact.
- Added Web regression checks for removed page IDs/names, QUANTNEX VIEW ownership of signal controls and preserved signal API routes; added a Backend TestClient check for the retired route returning 404 while the QUANTNEX VIEW routes remain registered.
- Evidence level: automated source/contract and Backend API tests cover the consolidation. Actual provider-backed signal generation and visual layout still require a live local browser/provider session and remain **PARTIAL / DEVICE VERIFICATION REQUIRED**.


## Update 026 — Signal lifecycle recovery, staged risk and chart usability

- Added a persistent local signal-trade ledger. QUANTNEX VIEW analysis, the cross-market scan, the multi-timeframe scanner and opt-in Telegram Auto Signals now save deterministic signal records; repeat scans of the same candle are idempotent and same-direction one-minute refreshes are deduplicated during a four-bar cooldown.
- Added a Colombo-day historical replay for the selected QUANTNEX VIEW symbol/timeframe. It rebuilds signal candidates from closed historical candles and stores them before outcome reconciliation. Coverage is disclosed; missing provider history is marked partial instead of inventing earlier outcomes.
- Added a restart-safe lifecycle worker that replays available one-minute candles for open signals and records TP1, TP2, TP3, original SL, breakeven protection, locked-profit exit and ambiguous same-candle outcomes.
- Staged virtual risk plan: 40% at TP1 then move the virtual stop to Entry; 30% at TP2 then move it to TP1; remaining 30% at TP3. Realized results are expressed in R. This is a research/alert simulation only and does not modify broker orders or prove an external broker fill.
- Added a persistent Telegram event outbox. TP/SL/protection/ambiguity events are sent once after Telegram delivery succeeds; temporary failures are retried with a 30-second backoff. Messages distinguish a candle-level price touch from a broker execution.
- Added a QUANTNEX VIEW signal outcome table with replay coverage, active-stop levels, target-hit markers and realized R. Market entries are explicitly labelled MARKET with their reference price.
- Upgraded the native chart with visible PRICE and TIME axes, crosshair axis readouts, independent price-scale zoom, and horizontal/trend/vertical/rectangle/Fibonacci drawing tools. Drawings persist per symbol/timeframe in local browser storage.
- The shared crypto ticker now starts with the workspace and remains active across visible views; it pauses only while the browser tab is hidden and reconnects on return. The chart keeps its existing provider-specific WebSocket failover and Gold quote polling.
- Automated evidence includes deterministic BUY/SELL target progression, staged stop changes, breakeven exit, original SL loss, ambiguous intrabar ordering, restart replay idempotency, chart axis/tool/ledger contract checks and global feed lifecycle checks. Physical device rendering and live provider/Telegram delivery remain external/device verification requirements.


## Update 027 — Live chart price visibility and label collision fix

- Reserved a responsive, dedicated right-side price axis so the current market price marker has predictable space and is clipped to the axis rather than the canvas edge.
- The live price label now measures its text and reduces its font size only when needed to fit the available axis width; crosshair price labels use the same protected axis region.
- Entry, stop-loss, take-profit and structure-level labels now use collision-aware vertical placement with opaque backing, so nearby levels do not overwrite one another.
- Updated pointer and wheel hit-testing to use the same responsive axis boundary, preserving independent price-scale zoom.
- Added regression assertions for axis sizing, label collision handling, live-price text fitting and marker clipping; cache-busted both chart assets.
- Evidence level: source-contract regression checks and CI can verify layout logic, but actual pixel rendering at the user's desktop/mobile sizes remains **PARTIAL / DEVICE VERIFICATION REQUIRED**.


## Update 028 — Windows Python bootstrap and launcher portability

- Added one shared Windows runtime resolver for both the full Web + Backend launcher and Backend-only launcher.
- Detects a working Python 3.11+ interpreter through the Python Launcher or PATH, validates the interpreter instead of trusting a Windows Store execution-alias stub, and checks common per-user installation paths.
- If no supported runtime is found, offers an explicit opt-in Python 3.12 installation through Windows Package Manager; provides the official python.org manual installation route when winget is unavailable.
- The full launcher now starts the supervisor with the resolved interpreter. The Backend-only launcher uses the same resolver before creating its virtual environment.
- Added regression checks for runtime detection, explicit installation consent and both launcher integrations.
- Evidence level: source-level regression tests and CI; a clean Windows PC first-run installation still requires physical-device verification.


## Update 029 — Signal outcome integrity and TradingView-style chart navigation

- Signal lifecycle now ignores the candle that generated the signal, preventing pre-entry OHLC movement from immediately closing a newly recorded position.
- When one OHLC candle contains both the active stop and next target, intrabar order remains unknown: the trade stays OPEN, records an ambiguity event, and waits for a later unambiguous closed candle. No win/loss is guessed.
- Confirmed exits remain price-driven: original SL, protected/break-even stop after TP1, locked stop after TP2, and staged TP1/TP2/TP3 completion. Signal eligibility/confirmation gates are unchanged.
- Native chart now reserves a 12-bar right-side gutter so the latest candle is not pinned to the chart edge. The viewport stays stable while live candles append.
- Mouse/touch chart gestures now support horizontal history pan (including limited future space), vertical price pan, independent price-axis scaling and time zoom; pointer geometry uses the same responsive price-axis width as rendering.
- Evidence: lifecycle and chart contract tests added/updated. Real browser interaction, provider-driven live tick speed and visual verification on desktop/mobile remain device-level checks.


## Update 030 — Signal outcome labels, persistent chart markers, Telegram live cards and daily pair report

- New confirmed stop-loss closures use the explicit `SL_HIT` outcome instead of the ambiguous generic `STOPPED` label. Existing historical `STOPPED` rows remain intact and render as `SL HIT`; signal history is not deleted or rewritten.
- Existing staged protection remains: TP1 moves the remaining simulated stop to entry, TP2 trails it to TP1, and the trade stays active until a later stop/profit-lock exit or TP3 completion. Ambiguous same-candle SL/TP bars stay active and are not guessed.
- QUANTNEX VIEW now reloads the persisted signal ledger for the selected pair and paints BUY below / SELL above the originating candle, preserving historical markers after chart refreshes. The latest analysis signal also receives a live marker.
- Each connected Telegram bot receives one signal card per tracked signal with pair, BUY/SELL, entry, active SL and TP1–TP3. The same Telegram message is edited as provider-backed mark price changes and when the outcome changes; floating result is shown in R, clearly labelled simulated (no broker order).
- Live marks refresh from the configured market-data provider with a shared per-symbol cache; unavailable/stale prices are not fabricated.
- Added a landscape vector PDF report for confirmed signal outcomes, pair-by-pair all-history win rates, daily closed trades, open positions, and R-based summary. Scheduled delivery defaults ON for connected bots at 21:00 Asia/Colombo; the existing per-bot toggle remains available.
- Evidence: lifecycle, Telegram-card, PDF statistics and chart-marker regression tests added. Actual connected-bot delivery, live provider latency, browser rendering and the first scheduled 21:00 delivery remain external runtime checks.
