const fs = require("node:fs");
const assert = require("node:assert/strict");

const html = fs.readFileSync("apps/web/index.html", "utf8");
const sidebar = html.match(/<aside class="sidebar">([\s\S]*?)<\/aside>/);
assert.ok(sidebar, "Sidebar shell must exist");
assert.match(sidebar[1], /<a class="brand"/, "Brand must remain in the sidebar");
assert.match(sidebar[1], /<nav class="sidebar-nav" aria-label="Workspace navigation">/, "Navigation links must use the dedicated scroll region");
assert.match(sidebar[1], /<div class="sidebar-bottom"/, "Local workspace status must remain in the sidebar");
const nav = sidebar[1].match(/<nav class="sidebar-nav"[\s\S]*?<\/nav>/);
assert.ok(nav, "Navigation scroll region must close correctly");
assert.ok((nav[0].match(/class="nav-link/g) || []).length >= 25, "All workspace links must remain inside the scroll region");
assert.ok(sidebar[1].indexOf('<a class="brand"') < sidebar[1].indexOf("<nav"), "Brand must stay above the scrolling region");
assert.ok(sidebar[1].indexOf("</nav>") < sidebar[1].indexOf('<div class="sidebar-bottom"'), "Footer must stay below the scrolling region");

const css = fs.readFileSync("apps/web/styles.css", "utf8");
assert.match(css, /\.sidebar\s*\{[^}]*overflow:hidden/s, "Sidebar shell must clip overflow");
assert.match(css, /\.sidebar \.sidebar-nav\s*\{[^}]*overflow-y:auto/s, "Navigation must have independent vertical scrolling");
assert.match(css, /\.sidebar \.sidebar-nav\s*\{[^}]*min-height:0/s, "Flex scroll region must allow shrinking");
console.log("Sidebar scroll regression checks passed.");
