// Asserts place() of src/tld/board/web/rules.js against tests/fixtures/board-links.json.
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const rules = require("../src/tld/board/web/rules.js");

const fx = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "board-links.json"), "utf8"));
const now = Date.parse(fx.now);
assert.deepStrictEqual(Object.keys(fx.expected).sort(), fx.entries.map((e) => e.id).sort());
const hidden = [];
for (const entry of fx.entries) {
  const want = fx.expected[entry.id];
  const got = rules.place(entry, fx.asks, now);
  assert.strictEqual(got.section, want.section, entry.id + " section");
  assert.strictEqual(got.badge, want.badge, entry.id + " badge");
  if (want.badge === "answer_received") {
    assert.ok(got.ask && got.ask.state === "answered", entry.id + " ask is answered");
    assert.ok(rules.linkedAsks(entry, fx.asks).includes(got.ask), entry.id + " ask is linked");
  } else {
    assert.strictEqual(got.ask, null, entry.id + " ask");
  }
  if (got.section === "hidden") hidden.push(entry.id);
}
assert.deepStrictEqual(hidden.sort(), [...fx.expected_stale].sort());
console.log("OK");
