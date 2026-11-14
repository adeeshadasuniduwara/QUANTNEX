# QUANTNEX Phase 07 — Advanced Trading Intelligence Architecture

## 1. Product boundary

Phase 07 is a local Windows trading research and paper-trading workspace. It preserves the selected local-only / no-login design. The API remains bound to loopback and the browser talks to the local API. There is no public multi-user service, broker connection, live order endpoint or real-money execution path.

Existing Wallet, completed Trade Journal, Preferences, Telegram configuration and Phase 06.3 audit/backup data remain in their existing tables. Phase 07 adds only the `paper_trades` table.

## 2. Runtime layout

```text
QUANTNEX Web Workspace
                 |
                 v
        apps/web (single-page UI)
                 |
       http://127.0.0.1:8000
                 |
                 v
          FastAPI local API
                 |
      +----------+-----------+
      |          |           |
      v          v           v
Intelligence  Paper Ledger  Risk / Performance
Engine        + Monitor     Analytics
      |          |           |
      +----------+-----------+
                 |
          Local SQLite DB
                 |
       +---------+----------+
       |         |          |
       v         v          v
   Wallet     Journal    Preferences
   (existing) (existing) (existing)
                 |
                 v
              Audit
```

## 3. Pages and responsibilities

| Page | Responsibilities |
|---|---|
| Market Intelligence | Provider quote board, daily high/low, source and unavailable status |
| AI Signal Center | Rule-based 15m / 1h / 4h confluence, quality filters, Entry / SL / TP1–TP3 or WAIT |
| Order Flow & Liquidity | Binance Spot depth snapshots, bid/ask quantity and imbalance |
| News Intelligence | Finnhub economic calendar when optional API key is configured |
| Paper Trading | Open/close virtual positions, fresh provider quote, automatic SL/TP monitoring |
| Performance Lab | Closed paper trade count, win rate, gross/net P&L and profit factor |
| Risk Management | Risk amount and theoretical base-unit sizing calculator |

## 4. Market-data adapters

- Binance public Spot REST: BTCUSDT, ETHUSDT and SOLUSDT ticker, klines and depth.
- Twelve Data: XAU/USD, EUR/USD, GBP/USD and USD/JPY quotes/candles. Requires `TWELVE_DATA_API_KEY`.
- Finnhub economic calendar: optional. Requires `FINNHUB_API_KEY`.
- Missing/unsupported data must be displayed as unavailable. Do not invent prices, order-book depth or calendar events.
- All provider prices are indicative; they are not executable broker quotes.

## 5. Signal engine

The current signal engine is deterministic and rule-based, not a trained machine-learning predictor. It uses 15m, 1h and 4h candles; EMA structure, MACD, RSI, ADX, BOS/MSS, liquidity sweep, OB/FVG reaction zones and premium/discount context. The score is a confluence count out of 10, not a probability or expected win rate. Directional quality filters must all pass; otherwise status is WAIT.

## 6. Paper execution flow

1. User selects market, side, quantity, stop loss and take profit.
2. API fetches a fresh provider quote and validates the SL/TP relationship against the quote.
3. A row is written to the additive `paper_trades` table.
4. A lightweight local worker checks open positions every 10 seconds while the API is running.
5. If a provider quote reaches SL or TP, the worker closes the virtual position and records simulated P&L.
6. User may also manually close a position using a fresh quote.
7. Performance endpoints aggregate closed paper trades only.

Quantity means base units, not broker lots. Contract multiplier, margin, broker tick value, fees, spread and slippage are not fully modeled. Provider polling stops when the local API is stopped; price gaps may affect simulated exit prices.

## 7. Data and safety rules

- Existing Wallet and Journal rows are not changed by paper trades.
- No broker credentials or trading permissions are requested.
- No live broker order route is included.
- Paper monitor, Telegram worker and daily backup worker are paused during database restore.
- Keep API bound to localhost/127.0.0.1; do not expose port 8000 to LAN or the public internet.
- Optional provider keys stay in local `backend/.env`, not in browser JavaScript, Git commits, API responses or audit events.

## 8. API groups

- `GET /api/v1/intelligence/markets`
- `GET /api/v1/intelligence/market/{symbol}/candles?timeframe=15m`
- `GET /api/v1/intelligence/market/{symbol}/orderbook`
- `POST /api/v1/intelligence/signals/scan`
- `GET /api/v1/intelligence/news?days=7`
- `POST /api/v1/intelligence/risk/calculate`
- `GET /api/v1/intelligence/performance`
- `GET /api/v1/paper-trading/trades`
- `POST /api/v1/paper-trading/trades`
- `POST /api/v1/paper-trading/trades/{id}/close`
- `GET /api/v1/paper-trading/summary`

## 9. Phase 07 delivery checklist

- [x] Multi-market adapter foundation
- [x] Rule-based MTF signal API
- [x] Binance crypto depth API
- [x] Optional economic calendar API
- [x] Isolated paper-trade table and APIs
- [x] Automatic paper SL/TP monitor
- [x] Risk calculator and performance endpoints
- [x] Seven new local dashboard sections
- [x] Unit tests for market catalog, risk sizing and SL/TP triggers
- [ ] Manual Windows end-to-end validation with the user's provider keys
- [ ] Verify local database backup and restore before enabling day-to-day paper usage
