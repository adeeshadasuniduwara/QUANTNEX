const assert=require("node:assert/strict");
const {toCsv}=require("./journal-export.js");
const rows=[{
  date:"2026-11-14",
  symbol:"=HYPERLINK(\"https://bad.example\",\"click\")",
  direction:"+CMD|' /C calc'!A0",
  outcome:"Win",
  pnl:-12.5,
  notes:"  @SUM(1,2) \"quoted\"\r\nsecond line"
}];
const csv=toCsv(rows);
assert.ok(csv.includes("'=HYPERLINK("),"Formula-like symbols must be forced to text.");
assert.ok(csv.includes("'+CMD|"),"Formula-like direction values must be forced to text.");
assert.ok(csv.includes("  '@SUM(1,2)"),"Leading whitespace must not bypass formula protection.");
assert.ok(csv.includes("\"\"quoted\"\"\r\nsecond line\""),"Quotes and newlines must remain correctly escaped.");
assert.ok(csv.includes(',"-12.5",'),"Legitimate negative numeric P&L must remain numeric.");
assert.throws(()=>toCsv([]),/no journal records/i);
assert.throws(()=>toCsv(null),/no journal records/i);
console.log("QUANTNEX journal CSV formula-injection tests passed.");
