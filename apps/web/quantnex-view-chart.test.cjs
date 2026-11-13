const fs = require("node:fs");
const assert = require("node:assert/strict");

const html = fs.readFileSync("apps/web/index.html", "utf8");
const js = fs.readFileSync("apps/web/quantnex-view-chart.js", "utf8");
const css = fs.readFileSync("apps/web/quantnex-view-chart.css", "utf8");

for (const id of ["qxRsiChart", "qxMacdChart", "qxAdxChart", "qxRsiValue", "qxMacdValue", "qxAdxValue"]) {
  assert.ok(html.includes(`id="${id}"`), `Missing indicator panel element: ${id}`);
}
for (const token of ["function rsiSeries", "function adxSeries", "function renderIndicatorPanels", "macdSignal", "createSeries"]) {
  assert.ok(js.includes(token), `Indicator calculation/render path missing: ${token}`);
}
assert.ok(js.includes("renderIndicatorPanels();"), "Indicator panels are not refreshed with candle data.");
assert.ok(css.includes(".qx-indicator-grid"), "Responsive indicator panel styles are missing.");
console.log("QUANTNEX VIEW RSI / MACD / ADX panel checks passed.");
