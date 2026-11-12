# QUANTNEX Phase 11 — Local AI Paper Desk, Telegram Reports & Personal Goals

Status: implementation scope and safety contract. This phase is based on the open QUANTNEX VIEW signal-intelligence branch and must remain a separate reviewable pull request.

## Product naming and navigation

- Do not present this as a standalone "Signal App".
- Product area name: **QUANTNEX AI Trading Desk**.
- Rename the existing "AI Signal Center" label to **AI Market Analysis**. It is an analysis/alert surface, not an autonomous trading bot.
- Add a distinct **AI Paper Desk** surface for user-authorized local paper automation.
- Keep **Risk Management** as its own section and expose its status inside the AI Paper Desk. Do not use "Risk Management Highest" as a product name or claim that risk is guaranteed.
- Keep **AI Assistant** as a separate optional integration. It must show its provider and connection state clearly; no provider key is required for deterministic local rule-based analysis. Any cloud AI provider must be explicitly configured by the user.

## 1. Local paper automation — explicit consent

- A clear opt-in checkbox with an animated checkmark is required before enabling autonomous paper simulation. The consent copy must say that the engine runs locally on this computer, uses supported live market feeds, records simulated trades, and sends no broker orders.
- Start/Stop controls, a visible running indicator, last heartbeat, data-feed health, and a persistent mode label are required. The engine must never run hidden or start automatically without consent.
- Paper mode only in this phase. No exchange API trading keys, broker order endpoints, real-money execution, or real account balance access.
- Run strategy backtests locally against historical closed candles before enabling a strategy for forward paper observation. Display sample size, date range, costs assumptions, win rate, profit factor, expectancy, max drawdown, and out-of-sample/forward status. Do not call a backtest a live result or imply a guaranteed edge.
- The strategy engine must support the full currently tradable Binance Spot symbol universe through exchange metadata discovery, with explicit quote-currency selection, status filtering, refresh/caching, and exclusions for leveraged/unsupported instruments. Do not hard-code only BTC/ETH/SOL. A failed/partial discovery must be shown as incomplete, never silently treated as the full universe.
- Candidate selection must be risk-first and data-health-gated. Enforce max simultaneous positions, per-trade risk, daily loss cap, max drawdown, duplicate-entry prevention, spread/slippage/fee assumptions where available, cooldowns, and an emergency Stop. No setup means WAIT.
- Paper positions must be monitored using timestamped provider quotes/streams and persisted locally. Display entry, stop, targets, current mark, unrealized P&L, realized P&L, fees/cost assumptions, and source/time. Stale or unavailable data must be visibly flagged and must not be replaced with fabricated prices.
- TP1 partial close must realize the configured portion of profit and move the remaining stop to entry only after the TP1 fill is confirmed by the paper simulator. If price later returns to entry, the remaining quantity closes at break-even; the already-realized TP1 profit remains in total net P&L. Track each partial fill separately. Include fees/slippage so break-even is not falsely described as net-zero when costs apply.
- Keep automated paper trades in a separate ledger from the user's manual real-account journal and wallet. Never auto-import bot trades into the user's personal journal.

## 2. Live dashboard and trade audit

- Add an AI Paper Desk dashboard with live open positions, current green/red unrealized P&L, realized P&L, today's closed trades, win rate, profit factor, drawdown, strategy and symbol breakdown.
- Each trade must show its source, strategy/version, symbol, direction, opened time, entry, SL, TP plan, partial exits, exit time/price, fees, realized result and current status.
- Preserve an auditable event/fill history so the user can compare exact simulated entry/exit levels and timestamps with independent chart data. Label provider quote vs broker executable price accurately.
- Keep manual journal records separate and clearly identify their origin as user-entered real-account records. Only those manual records may contribute to the personal-goal tracker; bot paper P&L must never count toward a user's real-money goals.

## 3. Telegram bot experience

