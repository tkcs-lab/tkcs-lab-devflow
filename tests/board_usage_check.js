// Asserts the usage functions of src/tld/board/web/rules.js: bar, newest window, verdict and ages.
const assert = require("assert");
const rules = require("../src/tld/board/web/rules.js");

const NOW = 1794570000;
const DAY = 86400;

assert.deepStrictEqual(rules.usageBar(0), { fill: 0, over: false });
assert.deepStrictEqual(rules.usageBar(50), { fill: 50, over: false });
assert.deepStrictEqual(rules.usageBar(100), { fill: 100, over: false });
assert.deepStrictEqual(rules.usageBar(130), { fill: 100, over: true });

assert.strictEqual(rules.usageNow([], NOW), null);
assert.strictEqual(rules.usageNow([{ resets_at: NOW - 5 }, { resets_at: NOW }], NOW), null);
const a = { resets_at: NOW + 100 };
const b = { resets_at: NOW + 900 };
assert.strictEqual(rules.usageNow([a, b], NOW), b);
assert.strictEqual(rules.usageNow([b, { resets_at: NOW - 1 }, a], NOW), b);

assert.strictEqual(rules.usageAgo(0), "just now");
assert.strictEqual(rules.usageAgo(59), "just now");
assert.strictEqual(rules.usageAgo(60), "1 min");
assert.strictEqual(rules.usageAgo(360), "6 min");
assert.strictEqual(rules.usageAgo(3599), "59 min");
assert.strictEqual(rules.usageAgo(3600), "1 h 0 min");
assert.strictEqual(rules.usageAgo(2 * 3600 + 14 * 60 + 30), "2 h 14 min");

// A finished, busy window lived on Max; i counts back from the newest in days (fine for either range).
function win(i, peak, extra) {
  const w = { resets_at: NOW - (i + 1) * DAY / 4, complete: true, idle: false, plan: "max",
    peak_standard: peak, over: peak > 100, blocked_hours: peak > 100 ? 1.5 : null };
  return Object.assign(w, extra || {});
}
function list(count, peak, overCount) {
  const out = [];
  for (let i = 0; i < count; i++) out.push(win(i, i < overCount ? 150 : peak));
  return out;
}
const verdict = (ws, kind) => rules.usageVerdict(ws, kind, NOW);

// few: edges of the minimum
assert.deepStrictEqual(verdict(list(5, 10, 0), "five_hour"),
  { kind: "few", text: "Not enough finished windows yet (5 of 6 needed)." });
assert.notStrictEqual(verdict(list(6, 10, 0), "five_hour").kind, "few");
assert.strictEqual(verdict(list(1, 10, 0), "seven_day").text, "Not enough finished windows yet (1 of 2 needed).");
assert.strictEqual(verdict(list(1, 10, 0), "seven_day").kind, "few");
assert.notStrictEqual(verdict(list(2, 10, 0), "seven_day").kind, "few");
assert.strictEqual(verdict([], "five_hour").text, "Not enough finished windows yet (0 of 6 needed).");

// max: over / n at exactly 0.25 and above; the blocked-hours sentence
const m = verdict(list(8, 10, 2), "five_hour");
assert.deepStrictEqual(m, { kind: "max", text: "Max makes sense: Standard would have run out in 2 of 8 windows (25%)." +
  " Standard would have blocked you for at least 3.0 h in total." });
assert.strictEqual(verdict(list(4, 10, 3), "seven_day").kind, "max");
// borderline: 1 of 5 is below 0.25
const bl = verdict(list(5, 10, 1), "seven_day");
assert.strictEqual(bl.kind, "borderline");
assert.strictEqual(bl.text, "Borderline: Standard would have run out in 1 of 5 windows (20%)." +
  " Standard would have blocked you for at least 1.5 h in total.");
// blocked_hours null counts as 0
const nul = list(5, 10, 1); nul[0].blocked_hours = null;
assert.ok(verdict(nul, "seven_day").text.endsWith(" for at least 0.0 h in total."));

// standard: p90 below 80 and no window over
const st = verdict(list(10, 79.9, 0), "five_hour");
assert.deepStrictEqual(st, { kind: "standard", text: "Standard would have been enough: it stayed below its limit in all 10 windows (busiest: 80% of Standard)." });
assert.strictEqual(verdict(list(10, 80.0, 0), "five_hour").kind, "borderline");
assert.strictEqual(verdict(list(10, 80.0, 0), "five_hour").text, "Borderline: Standard would have run out in 0 of 10 windows (0%).");

// 90th percentile: index ceil(0.9 n) - 1 of the ascending peaks. n = 10 -> index 8 (second largest)
const peaks = [10, 10, 10, 10, 10, 10, 10, 10, 90, 99].map((p, i) => win(i, p));
assert.strictEqual(verdict(peaks, "five_hour").kind, "borderline");           // p90 = 90
const peaks2 = [10, 10, 10, 10, 10, 10, 10, 10, 70, 99].map((p, i) => win(i, p));
assert.strictEqual(verdict(peaks2, "five_hour").kind, "standard");            // p90 = 70, the 99 is the single top
assert.ok(verdict(peaks2, "five_hour").text.includes("busiest: 99% of Standard"));
// n = 6 -> index 5 (the largest)
const six = [10, 10, 10, 10, 10, 85].map((p, i) => win(i, p));
assert.strictEqual(verdict(six, "five_hour").kind, "borderline");

// ignored: incomplete, idle, plan standard, outside the range
const base = list(5, 10, 0);
const noisy = base.concat([
  win(10, 10, { complete: false }), win(11, 3, { idle: true }), win(12, 10, { plan: "standard" }),
  win(13, 10, { resets_at: NOW - 31 * DAY }),
]);
assert.strictEqual(verdict(noisy, "five_hour").text, "Not enough finished windows yet (5 of 6 needed).");
assert.notStrictEqual(verdict(noisy.concat([win(14, 10)]), "five_hour").kind, "few");
// range edge: 31 days old counts for the weekly kind (56) but not for five_hour (30)
const old = [win(0, 10, { resets_at: NOW - 31 * DAY }), win(1, 10, { resets_at: NOW - 40 * DAY })];
assert.strictEqual(verdict(old, "seven_day").kind, "standard");
assert.strictEqual(verdict(old, "five_hour").kind, "few");
const older = [win(0, 10, { resets_at: NOW - 57 * DAY }), win(1, 10)];
assert.strictEqual(verdict(older, "seven_day").kind, "few");
console.log("OK");
