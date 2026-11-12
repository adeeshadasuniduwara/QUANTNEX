# QUANTNEX

**A modern trading workspace for Windows, Android and Web.**

QUANTNEX brings trading utilities, trade records and secure integrations together in one evolving application. The Web and Windows workspaces are designed for single-computer local use. QUANTNEX does not require a user login or cloud account.

## Download QUANTNEX

### Windows

[Download QUANTNEX for Windows (.EXE)](https://github.com/adeeshadasuniduwara/QUANTNEX/actions/runs/43185371316)

Download QUANTNEX.exe from the Artifacts section of the build page.

### Android

[Download QUANTNEX for Android (.APK)](https://github.com/adeeshadasuniduwara/QUANTNEX/actions/runs/43185377710)

Download app-debug.apk from the Artifacts section. This is an early Android starter build, not yet feature-complete.

Build artifacts are temporary and retained for 30 days. The Web Updates panel also links to the current source ZIP; the Updates panel checks the latest main branch commit directly.

## Applications

- Web: responsive browser workspace with position sizing, local journal, TradingView XAUUSD chart, configurable multi-timeframe XAUUSD confluence scans, risk planner and Telegram bot controls.
- Windows: desktop workspace with position sizing, local SQLite journal, Binance BTCUSDT candles, installation ID and a local wallet. No login or registration.
- Android: native application starter.
- Backend: loopback-only FastAPI service for the local journal, wallet ledger, preferences, optional AI gateway, Twelve Data XAU/USD analysis and Telegram bot command / price-level alert worker.

## Run from source on Windows

From the repository root, run run_quantnex.bat. Option 1 starts the current Python source (preferred for development and source ZIP updates); option 6 starts the packaged EXE when present. Choose Web or both for the browser workspace. The Web workspace can also be opened from apps/web/index.html.

## Backend

See backend/README.md and docs/ARCHITECTURE.md. The local API has no login, registration, password, JWT or remote account routes. It creates one local workspace identity internally so journal, wallet, signal settings and encrypted Telegram configuration can be stored consistently. On first startup, legacy account records are consolidated into that workspace and old password hashes are cleared. The API listens on 127.0.0.1 only and accepts the local Web origin; do not expose it to a network. Web browser journal entries remain in that browser profile; Windows journal entries remain in the local Windows data folder. Android is not connected to this local-only backend.

## Current capability and safety

The calculator uses broker-specific pip values entered by the user. The web journal stores data in that browser; the Windows journal stores data locally. The Web chart view embeds TradingView; signal calculations use a separate Twelve Data OHLC feed configured server-side in backend/.env. The rule-based 0–10 confluence score is not a win probability. EMA, MACD, RSI, ADX, ATR, swing structure, liquidity sweep and heuristic OB / Breaker / FVG / iFVG / premium-discount zones are included. The Reaper indicator is not active because its exact formula/source has not been confirmed. Telegram commands and approximate once-per-minute TP/SL price-level alerts require a connected bot, a configured market-data key and the local API to remain running. These alerts do not modify broker orders. The Windows Charts tab reads public BTCUSDT candles from Binance; its Gold button opens TradingView XAUUSD in a browser. The Windows installation ID is a random local identifier, not a login credential. Broker connections and automated order execution are not enabled. Never commit API keys, passwords, signing keys or broker tokens. QUANTNEX is configured for local single-computer use, not public deployment; do not expose its loopback API.

## Versioned releases and updates

When the Web workspace is started from run_quantnex.bat → **Start Web + Backend**, it uses apps/web/quantnex_local_server.py rather than a plain static file server. The Updates panel checks the latest commit on the official main branch at startup and whenever **Check & install updates** is pressed. If a newer commit exists, the loopback updater downloads the archive pinned to that exact commit SHA, validates the archive structure and file limits, backs up replaced Web files under data/updates/backups, and atomically replaces the Web workspace files. If installation fails, replaced files are restored from the backup. The browser polls for completion and reloads automatically. The updater preserves the local database, .env, Python virtual environment and other user data. Keep the single QUANTNEX CMD window open behind the browser while the API and Web updater run. This source updater changes apps/web only; backend and Windows desktop source updates are applied when you install a newer full source ZIP or use their own update path.

## Telegram release announcements

QUANTNEX includes an optional GitHub Actions workflow that announces published releases in an official Telegram channel. Create a bot with @BotFather, add it to the channel as an administrator with Post Messages permission, then configure repository Actions secrets TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID. See docs/TELEGRAM-RELEASE-NOTIFICATIONS.md.

## Live market overview, Signal Lab and Telegram Auto Signals

- The Overview displays BTC/USD and XAU/USD spot estimates from keyless Gold-API feeds with provider fallbacks, plus indicative LKR/gram and LKR/8g conversions using a daily USD/LKR reference rate. The LKR conversion is a spot-price estimate, not a local jeweller's retail quote; purity, taxes and dealer premiums are excluded.
- The two embedded TradingView charts are replaced by one dedicated TradingView workspace tab with XAUUSD/BTCUSDT symbol selection.
- The Signal Lab retains XAUUSD multi-timeframe analysis and adds directional quality gates for primary/trend EMA bias, selected-timeframe consensus, MACD direction, ADX strength and RSI range. Scores remain rule-count confluence, not win probability.
- The local user creates a Telegram bot through @BotFather, then connects its token and destination chat to the QUANTNEX workspace. Tokens are encrypted in the local database using a key derived from QUANTNEX_SECRET_KEY.
- Auto Signals are opt-in for the local workspace. When enabled, the local API scans XAUUSD at the selected interval (minimum 60 seconds), requires at least 8/10 confluence plus directional filters, and sends only a new primary-timeframe candle signal to the connected local bot. It does not place trades.
- Start Web + Backend using `run_quantnex.bat` option 2 to launch both the local API and Web updater. Keep the single CMD window open behind the browser. Configure `TWELVE_DATA_API_KEY` in `backend/.env` for Gold, USD/LKR and signal analysis; BTC ticker uses Binance public market data.
- The laptop must remain powered on, connected to the internet and running the QUANTNEX API for Auto Signals. A VPS can host the same API process for continuous operation. The browser itself does not need to stay open once Auto Signals are saved.
- Reaper is not implemented because its exact formula/source has not been provided. There is no broker execution, automatic SL movement, or verified win-rate calculation.

