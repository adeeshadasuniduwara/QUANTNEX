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
| Real goal certificate | POST `/api/v1/goals/{goal_id}/certificate`; local HMAC integrity fingerprint and verification route | Update 013 adds API generation, achieved-goal gating and tamper-detection coverage | Physical PDF download/display still requires UI/device check; verification scope is local workspace integrity only |
| Goal creation/contributions | Goal UI and GET/POST/PUT/contribution routes | Update 013 adds finite target/contribution checks and achievement-state consistency tests | Verify create/update/contribute persistence, real-funds confirmation, journal import duplicate protection and achieved-goal lock |
| Web journal | UI, local browser journal, CSV export; backend journal API also exists | Implemented with distinct local/browser and API storage paths | Exercise add/edit/delete/export, reload and data consistency |
| Wallet ledger | Backend deposit/withdrawal/summary APIs and Web/Windows UI | Implemented as a local record ledger, not a payment/bank integration; Update 009 adds explicit finite amount validation | Test deposit/withdrawal boundaries, NaN/Infinity/over-limit inputs, reload and journal P&L linkage; no actual payment rails are connected |
| QUANTNEX VIEW | First-party chart UI and candles/quote/analysis/backtest APIs | Implemented; provider-dependent | Test supported symbols/timeframes, empty/stale/provider errors, overlays and chart interactions |
| Signal Lab / Signal Center | Signal settings, scan APIs and Web UI | Implemented; Update 010 adds finite risk-percent validation; rule-based confluence is not win probability | Exercise valid/invalid scans, non-finite risk settings, settings persistence and unavailable market feeds |
| Market Intelligence / Order Flow / News | Market, order-book, signal and news APIs; UI panels | PARTIAL — crypto depth uses Binance; Gold depth uses optional MT5; Update 015 hardens Finnhub news-provider errors | Gold depth requires a local MT5 terminal and broker DOM; Forex depth remains provider-dependent. News requires Finnhub key; missing/invalid key must be explicit and malformed rows must not crash or be fabricated |
| Paper Trading / Autopilot | Paper-trade CRUD, close, summary, paper-engine and worker routes | Update 011 makes the status/risk dashboard include provider-marked floating P&L and blocks entries for unpriced open positions | Exercise open/close, realized/floating P&L, risk limits, restart persistence and worker stop/start; paper-only, no broker orders |
| Risk Management / Portfolio | Position-size, guardian, stress, portfolio and smart-open routes | Implemented in code | Boundary tests, unsafe trade rejection and no real order side effects |
| Strategy Laboratory | Replay, backtest, optimize, forward evaluation, research and walk-forward routes | Implemented in code | Test deterministic fixtures, invalid parameters, result persistence and empty history |
| Performance Analytics | Intelligence and advanced performance routes | Implemented in code; ledger-derived estimates | Verify calculations, time boundaries, empty states and no unsupported performance claims |
| Prop Firm Challenge | Virtual challenge routes and MT5 DEMO monitoring/guardian | Update 010 adds finite limits/P&L validation and trailing drawdown regression tests | Verify virtual daily/overall loss, minimum days and trailing drawdown; MT5 requires a local terminal and explicitly DEMO account; no real account is allowed |
| Web source updater | Local Web updater, periodic source check, staged file replacement and backups described in README | Update 018 adds a 100 MB compressed archive download cap, bounded streaming and partial-file cleanup | Existing extraction limits remain 20 MB/file, 80 MB total and 1,500 files; archive/path validation tests added. Real device rollback/reload and user-data preservation still need packaged testing |
| Windows EXE updater | GitHub Releases check, SHA256 verification, user-confirmed install and EXE backup | PASS — Update 008 Windows updater tests and EXE build/artifact upload passed | Requires official HTTPS GitHub release URLs, exact QUANTNEX.exe checksum entry, max 200 MB, 16 KB manifest, temp-file cleanup and preserve prior staged EXE on failure; real install/restart/rollback remains external |
| Android release updater | Checks latest GitHub Release, downloads APK and opens Android package installer | PASS — Update 004 Android unit tests and debug APK build passed | Requires APK + SHA256 manifest, validates HTTPS GitHub asset URLs, verifies exact APK digest before installer, blocks/removes mismatches; physical-device and production-signed release test remain external |
| Telegram bot / alerts | Connect/test/send, auto-signal and report APIs; encrypted local credentials | Update 016 adds getMe/getChat destination validation and group/channel posting-permission checks before storing credentials; actual delivery remains externally blocked until destination is corrected | The local app now rejects the bot's own ID, unresolved destinations and channels without admin/post rights. GitHub release secret TELEGRAM_CHAT_ID still needs the user's private chat ID after /start or intended group/channel ID; never expose the token |
| Telegram release notifications | GitHub Actions workflow with getMe/getChat/getChatMember preflight | Update 017 adds bot membership and posting-permission checks before send; actual send still not confirmed | Correct repository secret TELEGRAM_CHAT_ID (current value resolves to the bot itself), verify bot membership/post rights, then run the workflow and confirm Telegram API success |
| Windows native tools | Calculator, local SQLite journal, Charts and Wallet/Backend views | PARTIAL — Updates 007/009/012 add Gold chart, wallet validation and durable idempotent journal sync | Chart adapter, wallet validation, journal migration/pending-sync and API idempotency have tests; real desktop display, wallet flow and journal CRUD parity still need device-level verification |
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
- Added invalid-input cases for blank fields, nonnumeric/negative/zero amounts and unsupported/blank currency.
- Found and fixed a backend validation bug: explicitly supplied empty strings and zero amounts were replaced by defaults before validation. Defaults now apply only when fields are omitted; explicitly invalid values return HTTP 422.
- Existing UI contract test checks the demo form, endpoint wiring and preview flow.
- **Status:** PASS — backend tests passed on Python 3.12 and 3.14; Web checks passed; Windows EXE build and artifact upload passed. PR #109 merged as `de233f8`.

