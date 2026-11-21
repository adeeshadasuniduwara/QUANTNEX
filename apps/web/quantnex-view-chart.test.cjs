const fs = require("node:fs");
const assert = require("node:assert/strict");
const html = fs.readFileSync("apps/web/index.html", "utf8");
const js = fs.readFileSync("apps/web/quantnex-view-chart.js", "utf8");
const intel = fs.readFileSync("apps/web/quantnex-view-intelligence.js", "utf8");
const css = fs.readFileSync("apps/web/quantnex-view-chart.css", "utf8");
const app = fs.readFileSync("apps/web/app.js", "utf8");
const signalTool = fs.readFileSync("apps/web/signal-tool.js", "utf8");
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
assert.match(js, /loadChartMarkets\(true\)/, "Market selector must load the live symbol universe dynamically instead of relying on a hard-coded shortlist.");
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



assert.ok(html.includes("quantnex-view-chart.js?v=20261121-compact-layout2"), "Shared chart analysis must invalidate the chart bundle cache.");

assert.match(js, /quantnex:market-tick/, "Gold chart must consume the shared market tick feed.");
assert.doesNotMatch(js, /goldTimer|scan\(\)/, "The chart must not call the removed scan function or poll full Gold history every five seconds.");

assert.match(js, /apiRequest\("\/api\/v1\/charts\/quote\?symbol=XAUUSD&interval="\+encodeURIComponent\(pick\.interval\)\)/, "Gold chart must request a timeframe-matched quote from the configured chart-history provider.");
assert.match(js, /startsWith\("QUANTNEX VIEW · "\)/, "Gold chart must reject overview ticks from a different provider.");
assert.match(js, /goldQuoteTimer=setInterval\(\(\)=>\{if\(!document\.hidden&&isChartViewActive\(\)&&selected\(\)\.symbol==="XAUUSD"\)loadGoldQuote\(\);\},30000\)/, "Gold quote polling must be scoped to the visible active chart and rate limited.");

assert.match(js, /document\.hidden\|\|!isChartViewActive\(\)\|\|selected\(\)\.symbol!=="XAUUSD"/, "Gold quote requests must stop while the browser tab is hidden.");

