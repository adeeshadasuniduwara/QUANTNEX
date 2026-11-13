# QUANTNEX

**A modern trading workspace for Windows, Android and Web.**

QUANTNEX brings trading utilities, trade records and secure integrations together in one evolving application. The Web and Windows workspaces are designed for single-computer local use. QUANTNEX does not require a user login or cloud account.

## Download QUANTNEX

### Windows EXE automatic updates

The packaged Windows desktop app checks the official GitHub Releases channel at startup and every five minutes while it remains open. When a newer release is available, it downloads the published `QUANTNEX.exe` and verifies its SHA256 checksum before enabling **Install & restart**. The external Windows updater waits for QUANTNEX to close, backs up the currently installed EXE, replaces it, and relaunches the app. If replacement or launch fails, it attempts to restore the previous EXE. The local journal, device ID, wallet and settings are stored separately under `%LOCALAPPDATA%\QUANTNEX` and are not overwritten by the EXE update. Updates require a published GitHub Release containing `QUANTNEX.exe` and `SHA256SUMS.txt`; a source commit or CI artifact alone is not a published EXE update.

## Android

[Download QUANTNEX for Android (.APK)](https://github.com/adeeshadasuniduwara/QUANTNEX/actions/runs/43185377710)

Download app-debug.apk from the Artifacts section. This is an early Android starter build, not yet feature-complete.

Build artifacts are temporary and retained for 30 days. The Web Updates panel also links to the current source ZIP; the Updates panel checks the latest main branch commit directly.

## Applications

- Web: responsive local browser workspace with QUANTNEX VIEW first-party charts, live crypto/Gold market data, multi-timeframe signal analysis, local journal and wallet, paper trading, risk tools, strategy research and Telegram controls.
- Windows: desktop workspace with position sizing, a local SQLite journal, Binance BTCUSDT candles, installation ID and a wallet shared with the local backend when it is running. No login or registration.
- Android: native application starter.
- Backend: loopback-only FastAPI service for the local journal, wallet ledger, preferences, optional AI gateway, Twelve Data XAU/USD analysis and Telegram bot command / price-level alert worker.

## Run from source on Windows

From the repository root, run run_quantnex.bat. Option 1 starts the Windows Desktop source app; option 2 starts the local Backend API and Web updater together (recommended for the complete browser workspace); option 3 starts Desktop + Backend + Web together; option 4 starts the Backend API only; option 5 opens the Web source folder; option 6 starts the packaged EXE when present. Use option 2 or 3 for the full Web experience. Do not open apps/web/index.html directly: API-backed features require the trusted local origin served at http://127.0.0.1:5500.

## Backend

See backend/README.md and docs/ARCHITECTURE.md. The local API has no login, registration, password, JWT or remote account routes. It creates one local workspace identity internally so journal, wallet, signal settings and encrypted Telegram configuration can be stored consistently. On first startup, a SQLite backup is saved under data/backups before legacy account records are consolidated into that workspace and old password hashes are cleared. The API listens on 127.0.0.1 only and accepts the local Web origin; do not expose it to a network. Web browser journal entries remain in that browser profile; Windows journal entries remain in the local Windows data folder. Android is not connected to this local-only backend.

## Current capability and safety

The calculator uses broker-specific pip values entered by the user. The web journal stores data in that browser; the Windows journal stores data locally. QUANTNEX VIEW renders first-party charts using TradingView Lightweight Charts (the rendering library, not a hosted TradingView widget). Crypto OHLC candles use Binance Spot; XAUUSD candles use the Twelve Data OHLC feed configured server-side in backend/.env. The rule-based 0–10 confluence score is not a win probability. EMA, MACD, RSI, ADX, ATR, swing structure, liquidity sweep and heuristic OB / Breaker / FVG / iFVG / premium-discount zones are included. The Reaper indicator is not active because its exact formula/source has not been confirmed. Telegram commands and approximate once-per-minute TP/SL price-level alerts require a connected bot, a configured market-data key and the local API to remain running. These alerts do not modify broker orders. The Windows Charts tab reads public BTCUSDT candles from Binance; its Gold button opens TradingView XAUUSD in a browser. The Windows installation ID is a random local identifier, not a login credential. Broker connections and automated order execution are not enabled. Never commit API keys, passwords, signing keys or broker tokens. QUANTNEX is configured for local single-computer use, not public deployment; do not expose its loopback API.

## GitHub source updates

When the Web workspace is started from run_quantnex.bat → **Start Web + Backend**, it uses apps/web/quantnex_local_server.py rather than a plain static file server. The Updates panel checks the official main branch when the Web workspace starts and every five minutes while it remains open. A newer commit is installed automatically: the loopback updater downloads the archive pinned to that exact commit SHA, validates the archive structure and file limits, backs up replaced Web files under data/updates/backups, and atomically replaces the Web workspace files. If installation fails, replaced files are restored from the backup. The browser reloads automatically after success. If the local user has connected a Telegram bot in QUANTNEX, the updater sends a private update-installed notification through the existing encrypted local Telegram integration; no bot token is placed in GitHub or source code. The updater preserves the local database, .env, Python virtual environment and other user data. Keep the single QUANTNEX CMD window open behind the browser while the API and Web updater run. Important: this source updater changes apps/web only; backend and Windows desktop source updates still use their own update path or a newer full source ZIP.

## Shared Economic News (optional Cloudflare Worker)

QUANTNEX can use one centrally hosted Finnhub economic-calendar feed for all installations. The read-only Worker lives in `services/shared-news`; its Finnhub key is stored as a Cloudflare Worker secret, never in the Web bundle or GitHub source. Deploy and connect it using [the Shared News Service guide](docs/SHARED-NEWS-SERVICE.md). Until the Worker is deployed and its public URL is configured in `apps/web/shared-news-config.js`, installations continue using their existing local Finnhub backend configuration. Wallet, journal, preferences and other personal workspace data remain local.

## Telegram release announcements

QUANTNEX includes an optional GitHub Actions workflow that announces published releases in an official Telegram channel. Create a bot with @BotFather, add it to the channel as an administrator with Post Messages permission, then configure repository Actions secrets TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID. See docs/TELEGRAM-RELEASE-NOTIFICATIONS.md.

## Live market overview, Signal Lab and Telegram Auto Signals

- The Overview displays BTC/USD and XAU/USD spot estimates from keyless Gold-API feeds with provider fallbacks, plus indicative LKR/gram and LKR/8g conversions using a daily USD/LKR reference rate. The LKR conversion is a spot-price estimate, not a local jeweller's retail quote; purity, taxes and dealer premiums are excluded.
- QUANTNEX VIEW is a dedicated first-party chart workspace with BTCUSDT/ETHUSDT/SOLUSDT and XAUUSD selection, multiple chart types, intervals, volume and local drawing tools.
- The Signal Lab retains XAUUSD multi-timeframe analysis and adds directional quality gates for primary/trend EMA bias, selected-timeframe consensus, MACD direction, ADX strength and RSI range. Scores remain rule-count confluence, not win probability.
- The local user creates a Telegram bot through @BotFather, then connects its token and destination chat to the QUANTNEX workspace. Tokens are encrypted in the local database using a key derived from QUANTNEX_SECRET_KEY.
- Auto Signals are opt-in for the local workspace. When enabled, the local API scans XAUUSD at the selected interval (minimum 60 seconds), requires at least 8/10 confluence plus directional filters, and sends only a new primary-timeframe candle signal to the connected local bot. It does not place trades.
- Start Web + Backend using `run_quantnex.bat` option 2 to launch both the local API and Web updater. Keep the single CMD window open behind the browser. Configure `TWELVE_DATA_API_KEY` in `backend/.env` for Gold, USD/LKR and signal analysis; BTC ticker uses Binance public market data.
- The laptop must remain powered on, connected to the internet and running the QUANTNEX API for Auto Signals. A VPS can host the same API process for continuous operation. The browser itself does not need to stay open once Auto Signals are saved.
- Reaper is not implemented because its exact formula/source has not been provided. There is no broker execution, automatic SL movement, or verified win-rate calculation.

## Prop Firm Challenge Simulator

- Practice evaluation rules using a local virtual account or optional Windows MT5 DEMO monitoring.
- Configure profit target, daily maximum loss, maximum overall loss, minimum trading days, daily reset timezone and static or trailing drawdown.
- MT5 mode accepts DEMO accounts only. On a rule breach the local guardian attempts to close open demo positions and locks the challenge; this is best-effort protection, not a broker-guaranteed loss limit.
- Virtual mode records manually entered closed P&L and does not create orders.
- Sidebar navigation supports grouped views and short fade transitions; reduced-motion preferences are respected.
