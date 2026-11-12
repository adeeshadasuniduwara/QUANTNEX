# QUANTNEX

**A modern trading workspace for Windows, Android and Web.**

QUANTNEX brings trading utilities, trade records and future secure integrations together in one evolving application. The project is actively being developed across desktop, mobile and web.

## Applications

- **Web:** responsive browser workspace with position sizing and a local trade journal.
- **Windows:** desktop workspace with position sizing, local SQLite journal and update checking.
- **Android:** native application starter.
- **Backend:** shared FastAPI foundation for accounts, journal sync, preferences and an optional AI gateway.

## Run on Windows

From the repository root, double-click `run_quantnex.bat` or run it from Command Prompt. Choose Desktop, Web, or both.

The Web workspace can also be opened directly from `apps/web/index.html`. For a local HTTP server, use the launcher menu.

## Windows executable

A Windows EXE can be built from the source using the included GitHub Actions workflow. Tagged releases are designed to publish the EXE and checksum to GitHub Releases. Downloaded updates require user confirmation before installation.

## Backend

See [backend setup](backend/README.md) and [architecture](docs/ARCHITECTURE.md). The API supports local SQLite development and PostgreSQL configuration. Existing app clients are not yet fully connected to cloud sync.

## Current capability and safety

The calculator uses broker-specific pip values entered by the user. The web journal stores data in that browser; the Windows journal stores data locally on that computer. Bot monitoring is currently a status panel only. Live market feeds, broker connections, Telegram control and automated order execution are not enabled. Never commit API keys, passwords, signing keys or broker tokens. Public deployment requires HTTPS, managed secrets, backups, monitoring and security testing.
