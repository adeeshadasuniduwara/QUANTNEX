# QUANTNEX live signal/provider smoke test

This is a read-only check of the real market-data providers and the signal engine. It does not send Telegram messages, place broker orders, enable live trading, or change settings.

## Windows PowerShell

Open PowerShell in the repository's `backend` folder and activate the Python environment used by QUANTNEX. Then run:

```powershell
python .\smoke_signal_engine.py
```

To check only crypto feeds:

```powershell
python .\smoke_signal_engine.py --symbols BTCUSDT,ETHUSDT,SOLUSDT
```

To check only Gold:

```powershell
python .\smoke_signal_engine.py --symbols XAUUSD
```

## Expected output

- `[SIGNAL]`: fresh candles were loaded and the current strategy rules produced a candidate. Review the reported provider, timestamp and Entry/SL/TP levels.
- `[WAIT]`: data loaded successfully, but the current market conditions did not meet the minimum confluence/quality filters. This is not a feed failure.
- `[ERROR]`: a provider, configuration or data-validation problem prevented the scan. The error text identifies the market and failure.

Crypto uses public Binance Spot candles with Coinbase fallback for BTC/ETH/SOL. Gold uses the local read-only MT5 feed when enabled, then Twelve Data when configured as fallback.

For MT5, open the local terminal and make sure the configured Gold symbol is available. If MT5 is not enabled, configure `TWELVE_DATA_API_KEY` in the backend environment. Never put API keys in command-line arguments or commit them to Git.

A successful smoke test proves that the selected provider returned usable data and the engine completed a scan at that moment. It does not prove profitability, future signal quality, broker execution, or a stable live connection.

## Automated public-crypto check

GitHub Actions also runs the read-only crypto smoke test daily through the **QUANTNEX Live Crypto Signal Smoke** workflow (BTCUSDT, ETHUSDT and SOLUSDT). It can be started manually from the repository's Actions tab. This cloud check does not test the local MT5 terminal or Gold feed.
