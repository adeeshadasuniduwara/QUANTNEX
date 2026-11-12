# QUANTNEX Product Roadmap

QUANTNEX is developed as one evolving application. New capabilities extend the existing workspace rather than creating disconnected duplicate apps.

## Current foundation

- Monorepo for Web, Android, Windows and shared backend.
- Responsive monochrome Web workspace with calculator and local trade journal.
- Windows desktop workspace with calculator, local SQLite journal and update checking.
- FastAPI foundation with authentication, user-isolated journal and preferences APIs.
- Shared dot-mark brand asset for the Web favicon and Android launcher icon.
- Web live chart workspace embeds TradingView charts for Binance BTCUSDT and OANDA XAUUSD.
- Windows Charts tab draws read-only BTCUSDT 15-minute candles from Binance public REST market data and links to TradingView BTC and XAUUSD charts.
- Windows installation identity uses a locally generated random UUID; it does not collect hardware serial numbers or MAC addresses.
- Android Java/Kotlin JVM targets are aligned to Java 17; Android remains an early starter app.

## Next priorities

1. Verify live chart behavior across networks and clearly show feed freshness / connection state.
2. Add a direct, supported XAUUSD market-data adapter for the Windows desktop chart, with provider/source disclosure.
3. Connect Windows, Web and Android clients to the shared authenticated API.
4. Build real login, registration, session management and server-side device revocation; the local installation ID is not an account login.
5. Add secure Telegram notifications and bot status integration.
6. Add read-only multi-market data adapters, watchlists, configurable timeframes and chart indicators.
7. Add wallet ledger, deposit/withdrawal records and full journal synchronization.
8. Add bot control only after independent execution safeguards and risk limits are tested.
9. Publish signed Windows and Android releases with verified update and rollback flows.

## Safety boundaries

Market charts are read-only and do not place orders. Binance public market data and embedded TradingView charts are third-party services; availability, symbols, latency and pricing can vary by region and provider. XAUUSD in the Windows app currently opens the TradingView chart in the browser rather than drawing an in-app gold feed. Login and cloud sync are not yet wired through all clients. No profitability claims are made. Public deployment requires security review, operational monitoring, backups and testing.
