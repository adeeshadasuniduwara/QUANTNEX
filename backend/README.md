# QUANTNEX Backend — Shared API

FastAPI shared API foundation for Windows, Android and Web.

## Included
- Health endpoint and OpenAPI documentation.
- Registration/login, Argon2 password hashes and expiring JWT bearer tokens.
- WebAuthn passkeys for platform authenticators such as Windows Hello, with one-time five-minute challenges, origin/RP validation, user verification and signature/counter checks.
- Multiple passkeys per account; the last registered passkey cannot be removed.
- Authentication endpoint throttling: up to five login/registration attempts per client IP per minute (per local API process).
- Telegram commands restricted to the configured owner's private chat; group/channel posts cannot control settings.
- Telegram `/help`, `/settings`, `/pause` and `/resume` commands in addition to timeframe, scan and status commands.
- Authenticated user profile.
- User-isolated trade journal list/create/delete APIs.
- Wallet ledger for manual deposits and withdrawals, with balance checks.
- Journal P&L automatically creates a linked wallet ledger entry; deleting a journal record removes its linked P&L entry.
- User-isolated preferences read/write APIs.
- Optional server-side OpenAI-compatible AI chat gateway; disabled until configured.
- SQLite local development and PostgreSQL driver support.

## Run locally (Python 3.11+)

From the repository root:

