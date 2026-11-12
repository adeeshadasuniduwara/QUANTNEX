# Phase 19 — Live Market Terminal

## Scope
This phase improves the local QUANTNEX web workspace without changing the local-only, login-free architecture or enabling broker execution.

## BTC and XAUUSD charts and live result estimate
- Retain the TradingView chart selector for XAUUSD and BTCUSDT.
- Publish incoming BTC Binance trade events and periodic XAUUSD provider quotes through the shared `quantnex:market-tick` browser event.
- Add a gross unrealized P&L calculator for LONG/SHORT positions.
- BTC quantity is denominated in BTC; XAUUSD quantity is denominated in broker lots multiplied by an editable ounces-per-lot contract size (default 100 oz; users must confirm their broker's contract specification).
- The estimate is price movement multiplied by quantity. It excludes spread, commissions, swaps, funding and slippage.
- The TradingView embedded chart is a display widget; its candle stream is not read by the calculator. The calculator uses the explicit market events above.

## Binance order-book heatmap
- Keep the Binance Spot `@depth20@100ms` feed for supported crypto pairs.
- Render a bounded rolling 120-snapshot (approximately 12-second) bid/ask liquidity heatmap on a canvas.
- Limit heatmap redraws to the incoming stream cadence and refresh the tabular top levels no more than twice per second.
- Cap canvas device pixel ratio at 1.25 to reduce rendering cost on lower-memory laptops.
- Pause drawing/telemetry while the relevant view is off-screen or the browser tab is hidden.
- This is a top-20 partial-depth snapshot visualization, not a full exchange order book, executed-volume footprint, or guaranteed liquidity display. Gold/Forex depth is not fabricated.

## System health
- Use the existing loopback-only `/api/v1/system/metrics` endpoint for real host CPU, memory and disk samples.
- Refresh CPU/RAM once per second while the System Health panel is visible.
- Stop polling while the panel is off-screen or the browser tab is hidden.
- Database/backups/audit status remains separate from the lightweight telemetry endpoint.

## Bot connection and clean UI
- Add a direct Connect Telegram Bot action from Connections & Integrations to the existing encrypted local Telegram setup form.
- Keep token values out of the browser status response and out of visible UI text.
- Remove visible inline code snippets and developer configuration examples from the end-user page.
- Keep the workspace login-free, loopback-only and local-device hosted.

## Safety and limitations
- This phase does not place live broker orders, connect a broker, or modify external positions.
- Live quotes depend on provider availability, latency, plan entitlements and the local API remaining online.
- No user wallet, journal, paper-trading ledger or local workspace data is intentionally migrated or deleted.
