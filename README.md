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

- Web: responsive browser workspace with position sizing, local journal, Charts section and TradingView BTCUSDT / XAUUSD charts.
- Windows: desktop workspace with position sizing, local SQLite journal, update checking, Binance BTCUSDT candles and local installation ID.
- Android: native application starter.
- Backend: shared FastAPI foundation for accounts, journal, preferences, wallet ledger and optional AI gateway.

## Run from source on Windows

From the repository root, run run_quantnex.bat and choose Desktop, Web, or both. The Web workspace can also be opened from apps/web/index.html.

## Backend

See backend/README.md and docs/ARCHITECTURE.md. The authenticated API now includes a wallet ledger for manual deposits and withdrawals, withdrawal balance checks, and automatic wallet P&L entries when an API journal trade is created. Existing Web, Windows and Android clients are not yet connected to the shared authenticated API, so this backend feature is not yet visible as a synchronized wallet in the apps.

## Current capability and safety

The calculator uses broker-specific pip values entered by the user. The web journal stores data in that browser; the Windows journal stores data locally. Bot monitoring is currently a status panel only. The Web chart view embeds TradingView charts. The Windows Charts tab reads public BTCUSDT candles from Binance; its Gold button opens TradingView XAUUSD in a browser. The Windows installation ID is a random local identifier, not a login credential. Broker connections, Telegram control and automated order execution are not enabled. Never commit API keys, passwords, signing keys or broker tokens. Public deployment requires HTTPS, managed secrets, backups, monitoring and security testing.

## Telegram release announcements

QUANTNEX includes an optional GitHub Actions workflow that announces published releases in an official Telegram channel. Create a bot with @BotFather, add it to the channel as an administrator with Post Messages permission, then configure repository Actions secrets TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID. See docs/TELEGRAM-RELEASE-NOTIFICATIONS.md.
