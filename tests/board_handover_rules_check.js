// Pure-node check of the plan ready rules (rules.js) against tests/fixtures/board-records-handover.json.
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const rules = require("../src/tld/board/web/rules.js");

const NOW = Date.parse("2026-11-09T12:00:00Z");
const docs = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "board-records-handover.json"), "utf8"));
const entries = docs.map((d) => ({ id: d.id, data: d.data, version: 1 }));
const byPlan = (slug, kind) => entries.find((e) => e.data.kind === kind && (e.data.handover ? e.data.handover.plan_slug : e.data.plan_slug) === slug &&
  (kind === "run" ? e.data.project === "tkcs-lab-devflow" : true));
const where = (e, list) => rules.place(e, [], NOW, list || entries).section;

const a = byPlan("demo-plan", "command");
const i = byPlan("re-planned", "command");
const b = byPlan("issue-12", "command");
const c = byPlan("other-plan", "command");
const e8 = byPlan("old-plan", "command");
const f = entries.find((x) => x.data.kind === "command" && !x.data.handover);
const k = byPlan("same-time", "command");
const m = entries.find((x) => x.data.status === "pr_open");
const g = entries.find((x) => x.data.project === "other-project");
const h = byPlan("unrelated", "run");
for (const x of [a, i, b, c, e8, f, k, m, g, h]) assert.ok(x, "fixture record found");

assert.strictEqual(where(a), "ready");
assert.strictEqual(where(b), "ready");
assert.strictEqual(where(c), "done");
assert.strictEqual(where(e8), "hidden");
assert.strictEqual(where(f), "done");
assert.strictEqual(rules.place(Object.assign({}, a, { dismissed_at: "2026-11-09T11:00:00Z" }), [], NOW, entries).section, "hidden");
// (g) and (h) are newer than (a), but only the same project and plan slug may hide the card.
assert.ok(Date.parse(g.data.updated_at) > Date.parse(a.data.finished_at));
assert.ok(Date.parse(h.data.updated_at) > Date.parse(a.data.finished_at));
assert.strictEqual(where(a, entries), "ready");
assert.strictEqual(where(a, [a, g, h]), "ready");
assert.strictEqual(where(i), "ready", "an older failed run of the slug does not hide the card");
assert.strictEqual(where(k), "done", "a run at the finish time hides the card (>=)");
assert.strictEqual(where(m), "pr_open");
assert.strictEqual(rules.place(a, [], NOW).section, "ready", "no entries: ready");

// summaryParts
const parts = rules.summaryParts(a.data.handover.summary);
assert.deepStrictEqual(parts.map((p) => p.label), ["Use it", "Scope", "Review focus"]);
assert.ok(parts[1].text.startsWith("<img src=x"), "markup stays text");
assert.ok(parts[1].text.endsWith("see https://example.com/page"), "URL stays text");
assert.deepStrictEqual(rules.summaryParts("plain\n\n- **Label:** x\nmore"), [
  { label: null, text: "plain" }, { label: "Label", text: "x\nmore" }]);

// handoverLinks agrees with the Python rules on the shared corpus.
const corpus = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "handover-links.json"), "utf8"));
corpus.forEach((row) => {
  const rec = { repo: row.repo, handover: { plan_slug: row.plan_slug, issue_url: null, plan_url: null, spec_url: null } };
  rec.handover[row.key] = row.url;
  const kept = rules.handoverLinks(rec).length === 1;
  assert.strictEqual(kept, row.ok, row.key + " " + JSON.stringify(row.url));
});

// handoverCommand
const plan = a.data.handover.plan_url;
const cmd = (next) => rules.handoverCommand({ repo: a.data.repo, handover: Object.assign({}, a.data.handover, { next_command: next }) });
assert.strictEqual(cmd("/tld:implement " + plan), "/tld:implement " + plan);
assert.strictEqual(cmd("implement " + plan), "implement " + plan);
assert.strictEqual(cmd("/tld:implement " + plan + " x"), null);
assert.strictEqual(cmd("/tld:implement " + plan + "\n"), null);
assert.strictEqual(cmd("/tld:implement  " + plan), null);
assert.strictEqual(cmd("/tld:implement https://github.com/other/r/blob/main/p.md"), null);
assert.strictEqual(rules.handoverCommand(b.data), null);
console.log("OK");
