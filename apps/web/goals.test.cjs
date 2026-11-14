const assert = require("node:assert/strict");
const fs = require("node:fs");
const html = fs.readFileSync("apps/web/index.html", "utf8");
const js = fs.readFileSync("apps/web/goals.js", "utf8");
assert.match(html, /id="goalCreateForm"/, "Goals must expose the create form");
assert.match(html, /id="goalTitle"[^>]*required/, "Goal name must be required");
assert.match(html, /id="goalTarget"[^>]*required/, "Target amount must be required");
assert.match(html, /id="goalCurrency"/, "Goal currency must be selectable");
assert.ok(html.includes("Goal photo URL (optional)"), "Goal image must remain optional");
assert.match(html, /id="goalCards"/, "Goals must expose the saved-goals list");
assert.match(html, /id="goalDemoCertificate"/, "A demo certificate preview must be available without achieving a goal");
assert.match(js, /\/api\/v1\/goals\/demo-certificate/, "Demo certificate must use the dedicated sample endpoint");
assert.match(js, /Number\.isFinite\(target_amount\)/, "Goal creation must reject invalid target values before sending");
assert.match(js, /setTimeout\(\(\)=>URL\.revokeObjectURL\(url\),30000\)/, "PDF download URLs must remain available long enough for browser downloads");
console.log("QUANTNEX goals creation and demo-certificate UI checks passed.");

assert.match(html, /id="goalDemoTitle"/, "Demo certificate must have its own sample goal title field.");
assert.match(html, /id="goalDemoMessage"/, "Demo certificate must have its own achievement message field.");
const demoHandler = js.slice(js.indexOf('$("goalDemoCertificate")'), js.indexOf('$("goalGenerateCertificate")'));
assert.ok(demoHandler.includes('goalCertificateName'), "Demo preview must use the entered display name.");
assert.ok(demoHandler.includes('goalDemoTitle') && demoHandler.includes('goalDemoMessage'), "Demo preview must use its dedicated sample fields.");
assert.ok(!demoHandler.includes('goalCertificateSelect'), "Demo preview must not depend on choosing an achieved goal.");

assert.match(html, /id="goalCertificateDownload"[^>]*download[^>]*hidden/, "Certificate preview must expose a hidden-until-ready PDF download link.");
assert.match(js, /download\.href=certificatePreviewUrl/, "The download link must use the generated PDF blob, not a guessed URL.");
assert.match(js, /QUANTNEX-Demo-Certificate-NOT-VALID\.pdf/, "Demo PDF downloads must be clearly named as invalid samples.");
assert.match(js, /download\.hidden=false/, "The PDF download link must become visible only after a preview is ready.");
console.log("QUANTNEX certificate PDF download UI contract checks passed.");
