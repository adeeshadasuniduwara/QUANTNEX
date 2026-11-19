const fs = require("node:fs");
const assert = require("node:assert/strict");
const html = fs.readFileSync("apps/web/index.html", "utf8");
const source = fs.readFileSync("apps/web/auto-refresh.js", "utf8");
const scheduled = [
  "p7RefreshPaper", "p11Refresh", "paperEngineRefresh", "paperUniverseRefresh",
  "p8ResearchRefresh", "p9Refresh", "refreshSystemBackups", "refreshSystemAudit",
  "watchlistRefresh", "forexDeskRefresh", "cryptoDeskRefresh", "goldDeskRefresh",
  "historyRefresh", "goalsRefresh", "strategyLibraryRefresh",
  "portfolioMonitorRefresh", "bnRefresh", "integrationRefresh"
];
const alreadyAutomatic = [
  "p7RefreshMarkets", "qxSignalLedgerRefresh", "calendarRefresh",
  "paperEngineMonitor", "paperEngineEventsRefresh", "pcRefresh"
];
assert.match(html, /auto-refresh\.js/);
for (const id of [...scheduled, ...alreadyAutomatic]) {
  assert.ok(html.includes('id="' + id + '"'), "missing refresh control " + id);
  assert.ok(source.includes('"' + id + '"') || source.includes(id + ":"), "refresh control is not managed: " + id);
}
assert.match(source, /button\.hidden = true/);
assert.match(source, /window\\.setInterval\\(\\(\\) => runRefresh\\(id, interval\\), interval\\)/);
console.log("Automatic refresh controller checks passed.");