assert.match(js, /charts\/quote\?symbol=XAUUSD&interval=\"\+encodeURIComponent\(pick\.interval\)/, "Gold quote freshness must use the selected chart timeframe.");

assert.match(js, /recovering=reconnectAttempts>0/, "The chart must distinguish first connect from WebSocket recovery.");
assert.match(js, /if\(recovering\)loadHistory\(\)/, "A reconnect must backfill candles missed while the WebSocket was offline.");
assert.match(js, /const liveTail=candles\.filter\(c=>c\.time>=unique\.at\(-1\)\.time\)/, "REST backfill must preserve newer live candle updates.");
assert.doesNotMatch(js, /historyTimer=setInterval/, "The chart must not download 1,000 historical candles every minute while a live WebSocket is active.");
console.log("QUANTNEX chart reconnect backfill and low-polling checks passed.");


assert.ok(js.includes("wss://ws-feed.exchange.coinbase.com"), "BTC chart must have a Coinbase public WebSocket fallback.");
assert.ok(js.includes('channels:["ticker"]'), "Coinbase fallback must subscribe only to public ticker market data.");
assert.ok(js.includes("reconnectAttempts>=2"), "Coinbase fallback must activate after repeated Binance WebSocket failures.");
assert.ok(js.includes("quote.quote_only"), "Gold live quote must remain visible when historical candles are not configured.");
assert.ok(js.includes("GOLD LIVE QUOTE · HISTORICAL CANDLES REQUIRE MT5 OR TWELVE DATA"), "Gold quote-only mode must clearly disclose its historical-candle requirement.");
assert.match(js, /else\{setStatus\(candles\.length\?"GOLD FEED · MATCHING HISTORY PROVIDER":"GOLD HISTORY UNAVAILABLE · CHECK FEED SETTINGS"/, "Gold quote polling must run even when historical candles are unavailable.");

console.log('QUANTNEX BTC Coinbase failover and Gold quote-only visibility checks passed.');


for (const id of ["qxSignalLedger", "qxSignalLedgerRows", "qxSignalLedgerSummary", "qxSignalLedgerStatus", "qxSignalReplayNote", "qxSignalLedgerRefresh"]) assert.ok(html.includes(`id="${id}"`), `Missing signal lifecycle ledger element: ${id}`);
for (const tool of ["horizontal", "trend", "vertical", "rectangle", "fib"]) assert.ok(html.includes(`data-qx-draw="${tool}"`), `Missing chart drawing tool: ${tool}`);
assert.match(js, /fillText\("PRICE"/, "Chart must show a dedicated price scale.");
assert.match(js, /fillText\("TIME"/, "Chart must show a dedicated time scale.");
assert.match(js, /view\.priceZoom/, "Price scale must be interactively zoomable.");
assert.match(js, /timeLabel\(bar\.time\)/, "Crosshair must display the selected candle time on the time axis.");
assert.match(js, /function priceAxisWidth\(width\)/, "Price axis must reserve a responsive, explicit width for readable live prices.");
assert.match(js, /cx>=r\.width-priceAxisWidth\(r\.width\)/, "Mouse wheel over the full responsive price axis must zoom price independently.");
assert.match(js, /const priceLabelPlacements=\[\]/, "Trade and structure labels must avoid vertical collisions.");
assert.match(js, /ctx\.measureText\(liveText\)\.width>axisWidth-12/, "Live price text must fit within the reserved axis instead of being clipped.");
assert.match(js, /ctx\.rect\(right\+1,top,axisWidth-2,plotH\)/, "Live and crosshair price markers must be clipped to the dedicated price axis.");
assert.match(intel, /\/api\/v1\/quantnex-view\/replay/, "QUANTNEX VIEW must request a historical signal replay on chart entry.");
assert.match(intel, /\/api\/v1\/signals\/trades/, "QUANTNEX VIEW must display persisted signal outcomes.");
assert.match(intel, /MARKET \(/, "Market scalp entries must be labelled MARKET with the reference price.");
console.log("QUANTNEX VIEW signal lifecycle, TradingView-style axes and advanced drawing tools checks passed.");


assert.ok(js.includes("function drawingsStorageKey"), "Chart drawings must persist per symbol and timeframe.");
assert.ok(js.includes("restoreChartSelection") && js.includes("quantnex.chart.selection.v1"), "Chart symbol/timeframe selection must be restored on next application start.");
assert.ok(intel.includes("replayHistory(selected())"), "Selected-market historical replay must begin on application startup, not only after manually opening QUANTNEX VIEW.");
assert.ok(js.includes("saveDrawings()"), "Drawing edits and clear actions must save to local chart storage.");
assert.ok(intel.includes("MARKET (") && intel.includes("entry_type"), "Live signal table must preserve MARKET entry labels and reference prices.");

assert.match(js, /view=\{start:0,count:120/, "The chart must keep a right-side future-bar gutter in live and historical views.");
assert.match(js, /plotSlots=Math\.max\(24,view\.count\+12\)/, "Candle spacing must reserve room for future bars instead of stretching the last candle to the edge.");
assert.match(js, /Math\.min\(48,view\.count-1\)/, "Horizontal chart panning must allow a small future-space offset.");
assert.match(js, /view\.priceShift=view\.drag\.priceShift\+\(e\.clientY-view\.drag\.y\)/, "Dragging inside the plot must pan the visible price range vertically.");
assert.match(js, /right=r\.width-priceAxisWidth\(r\.width\)/, "Pointer gestures must use the same responsive price-axis boundary as drawing.");
assert.match(css, /touch-action:none/, "Touch gestures must be routed to chart pan/zoom instead of browser page scrolling.");
console.log("QUANTNEX VIEW free pan, future-bar gutter and touch gesture checks passed.");


for (const id of ["qxSignalOverallSummary", "qxSignalOverallPnl", "qxSignalRealizedPnl", "qxSignalFloatingPnl", "qxSignalWinRate", "qxSignalTotalTrades", "qxSignalPerformanceStatus", "qxSignalOverallNote"]) {
  assert.ok(html.includes(`id="${id}"`), `Missing all-market signal performance element: ${id}`);
}
assert.match(intel, /\/api\/v1\/signals\/performance/, "QUANTNEX VIEW must load the all-market overall signal P&L.");
assert.match(intel, /refreshOverallPerformance\(\)/, "Overall signal P&L must refresh with the lifecycle ledger.");
assert.match(intel, /unpriced_open_trades/, "Missing current prices must be disclosed instead of reporting a false complete P&L.");
console.log("QUANTNEX VIEW all-market overall signal P&L checks passed.");

assert.ok(html.includes('id="qxMarketType"'), "Chart must expose separate Spot/Futures market selection.");
assert.ok(html.includes('id="qxChartTicker"'), "Selected exchange-style ticker must be visible beside the chart price.");
assert.ok(js.includes("ticker.textContent=chartTicker(pair.value,marketType)"), "Visible chart ticker must update when market type or pair changes.");
assert.ok(html.includes('id="qxSymbol"'), "Chart must retain a pair selector separate from market type.");
assert.match(js, /\/api\/v1\/charts\/markets\?market_type=/, "Chart symbols must come from authoritative market-type metadata.");
assert.match(js, /marketType==="BINANCE_USDM_FUTURES"\?"\.P":""/, "USDⓈ-M perpetual tickers must display the .P suffix.");
assert.match(js, /wss:\/\/fstream\.binance\.com\/ws\//, "Futures chart must use Binance USDⓈ-M live kline streams.");
assert.match(js, /\/api\/v1\/charts\/futures\/candles/, "Futures chart history must use the separate USDⓈ-M candle endpoint.");
assert.match(js, /marketType==="BINANCE_USDM_FUTURES"/, "Futures selection must remain isolated from Spot feeds.");
assert.match(js, /quantnex\.chart\.selection\.v1/, "Market type selection must persist across reloads.");
console.log("QUANTNEX VIEW Spot/USDⓈ-M Futures market selector and .P ticker checks passed.");

assert.match(html, /Futures chart-only; signal and Order Flow engines remain Spot-only/, "UI must disclose that Futures chart support does not imply Futures signal/order-flow support.");

const intelligence = fs.readFileSync("apps/web/quantnex-view-intelligence.js", "utf8");
assert.match(intelligence, /marketType:\$\("qxMarketType"\)\?\.value\|\|"BINANCE_SPOT"/, "Intelligence selection must include the selected market type.");
assert.match(intelligence, /FUTURES CHART ONLY · FUTURES SIGNAL ENGINE NOT ENABLED/, "Futures chart must never call the Spot signal engine.");
assert.match(intelligence, /selection\.marketType!=="BINANCE_SPOT"/, "Futures historical signal replay must be explicitly disabled.");
assert.match(intelligence, /current\.marketType!==s\.marketType/, "Async signal responses must be discarded after switching market type.");
console.log("QUANTNEX VIEW Futures chart/Spot signal isolation checks passed.");

assert.match(js, /restoredChartSymbol/, "Dynamically populated chart selectors must restore a saved non-default pair after exchange metadata loads.");

// Compact QUANTNEX VIEW layout: keep Signal Results Sheet and Technical Indicators; remove duplicate Live Signal Sheet.
for (const id of ["qxSignalSettingsToggle", "qxSignalSettingsPanel",
  "qxSignalLedgerToggle", "qxSignalLedgerContent", "qxIndicatorsToggle", "qxIndicatorsContent"]) {
  assert.ok(html.includes(`id="${id}"`), `Missing compact layout control: ${id}`);
}
for (const id of ["qxSignalLedgerContent", "qxIndicatorsContent"]) {
  assert.ok(html.includes(`id="${id}" hidden`), `${id} should start collapsed to preserve chart space.`);
}
assert.ok(html.indexOf('id="qxSignalSettingsPanel"') < html.indexOf('id="qxChartHost"'),
  "Signal timeframe preferences must be housed above the chart behind its settings control.");
assert.ok(html.includes('id="qxLiveSignalsPanel"'), "The upper Current Pool Live Signals box must remain.");
assert.ok(!html.includes("LIVE SIGNAL SHEET") && !html.includes("qxChartSignalSheetContent"), "The duplicate Live Signal Sheet must be completely removed.");
assert.ok(!html.includes("Cross-Market Signal Scan") && !html.includes("qxCrossMarketSignalScan") && !html.includes("p7RunScan"), "The obsolete Cross Market Signal Scan must be completely removed.");
assert.ok(html.indexOf('id="qxLiveSignalsRows"') > html.indexOf('id="qxChartHost"') &&
  html.indexOf('id="qxLiveSignalsRows"') < html.indexOf('id="qxMarketSessions"'),
  "Live signal table must sit directly below the chart and above the Sri Lanka/New York session clocks.");
assert.ok(html.includes('class="qx-indicator-table"'), "Technical indicators must be consolidated into one table.");
assert.ok(!html.includes("qx-indicator-grid"), "The six separate indicator cards must be removed.");
assert.ok(!html.includes("live-pnl-panel") && !html.includes("livePnlSymbol"),
  "The unused Live Trade Results Calculator UI must be removed.");
assert.ok(!html.includes("qxSignalIntelligence") && !html.includes("Live Strategy Engine"),
  "The Live Strategy Engine panel must be removed from QUANTNEX VIEW.");
assert.ok(html.includes('class="position-summary-table"') && html.includes('tbody id="positionSummary"'),
  "Position tool must expose its upgraded calculation table.");
assert.ok(!app.includes("initLivePnlCalculator") && !app.includes("livePnlSymbol"),
  "The removed live PnL calculator must not keep background quote listeners.");
assert.match(signalTool, /TP1 estimated reward/);
assert.ok(html.includes('class="position-summary-table"'), "Position tool summary must render as a semantic HTML table.");
for (const toggle of ["qxSignalSettingsToggle", "qxSignalLedgerToggle", "qxIndicatorsToggle"]) {
  assert.ok(js.includes(`bindDisclosure("${toggle}"`), `Missing toggle handler for ${toggle}`);
}
assert.doesNotMatch(intel, /bindDisclosure\(/, "Disclosure handlers must have one owner to prevent double-toggle cancellation.");
assert.doesNotMatch(js, /qxChartSignalSheetToggle/, "Removed Live Signal Sheet must not retain a dead disclosure handler.");
assert.match(intel, /qxLiveSignalsRows/, "Automatic chart analysis must render into the live signals table.");
assert.doesNotMatch(intel, /qxStrategyList|qxRunBacktest|function backtest\(|function renderBacktest\(/, "Retired Live Strategy Engine UI/controller code must not remain.");
assert.match(intel, /setInterval\(\(\)=>\{if\(isTradingViewActive\(\)\)analyze\(\);\},60000\)/,
  "Live signal analysis must continue on its timer while the display panels are collapsed.");
assert.match(css, /\.qx-indicator-table/);
assert.match(css, /\.qx-live-signals-table/);
assert.match(css, /\.qx-collapsible-heading/);
console.log("QUANTNEX compact chart layout, collapsed live sheets, live signals table and position risk table checks passed.");
