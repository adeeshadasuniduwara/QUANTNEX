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
  "integrations-center"
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

assert.match(realtime, /connectedOnce&&current!==lastEventId/, "A restarted event gateway must trigger a workspace snapshot resync");
assert.match(realtime, /event_stream_restarted/, "A lower sequence after reconnect must be identified as an event-service restart");
assert.match(realtime, /lastEventId=current/, "The event cursor must reset to the new process sequence after a restart");
console.log("Realtime event restart-resync checks passed.");

const chartClient = fs.readFileSync("apps/web/quantnex-view-chart.js", "utf8");
assert.ok(/src="quantnex-view-chart\.js\?v=20261113-analysis-dedupe1"/.test(html), "Live chart controller must load with the current cache version");
assert.ok(html.includes('id="qxChartIntelMetrics"'), "Chart must expose indicator readouts");
assert.ok(html.includes('id="qxOverlayZones"'), "Chart must expose zone visibility control");
for (const feature of ["bullish_fvg", "bearish_fvg", "bullish_order_block", "bearish_order_block",
  "bullish_breaker_block", "bearish_breaker_block", "bullish_ifvg", "bearish_ifvg",
  "swing_high", "swing_low", "equilibrium", "liquidity_sweep", "quantnexViewSetTradePlan"]) {
  assert.ok(chartClient.includes(feature), "Chart intelligence renderer is missing: " + feature);
}
assert.match(chartClient, /api\/v1\/charts\/candles/, "Chart must use the local historical candle API");
assert.match(chartClient, /api\/v1\/quantnex-view\/analyze/, "Chart must use the QUANTNEX VIEW analysis API");
console.log("QUANTNEX VIEW checks passed: local candles, signal plan levels, structure, liquidity and OB/BB/FVG/SR overlays.");

const polish = fs.readFileSync("apps/web/workspace-polish.js", "utf8");
const polishCss = fs.readFileSync("apps/web/workspace-polish.css", "utf8");
assert.ok(html.includes('href="workspace-polish.css?v=20261113-sidebar1"'), "Professional workspace stylesheet must load");
assert.ok(html.includes('src="workspace-polish.js?v=20261113-sidebar1"'), "Professional navigation script must load");
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
