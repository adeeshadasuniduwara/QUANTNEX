# QUANTNEX

**A modern trading workspace for Windows, Android and Web.**

QUANTNEX brings trading utilities, trade records and secure integrations together in one evolving application. The project is actively being developed across desktop, mobile and web.

## Download QUANTNEX

### Windows

[Download QUANTNEX for Windows (.EXE)](https://github.com/adeeshadasuniduwara/QUANTNEX/actions/runs/43185371316)

Download QUANTNEX.exe from the Artifacts section of the build page.

### Android

[Download QUANTNEX for Android (.APK)](https://github.com/adeeshadasuniduwara/QUANTNEX/actions/runs/43185377710)

Download app-debug.apk from the Artifacts section. This is an early Android starter build, not yet feature-complete.

Build artifacts are temporary and retained for 30 days. A permanent public download link will be added to GitHub Releases after the first versioned release.

## Applications

- Web: responsive browser workspace with position sizing, local journal, TradingView XAUUSD chart, configurable multi-timeframe XAUUSD confluence scans, risk planner and Telegram bot controls.
- Windows: desktop workspace with position sizing, local SQLite journal, Binance BTCUSDT candles, installation ID, and optional authenticated Account & Wallet connection to the shared API.
- Android: native application starter.
- Backend: shared FastAPI foundation for accounts, journal, preferences, wallet ledger, optional AI gateway, Twelve Data XAU/USD analysis and Telegram bot command / price-level alert worker.

## Run from source on Windows

From the repository root, run run_quantnex.bat. Option 1 starts the current Python source (preferred for development and source ZIP updates); option 6 starts the packaged EXE when present. Choose Web or both for the browser workspace. The Web workspace can also be opened from apps/web/index.html.

## Backend

See backend/README.md and docs/ARCHITECTURE.md. The authenticated API includes a wallet ledger, XAU/USD multi-timeframe analysis endpoints, per-user signal preferences, encrypted Telegram bot credentials, command polling and TP/SL level notifications while the local API is running. The Web Account & Wallet and Windows Account & Wallet clients connect to the shared authenticated API when a reachable API URL is configured. The Windows client syncs newly saved journal trades while signed in; older local-only records are not automatically migrated. The existing Web local journal remains browser-local until a dedicated journal-sync phase. Android is not yet connected.

## Current capability and safety

The calculator uses broker-specific pip values entered by the user. The web journal stores data in that browser; the Windows journal stores data locally. The Web chart view embeds TradingView; signal calculations use a separate Twelve Data OHLC feed configured server-side in backend/.env. The rule-based 0–10 confluence score is not a win probability. EMA, MACD, RSI, ADX, ATR, swing structure, liquidity sweep and heuristic OB / Breaker / FVG / iFVG / premium-discount zones are included. The Reaper indicator is not active because its exact formula/source has not been confirmed. Telegram commands and approximate once-per-minute TP/SL price-level alerts require a connected bot, a configured market-data key and the local API to remain running. These alerts do not modify broker orders. The Windows Charts tab reads public BTCUSDT candles from Binance; its Gold button opens TradingView XAUUSD in a browser. The Windows installation ID is a random local identifier, not a login credential. Broker connections and automated order execution are not enabled. Never commit API keys, passwords, signing keys or broker tokens. Public deployment requires HTTPS, managed secrets, backups, monitoring and security testing.

## Versioned releases and updates

The Windows update checker reads the latest published GitHub Release and verifies the EXE with SHA256 before installation. A successful source ZIP update and a published Windows EXE release are separate update paths. To publish the first Windows release, open Actions → QUANTNEX Publish Release → Run workflow and use version `v0.6.0`; later releases can also be triggered by pushing a `v*` tag. Until the first release is published, packaged EXEs correctly report that no published release is available.

## Telegram release announcements

QUANTNEX includes an optional GitHub Actions workflow that announces published releases in an official Telegram channel. Create a bot with @BotFather, add it to the channel as an administrator with Post Messages permission, then configure repository Actions secrets TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID. See docs/TELEGRAM-RELEASE-NOTIFICATIONS.md.
