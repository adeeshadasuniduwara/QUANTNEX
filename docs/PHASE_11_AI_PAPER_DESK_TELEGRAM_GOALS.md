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

## Implementation update — Telegram, certificates and goals

### Telegram delivery now implemented
- /start and /help present an inline-button menu for dashboard, BTC/ETH/SOL/Gold scans, timeframe settings, status, help and PDF reporting.
- Button callbacks are polled and handled by the local Telegram worker; responses edit the existing menu message where Telegram permits, with a send-message fallback.
- Telegram API calls use bounded retries for rate-limit responses and server errors. Retry-After is capped; permanent errors are not retried indefinitely.
- Signal Lab exposes a daily-report preference. When enabled, the worker sends one A4 portrait PDF per Colombo calendar day at/after 20:00, recording the delivered local date to avoid repeated scheduled sends.
- The PDF is generated from the separate persisted PaperTrade ledger only. It includes opened/closed counts, win/loss/breakeven, win rate, gross positive P&L, total negative P&L, recorded realized P&L, closed-trade entry/exit levels and timestamps, and open positions at cutoff.
- Report scope is limited by the current PaperTrade schema: it does not yet persist strategy/version, partial-fill events, fee breakdown, or a provider-marked unrealized P&L snapshot. Those fields must not be fabricated and remain future integration work.

### Goals and certificates now implemented
- Local API and UI for multiple personal goals, image URL, currency, target amount/date, progress, manual contributions and achievement state.
- Initial savings and later contributions require explicit confirmation that funds are genuinely available real-account savings/profit. Paper trades, backtests and wallet estimates are excluded. Contributions are currently entered manually in the Goals panel; they are not yet auto-imported from the browser's localStorage journal.
- A goal becomes achieved when confirmed contributions plus confirmed initial savings reach the target.
- A4 portrait monochrome certificate PDF includes a vector Q-mark, display name, goal and recorded goal value, dates, elapsed days, QUANTNEX Support Team product branding, certificate ID and local integrity fingerprint.
- Certificate generation is locked until the target is achieved. HMAC integrity is stored with an encrypted local secret. Verification is local-workspace integrity only, not a remote public authority signature or a guarantee that a machine owner cannot modify local source/data.
- Personal goals and contributions are migrated during local workspace owner consolidation to preserve existing data.

### Still pending
- The full AI Paper Desk autonomous paper-position monitor and local strategy scheduler.
- Full dynamic Binance Spot tradable-pair universe integration for the autonomous paper engine.
- Telegram daily report extensions for strategy version, fee ledger, partial fills and timestamped live mark/unrealized P&L.
- Exact SVG asset embedding and final browser visual review. Current PDFs use a compact monochrome vector Q-mark approximation; Windows build has passed CI.
- Full integration testing of Telegram callback delivery with an actual user bot; no live Telegram message was sent during development. Latest backend, web and Windows CI checks passed.

## QUANTNEX roadmap — next ten phases (12–21)

These are the next ten planned delivery phases. They are roadmap commitments, not claims that the features below are already implemented. Each phase must be developed on a reviewable branch, retain the local-only/no-login model, preserve existing SQLite and browser data, and pass automated checks before it is presented as complete.

### Phase 12 — Autonomous Paper Desk foundation
- Local opt-in scheduler, explicit start/stop controls, process heartbeat, pause/resume and persisted engine state.
- Paper-only execution boundary; no broker order endpoints or live credentials.
- Crash-safe restart and duplicate-run prevention.

### Phase 13 — Full market-universe discovery
- Exchange metadata discovery for eligible Binance Spot pairs, with quote filters, symbol status and leveraged-token exclusions.
- Provider adapters for supported Forex and XAUUSD feeds, each with source timestamps and rate-limit handling.
- Cache freshness and incomplete-universe warnings; never silently label a partial scan as complete.

### Phase 14 — Paper position lifecycle and event ledger
- Persistent simulated orders, fills, partial exits, SL/TP events and restart recovery.
- TP1 partial-profit accounting with remaining quantity moved to entry only after simulated fill confirmation.
- Separate gross, fees, modeled slippage and net realized P&L; no fabricated fill prices.

### Phase 15 — Risk Guardian and Prop Challenge Toolkit integration
- Per-trade risk, daily loss, max drawdown, exposure, concurrent-position and cooldown limits.
- Static/trailing prop drawdown configuration and clear breach warnings.
- Fail-closed behavior when required price or account data is stale; no guarantee that an external MT5 terminal can always close a position.

### Phase 16 — Live paper-position monitoring
- Timestamped provider marks, unrealized P&L, stale-feed detection and per-position source labels.
- WebSocket with bounded polling fallback, reconnect/resync and duplicate-event handling.
- Stop new simulated entries when data health is unsafe; disclose that provider marks are not broker-executable prices.

### Phase 17 — Performance and portfolio analytics
- Equity curve, drawdown, expectancy, profit factor, win/loss distribution and symbol/strategy/timeframe breakdown.
- Clearly separated paper, backtest and manual-journal reports.
- Sample-size and date-range labels; no uncalibrated confluence score presented as a win probability.

