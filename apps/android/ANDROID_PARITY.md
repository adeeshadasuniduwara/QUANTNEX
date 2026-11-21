# QUANTNEX Android — Full Workspace Parity

## Product requirement

The Android APK must provide the QUANTNEX Web workspace's actual trading tools on-device. A navigation shell, placeholder cards, or a remote website displayed in a WebView does not satisfy this requirement. The APK is the product; users must not need a separately hosted website or a Windows PC for core Android workflows.

## Architecture rules

- Keep the existing login-free, local-first model. Do not add mandatory accounts or cloud sync.
- Package the Android UI and its required assets in the APK. Do not require a user-supplied HTTPS workspace URL.
- Implement Android-native navigation and responsive layouts. Reuse the web product's calculations and analysis rules only where they can be shared and tested safely.
- Keep user data on the device. Use a versioned Room/SQLite data layer and explicit migrations before moving existing Android journal/settings data.
- Use Android-compatible market data adapters. Clearly label live, delayed, indicative, demo, stale and unavailable data; never label a feed live unless freshness is verified.
- Keep broker execution disabled by default. No live order placement is part of parity work without separate explicit approval.
- Never ship API keys, bot tokens, signing keys or other secrets in the APK.
- A feature is complete only when it has a working UI, its required data path, error/loading/empty states, persistence where applicable, tests, and a successful installable APK build.

## Required feature parity

| Web workspace area | Android acceptance requirement |
|---|---|
| Overview / market ticker | Native market overview, feed timestamps and stale/error states |
| QUANTNEX VIEW | First-party candlestick chart with pan, pinch zoom, crosshair, price/time axes, timeframe and symbol selection, OHLC, volume, indicators, drawing tools and chart intelligence |
| Position calculator | Working lot-size/risk calculator with symbol/pip-value inputs and validation |
| Trade journal / trade history | Create, edit, delete, filter, review and export records; durable local storage |
| Account & wallet | Local wallet ledger and summaries; no false broker balance claims |
| Signal Lab / AI Signal Center | Functional signal analysis, setup details, invalidation and risk context |
| Market intelligence / data reliability | Market regime and feed-health details with timestamps |
| Order Flow & Liquidity | Supported market depth/order-flow sources, clear unavailable states where no source exists |
| News intelligence / economic calendar | Working news/calendar sources, event times localized to Asia/Colombo |
| Paper trading / autopilot | Simulated trades only, with explicit paper mode and risk limits |
| Performance Lab / strategy library / AI Strategy Laboratory | Working statistics, saved strategies and backtest/research workflows |
| Risk management | Position and account risk controls and warnings |
| Live Watchlist / Forex / Crypto / Gold desks / price alerts | Functional watchlists and alerts with supported data sources |
| Portfolio monitor / integrations | Local portfolio view and secure integration status/configuration |
| Prop Firm Challenge | Virtual challenge simulator and supported demo-only risk monitoring |
| Goals & certificates / support | Existing goals, certificates and donation/support information |
| Updates / system security | Signed APK release updates, checksum/signature validation, rollback-safe install guidance and security status |
| Telegram | Secure user-configured bot integration; never embed credentials in APK |

## Delivery sequence

### Android 1 — parity inventory and app foundation
- Map every web workspace section, interaction, API endpoint, data dependency and desktop-only dependency.
- Define Android navigation, local persistence, feed adapters and secure integration boundaries.
- Replace the current misleading placeholder-only product definition with this acceptance contract.

### Android 2 — core workspace
- Implement native overview, chart, calculator, journal, wallet and history.
- The chart must meet the QUANTNEX VIEW acceptance criteria above; a static screenshot or basic candle list is not enough.

### Android 3 — analysis and market desks
- Implement Signal Lab, chart intelligence, indicators/drawings, liquidity/order-flow, watchlists, forex/crypto/gold desks, news and alerts.

### Android 4 — management and intelligence
- Implement paper trading, performance, strategy lab, risk management, prop firm challenge, goals and integrations.

### Android 5 — release hardening
- Implement Telegram safely, signed release/update flow, migrations, offline/error handling, accessibility, performance and security tests.
- Test the release APK on physical Android devices before calling it complete.

## Current known gaps (must not be described as complete)

- The existing Android shell's Trading Room, Journal and More screens are placeholders.
- The current NativeChart is a limited crypto candle chart and is not feature-equivalent to QUANTNEX VIEW.
- The current native dashboard is not the full Web workspace.
- The Android release workflow only attaches an APK when the four Android signing secrets are configured. The currently published v0.6.0 release has no APK asset.
- Existing Web workspace features call a loopback backend at 127.0.0.1:8000 and the chart uses backend candle/analysis endpoints. That Windows/local backend is not automatically available inside Android. Each dependency needs an Android implementation or a deliberately designed, secure, optional integration. Do not solve this by exposing the desktop loopback service to the public internet.
- A successful CI debug APK is not proof of production signing, device compatibility or runtime functionality.

## Definition of done

The Android parity project is complete only when every required area is either implemented and device-tested or explicitly marked unsupported with a clear reason; no section may be represented by a working-looking placeholder. The signed APK must be attached to a GitHub Release and installed/tested on a physical Android device.