# QUANTNEX Architecture

## Repository layout

- apps/web: browser client and loopback updater.
- apps/android: native Android starter (not connected to the local API).
- apps/windows: Windows desktop client.
- backend: loopback-only FastAPI service for one local workspace.
- core: future shared domain logic and risk rules.
- shared: future versioned API contracts.
- docs: plans, threat model and operating guides.

## Runtime model

The Windows launcher starts the FastAPI backend on 127.0.0.1:8000 and the Web updater/server on 127.0.0.1:5500. The browser opens after both services pass health checks. Keep the single CMD supervisor running behind the browser; Ctrl+C stops its child processes.

QUANTNEX is currently a single-computer local application. It has no login, registration, password, JWT or remote account system. The backend keeps one internal local workspace identity so journal, wallet, preferences and Telegram configuration can share a consistent database owner. On first startup, legacy account data is consolidated into that local workspace and old password hashes are cleared.

## Security boundaries

- The backend and Web updater bind to loopback only; do not expose their ports to a LAN or the public internet.
- FastAPI validates Host values and restricts CORS to the local QUANTNEX Web origin.
- Local API access relies on the Windows account and device security; any process running as the local Windows user can access the local API.
- Telegram bot tokens are encrypted at rest using a persistent key stored in the local backend environment.
- Never embed API keys, broker credentials or signing keys in APKs or web bundles.
- Read-only market data access is the default.
- Trading execution requires a separate explicit opt-in, risk limits and audit logs.
- Web updates are downloaded from a GitHub commit pinned by its SHA, staged, backed up and rolled back on copy failure.

## Current limitations

The Web updater replaces Web workspace files only. Backend and Windows desktop source changes require installing a newer full source snapshot or using the Windows desktop update path. Browser journal data stays in that browser profile; Windows journal data stays in the local application data folder. No broker connections, order placement or verified win-rate calculations are implemented. Before any future remote/public deployment, reintroduce a proper identity and authorization model, then add HTTPS, managed secrets, migrations, rate limiting, audit logs, monitoring, backups and security testing.
