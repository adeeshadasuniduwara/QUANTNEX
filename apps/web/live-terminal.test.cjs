"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const html = fs.readFileSync("apps/web/index.html", "utf8");
const app = fs.readFileSync("apps/web/app.js", "utf8");
const css = fs.readFileSync("apps/web/styles.css", "utf8");
const workspace = fs.readFileSync("apps/web/workspace-pages.js", "utf8");

assert.match(html, /id="p7BookmapCanvas"/, "Bookmap must render through a canvas");
assert.match(html, /id="livePnlSymbol"/, "BTC/XAUUSD live P&L market selector is missing");
assert.match(html, /id="livePnlEntry"/, "Live P&L entry input is missing");
assert.match(html, /id="livePnlQuantity"/, "Live P&L quantity input is missing");
assert.match(html, /id="livePnlContractSize"/, "Gold broker contract-size input is missing");
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
assert.match(app, /const pnl=\(price-entry\)\*qty\*direction/, "P&L must calculate signed gross price movement");

assert.match(css, /\.p7-bookmap canvas/, "Heatmap canvas styles are missing");
assert.match(css, /\.live-pnl-grid/, "Live P&L styles are missing");
assert.match(workspace, /scrollIntoView\(\{behavior:"smooth"/, "Bot shortcut must navigate to the connection panel");

console.log("Live terminal checks passed: BTC/XAUUSD P&L, bounded 100ms depth heatmap, auto health and bot shortcut.");
