# QUANTNEX

**AI-powered trading workspace for Windows, Android and Web.**

QUANTNEX is a modular multi-platform project with platform clients and a shared backend foundation.

> **Development status:** Phase 04 backend foundation and Phase 03 Windows desktop MVP. This is not a live trading system. No broker orders are sent and no real account is connected.

## Platforms

| Platform | Path | Distribution |
|---|---|---|
| Web | apps/web/ | Web hosting / ZIP |
| Android | apps/android/ | Signed APK via GitHub Releases |
| Windows | apps/windows/ | Windows executable artifact |
| Backend | backend/ | FastAPI service |

## Phase 04 — Backend foundation

The backend includes Argon2/JWT authentication, user-isolated journal and preferences APIs, optional server-side AI chat, SQLite local development and PostgreSQL driver support. Existing clients are not connected yet.

See [Phase 04 guide](docs/PHASE-04.md) and [backend setup](backend/README.md).

## Windows desktop

The Windows MVP includes a position-size calculator, local SQLite journal and GitHub Releases update check. A GitHub Actions workflow builds a downloadable EXE artifact when Windows source changes.

## Security

Never commit API keys, passwords, signing keys, broker tokens or personal account data. Public deployment requires HTTPS, strong secrets, backups, monitoring and security testing. Broker execution remains disabled.