```powershell
cd backend
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set a unique QUANTNEX_SECRET_KEY in .env, then run:

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/health and http://127.0.0.1:8000/docs.

## API routes

| Method | Path | Auth |
|---|---|---|
| GET | /health | No |
| POST | /api/v1/auth/register | No |
| POST | /api/v1/auth/login | No |
| POST | /api/v1/auth/passkeys/login/options | No |
| POST | /api/v1/auth/passkeys/login/verify | No |
| POST | /api/v1/auth/passkeys/register/options | Bearer |
| POST | /api/v1/auth/passkeys/register/verify | Bearer |
| GET | /api/v1/auth/passkeys | Bearer |
| DELETE | /api/v1/auth/passkeys/{credential_pk} | Bearer |
| GET | /api/v1/auth/me | Bearer |
| GET, POST | /api/v1/journal | Bearer |
| DELETE | /api/v1/journal/{trade_id} | Bearer |
| GET | /api/v1/wallet/summary | Bearer |
| GET, POST | /api/v1/wallet/transactions | Bearer |
| GET | /api/v1/preferences | Bearer |
| PUT | /api/v1/preferences/{key} | Bearer |
| GET | /api/v1/ai/status | Bearer |
| POST | /api/v1/ai/chat | Bearer |

Wallet transaction amounts are stored as signed ledger entries. Deposits are positive, withdrawals are negative, and journal P&L is linked to its trade. This is an internal record-keeping ledger, not a bank, broker, or payment integration. Existing clients are not yet connected to these wallet endpoints.

Set AI_BASE_URL, AI_API_KEY and AI_MODEL on the server only. The API key is never shipped to client applications.

## Production checklist

Use HTTPS, managed secrets, PostgreSQL, Alembic migrations, backups, rate limiting, audit logs, monitoring and security testing before public deployment. SQLite/create_all are development MVP choices. This API does not connect to brokers, fetch live prices, run bots or place orders.


## XAUUSD signal engine (local API)

The Web Trading Tool can request authenticated XAU/USD multi-timeframe analysis from the backend. Configure a Twelve Data API key on the server; do not place provider keys in browser JavaScript or GitHub.

1. Create a Twelve Data account and obtain an API key: https://twelvedata.com/
2. Add `TWELVE_DATA_API_KEY=your_key` to `backend/.env`.
3. Restart the API process.
4. Sign in to QUANTNEX Web, select primary/trend/analysis timeframes, then run a signal scan.

The engine retrieves OHLC candles for M1, M5, M15, M30 and H1. M50 is custom-aggregated from M1 candles and therefore has shorter history (EMA200 is unavailable until enough candles exist). Twelve Data documents supported intervals and output-size limits at https://support.twelvedata.com/en/articles/5656039-how-to-get-historical-prices.

### Indicator / confluence rules

The current rule-based model calculates EMA 20/50/200, MACD (12,26,9), RSI(14), ADX(14), ATR(14), swing-based BOS/MSS, simple liquidity sweeps, and heuristic Order Block, Breaker Block, FVG and inverse-FVG zones. The selected enabled timeframes contribute to a 0–10 confluence score. The score is a count of rules that align, **not** a measured win probability or backtested accuracy. The default signal threshold is 7/10. A scan returns WAIT when the threshold is not met.

The "Reaper" name does not identify a verified formula or source script in this repository. It is intentionally not counted as an active indicator until its exact definition/source is supplied. OB/Breaker/FVG detection here is an explicitly heuristic implementation, not a certified ICT indicator.

### Telegram bot

1. In Telegram, open @BotFather, send `/newbot`, and create a bot.
2. Open the new bot and send `/start`. Obtain your private numeric chat ID (or add the bot as a channel admin and use `@ChannelUsername`).
3. Sign in to QUANTNEX Web and use **Connect bot & enable commands**. The API verifies the token and stores it encrypted using a key derived from `QUANTNEX_SECRET_KEY`.
4. Keep the local API running. The background worker polls the bot and watches active XAU/USD signal levels while the API process is alive.

Commands: `/help`, `/status`, `/settings`, `/timeframes`, `/settf 5`, `/settrend 60`, `/setanalysis 1,5,15,30,50,60`, `/scan`, `/pause`, `/resume`.

Interactive commands are accepted only from the configured numeric private chat. Group/channel messages are ignored for command control, even if the bot is a member or administrator. A channel can still be configured as an alert destination, but use your own private chat ID for bot control. Login and registration are throttled per source IP in this single API process; this in-memory guard is intended for local single-computer use and is not a substitute for a shared rate limiter behind a public deployment.

When a signal is active, the worker checks price levels approximately once per minute and sends SL/TP1/TP2/TP3 touch alerts. TP1 alert advises moving SL to breakeven; it does not change a broker order. This is price-level monitoring, not guaranteed tick-by-tick execution. Provider quotas, outages, stale data and network delays can delay or miss alerts.

### Safety and operating limits

- This is analysis and notification only. No broker account, order routing, trade execution or automatic stop modification is connected.
- Entry/SL/TP levels are derived from the latest provider candle and ATR/swing structure; validate them against your broker's quote, spread and contract specification.
- Use a dedicated Telegram bot and a strong, persistent `QUANTNEX_SECRET_KEY`. Changing that key makes stored bot tokens undecryptable; reconnect the bot after key rotation.
- Do not use the default development secret in a public deployment. Use HTTPS, a persistent always-on host, secure database backups, rate limiting and monitoring before exposing the API to the internet.
- Test the strategy on historical data and paper trading before relying on it. A 7/10 confluence score does not imply a 70% win rate.


## Windows Hello / Passkey sign-in

The local launcher opens the web workspace at http://localhost:5500/ because WebAuthn requires a secure context; localhost is treated as secure by modern browsers. Keep the browser on this hostname (do not switch to 127.0.0.1) for passkey enrollment and sign-in.

1. Start QUANTNEX with run_quantnex.bat.
2. Sign in once with the existing QUANTNEX email and password.
3. Select Add Windows Hello Passkey and approve the Windows Security prompt with the Windows Hello PIN, fingerprint or face sign-in supported by the device.
4. Sign out, enter the same account email, and choose Sign in with Windows Hello to test the passkey.
5. Keep a second passkey/recovery method where possible.

The website never receives the Windows account password. WebAuthn private keys remain with the platform authenticator; QUANTNEX stores the credential public key and credential identifier only. Passkey challenges expire after five minutes and are single-use. The API checks the exact allowed origin and RP ID and requires user verification.

Default local configuration:
- WEBAUTHN_RP_ID=localhost
- WEBAUTHN_ALLOWED_ORIGINS=http://localhost:5500

For a remote deployment, configure a real HTTPS origin and matching RP ID; do not expose the local development defaults to the public internet.

Migration safety: existing email/password login remains available in this release. Do not disable it until the owner has successfully tested the passkey and configured a recovery passkey. Losing the only platform passkey before recovery is configured can lock the user out. The new credential/challenge tables are created additively at API startup; existing user, journal and wallet rows are not rewritten.
