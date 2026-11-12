# QUANTNEX

**A modern trading workspace for Windows, Android and Web.**

QUANTNEX brings trading utilities, trade records and future secure integrations together in one evolving application. The project is actively being developed across desktop, mobile and web.

## Download QUANTNEX

Choose the installer for your device. Each download is provided separately.

### Windows

**[Download QUANTNEX for Windows (.EXE)](https://github.com/adeeshadasuniduwara/QUANTNEX/actions/runs/43185371316)**

The Windows desktop application is packaged as a standalone executable. Download the `QUANTNEX.exe` file from the **Artifacts** section on the linked build page, then double-click it to launch. No separate Python installation is required.

### Android

**[Download QUANTNEX for Android (.APK)](https://github.com/adeeshadasuniduwara/QUANTNEX/actions/runs/43185377710)**

The Android package is an installable debug APK. Download `app-debug.apk` from the **Artifacts** section on the linked build page, open it on your Android device, and allow installation from that source if Android asks. This is an early Android starter build, not yet feature-complete.

> Build artifacts are temporary GitHub Actions downloads and are retained for 30 days. A permanent public download link will be added to GitHub Releases after the first versioned release is published.

## Applications

- **Web:** responsive browser workspace with position sizing, a local trade journal, a dedicated Charts section, and embedded TradingView BTCUSDT / XAUUSD charts.
- **Windows:** desktop workspace with position sizing, local SQLite journal, update checking, a Binance BTCUSDT 15-minute candlestick chart, and a local installation ID.
- **Android:** native application starter.
- **Backend:** shared FastAPI foundation for accounts, journal sync, preferences and an optional AI gateway.

## Run from source on Windows

From the repository root, double-click `run_quantnex.bat` or run it from Command Prompt. Choose Desktop, Web, or both.

The Web workspace can also be opened directly from `apps/web/index.html`. For a local HTTP server, use the launcher menu.

## Backend

See [backend setup](backend/README.md) and [architecture](docs/ARCHITECTURE.md). The API supports local SQLite development and PostgreSQL configuration. Existing app clients are not yet fully connected to cloud sync.

## Current capability and safety

The calculator uses broker-specific pip values entered by the user. The web journal stores data in that browser; the Windows journal stores data locally on that computer. Bot monitoring is currently a status panel only. The Web chart view embeds third-party TradingView charts. The Windows Charts tab reads public BTCUSDT candles from Binance; its Gold button opens the TradingView XAUUSD chart in your browser. The Windows installation ID is a random local identifier, not a login credential. Broker connections, Telegram control and automated order execution are not enabled. Never commit API keys, passwords, signing keys or broker tokens. Public deployment requires HTTPS, managed secrets, backups, monitoring and security testing.
