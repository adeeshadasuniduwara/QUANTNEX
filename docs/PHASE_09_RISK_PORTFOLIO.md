# QUANTNEX Phase 09 — Advanced Risk & Portfolio Intelligence

## Scope
Phase 09 adds local portfolio exposure snapshots, explicit-contract position sizing, a paper-trade drawdown guardian, deterministic shock scenarios and a risk-gated paper-entry endpoint. It preserves local-only/no-login operation and the existing wallet, journal and paper ledger.

## Safety model
- All trade execution remains paper-only. No broker order, live execution, credential or remote login endpoint is added.
- Smart sizing requires an explicit contract multiplier supplied by the user; the system does not guess forex lots, pip values, gold contract size or cross-currency conversions.
- Risk guard uses closed paper-trade results, UTC calendar-day realized loss, user-supplied equity, a historical closed-trade equity curve and loss streak. It does not include open P&L or cashflows.
- Portfolio notional and stress calculations are estimates. They do not claim measured correlations or calibrated volatility.
- Guard blocks only the Phase 09 smart paper-entry endpoint; existing manual paper workflow remains available and is visibly distinguished. Configure conservative limits and test with paper data.

## API
- GET /api/v1/risk/portfolio
- POST /api/v1/risk/position-size
- POST /api/v1/risk/guardian
- POST /api/v1/risk/stress
- POST /api/v1/paper-trading/smart-open

All endpoints use the existing local workspace dependency. No new identity or account system is introduced.

## Stress assumptions
Default scenarios apply parallel -5%, +5%, and -10% price shocks to each open position, with direction-aware linear P&L. This is a transparent what-if, not VaR, expected shortfall, correlation modelling or a prediction.
