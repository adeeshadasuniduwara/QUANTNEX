# QUANTNEX Architecture

## Product scope

QUANTNEX has two user-facing products:
- `apps/web`: responsive browser workspace and loopback Web server.
- `apps/android`: native Android shell with navigation, workspace settings and verified APK release updates.

The local Backend is a supporting service for the Web workspace. Windows is supported as a host operating system for the local launcher and Backend; there is no Windows desktop app, executable or installer.

## Repository layout

- `apps/web`: browser client, local Web server and Web update interface.
- `apps/android`: native Android application.
- `backend`: loopback-only FastAPI service for one local workspace.
- `services`: optional shared services such as the economic-news Worker.
- `shared`: versioned contracts and reusable service code.
- `docs`: architecture, threat model and operating guides.
- `tests`: source updater, launcher and integration regression tests.

## Runtime model

On a Windows host, `run_quantnex.bat` starts `run_quantnex_services.py`. The supervisor prepares the Backend virtual environment, runs the startup preflight, starts FastAPI on `127.0.0.1:8000` and starts the Web server on `127.0.0.1:5500`. It waits for both health endpoints before opening the browser. Keep the Command Prompt supervisor running behind the browser; Ctrl+C stops its child processes. The launcher writes a persistent diagnostic log to `logs/launcher.log` and remains open after startup failures.

The Backend and Web workspace are local-first. There is no login, registration, password, JWT or remote account system. The Backend keeps one internal local workspace identity so journal, wallet, preferences and Telegram configuration can share a consistent database owner. On first startup, the SQLite database is backed up under `data/backups`, legacy account data is consolidated into the local workspace and old password hashes are cleared.

The Android app loads a separately hosted HTTPS Web workspace reachable from the phone. A computer's `127.0.0.1` address is not reachable from Android. The Android app does not tunnel or expose the loopback Backend and does not automatically synchronize browser-local data with the computer.

## Security boundaries

- The Backend and local Web server bind to loopback only; do not expose their ports to a LAN or the public internet.
- FastAPI validates Host values and restricts CORS to the local QUANTNEX Web origin.
- Local API access relies on the host operating-system account and device security; any process running as that local user can access the local API.
- Telegram bot tokens are encrypted at rest using a persistent key stored in the local Backend environment.
- Never embed API keys, broker credentials or signing keys in APKs or Web bundles.
- Read-only market data access is the default.
- Trading execution requires a separate explicit opt-in, risk limits and audit logs.
- Web source updates are downloaded from a GitHub commit pinned by its SHA, staged, backed up and rolled back on copy or startup failure.
- Android release updates require the official GitHub Release, a stable app-signing key and a matching SHA256 checksum manifest. Android still asks the user to approve installation.

## Update model

The local source supervisor updates the Web and Backend source tree from the official `main` branch every five minutes while running. It validates the pinned archive, preserves user data and local secrets, backs up changed source files, and performs rollback if the updated services fail their startup health checks.

Android APKs are released separately through GitHub Releases. The Android app checks for a newer release, verifies the APK digest against `SHA256SUMS.txt`, and launches Android's package installer. The same private signing keystore must be used for every production APK so upgrades remain compatible.

## Current limitations

The Android shell requires an HTTPS-hosted Web workspace and does not connect to the local-only Backend. Browser journal data remains in that browser profile. No broker order placement or verified win-rate calculation is implemented. Before any future remote Backend deployment, add a proper identity and authorization model, HTTPS, managed secrets, migrations, rate limiting, audit logs, monitoring, backups and security testing.
