# Binance Spot Demo Auto Trading

QUANTNEX Spot Auto Trading is an opt-in execution worker for Binance **Demo Trading only**.

## Environment and permissions

- REST requests are pinned to `https://demo-api.binance.com/api`; the engine contains no live Spot host fallback.
- Create a separate API key inside Binance Spot Demo Trading. Enable Spot trading permission and keep withdrawals disabled.
- QUANTNEX stores the key and secret encrypted in its local preferences database. Never send either value through Telegram.
- USD-M Futures credentials and settings are independent. This engine does not open Futures orders.
- Spot is long-only. It opens BUY market orders and does not use leverage, short selling, DCA or martingale.

## Enable

1. Connect and test the Binance Spot Demo key in **Binance Exchange Center**.
2. Configure a USDT symbol watchlist, signal score, scan interval and risk limits.
3. Save the Spot Auto settings. Saving does not start trading.
4. Explicitly choose **Start Spot Demo Auto Trading** after reviewing the settings.
5. Keep QUANTNEX running. The background worker scans while the local API is active.

Defaults are 0.5% risk per trade, one open position, three entries per UTC day, 2% daily loss limit, 12 bps maximum spread, and a $10m minimum 24-hour quote volume. The signal engine must return a fresh BUY setup with a MARKET entry type; pending LIMIT setups are skipped by this first execution version, and SELL signals are ignored in Spot mode. The engine uses the signal's own stop-loss and TP3 levels, then rechecks stop risk against the actual average fill.

## Execution and protection

- The worker checks the account's trade permission, free USDT, market quote, spread, 24-hour quote volume, symbol status, quantity step/minimum, price tick and minimum notional.
- Position size is derived from free USDT risk budget and signal stop distance, then capped to 90% of available USDT.
- A deterministic client order ID is used so an uncertain market-order response can be queried instead of blindly submitting a duplicate.
- After the BUY fill, QUANTNEX submits a Binance-native SELL OCO list containing a take-profit limit and stop-loss limit. The exchange manages those exits even if the local QUANTNEX process closes.
- If OCO placement cannot be confirmed, QUANTNEX attempts an emergency market sell and sends a Telegram safety notification. If neither protection nor emergency exit can be confirmed, the bot sends a manual-action warning; inspect Binance immediately.
- One active position per symbol is enforced in the local execution ledger. The signal fingerprint prevents repeated execution of the same candle setup.
- Auto OFF blocks new entries. Existing exchange-native OCO orders are not canceled by the emergency stop.

## Telegram notifications

If a personal Telegram bot is connected in QUANTNEX, the Spot engine sends trade-open, trade-close and safety notifications to that bot. API keys and secrets are never included in Telegram messages.

The existing local updater checks GitHub for new `main` commits while QUANTNEX is open, applies updates with backup/rollback, and notifies the connected personal Telegram bot after a successful local update. GitHub's repository-wide Telegram announcement is a separate workflow and requires valid repository Actions secrets.

## Important limitations

- This is a Demo Trading execution feature, not a promise of profitability. Signal confluence is not win probability.
- Daily realized P&L is estimated from Binance order quote totals and does not include every commission/fee conversion. The daily guard also reserves the planned stop risk of open trades; exchange gaps, slippage and stop-limit non-fills can still exceed planned loss.
- Stop-loss is a stop-limit OCO leg, not a guaranteed market exit. In a fast market it may trigger without filling immediately.
- Keep the API bound to localhost. Do not expose the QUANTNEX local API to a LAN or public network.
- Never enable this engine with live credentials. Only the Binance Demo Trading host is supported.
