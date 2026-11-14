# QUANTNEX

**A trading workspace for Android and Web.**

QUANTNEX combines market charts, trading utilities, trade records, paper trading, risk tools and secure local integrations. The project is focused on two user-facing products: the responsive Web workspace and the native Android APK. There is no Windows desktop executable or installer. A Windows computer may be used as the local host for the Web workspace and its Backend API.

## Download

- **Android APK:** [Open GitHub Releases](https://github.com/adeeshadasuniduwara/QUANTNEX/releases) and download `QUANTNEX-Android.apk` from the latest signed Android release. The previous v0.6.0 release predates the Android-only release pipeline.
- **Release notes and SHA256:** [Latest GitHub Release](https://github.com/adeeshadasuniduwara/QUANTNEX/releases/latest)
- **Web workspace:** Run the local Web + Backend launcher as described below, or host the Web workspace on an HTTPS origin reachable by the Android phone.

Android updates are checked against the latest GitHub Release. The app verifies the APK SHA256 against the release checksum manifest before opening Android's package installer. Android requires the user to approve installation; silent self-install is not available. Production APKs must use the same private signing keystore for every release so installed copies can update in place.

## Products

- **Web:** responsive browser workspace with QUANTNEX VIEW charts, live crypto/Gold market data, multi-timeframe signal analysis, browser-local journal, wallet, paper trading, risk tools, strategy research and Telegram controls.
- **Android:** native app shell that loads the hosted QUANTNEX Web workspace and provides Android navigation, workspace settings and verified APK update checks.
- **Backend:** loopback-only FastAPI service for the local Web workspace, journal, wallet ledger, preferences, optional AI gateway, XAU/USD analysis and Telegram bot command / price-level alert worker.

The Android app needs an HTTPS Web workspace URL reachable from the phone. A `127.0.0.1` URL on a Windows computer is not reachable from an Android phone. The Android app does not expose or tunnel the local-only Backend API. Personal browser journal data remains in that browser profile.

## Run the Web workspace on Windows

1. Install Python 3.11 or newer and make sure the Python launcher (`py`) or `python` is available in PATH.
2. Download or clone this repository.
3. Run `run_quantnex.bat` from the repository root.
4. Choose **1 — Start Web + Backend + Auto Updates**.
5. Keep the Command Prompt window open while using QUANTNEX. The browser opens at [http://127.0.0.1:5500](http://127.0.0.1:5500).

The first start creates an isolated Python environment, installs Backend dependencies and runs a configuration/database preflight. This can take several minutes. Startup output is shown in the console and saved to `logs/launcher.log`. If startup fails, the launcher stays open and displays the error instead of silently closing. Do not open `apps/web/index.html` directly: API-backed features require the trusted local Web origin.

Launcher options:
- **1:** Web + Backend with automatic source updates (recommended).
- **2:** Backend API only.
- **3:** Open Web source files; this does not start the services.

## Backend and local-data safety

See [backend/README.md](backend/README.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). The local API has no login, registration, password, JWT or remote account routes. It creates one local workspace identity internally so journal, wallet, signal settings and encrypted Telegram configuration can be stored consistently. On first startup, a SQLite backup is saved under `data/backups` before legacy account records are consolidated into that workspace and old password hashes are cleared.

The API listens on `127.0.0.1` only and accepts the local Web origin. Do not expose it to a LAN or the public internet. Never commit API keys, passwords, signing keys or broker tokens.

## Market data and trading safety

QUANTNEX VIEW renders first-party charts using TradingView Lightweight Charts (the rendering library, not a hosted TradingView widget). Crypto OHLC candles use Binance Spot, with Coinbase Exchange fallback for BTC/ETH/SOL on supported intervals. XAUUSD historical candles use the optional local read-only MT5 terminal when enabled or the Twelve Data OHLC feed configured server-side in `backend/.env`. If neither historical provider is available, the chart can show a clearly labelled Gold-API indicative live quote; that quote is not OHLC history or an executable broker price.

The Overview displays BTC/USD and XAU/USD spot estimates with provider fallbacks, plus indicative LKR/gram and LKR/8g conversions using a daily USD/LKR reference rate. The LKR conversion is not a jeweller's retail quote; purity, taxes and dealer premiums are excluded.

The rule-based 0–10 confluence score is not a win probability. EMA, MACD, RSI, ADX, ATR, swing structure, liquidity sweep and heuristic OB / Breaker / FVG / iFVG / premium-discount zones are included. Reaper is not active because its exact formula/source has not been confirmed. Telegram commands and approximate once-per-minute TP/SL price-level alerts require a connected bot, a configured market-data key and the local API to remain running. These alerts do not modify broker orders. Broker connections and automated order execution are not enabled.

The local API can optionally read MT5 DEMO data on a supported Windows host when explicitly configured. This is a Backend data integration, not a Windows desktop application. MT5 DEMO monitoring is best-effort and does not guarantee broker-side loss limits.

## Source updates

When started with launcher option 1, `run_quantnex_services.py` supervises the local source tree. It checks the official `main` branch at startup and every five minutes, downloads the archive pinned to the exact commit SHA, validates it, backs up changed source files, and atomically installs the update. The Updates panel reports installed and latest `main@SHA` revisions; **Check for updates** can request an immediate supervisor check. If an update is applied, the supervisor restarts the services, confirms startup health and the browser refreshes. Failed startup checks trigger automatic source rollback.

The updater preserves local data, `.env` files, Python virtual environments and other user data. If the local user has connected a Telegram bot, the updater can send a private update-installed notification through the existing encrypted local Telegram integration. Keep the single QUANTNEX Command Prompt window open behind the browser.

The source updater updates the Web and Backend source. Android APK releases are separate: the Android app checks GitHub Releases, verifies the signed APK checksum and asks the user to approve installation.

## Shared Economic News (optional Cloudflare Worker)

QUANTNEX can use one centrally hosted Finnhub economic-calendar feed for all installations. The read-only Worker lives in `services/shared-news`; its Finnhub key is stored as a Cloudflare Worker secret, never in the Web bundle or GitHub source. Deploy and connect it using [the Shared News Service guide](docs/SHARED-NEWS-SERVICE.md). Until the Worker is deployed and its public URL is configured in `apps/web/shared-news-config.js`, installations continue using their existing local Finnhub Backend configuration. Wallet, journal and preferences remain local.

## Android release process

The Android release workflow publishes only `QUANTNEX-Android.apk` and `SHA256SUMS.txt`. It does not build or publish Windows executables. Configure these repository Actions secrets before publishing: `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS` and `ANDROID_KEY_PASSWORD`. The same private PKCS#12 keystore must be retained for every production release. See [docs/RELEASES.md](docs/RELEASES.md).

Telegram release announcements are optional. Configure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` Actions secrets if announcements are wanted.

## Important limitations

- Android currently hosts the Web workspace; it does not connect to the computer's loopback-only Backend.
- The laptop/host must remain powered on, connected to the internet and running the QUANTNEX API for local Telegram Auto Signals.
- No broker order placement or verified win-rate calculation is implemented.
- QUANTNEX is designed for local single-computer use, not public Backend deployment. Do not expose the loopback API.
