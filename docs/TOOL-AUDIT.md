# QUANTNEX Full Tool Audit

**Audit refreshed:** 2026-11-14  
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
| Web journal | Browser-local journal and CSV export; separate Backend journal APIs | Implemented with separate storage paths | Exercise add/edit/delete/export, reload and duplicate protection |
| Wallet ledger | Backend deposit/withdrawal/summary APIs and Web UI | Local record ledger only; not a bank/payment integration | Test amount boundaries, NaN/Infinity/over-limit inputs, reload and journal P&L linkage |
| Signal Lab / Signal Center | Signal settings and scan APIs; rule-based confluence score | Implemented; not a win probability | Exercise valid/invalid scans, settings persistence and unavailable market feeds |
| Market Intelligence / Order Flow / News | Market, order-book, signal and news APIs | Partial/provider-dependent | Gold depth needs local MT5 + broker DOM; Forex depth needs a configured provider; Finnhub news needs a valid key |
| Paper Trading / Autopilot | Paper-trade CRUD, close, summary, risk gates and worker lifecycle | Implemented in paper mode | Verify open/close, realized/floating P&L, risk limits, restart persistence and worker stop/start |
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

## Maintenance work in progress

- Remove the retired Windows desktop app, Windows EXE build workflow and EXE release steps.
- Keep the project focused on the Android APK and Web workspace.
- Harden the Windows-hosted Web + Backend launcher so failed dependency installation or startup diagnostics remain visible and are saved to `logs/launcher.log`.
- Run full Backend, Web and Android CI on the maintenance pull request before merging.

## Audit status vocabulary

- **PASS:** relevant automated and/or controlled end-to-end test passed with evidence.
- **FAIL:** test or real flow failed; include root cause and repair issue/PR.
- **PARTIAL:** some layers work, but UI/service/provider/persistence path is incomplete.
- **EXTERNAL BLOCKER:** code path exists but a required key, account, permission, terminal or service is unavailable.
- **NOT IMPLEMENTED:** no functional implementation found.

Do not convert static code inspection or CI success into a claim that a real external feed, Telegram message, APK install or local-device startup was verified.
