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
```

Keep the generated QUANTNEX_SECRET_KEY in backend/.env stable so saved Telegram tokens remain decryptable. Then run:

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
