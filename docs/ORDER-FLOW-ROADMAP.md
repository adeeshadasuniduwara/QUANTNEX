# QUANTNEX Advanced Order-Flow Roadmap

## Current verified boundary

The current signal engine supports Binance Spot symbol discovery, fresh best-bid/ask and REST depth snapshots, adaptive MARKET/LIMIT entry selection, and candle-based multi-timeframe confluence. Historical walk-forward replay is Binance Spot only. It does not contain historical L2 order-book history or trade-side footprint replay. A Spot SELL signal is not a Futures short.

This roadmap adds order-flow as measured evidence, not a promise of higher win rate. Calculations must be causal, time-stamped, source-attributed and fail closed when data is malformed or stale.

## Phase A — deterministic order-flow analytics (this PR)

Implemented in backend/app/order_flow.py:

- Binance Spot aggregate-trade aggressor-side inference using buyer-is-maker semantics (m=False aggressive buyer; m=True aggressive seller).
- De-duplication by aggregate-trade ID, chronological ordering, future-time rejection and configurable latest-trade freshness.
- Base-volume delta, signed quote-volume delta, window cumulative delta and UTC-session delta.
- Price-bucket footprint summaries and configurable buy/sell imbalance ratio.
- Validated L2 snapshot metrics: best bid/ask, spread bps, top-level depth imbalance, microprice and displacement.
- Explicit provenance: aggressor-side inferred delta is not consolidated quoted bid/ask volume; OHLCV candle volume is never used as a substitute.

Deterministic unit tests cover side mapping, duplicate IDs, chronological order, stale/future events, delta/session calculations, footprint buckets, order-book metrics and malformed candle-only input.

## Phase B — live Binance public-feed collector

Next:
- Fetch recent Spot aggregate trades and L2 snapshots using public read-only endpoints.
- Preserve exchange event timestamps and snapshot update IDs; validate snapshot age.
- Add bounded async caching, request throttling, retry/backoff and symbol-aware polling so all eligible symbols do not overwhelm API weight limits.
- For continuous depth, use the documented snapshot + diff stream sequence procedure; invalidate and resync on any update-ID gap. Independent REST snapshots are not continuous order-book history.
- Do not claim historical CVD/footprint beyond actual retained trades/backfill.

## Phase C — entry engine integration

- Add order-flow confluence as a separately visible score component with positive and negative evidence.
- Hard-veto stale trade data, invalid/crossed book, wide spread, inadequate liquidity and feed gaps.
- Explain delta/CVD divergence, footprint imbalance, depth imbalance and microprice evidence in each eligible signal.
- Keep MARKET/LIMIT selection grounded in current execution data; order-flow score cannot override execution or risk vetoes.
- Return WAIT when critical order-flow data is unavailable until a degraded-mode policy is tested.

## Phase D — derivatives and advanced methods

Only after Spot order-flow is stable:
- Verify USDⓈ-M and COIN-M metadata, trades, depth, funding, open interest and liquidation-feed availability independently.
- Build separate market-type adapters and tests; never mix Spot and Futures semantics.
- Add absorption/exhaustion proxies only when trade flow and depth updates are synchronized; label them as proxies.
- Add volume profile, VWAP/anchored VWAP, session profiles, multi-timeframe structure, S/R, supply/demand, OB/FVG/breaker/mitigation, liquidity sweeps, Fibonacci and regime/momentum/mean-reversion/breakout methods through a registry. Each method needs precise causal rules, fixtures and ablation evidence before production scoring.

## Validation and safety

- Deterministic fixtures must prove correct calculations and qualifying long/short replay setups.
- Replay must include realistic fees, spread, slippage, latency, partial/unfilled LIMIT behavior and chronological out-of-sample splits.
- Compare baseline, each method and combinations using trade count, win rate, expectancy, profit factor, max drawdown and cost sensitivity. Higher win rate alone is not success.
- Never invent data, force live signals, place real orders or enable live-money execution. Public feeds remain read-only; paper mode only.
- Binance Spot is the only market type covered by this first implementation. Futures support and true historical footprint/order-book replay remain unverified.
