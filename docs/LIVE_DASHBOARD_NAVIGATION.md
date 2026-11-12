# QUANTNEX Live Dashboard & Navigation Fix

## Navigation
The fixed left navigation is independently scrollable with a visible narrow scrollbar, touch/trackpad support and non-shrinking menu items. Scrolling the sidebar does not need to move the main page.

## Live system telemetry
- Local loopback endpoint: GET /api/v1/system/metrics.
- Reads real host CPU utilization, physical RAM use and disk capacity using psutil/shutil.
- Dashboard samples CPU/RAM every second while the page is visible.
- This is host-wide Windows/Linux system telemetry, not a fabricated animation or a browser-only estimate.

## Live market data
- BTCUSDT, ETHUSDT and SOLUSDT 24-hour ticker cards receive Binance public WebSocket ticker updates.
- Crypto order-book panel subscribes to Binance Spot partial-depth stream at up to 100 ms update cadence for the selected symbol. It displays the top visible bid/ask levels as a liquidity heatmap plus the existing depth table and quantity imbalance.
- The live depth feed reconnects after disconnect and pauses while the page is hidden.
- Gold/Forex quotes use the existing configured Twelve Data REST provider and refresh on a 60-second cadence to respect provider quotas. Actual freshness depends on the provider plan and source timestamp.
- Market data is never synthesized. A disconnected stream or unavailable provider is shown as unavailable; order-book depth is not executed volume and is not a guarantee of fillable liquidity.

## Background refresh
- Paper ledger summary and open positions: 10 seconds.
- Paper performance summary: 30 seconds.
- Advanced Performance Lab: 30 seconds.
- Market Data Reliability scan remains at 5 minutes to avoid excessive historical candle requests.
- Economic calendar: 15 minutes.
- Manual refresh buttons remain available.

## Scope and safety
- Local-only architecture is preserved; telemetry is loopback-only.
- No login, cloud relay, new credential or broker connection is added.
- Paper trading remains simulated. No live order execution is introduced.
- Browser WebSocket connections are outbound public market-data subscriptions only.
