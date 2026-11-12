# Phase 17 — Real-time Workspace Architecture

## Goal

Make QUANTNEX event-driven and responsive to genuine provider events. "Live" means rendering source events as they arrive, not animating values or polling at an artificially high frequency.

## Current implementation in this phase

- BTCUSDT, ETHUSDT and SOLUSDT consume Binance Spot WebSocket trade events (@trade) and 24-hour ticker events (@ticker).
- BTC trade events now update the Overview BTC price directly, instead of waiting for the Overview REST refresh.
- The browser emits quantnex:market-tick and quantnex:stream-status events so independent workspace widgets can subscribe without opening duplicate market sockets.
- Binance Spot depth uses the provider's @depth20@100ms partial-depth stream for the selected order-book symbol.
- Overview REST remains a slow fallback for Gold and USD/LKR reference values; it is not tick-by-tick data.
- Local CPU/RAM telemetry is sampled once per second from the local API. This is not market tick data.
- Existing paper/performance/news REST refresh intervals remain conservative until server-side change events are implemented.

## Provider limits and semantics

### Binance Spot

The public WebSocket API documents real-time trade streams, 100 ms or 1 s depth updates, and ticker streams. A WebSocket connection is limited to 24 hours and clients must reconnect. The application must show connection state and source timestamps. Partial depth is not a complete reconstructed order book and does not show executed-volume footprint.

### Twelve Data

Twelve Data supports a server-push WebSocket for subscribed symbols, but availability, simultaneous symbols, and access depend on the user's plan. The API key must remain on the local backend and must never be embedded in browser JavaScript. Forex/Gold should be marked streaming only after a successful authenticated provider subscription; otherwise the UI must clearly report REST/last-update mode.

### News, wallet, journal and paper trading

- Economic calendars change when providers publish or revise events; they are not millisecond market feeds.
- Wallet, journal and paper-trade changes should be pushed immediately after successful local API writes, then broadcast to connected local clients.
- Strategy scans and backtests are compute jobs, not continuous streams; show running/completed state and timestamps rather than pretending they update every tick.

## Target architecture

1. One local-only WebSocket event gateway bound exclusively to loopback.
2. Provider adapters: Binance public streams and optional Twelve Data authenticated stream.
3. A typed event envelope with type, symbol, provider, provider_time, received_time, sequence, and payload.
4. A browser event bus with one connection manager, automatic reconnect/backoff, heartbeat, stale-feed detection, and visibility-aware pause/resume.
5. UI widgets subscribe to the event bus; no widget creates its own duplicate provider connection.
6. Local mutations publish events after database commit. No cloud relay, login, or public listener.
7. Backpressure: coalesce high-frequency UI paints with requestAnimationFrame; never discard the underlying event for audit or order-book sequencing.
8. Data-quality gate: reject invalid/out-of-order events, detect sequence gaps, mark feeds stale, and require a fresh snapshot before rebuilding a local order book.

## Acceptance tests still required

- Simulated event-stream tests for connect, disconnect, reconnect, stale feed, duplicate/out-of-order event, and sequence gap.
- Browser tests proving trade events update Overview and Market Intelligence without a REST poll.
- Order-book snapshot + diff sequence reconciliation tests before claiming a complete local book.
- Twelve Data subscription tests with a real eligible API key, verifying that the key is not exposed to the browser.
- Local Windows .bat startup and shutdown tests, including no orphaned WebSocket tasks and loopback-only binding.
- End-to-end verification on the user's computer.

## Explicit non-goals

- No synthetic ticks or fake millisecond animation.
- No promise that network/provider data arrives every millisecond.
- No live broker orders, account execution, or public internet exposure.
- No claim that every dashboard card is fully event-driven until the acceptance tests above pass.