## Audit status vocabulary

- **PASS:** relevant automated and/or controlled end-to-end test passed with evidence.
- **FAIL:** test or real flow failed; include root cause and repair issue/PR.
- **PARTIAL:** some layers work, but UI/service/provider/persistence path is incomplete.
- **EXTERNAL BLOCKER:** code path exists but a required key, account, permission, terminal or service is unavailable.
- **NOT IMPLEMENTED:** no functional implementation found.

This report is a living audit record. Update it as each flow is exercised, repaired and verified; do not convert static code inspection into a PASS claim.

## Update 004 — Android release APK integrity

- Static audit found the Android updater previously downloaded the APK and immediately opened the installer without checking the release's `SHA256SUMS.txt`.
- Added release-asset selection that requires both the APK and checksum manifest, accepts only HTTPS assets hosted on `github.com`, and matches the manifest entry to the exact APK filename.
- Added streaming SHA-256 verification with a 150 MB safety limit. Download failures, missing/malformed checksum entries and mismatches block installation and remove the downloaded APK.
- Added user-visible error feedback instead of silently swallowing download/install failures.
- Added JVM tests for release asset selection, missing manifest, URL validation, valid digest, wrong digest and filename mismatch.
- Updated Android documentation to explain the integrity gate and its trust boundary.
- **Status:** PASS — Android CI run 43568789183 completed successfully, including JVM unit tests, debug APK build and artifact upload. Device-level installer testing and a production-signed release remain external verification items.

## Update 005 — Telegram destination diagnostics and message correctness

- Confirmed Telegram push workflow failures on main after Update 003 and Update 004: runs 43568542822 and 43568881250 both returned HTTP 403, "Forbidden: the bot can't send messages to the bot."
- Updated the notification workflow to call Telegram getMe and getChat before sending, detect a destination that resolves to the bot itself, and provide a precise setup instruction without printing credentials. Post-merge run 43569094937 confirmed this diagnostic.
- Corrected the push notification's link label: a main-branch source commit is now labeled "View source update", not "Open release & downloads". Release links retain their release label.
- Added static workflow regression tests for destination preflight, safe credential handling and correct link labels.
- **Status:** PASS — Web CI run 43569054132 passed. The post-merge workflow run 43569094937 confirmed getChat resolves TELEGRAM_CHAT_ID to the bot itself. Actual delivery remains blocked until the repository secret is corrected.

## Update 006 — Gold order-book depth via local MT5

