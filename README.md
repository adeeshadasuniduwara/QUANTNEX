# QUANTNEX

**AI-powered trading workspace for Windows, Android and Web.**

QUANTNEX is a modular, multi-platform trading software project. The repository keeps the platform clients and shared product documentation together while allowing each platform to ship its own release asset.

> **Development status:** Phase 03 – Windows desktop MVP and automated Windows build pipeline. This is not a live trading system. No broker orders are sent and no real account is connected.

## Platforms

| Platform | Project path | Distribution |
|---|---|---|
| Web | `apps/web/` | Web hosting / ZIP |
| Android | `apps/android/` | Signed APK via GitHub Releases |
| Windows | `apps/windows/` | Windows ZIP / installer |
| Shared contracts | `shared/` | Used by platform clients |

## Phase 01

- Establish the monorepo structure.
- Add the first responsive web dashboard prototype.
- Add the Android Jetpack Compose starter application.
- Define shared API and security boundaries.
- Keep live trading, broker credentials and automated execution disabled until separately implemented and tested.

See [Phase 01 plan](docs/PHASE-01.md) and [architecture](docs/ARCHITECTURE.md).

## Phase 03 — Windows desktop MVP

A lightweight Windows desktop app is in `apps/windows/quantnex_desktop.py`. It includes the position-size calculator, local SQLite trade journal and a GitHub Releases update check. A Windows GitHub Actions workflow builds `QUANTNEX.exe` as a downloadable workflow artifact when relevant files change. The executable is not available until that workflow succeeds.

## Run the web prototype

Open `apps/web/index.html` in a modern browser. It is a static prototype and does not require an API key or backend.

## Open the Android project

Open the `apps/android` folder in Android Studio with a compatible Android Gradle Plugin / Kotlin toolchain. Build a debug APK from Android Studio. A distributable release APK must be signed with a private release key; never commit that key or its passwords to this repository.

## Release strategy

A GitHub Release can contain separate assets for each platform, for example:

- `QUANTNEX-Windows-vX.Y.Z.zip`
- `QUANTNEX-Android-vX.Y.Z.apk`
- `QUANTNEX-Web-vX.Y.Z.zip`
- `SHA256SUMS.txt`

Each client checks its own platform-compatible release asset. Android mandatory updates must still use Android's package installer and obtain the user's confirmation; an ordinary APK cannot silently install itself.

## Security principles

- Never commit API keys, passwords, signing keys, broker tokens or personal account data.
- Use least-privilege API keys; do not enable withdrawal permissions.
- Keep broker execution disabled by default.
- Validate updates, verify hashes/signatures, back up local data and provide rollback paths.
- Treat all sample balances, prices and performance figures as mock data.

## License

No license has been selected yet. Until a license is added, standard copyright applies and reuse is not automatically permitted.
