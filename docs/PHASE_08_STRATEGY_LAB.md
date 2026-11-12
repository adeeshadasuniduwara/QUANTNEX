# QUANTNEX Phase 08 — AI Strategy Laboratory

## Product boundary
Phase 08 is a local-only research workspace layered on Phase 07. It adds an isolated strategy_lab_runs table. It does not alter existing Wallet, Journal, preferences, Telegram configuration, paper-trade rows or local workspace identity. It adds no login flow and no broker order integration.

## Features
- Strategy Builder: configurable EMA crossover template (fast EMA, slow EMA and risk/reward). This is a deterministic rule template, not a generative AI model.
- Backtesting: fetches provider candles and evaluates crossover entries with ATR-like recent-range stop distance, configured reward target, conservative same-candle stop-first handling, trade list, win rate, profit factor and max drawdown.
- Market Replay: retrieves historical provider candles and lets the user step through the candle sequence.
- Strategy Optimizer: tests a documented 27-combination grid of EMA periods and reward multiples, ranks historical results and warns about in-sample overfitting.
- AI Learning & Research: presents stored backtests, optimizer runs, forward observations and closed paper-trade statistics. No automatic model training or self-modifying strategy is claimed.
- Forward Testing: records a fresh provider candle observation against the selected EMA rule. It does not create a paper position or broker order. Repeated user-triggered observations provide a simple forward observation log.

## API
- GET /api/v1/strategy-lab/replay?symbol=BTCUSDT&timeframe=15m
- POST /api/v1/strategy-lab/backtest
- POST /api/v1/strategy-lab/optimize
- POST /api/v1/strategy-lab/forward/evaluate
- GET /api/v1/strategy-lab/research

All routes use the existing local workspace dependency and local database. Market data comes from Phase 07 provider adapters. Unsupported or unavailable data is returned as an error, never replaced with fabricated candles.

## Simulation limitations
The current strategy template is EMA crossover only. The simulation does not model bid/ask spread, commissions, slippage, swaps/funding, broker contract multipliers, margin, latency or partial fills. Position size is one abstract unit. Historical candles are in-sample; optimizer results are especially vulnerable to overfitting. Forward evaluation is observation-only and not a validated automated paper-execution strategy. Use unseen data and manual paper observation before relying on any strategy. No win rate or future profit is guaranteed.

## Local-only safety
The existing API remains loopback-only. No cloud account, user login, broker credentials, live order endpoint or real-money execution is introduced. Existing user data is preserved; the new strategy history is additive.