- Audit confirmed the Order Flow UI previously requested Binance order-book depth for all markets, while the backend correctly returned unsupported for Gold/Forex and did not fabricate depth.
- Added a read-only MT5 market-book adapter for XAUUSD. It subscribes to broker DOM, normalizes BUY/SELL levels, sorts bids/asks, calculates quantity imbalance, and always releases the market-book subscription.
- When MT5 Gold is enabled, the Gold order-book endpoint now uses the configured broker symbol. If the MT5 package, terminal, symbol or broker DOM is unavailable, the API returns an explicit unavailable reason.
- No order placement or position-management functions are used. Forex depth remains unsupported until a provider is configured.
- Added tests for level normalization, ordering, subscription release, invalid limits, unsupported terminal capability, configured Gold routing and the API route.
- Updated the Web status text to describe the configured provider rather than assuming Binance.
- **Status:** PASS — Backend CI (Python 3.12/3.14), Backend/Web CI, Web CI and Windows Build all passed for PR #113, including EXE build and artifact upload. A real Gold DOM snapshot still requires the user's Windows MT5 terminal and a broker that exposes market depth for its Gold symbol.

## Update 007 — Windows Desktop BTC/Gold chart selection

- Static tool audit found the Windows Charts tab only fetched Binance BTCUSDT candles; the Gold button merely opened an external TradingView page.
- Added a BTCUSDT/XAUUSD selector. BTC uses Binance Spot candles; XAUUSD uses the loopback-only backend MT5 candles endpoint.
- Gold requests omit the broker symbol query so the backend's configured QUANTNEX_MT5_GOLD_SYMBOL (including broker suffixes such as XAUUSD.a) is honored.
- Gold data is accepted only when the backend response explicitly confirms read-only market-data mode and orders_enabled=false. Missing backend, terminal, symbol or provider data is shown as an actionable unavailable state.
- Added a pure chart-data adapter and Windows-only unittest coverage for Binance data, MT5 data, configured broker symbol, read-only enforcement, provider errors and unsupported symbols. Windows CI now runs these tests before building the EXE.
- **Status:** PASS — Windows unit tests, Windows EXE build/artifact upload, Backend CI (Python 3.12/3.14), Backend/Web CI and Web checks all passed for PR #114. Real Windows desktop display and the user's MT5 terminal still require device-level verification.

## Update 008 — Windows EXE updater integrity and atomic staging

- Audit found the packaged Windows updater downloaded directly into the final staging path, did not validate the release asset host/path, accepted any checksum line containing the EXE name, and had no upper download-size bound.
- Added strict HTTPS github.com release-asset URL validation for both EXE and checksum manifest.
- Download now streams into a .part file with a 200 MB cap and a 100 KB minimum; checksum manifest is capped at 16 KB.
- SHA256 is calculated incrementally and must match the exact QUANTNEX.exe manifest filename. Only then is the temporary file atomically moved into the staged path.
- Failed/oversized/mismatched downloads remove the partial file and preserve any previously staged verified EXE.
- Added Windows tests for URL trust, exact filename matching, successful atomic staging, checksum mismatch, previous staged file preservation, size limits and no-network rejection of untrusted URLs.
- **Status:** PASS — Windows updater unit tests, Windows EXE build/artifact upload, backend tests and Web checks passed for PR #115. Actual EXE replacement, restart and rollback still require a packaged Windows-device test.

## Update 009 — Wallet amount validation across API and clients

- Wallet audit confirmed Web already rejected non-finite/non-positive values, but Windows only checked amount <= 0 and could pass NaN/Infinity to the API.
- Tightened the backend WalletTransactionCreate schema with `allow_inf_nan=False`, retaining the positive and $1,000,000,000 upper bound. CI then exposed a second server-side issue: Pydantic's 422 detail included the rejected NaN value, which Starlette could not serialize as strict JSON. Added a safe RequestValidationError handler that serializes non-finite inputs as strings while preserving HTTP 422.
- Added Windows `validate_wallet_amount` and used it before posting; it rejects malformed, NaN, infinite, zero, negative and over-limit values.
- Aligned Web validation with the backend maximum and clearer user feedback.
- Added backend API regression coverage proving invalid amounts return HTTP 422 and leave the wallet summary unchanged; added Windows unit coverage for client validation.
- **Status:** PASS — Backend CI (Python 3.12/3.14), Backend/Web CI, Web CI, Windows wallet/chart unit tests and Windows EXE build/artifact upload all passed for PR #116. This verifies local bookkeeping only; deposits and withdrawals are not bank/payment transactions.

