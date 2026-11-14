# QUANTNEX Product Roadmap

QUANTNEX is developed as one evolving application. New capabilities extend the existing workspace rather than creating disconnected duplicate apps.

## Implemented foundation

- Monorepo for Web, Android, Windows and shared backend.
- Responsive monochrome Web workspace with calculator and local trade journal.
- Android APK and Web workspace with shared chart, journal and update experiences.
- FastAPI authentication, user-isolated journal and preferences APIs.
- Wallet ledger API: authenticated manual deposits and withdrawals, balance validation, transaction history and summary.
- API journal P&L automatically creates a linked wallet ledger entry; deleting that journal record removes the linked P&L entry.
- Shared dot-mark brand asset for the Web favicon and Android launcher icon.
- Web live chart workspace embeds TradingView charts for Binance BTCUSDT and OANDA XAUUSD.
- Windows Charts tab draws read-only BTCUSDT 15-minute candles from Binance public REST market data and links to TradingView BTC and XAUUSD charts.
- Windows installation identity uses a locally generated random UUID; it does not collect hardware serial numbers or MAC addresses.
- Android remains an early starter app.

## Current phase: wallet foundation

The wallet ledger is currently implemented in the shared backend API only. The Web, Windows and Android clients are not yet connected to it. It is not a bank/payment integration and does not verify real deposits or withdrawals. The API journal automatically records the P&L value supplied when a trade is saved; it does not independently verify broker statements.

## Next development phases

1. Connect Web login, journal and wallet screens to the authenticated shared API.
2. Add matching wallet/account views to Windows and Android, using the same API and user identity.
3. Add secure session lifecycle, device management and account recovery.
4. Finish Telegram release notification verification and add opt-in journal/monthly reports.
5. Improve live chart feed freshness, provider disclosure and direct XAUUSD source support in Windows.
6. Add multi-market watchlists, timeframes and read-only indicators.
7. Add performance analytics: win rate, profit factor, drawdown, equity curve and monthly reports.
8. Add AI journal review and psychology coaching, disabled until server-side AI configuration is provided.
9. Consider broker connections or trade execution only after independent safeguards, explicit user confirmation and security review.

## Safety boundaries

Market charts are read-only and do not place orders. Binance public market data and embedded TradingView charts are third-party services; availability, symbols, latency and pricing can vary by region and provider. XAUUSD in the Windows app currently opens the TradingView chart in the browser rather than drawing an in-app gold feed. Login and cloud sync are not yet wired through all clients. No profitability claims are made. Public deployment requires security review, operational monitoring, backups and testing.
