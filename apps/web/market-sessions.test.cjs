const assert = require("node:assert/strict");
const { getSnapshot, formatDuration } = require("./market-sessions.js");

function session(snapshot, id) {
  return snapshot.sessions.find((item) => item.id === id);
}

// Winter: Sri Lanka remains UTC+05:30 while New York is on EST and London on GMT.
const winter = getSnapshot(new Date("2026-11-18T15:00:00.000Z"));
assert.equal(winter.colombo.time, "20:30:00");
assert.equal(winter.newYork.time, "10:00:00");
assert.equal(winter.colombo.offset, "GMT+5:30");
assert.equal(winter.newYork.offset, "GMT-5");
assert.deepEqual(winter.active.map((item) => item.id), ["london", "new-york"]);
assert.equal(winter.overlap, true);
assert.equal(session(winter, "london").colomboHours, "13:30–22:30");
assert.equal(session(winter, "new-york").colomboHours, "18:30–03:30");

// Summer: IANA time zones automatically move London to BST and New York to EDT.
const summer = getSnapshot(new Date("2026-07-15T12:00:00.000Z"));
assert.equal(summer.newYork.time, "08:00:00");
assert.equal(summer.newYork.offset, "GMT-4");
assert.equal(summer.colombo.time, "17:30:00");
assert.deepEqual(summer.active.map((item) => item.id), ["london", "new-york"]);
assert.equal(session(summer, "london").colomboHours, "12:30–21:30");
assert.equal(session(summer, "new-york").colomboHours, "17:30–02:30");

// The US and UK DST change on different dates; the clocks must not assume matching transitions.
const march = getSnapshot(new Date("2026-03-09T13:00:00.000Z"));
assert.equal(march.newYork.time, "09:00:00");
assert.equal(march.newYork.offset, "GMT-4");
assert.equal(march.colombo.time, "18:30:00");
assert.equal(session(march, "london").colomboHours, "13:30–22:30");

// A Saturday has no active weekday FX sessions; next-open calculations skip to Monday.
const weekend = getSnapshot(new Date("2026-11-21T12:00:00.000Z"));
assert.equal(weekend.active.length, 0);
assert.equal(weekend.overlap, false);
assert.equal(session(weekend, "new-york").status, "CLOSED");
assert.equal(session(weekend, "new-york").transitionType, "open");
assert.equal(session(weekend, "new-york").transitionAt.toISOString(), "2026-11-23T13:00:00.000Z");

// An active session reports its close transition rather than another opening.
const duringNewYork = getSnapshot(new Date("2026-11-18T20:00:00.000Z"));
assert.equal(session(duringNewYork, "new-york").transitionType, "close");
assert.equal(session(duringNewYork, "new-york").transitionAt.toISOString(), "2026-11-18T22:00:00.000Z");

assert.equal(formatDuration(3661000), "1h 01m");
assert.equal(formatDuration(61000), "1m 01s");
console.log("QUANTNEX live market-session clock: timezone, DST, overlap, weekend and countdown tests passed.");


// The live clocks and session board belong beside QUANTNEX VIEW, not the Overview page.
const fs = require("node:fs");
const html = fs.readFileSync(require.resolve("./index.html"), "utf8");
const chartPanel = html.indexOf('<section class="panel chart-panel qx-chart-panel"');
const chartHost = html.indexOf('id="qxChartHost"', chartPanel);
const chartEnd = html.indexOf("</section>", chartHost);
const sessionsPanel = html.indexOf('<section class="qx-chart-sessions"');
assert.ok(chartPanel >= 0 && chartHost > chartPanel && chartEnd > chartHost);
assert.ok(sessionsPanel > chartEnd, "market sessions must render immediately after the live chart");
assert.equal(html.includes('class="qx-overview-sessions"'), false, "remove the duplicate Overview placement");
assert.ok(html.includes('id="qxColomboTime"') && html.includes('id="qxNewYorkTime"'));
console.log("QUANTNEX chart session panel placement test passed.");