## Update 010 — Prop Firm and Signal Risk Input Safety

- Added explicit `allow_inf_nan=False` validation to Prop Challenge starting balance, profit target, daily loss, max loss and virtual-trade P&L.
- Added the same finite-number constraint to Signal Lab risk percentage.
- Added tests that send raw JSON NaN/Infinity values and verify HTTP 422 responses without creating a challenge, recording a virtual trade or changing signal settings.
- Added a trailing-drawdown scenario: after a new equity peak, a fall to the trailing floor must fail the virtual challenge while remaining above the daily-loss floor.
- Existing MT5 REAL/CONTEST account rejection remains unchanged; real terminal testing is not performed in CI.
- **Status:** PASS — Backend CI (Python 3.12/3.14, 178 tests each), Backend/Web CI, Web CI and Windows EXE build/artifact upload all passed for PR #117. Physical MT5 verification remains restricted to a user-authorized DEMO account and broker terminal.

## Update 011 — Paper Autopilot floating-risk status

- Audit found the background paper worker included floating P&L and unpriced-open-position blocks when deciding whether new entries were allowed, but the Paper Engine status endpoint called the same risk calculator without those values. The UI could therefore show a READY gate while the worker correctly blocked entries.
- Extracted a shared asynchronous open-position risk snapshot that uses current provider quotes and the existing data-health gate.
- Paper Engine status now includes floating P&L and marks any stale/unavailable/unpriced open position as unsafe; the risk gate blocks new automatic entries in that state.
- Paper equity estimate now includes realized plus current unrealized P&L, so subsequent risk sizing uses the current estimated equity.
- Updated the UI label to "Daily P&L incl. floating" to match the metric.
- Added unit and API tests for floating loss, current equity estimate, daily loss blocking, unpriced-position blocking and quote-unavailable behavior.
- **Status:** PASS — Backend CI (Python 3.12/3.14), Backend/Web CI, Web CI, Windows backend tests and Windows EXE build/artifact upload all passed for PR #118. All data is indicative paper-ledger/provider data only; no broker order is placed.

## Update 012 — Windows Journal durable, idempotent sync

- Audit found Windows journal entries were saved locally and posted once to the local API. If the API was unavailable or the response was lost, there was no durable pending state or retry control; retrying manually could duplicate wallet P&L.
- Added a sync_status column with migration: new entries are PENDING; successful syncs become SYNCED. Existing rows without sync history are marked UNKNOWN and are deliberately not auto-replayed to avoid duplicate historical wallet P&L.
- Added a visible Sync column, a Sync pending trades button and a one-time startup retry for new pending entries.
- Each new Windows trade stores a unique persistent UUID-based client_ref (windows_<uuid>); the backend's existing idempotency marker ensures a lost response can be retried without creating duplicate journal rows or wallet P&L.
- Prevent overlapping local sync workers. Failed syncs remain pending and can be retried when the local API is available.
- Added Windows tests for new pending/synced persistence, legacy-row migration safety and backend idempotency using the Windows client_ref.
- **Status:** PASS — Windows journal sync/migration tests, Windows EXE build/artifact upload, Backend CI (Python 3.12/3.14), Backend/Web CI and Web checks all passed for PR #119. Existing UNKNOWN legacy rows require manual review; they are not automatically replayed.

## Update 013 — Goal target and certificate integrity

- Goal creation already rejected non-finite target/initial amounts, but the goal update route only compared target <= 0 or > max; NaN passes both comparisons and could be persisted.
- Goal update now explicitly requires a finite target amount. Contribution validation also explicitly rejects non-finite values.
- Fixed a state consistency gap: if a user lowers an unachieved goal's target below already saved funds, the goal is now marked achieved immediately rather than showing 100% progress while certificate generation remains locked.
- Added API tests for NaN target/contribution rejection without balance mutation, achieved-goal gating, target-lowering achievement, real certificate PDF generation/verification and tamper detection.
- Updated the audit matrix to reflect the already-passed Windows updater CI and new goal/certificate coverage.
- **Status:** PASS — Backend CI (Python 3.12/3.14), Backend/Web CI, Web checks and Windows EXE build/artifact upload all passed for PR #120. Real certificate PDF rendering/download still needs a UI/device-level check; the HMAC verifies local workspace record integrity, not a public authority's credential.


