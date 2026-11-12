# QUANTNEX Backend — Local API

FastAPI service for one QUANTNEX workspace on one Windows computer. There is no user login, registration, password, JWT session or remote account system.

## Included
- Health endpoint and OpenAPI documentation.
- Local trade journal list/create/delete APIs.
- Local wallet ledger for manual deposits and withdrawals, with balance checks.
- Journal P&L automatically creates a linked wallet ledger entry; deleting a journal record removes its linked P&L entry.
- Local workspace preferences for signal settings and Telegram configuration.
- Optional server-side OpenAI-compatible AI chat gateway; disabled until configured.
- SQLite local development and PostgreSQL driver support for future migrations.
- Telegram bot credentials encrypted at rest using the persistent local QUANTNEX_SECRET_KEY.

## Run locally (Python 3.11+)

From the repository root:

```powershell
cd backend
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
Copy-Item .env.example .env
py bootstrap.py
```

The bootstrap step creates a strong local QUANTNEX_SECRET_KEY (if needed), validates imports and initializes the local database. Keep the generated key in backend/.env stable so saved Telegram tokens remain decryptable. Then run:

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/health and http://127.0.0.1:8000/docs.

## Local-only API routes

| Method | Path | Access |
|---|---|---|
| GET | /health | Loopback only |
| GET, POST | /api/v1/journal | Loopback only |
| DELETE | /api/v1/journal/{trade_id} | Loopback only |
| GET | /api/v1/wallet/summary | Loopback only |
| GET, POST | /api/v1/wallet/transactions | Loopback only |
| GET | /api/v1/preferences | Loopback only |
| PUT | /api/v1/preferences/{key} | Loopback only |
| GET | /api/v1/ai/status | Loopback only |
| POST | /api/v1/ai/chat | Loopback only |
| GET, PUT | /api/v1/signals/settings | Loopback only |
| POST | /api/v1/signals/scan | Loopback only |
| GET, POST, DELETE | /api/v1/telegram/* | Loopback only |

There are no /api/v1/auth/* routes. The backend binds to 127.0.0.1, restricts accepted Host values, and permits only the local QUANTNEX Web origin. Do not bind it to 0.0.0.0, forward its port, or expose it to a LAN or the public internet. Local API access assumes the Windows user account is trusted.

On first API use, legacy user records are migrated to one internal local workspace owner. Existing trades, wallet transactions and preferences are reassigned to that workspace; duplicate preference keys retain the first workspace value. Legacy account rows are removed and stored password hashes are cleared. Before migration, the app automatically backs up a SQLite database to data/backups/quantnex-pre-local-only-*.db. Keep this backup until you confirm the local workspace contains all your data.

Wallet transaction amounts are signed ledger entries. Deposits are positive, withdrawals are negative, and journal P&L is linked to its trade. This is internal record keeping, not a bank, broker or payment integration.

Set AI_BASE_URL, AI_API_KEY and AI_MODEL on the local server only. The API key is never shipped to client applications.

## XAUUSD signal engine and Telegram bot

The Web Trading Tool can request XAU/USD multi-timeframe analysis from the local backend. Configure TWELVE_DATA_API_KEY in backend/.env; never put provider keys in browser JavaScript or GitHub. Signal settings are saved to the local workspace.

1. Create a Telegram bot with @BotFather using /newbot.
2. Open the new bot and send /start. Obtain your private numeric chat ID, or add the bot as a channel admin and use @ChannelUsername.
3. In QUANTNEX Web, use **Connect bot & enable commands**. The API verifies the token and stores it encrypted using a key derived from QUANTNEX_SECRET_KEY.
4. The local API background worker polls the connected bot and monitors active XAU/USD signal levels while the API process is running.

Commands: /help, /timeframes, /settf 5, /settrend 60, /setanalysis 1,5,15,30,60, /scan, /status.

When a signal is active, the worker checks price levels approximately once per minute and sends SL/TP1/TP2/TP3 touch alerts. TP1 alert advises moving SL to breakeven; it does not change a broker order. This is price-level monitoring, not guaranteed tick-by-tick execution.

## Safety and operating limits

- This is local analysis and notification only. No broker account, order routing, trade execution or automatic stop modification is connected.
- Entry/SL/TP levels are derived from provider candles and ATR/swing structure; validate them against your broker quote, spread and contract specification.
- Keep QUANTNEX_SECRET_KEY stable and private. Changing it makes stored bot tokens undecryptable; reconnect the bot after key rotation.
- The local API has no per-user authentication because it is intentionally loopback-only. Do not expose it outside the trusted Windows computer.
- Test strategies on historical data and paper trading before relying on them. A 7/10 confluence score does not imply a 70% win rate.


## Phase 06.3 — Local database and system security

- Local SQLite backups use SQLite's online backup API so an active database is snapshotted consistently. Each backup has a SHA256 sidecar and is checked with PRAGMA integrity_check.
- The local API keeps the newest 14 backups. Backup creation, verification and restore are available under /api/v1/system/backups.
- Restore accepts only a generated backup filename, verifies both the SHA256 manifest and SQLite integrity, creates a separate pre-restore safety backup, then atomically replaces the database file.
- GET /api/v1/system/health reports database status/size, CPU, memory, disk capacity and backup status. GET /api/v1/system/audit shows local maintenance and workspace audit events.
- Audit records contain allow-listed metadata only; API keys, Telegram bot tokens, passwords, request bodies and secret values are not recorded.
- Automated file backup/restore currently supports persistent SQLite databases. PostgreSQL backup/restore is intentionally reported as unsupported until a separately tested pg_dump / pg_restore workflow is implemented.
- All system endpoints rely on the existing loopback-only API boundary. Do not bind to 0.0.0.0, port-forward the API, or expose it to a LAN/public network. This local-only mode trusts the Windows desktop user.


## Phase 07 — Advanced Trading Intelligence

Phase 07 adds a multi-market intelligence layer while preserving the local-only, no-login workspace and all existing Wallet, Journal, Preferences, Telegram settings and database records.

### Supported market feeds
- Crypto: BTCUSDT, ETHUSDT and SOLUSDT through public Binance Spot ticker, kline and order-book endpoints.
- Gold and Forex: XAUUSD, EURUSD, GBPUSD and USDJPY through the configured Twelve Data API key.
- Economic calendar: optional Finnhub calendar feed using `FINNHUB_API_KEY`. Without the key, the page clearly reports that the provider is not configured; no calendar events are fabricated.
- Order book: real Binance Spot depth snapshots for supported crypto pairs only. Gold/Forex depth is reported unsupported rather than simulated.

### Signal analysis
- Multi-timeframe technical analysis uses 15m, 1h and 4h candles, EMA structure, MACD, RSI, ADX, BOS/MSS and liquidity-sweep context.
- Signal scores are transparent rule-based confluence counts, not probabilities or promised win rates.
- Every scan returns BUY/SELL only if directional quality filters pass; otherwise it returns WAIT.
- Indicative market-provider prices can differ from broker execution quotes and spreads.

### Paper trading
- New `paper_trades` table is additive; the existing Wallet, Journal and user preferences are not rewritten.
- Paper entries use a fresh provider quote, require a valid stop/target relationship, and store virtual quantity only.
- Closing a paper trade uses a fresh quote and calculates simulated P&L. No broker API or live-order route exists.
- Paper trading is a separate virtual ledger; it does not change the existing wallet balance or journal.

### API routes
- `GET /api/v1/intelligence/markets`
- `GET /api/v1/intelligence/market/{symbol}/candles?timeframe=15m`
- `GET /api/v1/intelligence/market/{symbol}/orderbook`
- `POST /api/v1/intelligence/signals/scan` with `{"symbol":"BTCUSDT","min_score":6}`
- `GET /api/v1/intelligence/news?days=7`
- `POST /api/v1/intelligence/risk/calculate`
- `GET /api/v1/intelligence/performance`
- `GET /api/v1/paper-trading/summary`
- `GET /api/v1/paper-trading/trades`
- `POST /api/v1/paper-trading/trades`
- `POST /api/v1/paper-trading/trades/{id}/close`

### Local setup
- Add `TWELVE_DATA_API_KEY` for Gold/Forex data.
- Add `FINNHUB_API_KEY` only if you want the economic calendar.
- Binance public Spot endpoints work without an API key.
- Keep the API bound to localhost/127.0.0.1. This remains a local desktop workspace, not a public multi-user service.
- Real-money execution is intentionally not implemented in Phase 07.


## Phase 08 — Strategy Laboratory

- Strategy Builder currently provides a deterministic EMA crossover template (fast/slow EMA and reward multiple).
- Backtesting uses provider candles and reports trade outcomes, win rate, profit factor and maximum drawdown. It uses one abstract unit and does not model broker costs, spread, slippage or contract specifications.
- Market Replay steps through historical provider candles.
- Optimizer evaluates a bounded 27-combination EMA/reward grid and warns about in-sample overfitting.
- Forward evaluation records a live candle observation only; it does not open paper or broker positions. The Research page aggregates these records and closed paper-trade statistics.
- The new strategy_lab_runs table is additive. Existing Wallet, Journal, preferences, Telegram settings and paper-trade data are preserved.
- No automatic machine-learning training, broker integration, login flow or real-money execution is added. See docs/PHASE_08_STRATEGY_LAB.md.
