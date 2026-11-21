# QUANTNEX USDⓈ-M Futures Signal Engine

## Scope
- Independent Binance USDⓈ-M perpetual signal generation for active TRADING PERPETUAL contracts only.
- Uses fully closed, chronological, fresh Futures OHLCV candles from /fapi/v1/klines.
- Reuses the transparent QUANTNEX VIEW confluence catalogue; score is a rule-match ranking, not a probability or verified win rate.
- Signal symbols are namespaced with .P in the lifecycle ledger so Futures outcomes do not collide with Spot symbols.
- The lifecycle worker reconciles .P signals against Binance USDⓈ-M 1-minute candles, independently of Spot candle history.

## Explicit exclusions
- No COIN-M contracts, funding/OI/liquidation analysis, or Futures Order Flow integration in this release.
- No leverage selection, account access, API-key requirement, order placement, or auto-trading. Futures signals are monitor-only.
- A candle-confluence signal is not proof of profitability. Validate with paper observation and market-specific replay before considering any execution feature.
