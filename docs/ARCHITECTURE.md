# QUANTNEX Architecture

## Repository layout

- apps/web: browser client.
- apps/android: native Android client (Kotlin + Jetpack Compose).
- apps/windows: Windows desktop client.
- backend: Phase 04 FastAPI service, authentication, journal and preferences API.
- core: future shared domain logic and risk rules.
- shared: future versioned API contracts.
- docs: plans, threat model and operating guides.

## Runtime model

Windows, Android and Web clients are intended to call the same HTTPS API. The backend owns identity, authorization, synchronized journal data and user preferences. SQLite is for local development; PostgreSQL is intended for multi-user deployment. AI provider credentials stay on the server and are never shipped to client applications.

## Security boundaries

- UI clients are untrusted; authorize every user-owned record on the server.
- Passwords are hashed with Argon2; API sessions use expiring JWT bearer tokens.
- Never embed API keys, broker credentials or signing keys in APKs or web bundles.
- Configure exact CORS origins and HTTPS in deployed environments.
- Read-only market data access is the default.
- Trading execution requires a separate explicit opt-in, risk limits and audit logs.
- Software updates must be staged, verified and recoverable.

## Current limitations

Phase 04 establishes the backend API foundation, but the existing Windows, Android and Web clients are not yet integrated with it. No live market feeds, broker connections, bot execution or order placement are implemented. Before public deployment, add migrations, rate limiting, audit logs, monitoring, backups, HTTPS and security testing.
