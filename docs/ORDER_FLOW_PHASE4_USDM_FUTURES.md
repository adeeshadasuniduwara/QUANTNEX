# QUANTNEX Order Flow — Phase 4: Binance USDⓈ-M Futures

## Implemented in this PR

- Separate `BINANCE_USDM_FUTURES` event namespace and strict aggTrade / diff-depth normalizers.
- Dedicated USDⓈ-M REST depth snapshot bootstrap and Futures WebSocket combined stream.
- Snapshot bridge validation and strict `pu` continuity after the bridge.
- In-memory top-of-book updates; stale or invalid sequence state is never marked ready.
- Bounded per-symbol capture manager (five default perpetual pairs), reconnect backoff and event queue limits.
- Separate Futures raw-event persistence using the shared append-only event table but a distinct market-type partition and uniqueness namespace.
- Seven-day retention and idempotent archive reads.
- Read-only Futures status, live book and archived footprint endpoints.
- Advanced Footprint UI market selector now routes Futures to its own Futures archive; Spot and Futures volumes are never combined.
- Deterministic tests for snapshot bridging, old-event discard, pu gaps, queue overflow, event namespace isolation and recorder validation.

## Operational behaviour

- The local backend starts a bounded Futures capture set alongside the existing Spot stream managers.
- A Futures book is ready only after a REST snapshot bridge and a continuous `pu` chain; reconnect always resets the book and requires a new snapshot.
- Raw trades may be archived while the depth book is still bootstrapping, but the live depth is not published as valid until bridged.
- Queue overflow and sequence gaps invalidate the live book and force reconnect/resnapshot.
- Capture coverage is observed-only and is never described as complete.
- No API keys, signed endpoints, order placement, leverage changes or execution paths are used.

## Phase 5 hand-off

- Phase 5 has started in `docs/ORDER_FLOW_PHASE5_USDM_DERIVATIVES.md` with read-only funding, mark/index basis and bounded open-interest APIs.
- Remaining Phase 5 work includes mark-price and force-order WebSocket capture, liquidation context, persistent derivatives snapshots, Futures replay and UI panels.

## Integrity limits

- Spot and Futures event IDs, books, archives and footprint calculations remain separate.
- Aggregated public data cannot identify a participant or prove iceberg replenishment/spoofing intent.
- Absorption, repeated executions and liquidity pulls remain low-confidence observed context, not guaranteed trade signals.
- No live exchange end-to-end or Render deployment is claimed until verified in the running environment.
