"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const html = fs.readFileSync("apps/web/index.html", "utf8");
const app = fs.readFileSync("apps/web/app.js", "utf8");
const css = fs.readFileSync("apps/web/styles.css", "utf8");
const workspace = fs.readFileSync("apps/web/workspace-pages.js", "utf8");
const signal = fs.readFileSync("apps/web/signal-tool.js", "utf8");
const updater = fs.readFileSync("apps/web/quantnex_local_server.py", "utf8");

assert.match(html, /id="p7BookmapCanvas"/, "Bookmap must render through a canvas");
assert.match(html, /id="livePnlSymbol"/, "BTC/XAUUSD live P&L market selector is missing");
assert.match(html, /id="livePnlEntry"/, "Live P&L entry input is missing");
assert.match(html, /id="livePnlQuantity"/, "Live P&L quantity input is missing");
assert.match(html, /id="livePnlContractSize"/, "Gold broker contract-size input is missing");
assert.match(html, /id="livePnlContractSizeWrap" hidden/, "Gold contract-size control must start hidden until Gold is selected");
assert.match(html, /id="integrationConnectBot"/, "Integrations must offer a bot connection shortcut");
assert.match(html, /id="telegram-bot-connect"/, "Telegram connection panel anchor is missing");
assert.doesNotMatch(html, /<\/?(?:code|pre)\b/i, "User-facing HTML must not expose code snippets");
assert.doesNotMatch(html, /id="refreshSystemHealth"/, "System health must not require a manual refresh button");

assert.match(app, /@depth20@100ms/, "Bookmap must retain the 100ms Binance depth feed");
assert.match(app, /bookHistory\.length>120/, "Bookmap history must remain bounded");
assert.match(app, /setTimeout\(drawBookmap,90\)/, "Bookmap drawing must be throttled");
assert.match(app, /setInterval\(refresh,30000\)/, "Provider quotes must refresh at the cache-aware interval");
assert.match(app, /quantnex:market-tick/, "Live market events must feed the P&L calculator");
assert.match(app, /apiRequest\("\/api\/v1\/system\/metrics"\)/, "System health must use lightweight host telemetry");
assert.match(app, /setInterval\(update,1000\)/, "System health must refresh automatically once per second");
assert.match(app, /IntersectionObserver/, "System polling must pause when the health panel is off-screen");
assert.match(app, /const pnl=\(price-entry\)\*qty\*contractSize\*direction/, "P&L must apply the selected instrument contract size");

