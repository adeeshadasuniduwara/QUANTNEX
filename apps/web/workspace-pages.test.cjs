const fs = require("node:fs");
const assert = require("node:assert/strict");

const html = fs.readFileSync("apps/web/index.html", "utf8");
const sectionIds = [...html.matchAll(/<section\b[^>]*\bid="([^"]+)"/g)].map(match => match[1]);
const navTargets = [...html.matchAll(/class="nav-link[^"]*" href="#([^"]+)"/g)].map(match => match[1]);

assert.equal(new Set(sectionIds).size, sectionIds.length, "Section IDs must be unique");
const missingTargets = navTargets.filter(target => target !== "overview" && !sectionIds.includes(target));
assert.deepEqual(missingTargets, [], "Every sidebar link must point to an existing section");

const sidebar = html.match(/<aside class="sidebar">([\s\S]*?)<\/aside>/);
assert.ok(sidebar, "Sidebar shell must exist");
assert.match(sidebar[1], /<nav class="sidebar-nav" aria-label="Workspace navigation">/, "Sidebar links must live in a dedicated navigation scroll region");
assert.match(sidebar[1], /<a class="brand"/, "Brand must remain outside the scrolling navigation");
assert.match(sidebar[1], /<div class="sidebar-bottom"/, "Local workspace footer must remain outside the scrolling navigation");
const styles = fs.readFileSync("apps/web/styles.css", "utf8");
assert.match(styles, /\.sidebar \.sidebar-nav\s*\{[^}]*overflow-y:auto/s, "Sidebar navigation must scroll independently");
assert.match(styles, /\.sidebar\s*\{[^}]*overflow:hidden/s, "Sidebar shell must clip overflow so only its menu scrolls");


const requiredPages = [
  "watchlist-desk", "forex-desk", "crypto-desk", "gold-desk", "price-alerts",
  "economic-calendar", "trade-history", "strategy-library", "portfolio-monitor",
  "integrations-center"
];
for (const page of requiredPages) {
  assert.ok(sectionIds.includes(page), "Missing page section: " + page);
  assert.ok(navTargets.includes(page), "Missing sidebar link: " + page);
}
for (const asset of ["apps/web/workspace-pages.js", "apps/web/workspace-pages.css", "apps/web/realtime-events.js"]) {
  assert.ok(fs.existsSync(asset), "Missing workspace page asset: " + asset);
}
assert.ok(html.indexOf('src="realtime-events.js"') > html.indexOf('src="app.js"'), "Realtime event client must load after the main app");
console.log("Workspace page checks passed: 10 new pages, unique section IDs, valid navigation and local event client.");