### Phase 18 — Strategy Laboratory and validation pipeline
- Walk-forward and out-of-sample tests, parameter stability checks and realistic cost assumptions.
- Versioned strategy configurations and reproducible experiment records.
- Reject promotion when sample size, data coverage or risk criteria are inadequate.

### Phase 19 — Telegram control room and reporting v2
- Compact inline-button menu, message editing, opt-in event alerts and configurable Colombo-time reports.
- A4 PDF with full trade-event/fee coverage once the event ledger exists; idempotent scheduling and bounded retries.
- Strict command authorization for the local owner and no token leakage into logs or browser code.

### Phase 20 — Personal goals and journal bridge
- Optional import of eligible user-confirmed manual journal records, with preview and deduplication before applying.
- Minimal goal creation fields, inline image preview for direct HTTPS image URLs, and clear fallback for non-image Google search/result URLs.
- Paper trades and backtests remain excluded from real-savings goals; certificate integrity limits remain explicit for a local-only app.

### Phase 21 — Reliability, security and release engineering
- Regression suite, API contract checks, migration/backup/restore tests and Windows clean-install/update tests.
- Local API binding and origin checks, secret redaction, dependency/security review and safe rollback.
- Release checklist, changelog, verified artifacts and a final feature/limitation matrix before a stable release.

## Phase 11 follow-up fixes
- Simplified goal creation to the essentials: goal name, target amount, currency and optional image URL. Savings are entered separately through the existing contribution control, retaining the real-funds confirmation.
- Added an inline image preview and clickable full-image link. Google Images result/search-page URLs are not themselves image files; paste the direct HTTPS image URL shown by the image host. A failed preview is explained instead of silently disappearing.
- Fixed literal escaped newline sequences in the HTML that could appear as stray text and interfere with adjacent markup.
- Added the goals client to the web JavaScript syntax checks and added regression assertions for the goal preview and minimal form.


## Phases 12–20 — implementation slice added on branch `feature-qx-phases-12-20-paper-platform`

This branch contains an initial connected implementation across the nine phases. It is not a claim that every planned sub-feature is production-complete; see the verified scope below.

- **Phase 12:** Added a persistent local paper-autopilot settings API and opt-in background worker. It starts disabled, scans the existing validated BTCUSDT/ETHUSDT/SOLUSDT signal path, rejects stale quotes and duplicate signal candles, sizes paper positions from configured risk, and monitors worker-created positions for stop/target closure. The worker runs only while the local API is running.
- **Phase 13:** Added Binance Spot exchange metadata discovery for eligible TRADING USDT pairs, excluding leveraged tokens. Discovery is informational; the automated signal worker remains limited to BTC/ETH/SOL until broader symbols have validated signal coverage.
- **Phase 14:** Added a persistent `paper_trade_events` ledger for manual and automatic opens/closes, plus event API/UI. Existing paper trade table is preserved. Partial TP1/TP2 accounting and fee-aware multi-fill execution remain a follow-up; no partial fills are fabricated.
- **Phase 15:** Added daily realized-plus-unrealized loss, max drawdown and concurrent-position guards to the automated paper worker, with configurable limits and fail-closed entry behavior when an open position cannot be priced.
- **Phase 16:** Added provider-mark monitoring for open paper positions, including timestamp freshness and unavailable-feed states. Marks are indicative only and do not represent broker execution prices.
- **Phase 17:** Added paper-only performance metrics: wins/losses/breakeven, win rate, profit factor, expectancy, equity curve and max drawdown. Existing stored P&L has no historical fees/slippage, so the API warns accordingly.
- **Phase 18:** Added chronological 70/30 holdout validation using the existing deterministic strategy backtester and saves the result as a research run. This is a single holdout, not a full walk-forward optimization or proof of future edge.
- **Phase 19:** Reuses the existing local Telegram menu, retry handling and opt-in Colombo 20:00 PDF scheduler. The new engine has website controls and local state; Telegram start/stop buttons and full event-ledger PDF rendering are not yet wired in this slice.
- **Phase 20:** Added an optional journal-profit preview/import flow with explicit real-funds confirmation and per-goal deduplication. It is limited to USD goals because the journal schema does not store currency; it does not automatically assume journal P&L is cash savings.

### Operational safeguards and validation still required
- Paper mode is disabled by default; no broker order API, credentials or real-money execution were added.
- Automatic sizing is limited to crypto spot units. Forex/Gold remain excluded until contract multipliers and tick values are verified.
- Quote monitoring uses periodic provider snapshots; it cannot know intrabar stop/target order when both levels are crossed between snapshots. Stop is treated conservatively if both conditions appear true on a single mark.
- TP1/TP2 partial exits, fee/slippage event accounting, full dynamic pair scanning by the strategy engine, multi-window walk-forward testing, Telegram engine controls and event-ledger PDF inclusion remain pending.
- New SQLAlchemy event table is created on startup through existing metadata creation; existing user data tables are not dropped or reset.
- CI checks are required before marking this branch ready. A local Windows UI/market-feed test remains necessary after the PR is checked out and run on the user's computer.
