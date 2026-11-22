# QUANTNEX Order Flow — Phase 4: Binance USDⓈ-M Futures

## Scope

Phase 4 adds a separate, exchange-native Binance USDⓈ-M Futures Order Flow pipeline. It must remain isolated from Binance Spot data and must not reuse Spot sequence state, event identity, depth snapshots, or trade statistics.

## Foundation added in this branch

- Strict normalizer for USDⓈ-M aggregate trades (aggTrade).
- Strict normalizer for USDⓈ-M diff-depth events, including the Futures pu previous-update link.
- Snapshot bridge and sequential pu continuity validator.
- Separate BINANCE_USDM_FUTURES market namespace.
- Unit tests for maker-side semantics, malformed events, snapshot bridging, and sequence-gap fail-closed behaviour.

## Remaining Phase 4 implementation

1. Dedicated USDⓈ-M REST depth snapshot bootstrap and WebSocket diff-depth manager.
2. Bounded queue, overflow gap markers, reconnect/backoff, and resnapshot on any sequence break.
3. Dedicated Futures raw-event persistence and retention, separate from Spot.
4. Futures-specific read-only APIs for depth, trade flow, footprint, and capture health.
5. UI market selector wiring so Futures footprint is only shown when its own Futures archive is healthy.
6. Funding rate, open interest, mark/index price, and liquidation stream adapters with separate provenance.
7. Futures-only replay and test fixtures.

## Integrity requirements

- Use the USDⓈ-M public endpoints and event schemas, not Spot endpoints.
- Never merge Spot and Futures volumes or depth ladders.
- Require snapshot bridge plus pu continuity before publishing a valid book.
- Any missing sequence, queue overflow, stale feed, or malformed event invalidates the book until a fresh snapshot is bridged.
- Public aggregated data cannot identify individual participants or prove spoofing/iceberg intent.
- No order execution is included in this phase.

## Current status

The validation/normalization foundation is implemented in backend/app/binance_usdm_order_flow.py. The live capture manager, persistence, API, and UI remain pending. No Futures live feed is claimed by this foundation alone.
