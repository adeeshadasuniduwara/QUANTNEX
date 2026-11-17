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

GitHub Actions runs the read-only **QUANTNEX Live Crypto Signal Smoke** workflow daily. The updated workflow discovers the eligible Binance Spot universe from current `exchangeInfo` and scans a deterministic rotating sample of 20 pairs per run. This is a rate-conscious smoke subset, not a full-universe scan in one run. Use `python smoke_signal_engine.py --universe-sample-size 20` for the same mode, or pass `--symbols BTCUSDT,ETHUSDT` for an explicit sample. Pairs without enough fully closed candle history are reported as `[SKIP]`; provider/data failures remain `[ERROR]` and fail the job. Coinbase fallback remains limited to BTC/ETH/SOL. This cloud check does not test the local MT5 terminal or Gold feed. Binance USDⓈ-M and COIN-M Futures are not included.

The scheduled run on 2026-11-16 failed before scanning because the GitHub runner could not retrieve Binance Spot `exchangeInfo` metadata from the single configured REST host. A separate read-only Binance connector check later returned live Spot metadata and BTCUSDT trade/depth data, but that does not prove the GitHub runner can reach the API. The `fix/binance-public-data-endpoint-failover` branch is adding official public REST host fallback; verify the next scheduled run before treating this provider path as reliable.
