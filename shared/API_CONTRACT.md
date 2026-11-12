# QUANTNEX Local API Contract

This document describes the API currently implemented by `backend/app/main.py`,
`backend/app/system_security.py`, and `backend/app/events.py`. It replaces the
original Phase 01 planning placeholder.

## Runtime and security boundary

- Base path: `/api/v1`; health check: `GET /health`.
- The service is intended for one trusted local computer and binds to
  `127.0.0.1:8000`. It is not a public or multi-user API.
- No login, registration, password, JWT, session, or remote-account endpoints
  exist. The backend uses one internal local workspace owner to associate local
  records.
- The Web client is served from `http://127.0.0.1:5500`. Host validation,
  CORS restrictions, and explicit loopback checks on the WebSocket are part of
  the local-only boundary. Do not bind the API to `0.0.0.0`, port-forward it,
  or expose it to a LAN or the public internet.
- JSON request and response bodies use UTF-8. Timestamps are ISO-8601 values.
- FastAPI validation and application errors use the standard
  `{"detail":"..."}` response shape. A successful delete may return HTTP 204
  with no response body.

## Health, market data and charts

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Basic API and database health |
| GET | `/api/v1/market/overview` | Indicative BTC/USD, XAU/USD and USD/LKR overview |
| GET | `/api/v1/charts/candles` | Historical OHLC candles for QUANTNEX VIEW |
| GET | `/api/v1/intelligence/markets` | Supported intelligence markets |
| GET | `/api/v1/intelligence/market/{symbol}/candles` | Market candles for analysis |
| GET | `/api/v1/intelligence/market/{symbol}/orderbook` | Supported market order-book snapshot |
| GET | `/api/v1/data-reliability/markets` | Feed health overview |
| GET | `/api/v1/data-reliability/market/{symbol}` | Quote freshness and candle-integrity report |
| GET | `/api/v1/intelligence/news` | Configured news/calendar intelligence |
| POST | `/api/v1/intelligence/signals/scan` | Rule-based market signal analysis |
| POST | `/api/v1/intelligence/risk/calculate` | Risk calculation |
| GET | `/api/v1/intelligence/performance` | Intelligence performance summary |

Crypto market data uses public Binance Spot endpoints. Gold and supported Forex
data require a locally configured Twelve Data key. Market data is indicative;
provider prices are not guaranteed broker execution prices. Unsupported order
books are reported as unsupported rather than simulated.

## Local records and preferences

| Method | Path | Purpose |
|---|---|---|
| GET, POST | `/api/v1/journal` | List and create local journal records |
| DELETE | `/api/v1/journal/{trade_id}` | Delete a journal record and its linked journal-P&L ledger entry |
| GET | `/api/v1/wallet/summary` | Read local wallet ledger totals |
| GET, POST | `/api/v1/wallet/transactions` | List and add manual deposit/withdrawal records |
| GET | `/api/v1/preferences` | Read local workspace preferences |
| PUT | `/api/v1/preferences/{key}` | Save a local workspace preference |

The wallet is bookkeeping only; it is not a bank, payment, or broker balance.
Paper trades are stored separately and do not silently alter the manual wallet.

## Signals, Telegram and optional AI

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/signals/status` | Signal-provider configuration status |
| GET, PUT | `/api/v1/signals/settings` | Read and save local signal settings |
| POST | `/api/v1/signals/scan` | Scan a selected supported market |
| POST | `/api/v1/telegram/send` | One-off user-triggered Telegram send; supplied token is not stored |
| POST | `/api/v1/telegram/connect` | Verify and save an encrypted local bot connection |
| GET | `/api/v1/telegram/status` | Read bot connection status without returning secrets |
| DELETE | `/api/v1/telegram/connect` | Disconnect and remove the saved bot connection |
| GET, PUT | `/api/v1/telegram/auto-signals` | Read and save opt-in local auto-signal settings |
| POST | `/api/v1/telegram/notify` | Send a message through the saved local bot |
| GET | `/api/v1/ai/status` | Optional AI provider status |
| POST | `/api/v1/ai/chat` | Optional server-side AI chat gateway |

Telegram bot tokens are encrypted in the local database using the stable local
`QUANTNEX_SECRET_KEY`. Never put provider keys or bot tokens in browser code or
commit them to GitHub. Crypto signal scans use Binance Spot; XAUUSD requires
Twelve Data configuration.

## Paper trading, strategy research and risk

| Method | Path | Purpose |
|---|---|---|
| GET, POST | `/api/v1/paper-trading/trades` | List and open virtual paper trades |
| POST | `/api/v1/paper-trading/trades/{trade_id}/close` | Close a virtual paper trade |
| GET | `/api/v1/paper-trading/summary` | Paper ledger summary |
| POST | `/api/v1/paper-trading/smart-open` | Risk-checked paper entry using a fresh provider quote |
| GET | `/api/v1/strategy-lab/replay` | Historical market replay |
| POST | `/api/v1/strategy-lab/backtest` | Strategy backtest |
| POST | `/api/v1/strategy-lab/optimize` | Bounded parameter optimization |
| POST | `/api/v1/strategy-lab/forward/evaluate` | Save a forward observation |
| GET | `/api/v1/strategy-lab/research` | Saved research history |
| GET | `/api/v1/risk/portfolio` | Open paper exposure and planned risk |
| POST | `/api/v1/risk/position-size` | Position-size estimate |
| POST | `/api/v1/risk/guardian` | Evaluate configured paper-risk limits |
| POST | `/api/v1/risk/stress` | Portfolio stress scenarios |
| GET | `/api/v1/performance/advanced` | Advanced paper-trade performance analytics |

Paper trading is simulated and local. Backtests and confluence scores are not
verified win rates or guarantees. No broker order, live execution, or automatic
broker stop modification is exposed by these routes.

## Local system maintenance

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/system/health` | Database, device and backup health |
| GET, POST | `/api/v1/system/backups` | List or create a local SQLite backup |
| POST | `/api/v1/system/backups/{filename}/verify` | Verify a generated backup |
| POST | `/api/v1/system/backups/{filename}/restore` | Restore a verified local backup |
| GET | `/api/v1/system/audit` | Read allow-listed local audit events |
| GET | `/api/v1/system/metrics` | Local CPU, memory and disk telemetry |

Backup restore is a destructive maintenance action and must only use a generated,
verified local backup. PostgreSQL backup/restore is not implemented.

## Local real-time events

- WebSocket: `ws://127.0.0.1:8000/api/v1/events/stream`.
- The stream is loopback-only, process-local, bounded, and versioned.
- Events are published after the corresponding database transaction commits.
- The stream does not provide durable replay. Clients must reload REST snapshots
  after reconnect, sequence gaps, queue overflow, or a server restart.
- Binance provider market streams are separate from the local workspace event
  gateway.

## Not implemented / explicitly out of scope

- No `/api/v1/auth/*`, login, registration, password reset, or cloud identity.
- No public cloud relay or multi-user remote API.
- No broker account connection, live broker order placement, or auto execution.
- Android is currently a starter UI and is not connected to this local backend.
