// Asserts section() and isSilent() of src/tld/board/web/rules.js against the 13-record fixture.
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const rules = require("../src/tld/board/web/rules.js");

const NOW = Date.parse("2026-11-09T12:00:00Z");
const EXPECTED = {
  "f-starting": ["running", false],
  "f-running-ok": ["running", false],
  "f-running-silent": ["running", true],
  "f-running-nocheck": ["running", false],
  "f-waiting": ["needs_you", false],
  "f-reviewing": ["running", false],
  "f-pr-open": ["pr_open", false],
  "f-done-recent": ["done", false],
  "f-done-old": ["hidden", false],
  "f-failed": ["needs_you", false],
  "f-stale-quiet": ["hidden", false],
  "f-stale-needs": ["needs_you", false],
  "f-maint-deps": ["needs_you", false],
};

const docs = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "board-records.json"), "utf8"));
assert.strictEqual(docs.length, 13);
for (const doc of docs) {
  const rec = doc.data;
  assert.ok(rec.project in EXPECTED, "unexpected project " + rec.project);
  const [sec, silent] = EXPECTED[rec.project];
  assert.strictEqual(rules.section(rec, NOW), sec, rec.project + " section");
  assert.strictEqual(rules.isSilent(rec, NOW), silent, rec.project + " silent");
}
assert.strictEqual(docs.filter((d) => rules.section(d.data, NOW) === "hidden").length, 2);
assert.strictEqual(rules.elapsed("2026-11-09T11:58:30Z", NOW), 1);

// Drift indicator: count only, nothing for a clean or unrecorded phase.
const okRec = docs.find((d) => d.data.project === "f-running-ok").data;
assert.deepStrictEqual(rules.drift(okRec.phases[0]), {
  text: "drift 3", title: "3 files outside touches, 1 in another phase's touches", level: "collision" });
assert.strictEqual(rules.drift(okRec.phases[1]), null);
assert.strictEqual(rules.drift({ scope: { check: "unavailable", out_of_scope_count: null } }).text, "scope ?");
assert.strictEqual(rules.drift({ scope: { check: "ok", out_of_scope_count: 0 } }), null);
assert.strictEqual(rules.drift({ scope: { check: "ok", out_of_scope_count: 1, collision_count: 0, disposition: "reverted" } }).title,
  "1 file outside touches; reverted later");
console.log("OK");
