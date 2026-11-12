# QUANTNEX Phase 02 — Trading Tools MVP

## Scope delivered in this phase
- Browser-based position-size calculator using user-supplied account equity, risk %, stop distance and pip value per standard lot.
- Local trade journal storing symbol, direction, outcome, P&L, notes and date in browser localStorage.
- Bot monitor status placeholder to make it explicit that no bots are connected or executing trades.
- Responsive Phase 02 web tools page.

## Run
Open `apps/web/phase2.html` in a modern browser. No server or API key is required.

## Calculation
Risk amount = account equity × risk percentage / 100.

Estimated lots = risk amount / (stop distance in pips × pip value per 1.00 lot).

The user must supply a broker- and instrument-specific pip value. This is especially important for XAUUSD, indices and crypto CFDs, where contract specifications differ. The calculator is an estimate, not a broker quote or order ticket.

## Data and safety
- Journal data is stored in the current browser profile only.
- No live prices, broker accounts, API credentials, order placement, bot control or AI inference are connected.
- Do not use sample values as live trading advice.
- Later phases must add export/backup, secure authentication, server-side validation and broker-specific contract metadata before account integration.

## Not included yet
Native Android Phase 02 screens, Windows build, live market data, trade execution, bot connectivity, cloud sync and signed APK/release artifacts.
