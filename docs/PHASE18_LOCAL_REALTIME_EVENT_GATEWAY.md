# QUANTNEX Phase 18 — Local Real-Time Event Gateway

## Goal

Deliver committed workspace changes to every open QUANTNEX browser tab immediately, without polling loops, a cloud relay, user accounts, or public network exposure.

## Architecture

- FastAPI exposes `ws://127.0.0.1:8000/api/v1/events/stream`.
- The endpoint accepts only configured local browser origins and loopback clients/hosts. The test harness uses a dedicated test-only origin/client pair.
- A process-local `EventHub` fans out versioned JSON envelopes with monotonically increasing event IDs.
- Each connection has a bounded 128-event queue; the server limits the stream to eight local clients.
- Slow consumers receive `stream.resync_required` after queue overflow instead of silently trusting stale state.
- A 20-second heartbeat detects dead connections. The browser reconnects with capped exponential backoff.
- The stream does not persist or replay events. On reconnect or sequence gaps, clients reload authoritative REST snapshots.
- API handlers publish only after the database commit succeeds. Event payloads contain only the small fields needed to identify a changed record; secret values, notes and credentials are never broadcast.

## Published events

| Event | Trigger | Workspace response |
|---|---|---|
| `journal.changed` | Journal create/delete | Trade History reloads |
| `wallet.changed` | Wallet transaction or journal P&L | Wallet summary/ledger reloads |
| `paper_trade.changed` | Paper open/close, including Risk Guardian open | Paper analytics, Trade History and Portfolio Monitor reload |
| `strategy.research.changed` | Backtest, optimizer or forward observation saved | Strategy Library reloads |
| `preferences.changed` | Local preferences, signal settings or Auto Signals | Integration status reloads |
| `integration.changed` | Telegram connect/disconnect | Integration status reloads |
| `signals.changed` | Signal scan completed | Event available to other workspace modules |

## Browser behavior

The shared `realtime-events.js` client is loaded once by the workspace shell. It emits `quantnex:workspace-event`, `quantnex:workspace-resync` and `quantnex:stream-status` browser events. Existing market WebSockets remain separate provider feeds; this event gateway is for local workspace mutations, not a substitute for market ticks.

## Safety and limitations

- Local-only / no-login architecture is preserved. No cloud account or remote event relay is introduced.
- Paper trading remains paper-only. No broker execution route is added.
- The gateway is process-local: if the API process restarts, clients reconnect and fetch fresh snapshots. It is not a durable event log or cross-process message broker.
- This increment does not make Gold/Forex market quotes tick-by-tick. Their freshness remains dependent on the configured provider and subscription.
- Browser localStorage-only records from the older local journal are not synchronized through this server event bus; API-backed journal records are.

## Validation

Automated tests cover local-origin acceptance, rejected untrusted origins, event delivery, sequence IDs, payload limits and queue-overflow resynchronization. CI checks the JavaScript syntax and existing workspace navigation structure. Actual Windows launch/browser verification remains necessary before treating the feature as installed.
