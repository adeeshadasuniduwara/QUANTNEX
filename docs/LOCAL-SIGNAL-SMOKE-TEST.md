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

- `[SIGNAL]`: fresh Spot candles were loaded and the current Spot strategy rules produced a candidate. Review the provider, timestamp and Entry/SL/TP levels.
- `[WAIT]`: Spot data loaded successfully, but the current market conditions did not meet the minimum confluence/quality filters. This is not a feed failure.
- `[FUTURES CANDLE SIGNAL]`: the separate USDⓈ-M Futures candle-only monitor produced a candidate. The printed levels are references, not executable orders.
- `[FUTURES WAIT]`: USDⓈ-M candles loaded successfully but no qualifying candle-confluence setup exists.
- `[SKIP]` / `[FUTURES SKIP]`: the pair/contract is valid but does not yet have enough fully closed history.
- `[ERROR]` / `[FUTURES ERROR]`: a provider, configuration or data-validation problem prevented the scan. The error text identifies the market and failure.

Crypto uses public Binance Spot candles with Coinbase fallback for BTC/ETH/SOL. Gold uses the local read-only MT5 feed when enabled, then Twelve Data when configured as fallback.

For MT5, open the local terminal and make sure the configured Gold symbol is available. If MT5 is not enabled, configure `TWELVE_DATA_API_KEY` in the backend environment. Never put API keys in command-line arguments or commit them to Git.

A successful smoke test proves that the selected provider returned usable data and the engine completed a scan at that moment. It does not prove profitability, future signal quality, broker execution, or a stable live connection.

## Automated public-crypto check

GitHub Actions runs the read-only **QUANTNEX Live Crypto Signal Smoke** workflow daily and on pull requests that change the smoke runner, USDⓈ-M signal/provider adapters or this workflow. It independently discovers the current Binance Spot and USDⓈ-M Futures universes from their authoritative `exchangeInfo` endpoints, then scans deterministic rotating samples of 20 instruments per market type. Each sample rotates daily and is a rate-conscious smoke subset, not a full-universe scan in one run.

- Spot: `/api/v3/exchangeInfo` → active Spot-eligible pairs → multi-timeframe Spot signal engine, execution-quality checks and mandatory sequence-validated Spot Order Flow when a directional setup qualifies.
- USDⓈ-M: `/fapi/v1/exchangeInfo` → active `TRADING` `PERPETUAL` contracts → separate closed 5m candle-only monitor engine. This Futures path does **not** include Futures Order Flow, adaptive MARKET/LIMIT execution, quantity/filter validation for an order, or order placement. A Futures candle signal is not an executable trade instruction.
- COIN-M remains unsupported and is not scanned.
- Newly listed Spot pairs or Futures contracts without enough closed history are reported as skips; provider/data failures remain errors and fail the job.

Run both dynamic samples locally with:

```powershell
python .\\smoke_signal_engine.py --universe-sample-size 20 --usdm-universe-sample-size 20
```

Use `--skip-usdm` to omit the Futures sample, or pass `--symbols BTCUSDT,ETHUSDT` to constrain only the Spot sample. Coinbase fallback remains limited to BTC/ETH/SOL. This cloud check does not test the local MT5 terminal or Gold feed.

The scheduled run on 2026-11-16 failed before scanning because the GitHub runner could not retrieve Binance Spot `exchangeInfo` metadata from the single configured REST host. The shared public REST host failover was merged separately; successful provider smoke runs must still be checked independently from replay/strategy performance. A live WAIT is not proof of strategy quality, and a successful data scan is not proof of profitability.
