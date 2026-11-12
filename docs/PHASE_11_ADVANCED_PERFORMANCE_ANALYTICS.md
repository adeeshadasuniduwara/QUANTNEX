# QUANTNEX Phase 11 — Advanced Performance Analytics

## Scope
Descriptive analytics over closed QUANTNEX paper trades only. The existing wallet, journal and paper ledger remain separate and are not modified.

## Metrics
- Win rate, gross profit/loss, profit factor, net P&L and expectancy per trade.
- Average win/loss, largest win/loss, approximate R-multiple sample and average R.
- Cumulative realized P&L curve, peak-to-trough drawdown amount and maximum consecutive win/loss streaks.
- Average holding duration, daily realized P&L and symbol-level breakdown.
- All-history, 7, 30, 90 and 365-day filters.

## Methodology and limitations
R multiple is estimated as realized P&L divided by absolute entry-to-stop distance times quantity. It is not broker-normalized: contract multipliers, quote-currency conversion, commissions and slippage are not included.
Drawdown is measured on the selected period's cumulative realized P&L starting at zero. Its percentage is relative to the peak positive cumulative P&L, not total account equity. It is not an account-equity drawdown.
The ledger does not currently record strategy identifiers, so this phase does not attribute results to strategies. Browser-only journal rows and non-QUANTNEX trades are not mixed into the paper ledger metrics.
A small sample can be misleading. Metrics are descriptive and do not predict future returns or guarantee a win rate.

## Local-only and safety
Runs in the local QUANTNEX API; no login, cloud analytics, broker execution, or new data provider is added. Paper-only mode remains unchanged.