- After /start, prefer inline buttons for navigation/actions: Dashboard, AI Paper Desk, Market Update, Today's Report, Strategies, Risk Settings, Goals, Help, Pause and Resume. Commands remain available as fallback.
- Use the already-encrypted local Telegram connection; never expose tokens in browser code, logs, reports, or Git history.
- Add opt-in event notifications and a configurable daily report at **20:00 Asia/Colombo**. Report generation must use the configured local timezone and handle daylight-saving-independent Colombo time correctly.
- Daily report must include all paper trades opened/closed that day, open positions at cutoff, entry/exit timestamps, direction, quantity, entry/exit prices, SL/TP, realized and unrealized P&L, total gross/net profit, total loss, win/loss/breakeven counts, win rate, profit factor, max drawdown, fees/cost assumptions, data coverage and strategy breakdown.
- Generate a readable A4 portrait PDF with vector text/graphics and the existing QUANTNEX black/white logo assets. "4K" is not a PDF resolution setting; prioritize print-ready vector output and high-resolution embedded images where needed.
- Send the PDF as a Telegram document after the summary message. Respect Telegram rate limits with bounded queues, retries with exponential backoff, Retry-After handling, idempotency/deduplication, and per-chat throttling. Do not spam users or loop indefinitely.
- For repeated market-update requests, edit a single tracked Telegram message when possible instead of sending a flood of new messages. If editing is not possible, explain the fallback and rate-limit it. Use inline buttons for refresh/actions and escape Telegram HTML/Markdown safely.

## 4. Personal targets and achievement certificates

- Add a separate Goals area where the user can create multiple personal goals, e.g. a Nissan GT-R, with title, optional image, target amount/currency, starting saved amount, target date, notes and achieved date.
- Allow manual journal entries to contribute only when the user explicitly records eligible real-account profit/savings. Never use paper-bot P&L, simulated backtest results, or an unverified wallet figure as real savings.
- Show remaining amount, percentage progress, projected pace only when supported by recorded history, animated bubbles/progress, and "You can afford this" only when the recorded available savings meet the target and the user confirms the balance is genuinely available.
- Record goal creation and achievement timestamps so elapsed days/months/years can be calculated consistently.
- Generate an elegant monochrome A4 portrait certificate using the QUANTNEX logo, user's chosen display name, goal name, achieved date, elapsed duration, and a motivational message. Request/confirm the display name before generation. Use a decorative signature mark only as design artwork; do not impersonate a real person or falsely claim a human support agent signed it.
- Certificate issuer wording may say "Presented by the QUANTNEX Support Team" only as a product-branded motivational certificate, not a regulated financial credential or proof of trading skill.
- Include a verification ID and integrity hash/signature metadata. Because the app is local-only and user-editable, do not claim the certificate is impossible to forge or independently verified by a remote authority. Explain local verification limits.
- A user must not be able to unlock an achievement merely by editing a browser field. Achievement state must be derived from persisted local records and validated server-side; still disclose that an owner with access to the local machine and source can alter a local-only app.

## 5. Data boundaries and accounting rules

- Manual journal / personal goals: user-entered real-account records only.
- AI Paper Desk: separate simulated trade ledger only.
- Historical backtests: separate research results only.
- Never combine these three datasets into one "real profit" number.
- Display gross and net P&L separately. Net results must include modeled fees and any available spread/slippage assumptions.
- For TP1 then break-even: partial TP1 profit remains realized; the remaining quantity closed at entry contributes zero price P&L before costs. The final trade is not a loss solely because the remaining position returned to entry.

## 6. Delivery sequence

1. Navigation/product naming, opt-in consent UI, local paper-engine state and safety/status surface.
2. Binance symbol-universe discovery and data-quality-aware strategy research/backtest queue.
3. Persistent paper-position lifecycle, partial TP1/BE accounting, dashboard and audit trail.
4. Telegram inline-button UX, rate-limited live message updates, Colombo 20:00 scheduler and PDF report.
5. Personal goals, manual-journal-only progress accounting, achievement certificate and local integrity checks.
6. Unit/integration tests, UI checks, Windows build and documented limitations.

## Acceptance and validation

- No hidden execution; explicit opt-in and visible Stop.
- No broker/live orders.
- No synthetic market prices, fake fills, fake P&L, or fabricated win rates.
- Stale feed blocks new entries and is disclosed on existing positions.
- Backtest, paper ledger and manual real journal remain isolated.
- TP1 partial plus later BE is accounted for correctly.
- Telegram daily report is sent once per local day at 20:00 Asia/Colombo, with retries bounded and no duplicate PDFs.
- PDF is A4 portrait, print-ready, and uses the repository's real logo assets.
- Goals and certificates derive only from validated manual records and clearly disclose local-only verification limits.
- All changes must preserve the local-only, no-login architecture and existing workspace/database records.