## Update 014 — Certificate PDF download from preview

- Real and demo certificate PDFs were generated by the backend, but the preview panel only embedded the blob in an iframe; it did not expose a direct download control for the previewed PDF.
- Added a download link that uses the exact generated PDF Blob URL, becomes visible only after preview generation succeeds, and assigns a clear filename. Demo files are explicitly named `QUANTNEX-Demo-Certificate-NOT-VALID.pdf`; they remain sample-only and are not represented as valid achievements.
- Added Web UI contract tests for the download control, blob URL wiring, visibility and demo filename.
- **Status:** PASS — Web CI (contract tests and syntax), Backend/Web CI and Windows Build all passed for PR #121. Physical browser download testing remains device-level verification.

## Update 015 — Economic News provider error handling

- Audit found Finnhub can return an API-key error as an `error` field (rather than `status: error`), while the News API route caught only `httpx.HTTPError`. Such responses could be mistaken for an empty calendar; custom `IntelligenceDataError` payload failures could also escape as HTTP 500.
- The route now catches both provider transport and provider-payload errors and returns an actionable HTTP 502 without exposing the API key.
- Economic calendar normalization now discards malformed non-dictionary rows before sorting, preventing unexpected provider rows from causing attribute errors.
- Added tests for missing-key explicit-unconfigured response, invalid-key actionable 502, malformed event filtering, chronological sorting and 30-day horizon clamp.
- **Status:** PASS — Backend CI schema checks, Backend CI (Python 3.12/3.14), Backend/Web CI, Web checks and Windows EXE build/artifact upload all passed for PR #123. A real Finnhub event feed still requires the user's FINNHUB_API_KEY and provider quota; no synthetic events are shown.

## Update 016 — Local Telegram destination preflight

- Audit found the local Telegram connect endpoint validated the bot token with getMe but saved any syntactically valid chat_id without resolving it. This allowed the bot's own ID or a channel/group where it could not post to be stored as a "connected" integration.
- Connection now calls getMe and getChat before saving encrypted credentials; rejects a destination resolving to the bot itself or an unresolvable chat.
- For channels, the bot must be an administrator with can_post_messages=true. For groups/supergroups, the bot must be a member with permission to send.
- No token is stored until all checks pass; responses return destination type/title but never the token.
- Added mocked API tests for bot-self rejection, unresolved private destination, channel posting permission denial, verified private chat and authorized channel.
- **Status:** PASS — Telegram destination mock tests, Backend CI, Backend/Web CI (Python 3.12/3.14), Web checks and Windows EXE build/artifact upload all passed for PR #125. Real bot delivery still requires the user's actual Telegram account/chat and repository secret correction; no token values are requested or exposed.

## Update 017 — GitHub Release Telegram permission preflight

- The GitHub release workflow already resolved the bot and destination but did not verify that the bot could actually post to a group/channel before attempting the announcement.
- Added getChatMember preflight for group, supergroup and channel destinations.
- Channels require administrator status with can_post_messages=true (or creator status); groups/supergroups require membership and send permission.
- Private destinations remain supported and the bot-self check remains in place.
- Added workflow contract tests for getChatMember, channel posting permission and group send permission.
- **Status:** PASS — GitHub workflow contract tests and Web syntax checks passed for PR #126. Actual delivery still depends on the repository owner's TELEGRAM_CHAT_ID secret and a valid Telegram destination.

## Update 018 — Web source updater download safety

- Audit found the Web source updater streamed the pinned GitHub ZIP archive directly to disk with `shutil.copyfileobj` and no compressed-download size limit. Extraction limits did not prevent an unexpectedly large compressed download from consuming disk space.
- Added a 100 MB maximum archive download size, checks Content-Length when available and enforces the same limit while streaming when the header is missing or untrusted.
- Reject invalid/negative Content-Length and empty archives; delete partial archive files on every failure.
- Preserve the existing ZIP extraction limits (20 MB per file, 80 MB total, 1,500 files), path traversal checks and backup/rollback behavior.
- Added unit tests for advertised oversize, streaming oversize, invalid length, empty archive, valid archive and traversal/Windows path syntax.
- **Status:** PASS — Web CI, Backend CI (Python 3.12/3.14), Backend/Web CI, Windows backend tests and Windows EXE build/artifact upload all passed for PR #127. Full updater install/rollback/reload remains a packaged Windows device verification item.


