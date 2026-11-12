# Phase 01 – Foundation

## Goal

Create a safe, lightweight starting point for QUANTNEX across Web, Android and Windows. Phase 01 establishes the repository layout and first UI prototypes; it does not connect to brokers or place trades.

## Deliverables

- [x] Monorepo structure and project overview
- [x] Responsive static web dashboard prototype
- [x] Native Android Jetpack Compose starter screen
- [x] Shared API/security contract
- [ ] Windows desktop shell
- [ ] Automated build and test workflows
- [ ] First signed Android APK release

## Acceptance checks

1. Web dashboard opens without credentials and adapts to mobile and desktop widths.
2. Android project opens in Android Studio and builds a debug APK with a compatible toolchain.
3. All figures are marked as sample/demo data.
4. No API keys, broker credentials or signing keys are stored in source control.
5. No live order, trade execution or withdrawal capability is present.

## Next phases

- Phase 02: calculators and local preferences.
- Phase 03: backend API and authenticated client connections.
- Phase 04: Telegram notifications and bot monitoring.
- Phase 05: market data and AI features.
- Phase 06: signed platform releases and update clients.
