# QUANTNEX Full Tool Audit

**Audit started:** 2026-11-14  
**Baseline commit:** `16816bade34282231abf304b04e9b7ecee0efd12`  
**Method:** Trace each user-facing tool from navigation/UI through its JavaScript or native action, API/service/provider, response, and persistence. Static inventory is not proof of successful live operation.

## Initial inventory

- Web workspace: 32 primary navigation destinations identified in `apps/web/index.html`, including Overview, QUANTNEX VIEW, Position Calculator, Trade Journal, Account & Wallet, Signal Lab, Updates, Market Intelligence, Data Reliability, AI Signal Center, Order Flow & Liquidity, News Intelligence, Paper Trading, Paper Autopilot, Performance Lab, Risk Management, Watchlist, Forex/Crypto/Gold desks, Price Alerts, Economic Calendar, Trade History, Strategy Library, Portfolio Monitor, Integrations, Goals & Certificates, AI Strategy Laboratory, Prop Firm Challenge, System Security and Support.
- Backend: 75 FastAPI route declarations identified in `backend/app/main.py`.
- Windows: native Tkinter workspace; documented screens include Home, Calculator, Journal, Charts, Account/Wallet, Device and Updates. Windows README explicitly says broker connection, streaming, bots and order placement are not enabled.
- Android: native Overview, Chart, Trading Room, Journal and Updates navigation; native Journal was merged in Update 002. Production signing and full feature parity remain separate verification items.
- CI: Android, Windows, backend, Web and shared-news workflows exist. A green CI run proves the tested build/test job, not successful operation of every external provider on a user's device.

## Tool audit matrix (initial evidence)

| Tool / flow | Current evidence | Status | Remaining verification |
|---|---|---|---|
| Demo achievement certificate preview | Dedicated UI handler in `apps/web/goals.js`; POST `/api/v1/goals/demo-certificate`; ReportLab PDF builder; existing builder-level PDF tests | Implemented; API integration coverage added in Update 003, CI pending | Verify actual response PDF, validation, non-valid markings and no goal side effect in CI |
| Real goal certificate | POST `/api/v1/goals/{goal_id}/certificate`; local integrity fingerprint and verification route | Implemented in backend/UI | Exercise achieved-goal gating, generation, tamper detection and download |
| Goal creation/contributions | Goal UI and GET/POST/PUT/contribution routes | Implemented in code | Full CRUD, amount validation, persistence and journal import tests |
| Web journal | UI, local browser journal, CSV export; backend journal API also exists | Implemented with distinct local/browser and API storage paths | Exercise add/edit/delete/export, reload and data consistency |
| Wallet ledger | Backend deposit/withdrawal/summary APIs and Web UI | Implemented as a local record ledger, not a payment/bank integration | Test balance boundaries, invalid inputs, reload and journal P&L linkage |
| QUANTNEX VIEW | First-party chart UI and candles/quote/analysis/backtest APIs | Implemented; provider-dependent | Test supported symbols/timeframes, empty/stale/provider errors, overlays and chart interactions |
| Signal Lab / Signal Center | Signal settings, scan APIs and Web UI | Implemented; rule-based confluence, not win probability | Exercise valid/invalid scans, settings persistence and unavailable market feeds |
| Market Intelligence / Order Flow / News | Market, order-book, signal and news APIs; UI panels | Provider-dependent | Verify each provider response, stale/error states, API-key/quota behavior and no fabricated fallback data |
| Paper Trading / Autopilot | Paper-trade CRUD, close, summary, paper-engine and worker routes | Implemented in code; simulation only | Exercise open/close, P&L, risk limits, restart persistence and worker stop/start |
| Risk Management / Portfolio | Position-size, guardian, stress, portfolio and smart-open routes | Implemented in code | Boundary tests, unsafe trade rejection and no real order side effects |
| Strategy Laboratory | Replay, backtest, optimize, forward evaluation, research and walk-forward routes | Implemented in code | Test deterministic fixtures, invalid parameters, result persistence and empty history |
| Performance Analytics | Intelligence and advanced performance routes | Implemented in code; ledger-derived estimates | Verify calculations, time boundaries, empty states and no unsupported performance claims |
| Prop Firm Challenge | Virtual challenge routes and MT5 DEMO monitoring/guardian | Implemented; MT5 requires local demo terminal/account | Test virtual mode; live terminal test only with a user-authorized DEMO account |
| Web source updater | Local Web updater, periodic source check, staged file replacement and backups described in README | Implemented in code; device-level behavior not yet verified | Test checksum/archive/path validation, rollback, data preservation and reload |
| Windows EXE updater | GitHub Releases check, SHA256 verification, user-confirmed install and EXE backup | Implemented; not fully automatic | Test release asset/checksum, install/restart/rollback and local data preservation |
| Android release updater | Checks latest GitHub Release and invokes Android package installer | Implemented; user approval and production signing required | Verify signed APK artifact, same-key upgrade path, notification permission and install flow |
| Telegram bot / alerts | Connect/test/send, auto-signal and report APIs; encrypted local credentials | Implemented but external setup required | Verify bot can message the target chat; prior recorded attempt failed HTTP 403: bot cannot send messages to the bot |
| Telegram release notifications | GitHub Actions workflow and release workflow | Workflow exists; delivery not confirmed | Verify correct chat ID, bot membership/admin permission, workflow trigger and successful Telegram API response |
| Windows native tools | Calculator, local SQLite journal, Charts and Wallet/Backend views | Partial desktop capability | Exercise each screen and backend-unavailable behavior; README says bot monitor is not connected |
| Android native tools | Overview, chart, journal and update shell | Partial feature parity | Exercise each screen on emulator/device; verify release signing and remaining Trading Room/Updates flows |

## Confirmed external prerequisites / boundaries

- Market feeds depend on third-party providers, connectivity, symbol coverage, quotas and API configuration. No market value should be fabricated when a provider fails.
- Forex/Gold feed features may require a valid Twelve Data key and plan entitlement; MT5 requires an installed local terminal and a DEMO account.
- Telegram delivery requires a valid bot token and the correct destination chat ID. The bot must be started by the user in a private chat or added with appropriate posting permission to a group/channel.
- Stable Android upgrades require the same private signing keystore for every production APK. A debug CI APK is not a production-signed release.
- CI artifacts are temporary test downloads; they are not equivalent to a published GitHub Release.
- QUANTNEX remains local-only/login-free. Do not expose the loopback backend or enable real-money execution as part of this audit.

## Update 003 — Demo certificate API integration verification

- Added TestClient coverage for the actual demo certificate endpoint.
- Tests assert HTTP 200, PDF content type and signature, non-cacheable demo filename, minimum output size, and that previewing a demo does not create a real goal.
- Added invalid-input cases for blank fields, nonnumeric/negative amounts and unsupported currency.
- Existing UI contract test checks the demo form, endpoint wiring and preview flow.
- **Status:** CI pending. Do not mark this flow passed until the new backend test suite and Web tests complete successfully.

## Audit status vocabulary

- **PASS:** relevant automated and/or controlled end-to-end test passed with evidence.
- **FAIL:** test or real flow failed; include root cause and repair issue/PR.
- **PARTIAL:** some layers work, but UI/service/provider/persistence path is incomplete.
- **EXTERNAL BLOCKER:** code path exists but a required key, account, permission, terminal or service is unavailable.
- **NOT IMPLEMENTED:** no functional implementation found.

This report is a living audit record. Update it as each flow is exercised, repaired and verified; do not convert static code inspection into a PASS claim.
