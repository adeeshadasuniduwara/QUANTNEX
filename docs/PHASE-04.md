# QUANTNEX Phase 04 — Local MT5 Gold Feed Bridge

## Scope

Connect the local QUANTNEX backend to an already installed and running MetaTrader 5 terminal for **read-only market data**. The adapter is optional and disabled by default. QUANTNEX remains local-only and login-free.

## Implemented in this phase

- Lazy, optional MetaTrader5 Python package import; missing package or terminal connection returns a clear actionable error.
- Local terminal connection using the terminal's existing session. QUANTNEX does not request, store, or transmit broker passwords, investor passwords, or account credentials.
- Read-only terminal status, XAUUSD bid/ask quote, and normalized OHLC candle endpoints.
- Supported timeframes: 1m, 5m, 15m, 30m, 1h and 4h.
- Candle validation, UTC timestamps, ascending order, duplicate removal, and a 210–1000 candle limit.
- Opt-in integration into the existing XAUUSD candle analysis path using QUANTNEX_MT5_ENABLED=true; Twelve Data remains the default when the flag is off.
- No order placement, position management, account mutation, or trade execution methods are included.

## Local setup (Windows)

1. Install MetaTrader 5 from your broker and sign in to the broker terminal yourself.
2. Start QUANTNEX once so its backend environment and backend/.env are prepared.
3. Install the optional Python package in the QUANTNEX backend environment if it was not installed automatically:

   ```powershell
   cd backend
   .venv\Scripts\python.exe -m pip install MetaTrader5
   ```

4. In backend/.env, set:

   ```dotenv
   QUANTNEX_MT5_ENABLED=true
   QUANTNEX_MT5_GOLD_SYMBOL=XAUUSD
   ```

   If your broker uses a suffix (for example XAUUSD.a), set that exact Market Watch symbol instead. An optional QUANTNEX_MT5_TERMINAL_PATH can point to terminal64.exe.

5. Restart QUANTNEX and check:
   - http://127.0.0.1:8000/api/v1/market/mt5/status
   - http://127.0.0.1:8000/api/v1/market/mt5/quote?symbol=XAUUSD
   - http://127.0.0.1:8000/api/v1/market/mt5/candles?symbol=XAUUSD&interval=15m&limit=500

## Safety and limitations

- The bridge uses the local terminal's existing connection and does not log in to a trading account.
- Endpoints are served by QUANTNEX's loopback-only API. Do not expose the backend port to a LAN or public network.
- The MT5 terminal must be running, connected, and have sufficient symbol history loaded.
- Broker symbol names differ; use the exact Market Watch symbol.
- Quotes are indicative broker feed data and may be stale when the market is closed or the terminal loses connection.
- The integration is read-only by design. It does not send, modify, or close orders.
- A GitHub CI pass cannot verify a real broker terminal. A local Windows MT5 smoke test remains required.
