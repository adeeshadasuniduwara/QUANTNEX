const fs = require("node:fs");
const assert = require("node:assert/strict");

const html = fs.readFileSync("apps/web/index.html", "utf8");
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
for (const asset of ["apps/web/workspace-pages.js", "apps/web/workspace-pages.css"]) {
  assert.ok(fs.existsSync(asset), "Missing workspace page asset: " + asset);
}
console.log("Workspace page checks passed: 10 new pages, unique section IDs and valid sidebar targets.");