assert.match(css, /\.p7-bookmap canvas/, "Heatmap canvas styles are missing");
assert.match(css, /\.live-pnl-grid/, "Live P&L styles are missing");
assert.match(workspace, /scrollIntoView\(\{behavior:"smooth"/, "Bot shortcut must navigate to the connection panel");

console.log("Live terminal checks passed: BTC/XAUUSD P&L, bounded 100ms depth heatmap, auto health and bot shortcut.");

assert.match(html, /QUANTNEX VIEW/, "The chart workspace must use the exact QUANTNEX VIEW name");
assert.match(html, /id="qxChartHost"/, "First-party QUANTNEX VIEW chart container is missing");
assert.match(html, /id="qxChartType"/, "Chart type selector is missing");
assert.match(html, /Heikin Ashi/, "Heikin Ashi chart option is missing");
assert.match(html, /name="autoSignalSymbol"/, "Selectable Telegram auto-signal markets are missing");
assert.match(html, /id="signalMarketSymbol"/, "Manual signal market selector is missing");
assert.doesNotMatch(html, /external-embedding\/embed-widget-advanced-chart|TradingView Advanced Chart/, "The embedded TradingView widget must be removed");
assert.match(signal, /api\/v1\/charts\/candles/, "QUANTNEX VIEW must load real local OHLC candles");
assert.match(signal, /CandlestickSeries/, "First-party candlestick rendering is missing");
assert.match(signal, /const ha=/, "Heikin Ashi candle calculation is missing");
assert.match(signal, /data-qx-draw/, "Chart drawing tools are missing");
assert.match(signal, /apiRequest\("\/api\/v1\/signals\/scan\?symbol=/, "Manual signal scan must use the selected market");
assert.match(signal, /symbols\}\)/, "Telegram auto-signal settings must save selected markets");
assert.match(app, /volume:isTrade\?Number\(data\.q\|\|0\):0/, "Live Binance trade size must feed chart volume");

console.log("QUANTNEX VIEW and crypto Telegram signal checks passed.");

assert.match(html, /id="webUpdateModal"/, "A new-version notification dialog must be present");
assert.match(html, /id="webUpdateModalVersion"/, "The update dialog must show the target version");
assert.match(html, /id="webUpdateModalChanges"/, "The update dialog must list what changed");
assert.match(html, /id="webUpdateModalInstall"/, "The update dialog must offer Download & Install Now");
assert.match(html, /id="webInstallUpdate" hidden/, "The Updates page install action must remain hidden until an update is found");
assert.match(app, /New update released:/, "The updater must announce a newly available version");
assert.match(app, /\["127\.0\.0\.1","localhost"\]\.includes\(location\.hostname\)/, "The updater must work on both supported loopback hostnames");
assert.match(app, /openUpdateModal\(result\)/, "A detected update must open the notification dialog");
assert.match(app, /modalInstallButton\?\.addEventListener\("click",\(\)=>installLatestCommit\(\)/, "The popup install action must start the update only after a click");
assert.match(app, /rememberUpdateDismissed\(sha\)/, "The user must be able to dismiss the same notification until the next version");
assert.match(app, /300000/, "The updater must periodically check for new GitHub commits while visible");
assert.doesNotMatch(app, /Starting automatic installation/, "Detecting an update must never silently install it");
assert.match(updater, /compare\/\{installed\}\.\.\.\{latest\['sha'\]\}/, "The updater must compare installed and latest GitHub commits");
assert.match(updater, /"files_changed": files_changed/, "The updater must return changed-file metadata");
assert.match(css, /\.web-update-dialog/, "The update dialog must have dedicated responsive styling");

console.log("QUANTNEX update notification and user-approved install checks passed.");

assert.ok(html.includes("cdn.jsdelivr.net/npm/lightweight-charts"), "QUANTNEX VIEW must load its chart engine from the primary CDN");
assert.ok(html.includes("unpkg.com/lightweight-charts"), "QUANTNEX VIEW must have a fallback chart-engine CDN");
assert.match(signal, /api\.binance\.com\/api\/v3\/klines/, "Crypto chart must fall back to Binance public OHLC candles");
assert.match(signal, /Binance Spot · direct fallback/, "Direct crypto fallback provider must be identified");
assert.match(signal, /SIGNAL STATUS UNAVAILABLE/, "Signal status API errors must be visible instead of leaving a stale feed status");
assert.match(signal, /Chart data unavailable/, "Chart load errors must use a chart-specific status");
assert.match(signal, /if\(!window\.LightweightCharts\)throw new Error/, "Missing chart library must be caught and shown in the chart panel");
assert.match(css, /height:clamp\(390px,58vh,620px\)/, "QUANTNEX VIEW must use a responsive chart height");
console.log("QUANTNEX VIEW CDN fallback, direct market fallback and error-state checks passed.");

assert.match(signal, /quantnex:workspace-event/, "Signal Lab must react to local workspace events");
assert.match(signal, /detail\.type==="preferences\.changed"/, "Telegram timeframe changes must refresh Signal Lab settings");
assert.match(signal, /detail\.type==="integration\.changed"/, "Telegram connect/disconnect events must refresh the Signal Lab bot status");
assert.match(signal, /quantnex:workspace-resync/, "Signal Lab must refresh provider/settings state after event-stream resync");
console.log("Signal Lab local event integration checks passed.");
