# QUANTNEX Advanced — Order Flow Roadmap

## Product boundary

QUANTNEX Advanced is the dedicated chart workspace for market microstructure and Order Flow research. QUANTNEX VIEW remains the general chart and signal workspace. The two chart instances use separate DOM IDs, chart-selection persistence, drawings persistence, and browser callbacks.

## Phase 1 — Workspace and chart foundation

Implemented in this change:
- Dedicated sidebar destination and workspace.
- Independent native candle chart using the existing Binance Spot / USDⓈ-M Futures chart market catalogue, historical candle loader, and live kline WebSocket.
- Existing QUANTNEX VIEW Order Flow toolkit moved into Advanced.
- Existing sequence-validated Binance Spot L2 depth and aggregate-trade flow are scoped to the Advanced workspace and follow its selected symbol/timeframe.
- Unsupported venue/market combinations remain explicitly unavailable; no synthetic order book, bid/ask volume, or trade delta is fabricated.
- No order execution or account permissions are introduced.

## Phase 2 — Candle-aligned market-data recorder

Implemented in this change:
- Append-only archive for Binance Spot raw aggregate trades, sequence-validated diff-depth updates, and REST depth bootstrap snapshots.
- Preserve exchange event time, local receive time, UTC 1-minute bucket, event IDs / depth sequence ranges, source type, and stream-session ID.
- Idempotent event keys prevent duplicate aggregate-trade IDs and depth update IDs from being stored twice.
- Bounded asynchronous writes, bounded event queues, explicit backpressure errors, and seven-day retention.
- Read-only API endpoints expose raw events and per-minute event counts for later replay/analytics.
- Archive health is visible in the Advanced workspace and capture-status endpoint.
- Event buckets are explicitly labelled observed/partial or recovered-with-backfill; they are never advertised as complete candles. A sequence-valid event archive alone cannot prove full candle coverage.

Not included yet:
- Persisted bid/ask footprint per price level and candle analytics.
- A strict complete-candle certification pipeline across every subscription and reconnect window.
- Futures, Gold, or Forex raw feeds; current raw event archive is Binance Spot only.

## Phase 3 — Footprint and volume analytics

- Bid/ask footprint by price level and candle.
- Delta per price level, stacked imbalance, volume clusters, POC, VAH/VAL, and session profiles.
- Candle delta, cumulative delta (CVD), and divergence views.
- Show coverage and data provenance on every panel.

## Phase 4 — Absorption and exhaustion

- Buy/sell absorption candidates using aggressor pressure, limited price progress, and replenishment/holding evidence.
- Buy/sell exhaustion candidates using declining participation relative to a measured baseline and failure to continue.
- Require multiple independent observations; distinguish candidate, confirmed, and invalidated states.
- No single candle wick or volume spike is sufficient evidence by itself.

## Phase 5 — Liquidity behaviour

- Iceberg/replenishment candidates.
- Liquidity pull / spoofing-like behaviour candidates with sequence and persistence checks.
- Resting liquidity migration and depth imbalance history.
- Clearly label inference and uncertainty; never claim intent from public order-book data alone.

## Phase 6 — Multi-market data adapters

- Independent Binance USDⓈ-M Futures depth and trade streams.
- Gold and Forex only through configured, venue-specific broker/provider feeds.
- Normalize timestamps, contract units, tick sizes, and aggressor-side provenance without mixing incompatible venues.

## Phase 7 — Order Flow confirmation and signal integration

- Configurable confluence gates and multi-timeframe confirmation.
- Walk-forward evaluation against chronological, out-of-sample outcomes.
- Measure false positives, coverage, latency, and realized execution costs.
- Keep Order Flow score separate from measured win probability.

## Data integrity rules

- Exchange timestamps and sequence IDs are retained wherever available.
- Candle windows use UTC boundaries and explicit closed/incomplete state.
- No candle-volume-only bid/ask split is allowed.
- Missing history, feed gaps, and unavailable venue feeds remain visible.
- Research outputs are read-only until separately reviewed execution controls are designed and approved.