## Sidebar duplicate-icon hotfix — 2026-11-14

- User reported that every item in the left navigation appeared with two icons.
- Root cause hardening: the static HTML still carried legacy Unicode glyphs inside each navigation link while the workspace enhancement replaces link contents with an SVG icon and a label. Remove the legacy glyph markup so even a cached/failed enhancement cannot display a second icon; bump both the stylesheet and script cache keys so clients fetch the current one-icon renderer.
- Correct the label CSS so the global legacy `nav-link span` fixed icon width does not constrain the generated text label.
- Add regression assertions for absence of legacy icon spans and cache invalidation.
- **Status:** MERGED — PR #128 (`db93d8561f16a18adcb9cd2ab8cd31ad28942013`). Web CI, Backend/Web CI (Python 3.12/3.14), and Windows Build all passed on the final PR head. This is a source-level regression fix; visual confirmation in the user's browser still requires loading the updated build.


## Update and live-feed recovery audit — 2026-11-14

### Reproduced source-level causes

- The local Web updater's QUANTNEX_SUPERVISED=1 branch returned placeholder values (Supervisor managed / Automatic source updates) instead of reading the full-source updater state in data/quantnex_update_state.json. The Updates screen therefore could not identify the installed main@SHA revision or compare it to GitHub main.
- The Web updater's legacy installed-revision lookup only read data/quantnex_web_version.json, which is not written by the full-source ZIP/supervisor updater. ZIP installs could consequently appear as an unknown source revision.
- In supervisor mode the Web button only read status; it had no request path to ask the running launcher to check immediately. The launcher itself only checked on startup and every five minutes.
- BTC chart history and live stream were Binance-only. If Binance REST or WebSocket connectivity failed, there was no alternate crypto provider.
- Gold OHLC history correctly required either an enabled, connected read-only MT5 feed or a Twelve Data API key. However, MT5 failure prevented Twelve Data fallback, and the chart did not display the keyless indicative Gold-API quote if OHLC history was unavailable.

### Fixes in progress (PR pending)

- Report actual installed and latest full-source revisions in supervisor mode; read the full-source state marker for ZIP installs.
- Add a same-origin manual-check request endpoint and have the launcher consume the queued request, perform the existing safe updater, and restart only when an update was applied.
- Make the Updates UI show real revisions and an actionable status instead of silent placeholder values.
- Add public Coinbase Exchange REST candle fallback and Coinbase ticker WebSocket fallback for BTC after Binance connectivity failures. Show the actual history provider.
- Add MT5-to-Twelve-Data failover for Gold history/quotes. If no OHLC provider is configured, still show a keyless indicative Gold-API quote while clearly labelling that historical candles need MT5 or Twelve Data. Never fabricate candles or treat the indicative quote as an executable broker price.
- Add regression tests for source version detection, manual check queue, Coinbase BTC fallback, MT5-to-Twelve Data fallback, and Gold quote-only chart visibility.

### Release / verification boundary

- The latest published GitHub Release observed during this audit is still v0.6.0, with QUANTNEX.exe and SHA256SUMS.txt. Merging source changes does not publish a new Windows EXE release. A new release build must complete before the packaged EXE updater can receive a newer binary.
- This PR can be validated by GitHub CI and source-level tests. A real local MT5 terminal/broker connection, the user's provider credentials/network, and the installed Windows/ZIP runtime are not available to this audit environment; those require a post-download smoke test. Gold historical candles will remain explicitly unavailable until the user has an enabled MT5 feed or a valid Twelve Data key.
- Status: MERGED — PR #130 (merge commit 8212a1289a1db4a35793150133468a7952eeef10). Web CI, Backend CI, Backend/Web CI (Python 3.12/3.14), and Windows Build all passed on the final PR head. Source-level fixes are now on main. No claim that the user's installed copy has already updated or that live market providers have been reached from the user's laptop.
