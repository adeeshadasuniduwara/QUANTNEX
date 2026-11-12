# QUANTNEX Architecture

## Repository layout

- `apps/web`: responsive browser client.
- `apps/android`: native Android client (Kotlin + Jetpack Compose).
- `apps/windows`: reserved for the Windows desktop client.
- `core/`: future shared domain logic and risk rules.
- `backend/`: future authenticated API and service orchestration.
- `shared/`: API contracts and platform-independent documentation.
- `docs/`: project plans, threat model and operating guides.

## Runtime model

Clients should remain lightweight. Market data processing, AI inference and bot orchestration belong in a separately deployed backend or an explicitly configured local engine, not in every mobile client.

The Android app must not run a permanent heavy trading process. Use short-lived network requests and scheduled background work only when required. Push notifications should be delivered through a push provider rather than a continuously running socket.

## Safety boundaries

- UI clients are not trusted execution environments.
- Broker credentials must never be embedded in APKs or web bundles.
- The backend must authenticate users and authorize every action.
- Read-only market data access is the default.
- Trading execution requires a separate explicit opt-in, risk limits and audit logs.
- Software updates must be staged, verified and recoverable.
- A client update must not be treated as proof that a broker-side position is safe; open positions remain at the broker and require independent monitoring.

## Update design

Windows and Android have separate update mechanisms. Android can notify about a mandatory update and open the system package installer, but the user must confirm installation unless the device is managed under an appropriate enterprise device-owner policy. Preserve app data and verify the installed version after restart.
