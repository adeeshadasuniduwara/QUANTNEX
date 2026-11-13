const fs = require("node:fs");
const assert = require("node:assert/strict");
const html = fs.readFileSync("apps/web/index.html", "utf8");
const js = fs.readFileSync("apps/web/quantnex-view-chart.js", "utf8");
const intel = fs.readFileSync("apps/web/quantnex-view-intelligence.js", "utf8");
const css = fs.readFileSync("apps/web/quantnex-view-chart.css", "utf8");
for (const id of ["qxRsiChart", "qxMacdChart", "qxAdxChart", "qxAtrChart", "qxStochChart", "qxCciChart", "qxRsiValue", "qxMacdValue", "qxAdxValue", "qxAtrValue", "qxStochValue", "qxCciValue", "qxConfidenceMeter", "qxConfidenceFill"]) assert.ok(html.includes(`id="${id}"`), `Missing chart element: ${id}`);
for (const token of ["function rsiSeries", "function adxSeries", "function atrSeries", "function stochSeries", "function cciSeries", "function renderIndicatorPanels", "new WebSocket", "kline_", "function pointerDown", "function wheel", "function mergeCandle", "window.quantnexViewSetAnalysis"]) assert.ok(js.includes(token), `Native chart/live path missing: ${token}`);
assert.ok(!js.includes("window.LightweightCharts"), "Chart must not depend on the TradingView Lightweight Charts runtime.");
assert.ok(!html.includes("lightweight-charts@"), "No external Lightweight Charts runtime may be loaded.");
assert.ok(!html.includes("TradingView Lightweight Charts"), "Chart footer must not credit the removed chart runtime.");
assert.ok(!fs.readFileSync("apps/web/signal-tool.js", "utf8").includes("window.LightweightCharts"), "Legacy TradingView chart controller must be removed.");
assert.ok(js.includes("quantnex:market-tick"), "Native chart must subscribe to the shared Trading Room market feed.");
assert.ok(intel.includes("Signal analysis unavailable: "), "Analysis errors must expose their actual cause in Chart Intelligence.");
assert.ok(js.includes("historyRequests=new Map()"), "History requests must be isolated by symbol/timeframe to avoid selection races.");
assert.ok(js.includes("if(historyRequests.has(key))return historyRequests.get(key)"), "Repeated history requests for one market/timeframe must be deduplicated.");
assert.ok(!js.includes("candles.length<210)throw Error"), "A valid short history must still render instead of blanking the chart.");
assert.ok(js.includes("INDICATORS WARMING UP"), "Short histories must clearly disclose indicator warm-up instead of failing chart preview.");
assert.ok(js.includes("c.high>=Math.max(c.open,c.close,c.low)"), "Malformed OHLC candles must be filtered before canvas rendering.");
assert.ok(css.includes(".qx-native-chart-canvas"), "Native chart canvas styles are missing.");
for (const symbol of ["BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT"]) assert.ok(html.includes(`value="${symbol}"`), `Missing market selector option: ${symbol}`);
console.log("QUANTNEX native canvas chart, live feed, indicators and market selector checks passed.");

assert.match(js, /Math\.min\(30000,1000\*Math\.pow\(2,/ , "Live feed reconnect must use capped exponential backoff.");
assert.match(js, /Date\.now\(\)-lastFeedMessageAt>30000/, "Stale WebSocket feeds must be detected.");
assert.match(js, /LIVE FEED STALE · RECONNECTING/, "Stale feed recovery must be visible to users.");
assert.match(js, /document\.addEventListener\("visibilitychange"/, "Live feed must recover when the workspace becomes visible again.");
console.log("QUANTNEX VIEW feed recovery checks passed.");

assert.match(js, /reconnectAttempts=0;stopFeed\(\);feedState=/, "Changing markets must reset the prior market retry backoff.");
assert.match(js, /readyState===WebSocket\.OPEN&&lastFeedMessageAt&&Date\.now\(\)-lastFeedMessageAt>30000/, "A stale open feed must be checked immediately when the workspace becomes visible.");
console.log("QUANTNEX market-switch and resume recovery checks passed.");

assert.ok(js.includes('bars.stale?" · STALE DATA":" · FRESH"'), "Chart must visibly distinguish stale market candles from fresh data.");


assert.match(js, /indicatorCacheRevision===candleRevision/, "Indicator arrays must be reused between redraws when candle data is unchanged.");
assert.match(js, /canvas\.width!==width/, "Canvas backing-store dimensions must only change when the actual size changes.");
assert.match(js, /function scheduleDraw\(\).*requestAnimationFrame/, "High-frequency market ticks must coalesce chart redraws to animation frames.");
assert.match(js, /candleRevision\+\+/, "New or updated candles must invalidate the indicator cache.");
assert.match(js, /cancelAnimationFrame\(drawFrame\)/, "Pending chart redraws must be cancelled when leaving the chart.");
console.log("QUANTNEX chart redraw performance regression checks passed.");



assert.ok(html.includes("quantnex-view-chart.js?v=20261113-analysis-dedupe1"), "Shared chart analysis must invalidate the chart bundle cache.");

assert.match(js, /quantnex:market-tick/, "Gold chart must consume the shared market tick feed.");
assert.doesNotMatch(js, /goldTimer|scan\(\)/, "The chart must not call the removed scan function or poll full Gold history every five seconds.");

assert.match(js, /apiRequest\("\/api\/v1\/charts\/quote\?symbol=XAUUSD&interval="\+encodeURIComponent\(pick\.interval\)\+""\)/, "Gold chart must request a timeframe-matched quote from the configured chart-history provider.");
assert.match(js, /startsWith\("QUANTNEX VIEW · "\)/, "Gold chart must reject overview ticks from a different provider.");
assert.match(js, /goldQuoteTimer=setInterval\(\(\)=>\{if\(!document\.hidden&&isChartViewActive\(\)&&selected\(\)\.symbol==="XAUUSD"\)loadGoldQuote\(\);\},30000\)/, "Gold quote polling must be scoped to the visible active chart and rate limited.");

assert.match(js, /document\.hidden\|\|!isChartViewActive\(\)\|\|selected\(\)\.symbol!=="XAUUSD"/, "Gold quote requests must stop while the browser tab is hidden.");

assert.match(js, /charts\/quote\?symbol=XAUUSD&interval=\"\+encodeURIComponent\(pick\.interval\)/, "Gold quote freshness must use the selected chart timeframe.");

assert.match(js, /recovering=reconnectAttempts>0/, "The chart must distinguish first connect from WebSocket recovery.");
assert.match(js, /if\(recovering\)loadHistory\(\)/, "A reconnect must backfill candles missed while the WebSocket was offline.");
assert.match(js, /const liveTail=candles\.filter\(c=>c\.time>=unique\.at\(-1\)\.time\)/, "REST backfill must preserve newer live candle updates.");
assert.doesNotMatch(js, /historyTimer=setInterval/, "The chart must not download 1,000 historical candles every minute while a live WebSocket is active.");
console.log("QUANTNEX chart reconnect backfill and low-polling checks passed.");
