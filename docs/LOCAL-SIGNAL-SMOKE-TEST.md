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
- `[WAIT]`: Spot data loaded successfully, but the current market conditions did not meet the minimum confluence/quality filters. The line includes a concise engine reason (for example, score below threshold, conflicting direction, or a failed trend/ADX/RSI/timeframe gate). This is not a feed failure.
- `[FUTURES CANDLE SIGNAL]`: the separate USDⓈ-M Futures candle-only monitor produced a candidate. The printed levels are references, not executable orders.
- `[FUTURES WAIT]`: USDⓈ-M candles loaded successfully but no qualifying candle-confluence setup exists.
- `[SKIP]` / `[FUTURES SKIP]`: the pair/contract is valid but does not yet have enough fully closed history.
- `[ERROR]` / `[FUTURES ERROR]`: a provider, configuration or data-validation problem prevented the scan. The error text identifies the market and failure.
- `[ORDER FLOW READY]`: the independent live Spot probe received public aggregate trades and reconstructed a sequence-validated L2 book for its selected liquid pair. Delta is inferred from Binance's buyer-is-maker flag; CVD is complete only since the bounded stream seed.
- `[ORDER FLOW NOT READY]` / `[ORDER FLOW PROBE ERROR]`: the live stream did not reach safe readiness or a provider/data check failed. This is not a candle WAIT and makes the smoke command exit non-zero.

Crypto uses public Binance Spot candles with Coinbase fallback for BTC/ETH/SOL. Gold uses the local read-only MT5 feed when enabled, then Twelve Data when configured as fallback.

For MT5, open the local terminal and make sure the configured Gold symbol is available. If MT5 is not enabled, configure `TWELVE_DATA_API_KEY` in the backend environment. Never put API keys in command-line arguments or commit them to Git.

A successful smoke test proves that the selected provider returned usable data and the engine completed a scan at that moment. It does not prove profitability, future signal quality, broker execution, or a stable live connection.

## Automated public-crypto check

GitHub Actions runs the read-only **QUANTNEX Live Crypto Signal Smoke** workflow daily. It independently discovers the current Binance Spot and USDⓈ-M Futures universes from their authoritative `exchangeInfo` endpoints, then scans deterministic rotating samples of 20 instruments per market type. Each sample rotates daily and is a rate-conscious smoke subset, not a full-universe scan in one run.

- Spot: `/api/v3/exchangeInfo` → active Spot-eligible pairs → multi-timeframe Spot signal engine, execution-quality checks and mandatory sequence-validated Spot Order Flow when a directional setup qualifies.
- USDⓈ-M: `/fapi/v1/exchangeInfo` → active `TRADING` `PERPETUAL` contracts → separate closed 5m candle-only monitor engine. This Futures path does **not** include Futures Order Flow, adaptive MARKET/LIMIT execution, quantity/filter validation for an order, or order placement. A Futures candle signal is not an executable trade instruction.
- COIN-M remains unsupported and is not scanned.
- Newly listed Spot pairs or Futures contracts without enough closed history are reported as skips; provider/data failures remain errors and fail the job.

The default command also runs a separate Spot Order Flow health probe even when every candle scan returns WAIT. It ranks eligible USDT-quoted Spot pairs by Binance `/api/v3/ticker/24hr` quote volume, selects one feed-health sentinel, starts the bounded read-only stream manager and waits up to eight seconds for both aggTrade continuity and a sequence-validated depth book. It does not force a signal or change strategy thresholds. The probe is only a live feed-health sample, not a full-universe Order Flow scan.

Use `--skip-order-flow-probe` to omit that independent check, or `--order-flow-probe-wait-seconds 15` to allow a longer bootstrap window (1–30 seconds). A failed/not-ready probe is counted as a provider/quality failure so the command cannot report a completely green run when the required Spot live Order Flow feed was not verified.

Run both dynamic samples locally with:

```powershell
python .\\smoke_signal_engine.py --universe-sample-size 20 --usdm-universe-sample-size 20
```

Use `--skip-usdm` to omit the Futures sample, or pass `--symbols BTCUSDT,ETHUSDT` to constrain only the candle Spot sample. The independent Order Flow sentinel is still chosen from the full current eligible USDT Spot universe unless `--skip-order-flow-probe` is supplied. Coinbase fallback remains limited to BTC/ETH/SOL. This cloud check does not test the local MT5 terminal or Gold feed.

The scheduled run on 2026-11-16 failed before scanning because the GitHub runner could not retrieve Binance Spot `exchangeInfo` metadata from the single configured REST host. The shared public REST host failover was merged separately; successful provider smoke runs must still be checked independently from replay/strategy performance. A live WAIT is not proof of strategy quality, and a successful data scan is not proof of profitability.


### Latest verified public scan and current provider limitation (2026-11-22)

- Scheduled main run [#45000648674](https://github.com/adeeshadasuniduwara/QUANTNEX/actions/runs/45000648674) discovered 1,376 eligible Spot pairs and scanned 20 rotating pairs: 20 WAIT, zero provider errors and zero insufficient-history skips. No directional candidate passed, so Order Flow correctly reported `NOT_EVALUATED_NO_DIRECTIONAL_SETUP`. This is not a signal-quality or profitability result.
- The USDⓈ-M PR smoke attempt [#45002095522](https://github.com/adeeshadasuniduwara/QUANTNEX/actions/runs/45002095522) received HTTP 451 from Binance `/fapi/v1/exchangeInfo` on the GitHub-hosted runner. Keep the failure visible. Do not report Futures scan success until a live request succeeds from an allowed network. The Futures monitor remains a separate candle-only path; COIN-M and Futures Order Flow are unsupported.
- The smoke runner now continues the independent USDⓈ-M sample when Spot metadata discovery fails, but still exits non-zero if either provider fails. A successful Spot leg must not conceal a failed Futures leg.


## Export retained local Spot raw events for research

The live app's Spot stream manager stores public aggTrade, depth snapshot/diff and explicit capture-gap events in the local database. To provide a bounded archive for the causal replay/ablation tool, run this from the `backend` folder while using the same `.env` / `DATABASE_URL` as QUANTNEX:

```powershell
python .\\export_spot_order_flow_archive.py --symbol BTCUSDT --start 2026-11-26T00:00:00Z --end 2026-11-27T00:00:00Z --output .\\exports\\BTCUSDT-orderflow.json
```

- Replace the example symbol and UTC window with a period that exists in the local database. Raw events are retained for a bounded period; the default raw-event retention is seven days.
- The exporter reads the existing database only. It does not connect to Binance, create tables, change settings, send Telegram messages or place orders.
- The export is capped at 5,000 events, matching the replay limit. If the query is truncated, empty, malformed or over the cap, the export fails without writing a partial archive; narrow the time window and retry.
- The JSON manifest reports event counts, stream sessions and explicit `captureGap` markers. `coverage_is_complete` is always false: a bounded local capture is not proof of complete exchange-event or full UTC-session coverage.
- The exporter refuses to overwrite an existing destination. Use a new filename for each export.
- The archive contains public Binance Spot market events only. It does not include API keys, account data, candles, execution quotes, fee tier or fills. Candles and execution costs must still be aligned separately for walk-forward research.
