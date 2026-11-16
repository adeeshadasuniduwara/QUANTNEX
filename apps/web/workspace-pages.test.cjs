const fs = require("node:fs");
const assert = require("node:assert/strict");

const html = fs.readFileSync("apps/web/index.html", "utf8");
const realtime = fs.readFileSync("apps/web/realtime-events.js", "utf8");
const sectionIds = [...html.matchAll(/<section\b[^>]*\bid="([^"]+)"/g)].map(match => match[1]);
const navTargets = [...html.matchAll(/class="nav-link[^"]*" href="#([^"]+)"/g)].map(match => match[1]);

assert.equal(new Set(sectionIds).size, sectionIds.length, "Section IDs must be unique");
const missingTargets = navTargets.filter(target => target !== "overview" && !sectionIds.includes(target));
assert.deepEqual(missingTargets, [], "Every sidebar link must point to an existing section");

const requiredPages = [
  "watchlist-desk", "forex-desk", "crypto-desk", "gold-desk", "price-alerts",
  "economic-calendar", "trade-history", "strategy-library", "portfolio-monitor",
  "integrations-center", "telegram-bot"
];
for (const page of requiredPages) {
  assert.ok(sectionIds.includes(page), "Missing page section: " + page);
  assert.ok(navTargets.includes(page), "Missing sidebar link: " + page);
}
for (const asset of ["apps/web/workspace-pages.js", "apps/web/workspace-pages.css", "apps/web/realtime-events.js", "apps/web/prop-challenge.js"]) {
  assert.ok(fs.existsSync(asset), "Missing workspace page asset: " + asset);
}
assert.ok(html.indexOf('src="realtime-events.js"') > html.indexOf('src="app.js"'), "Realtime event client must load after the main app");
assert.ok(!html.includes("\\n"), "HTML must not contain literal escaped newline text");
assert.ok(html.includes('id="goalImagePreview"'), "Personal goals must expose an inline image preview");
assert.ok(html.includes('id="goalImage"'), "Personal goals must accept an image URL");
assert.ok(html.includes('id="goalDescription"'), "Personal goals must support a custom achievement message");
assert.ok(html.includes('id="goalTargetDate"'), "Personal goals must support an optional target date");
assert.ok(html.includes('id="paper-autopilot"'), "Paper autopilot workspace section must exist");
assert.ok(html.includes('id="paperEngineToggle"'), "Paper autopilot must expose an explicit start/pause control");
assert.ok(html.includes('id="paperUniverseRefresh"'), "Market universe discovery control must exist");
assert.ok(html.includes('id="paperWalkForwardRun"'), "Strategy holdout validation control must exist");
assert.ok(html.includes('id="goalJournalPreview"'), "Personal goals must support journal preview");
assert.ok(html.includes('id="goalJournalImport"'), "Personal goals must require explicit journal import");
assert.ok(html.includes('src="phase12-20.js"'), "Paper platform client must be loaded");
assert.ok(fs.existsSync("apps/web/phase12-20.js"), "Paper platform client asset must exist");
console.log("Workspace page checks passed: 10 new pages, unique section IDs, valid navigation and local event client.");
const telegramArticleStart = html.indexOf('id="telegram-bot-connect"');
const telegramPageStart = html.indexOf('id="telegram-bot"');
const tradingViewStart = html.indexOf('id="tradingview"');
assert.ok(tradingViewStart >= 0 && telegramPageStart > tradingViewStart, "QUANTNEX VIEW must precede the dedicated Telegram Bot page.");
assert.ok(!sectionIds.includes("signal-lab") && !navTargets.includes("signal-lab"), "The retired Signal Lab page and sidebar link must be removed.");
assert.ok(!sectionIds.includes("ai-signal-center") && !navTargets.includes("ai-signal-center"), "The duplicate AI Signal Center page and sidebar link must be removed.");
assert.doesNotMatch(html, /Signal Lab|AI Signal Center/, "Retired signal workspace names must not remain in the active Web UI.");
const tradingViewMarkup = html.slice(tradingViewStart, telegramPageStart);
for (const id of ["signalMarketSymbol", "runSignalScan", "runSignalBacktest", "signalResult", "p7SignalSymbol", "p7SignalThreshold", "p7RunScan", "p7SignalResult", "p7SignalFrames", "p7UseSignal", "qxSignalIntelligence", "qxMainSignal", "qxPositionPreview"]) {
  assert.ok(tradingViewMarkup.includes(`id="${id}"`), "QUANTNEX VIEW must retain signal functionality: " + id);
}
assert.ok(navTargets.includes("telegram-bot"), "Telegram Bot must have its own sidebar entry.");
assert.ok(telegramArticleStart > telegramPageStart, "Bot credentials and delivery controls must live inside the Telegram Bot page.");
assert.ok(html.includes('id="openTelegramBotTool"'), "QUANTNEX VIEW must link to the separate Telegram Bot tool.");
assert.ok(html.includes('id="signalTelegramStatus"'), "QUANTNEX VIEW must display the shared Telegram connection/delivery status.");
const signalTool = fs.readFileSync("apps/web/signal-tool.js", "utf8");
assert.ok(signalTool.includes("new MutationObserver(syncTelegramStatus"), "QUANTNEX VIEW signal status must stay synchronized with Telegram Bot actions.");
assert.doesNotMatch(signalTool, /Signal Lab/, "Signal client must not reference the retired page.");
assert.ok(signalTool.includes("/api/v1/signals/scan"), "QUANTNEX VIEW must retain the multi-timeframe signal API.");
assert.ok(fs.readFileSync("apps/web/quantnex-view-intelligence.js", "utf8").includes("/api/v1/quantnex-view/analyze"), "QUANTNEX VIEW must retain its chart intelligence API.");
assert.ok(fs.readFileSync("apps/web/workspace-pages.js", "utf8").includes('quantnexNavigate("telegram-bot")'), "Connections & Integrations must open the dedicated Telegram Bot tool.");
console.log("Signal consolidation checks passed: no duplicate pages; all signal analysis, cross-market scanning, research and trade planning live inside QUANTNEX VIEW.");
assert.ok(fs.readFileSync("apps/web/app.js", "utf8").includes('window.quantnexNavigate("paper-trading")'), "Cross-market scan handoff must open the Paper Trading workspace.");

assert.match(realtime, /connectedOnce&&current!==lastEventId/, "A restarted event gateway must trigger a workspace snapshot resync");
assert.match(realtime, /event_stream_restarted/, "A lower sequence after reconnect must be identified as an event-service restart");
assert.match(realtime, /lastEventId=current/, "The event cursor must reset to the new process sequence after a restart");
console.log("Realtime event restart-resync checks passed.");

const chartClient = fs.readFileSync("apps/web/quantnex-view-chart.js", "utf8");
const chartIntelligence = fs.readFileSync("apps/web/quantnex-view-intelligence.js", "utf8");
assert.ok(/src="quantnex-view-chart\.js\?v=20261114-coinbase-goldfeed1"/.test(html), "Live chart controller must load with the current cache version");
assert.ok(html.includes('id="qxChartIntelMetrics"'), "Chart must expose indicator readouts");
assert.ok(html.includes('id="qxOverlayZones"'), "Chart must expose zone visibility control");
for (const feature of ["bullish_fvg", "bearish_fvg", "bullish_order_block", "bearish_order_block",
  "bullish_breaker_block", "bearish_breaker_block", "bullish_ifvg", "bearish_ifvg",
  "swing_high", "swing_low", "equilibrium", "liquidity_sweep", "quantnexViewSetTradePlan"]) {
  assert.ok(chartClient.includes(feature), "Chart intelligence renderer is missing: " + feature);
}
assert.match(chartClient, /api\/v1\/charts\/candles/, "Chart must use the local historical candle API");
assert.match(chartClient, /window\.quantnexViewSetAnalysis=renderAnalysis/, "Chart must expose the shared analysis renderer");
assert.match(chartIntelligence, /api\/v1\/quantnex-view\/analyze/, "Chart Intelligence must own the QUANTNEX VIEW analysis API request");
console.log("QUANTNEX VIEW checks passed: local candles, signal plan levels, structure, liquidity and OB/BB/FVG/SR overlays.");

const polish = fs.readFileSync("apps/web/workspace-polish.js", "utf8");
const polishCss = fs.readFileSync("apps/web/workspace-polish.css", "utf8");
assert.ok(html.includes('href="workspace-polish.css?v=20261116-sidebar-compact1"'), "Professional workspace stylesheet must load");
assert.ok(html.includes('src="workspace-polish.js?v=20261114-single-icon2"'), "Professional navigation script must load");
assert.match(polish, /qxNavSearch/, "Sidebar tool search must be available");
assert.match(polish, /aria-expanded/, "Sidebar groups must be keyboard-accessible toggles");
assert.match(polish, /createElementNS/, "Navigation icons must use consistent SVG artwork");
assert.match(polishCss, /\.qx-nav-search/, "Sidebar search must be styled");
assert.match(polishCss, /\.qx-nav-icon svg/, "Sidebar SVG icons must share a consistent size and stroke");
console.log("Professional workspace navigation checks passed.");

const app = fs.readFileSync("apps/web/app.js", "utf8");
const welcomeJs = fs.readFileSync("apps/web/welcome-whats-new.js", "utf8");
const welcomeCss = fs.readFileSync("apps/web/welcome-whats-new.css", "utf8");
assert.ok(html.includes('href="welcome-whats-new.css?v=20261113-1"'), "Welcome stylesheet must load");
assert.ok(html.includes('src="welcome-whats-new.js?v=20261113-1"'), "Welcome script must load");
assert.match(welcomeJs, /quantnex\.onboarding\.firstRun/, "First-run guide completion must persist");
assert.match(welcomeJs, /quantnex\.onboarding\.lastSeenRelease/, "Last-seen release must persist");
assert.match(welcomeJs, /showRelease/, "Updater release changes must have a display flow");
assert.match(welcomeJs, /replay/, "Users must be able to replay the welcome guide");
assert.match(welcomeCss, /prefers-reduced-motion/, "Onboarding must respect reduced-motion preferences");
assert.match(app, /QuantnexOnboarding\?\.showRelease/, "Updater must pass release changes to What's New");
console.log("Welcome and release onboarding checks passed.");


assert.ok(html.includes('id="prop-challenge"'), "Prop Firm Challenge workspace section must exist");
assert.ok(html.includes('id="pcCreateForm"'), "Prop Firm Challenge must expose its rule configuration form");

assert.match(app, /apiRequest\("\/api\/v1\/journal"/, "Journal entries must persist through the local database API.");
assert.match(app, /apiRequest\("\/api\/v1\/journal\/import"/, "Legacy browser journal entries must migrate to the database.");
assert.match(app, /saveTrades\(journalRowsCache\)/, "The browser must retain a recoverable journal cache.");
assert.match(app, /source_ref:row\.client_ref/, "Offline journal retries must use stable idempotency references.");
assert.match(app, /window\.addEventListener\("online"/, "Offline journal rows must sync when the browser reconnects.");
assert.match(app, /Recover and reconcile queued rows on every workspace startup/, "Offline journal recovery must run on initial workspace startup.");
assert.match(app, /syncJournal\(\);\nfunction renderWalletTransactions\(transactions\)/, "Initial journal recovery must run without waiting for a reconnect event.");
assert.ok(html.includes('id="journalStatus"'), "The journal must expose database synchronization status.");
assert.ok(!html.includes("Records are stored in this browser only."), "Journal copy must not imply browser-only persistence.");
console.log("Database-backed journal and legacy recovery checks passed.");

assert.match(app, /created_at:dateValue\.toISOString\(\)/, "Journal create and edit writes must preserve the selected local calendar date.");
assert.ok(app.includes('/[zZ]|[+-]\\d{2}:\\d{2}$/'), "SQLite timestamps without an offset must be parsed as UTC.");
console.log("Journal timezone normalization checks passed.");

assert.match(app, /client_ref:trade\.client_ref/, "Online journal writes must carry the same idempotency key as offline retries.");
console.log("Journal online/offline idempotency checks passed.");

const journalHtml = html.slice(html.indexOf('id="journal"'), html.indexOf('id="automation"'));
assert.match(journalHtml, /id="tradeDate" type="date" required/, "Journal entries must allow an explicit trade date.");
assert.match(journalHtml, /id="cancelJournalEdit"/, "Journal edit mode must have a cancel action.");
assert.match(journalHtml, /id="saveTrade"/, "Journal create and edit must share a visible save action.");
assert.match(app, /function beginJournalEdit\(/, "Every journal row must expose an edit flow.");
assert.match(app, /function cancelJournalEdit\(/, "Journal edits must be cancellable without writing.");
assert.match(app, /apiRequest\("\/api\/v1\/journal\/"\+existing\.id,\{method:"PUT"/, "Persisted journal edits must update the local database API.");
assert.match(app, /journalRowsCache=journalRowsCache\.map\(row=>journalRowKey\(row\)===key\?updated:row\)/, "An edited journal row must replace only its matching cached record.");
assert.match(app, /if\(error\.status\)\{setJournalStatus\("Trade could not be saved:/, "API validation errors must not be misclassified as offline queued trades.");
console.log("Web journal create/edit/delete UI wiring checks passed.");

assert.ok(app.includes("function money(value)"), "The shared USD formatter must exist before journal and wallet rendering.");
assert.ok(app.includes("function renderWalletTransactions(transactions)"), "Wallet history must have a concrete renderer.");
assert.ok(app.includes('const body=$("walletRows")'), "Wallet history must target the visible transaction table.");
assert.ok(app.includes("transaction.transaction_type"), "Wallet history must label deposit, withdrawal and journal P&L rows.");
assert.ok(app.includes("cell.textContent=value"), "Wallet history must render data through textContent rather than HTML.");
assert.ok(app.includes("walletWriteInFlight"), "Wallet writes must ignore duplicate clicks while a request is pending.");
assert.ok(app.includes("wallet display could not refresh"), "A saved transaction must not be misreported as an unsaved write when refresh fails.");
assert.ok(app.includes("wallet/transactions?limit=500"), "Wallet UI must request the latest supported transaction-history page.");
console.log("Wallet UI checks passed: shared formatter, safe history rendering, duplicate-submit guard and explicit refresh errors.");

assert.ok(app.includes("item.exit_price"), "Closed paper trades must render their exit price.");
assert.ok(app.includes("item.realized_pnl"), "Closed paper trades must render realized P&L per position.");
assert.ok(app.includes("await loadPaper();"), "A failed close action must reload the ledger so concurrent-close state is reconciled.");
assert.ok(html.includes("<th>Exit</th>") && html.includes("<th>Realized P&amp;L</th>"), "The paper ledger must expose exit and realized P&L columns.");
assert.ok(html.includes('colspan="11"'), "The empty paper ledger row must span the expanded table.");
assert.ok(app.includes("td.colSpan=11"), "The dynamically rendered empty row must span the expanded table.");
console.log("Paper Trading UI checks passed: closed results and close-error reconciliation.");
