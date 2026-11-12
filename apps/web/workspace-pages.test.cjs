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
for (const asset of ["apps/web/workspace-pages.js", "apps/web/workspace-pages.css", "apps/web/realtime-events.js"]) {
  assert.ok(fs.existsSync(asset), "Missing workspace page asset: " + asset);
}
assert.ok(html.indexOf('src="realtime-events.js"') > html.indexOf('src="app.js"'), "Realtime event client must load after the main app");
console.log("Workspace page checks passed: 10 new pages, unique section IDs, valid navigation and local event client.");

assert.match(realtime, /connectedOnce&&current!==lastEventId/, "A restarted event gateway must trigger a workspace snapshot resync");
assert.match(realtime, /event_stream_restarted/, "A lower sequence after reconnect must be identified as an event-service restart");
assert.match(realtime, /lastEventId=current/, "The event cursor must reset to the new process sequence after a restart");
console.log("Realtime event restart-resync checks passed.");
