// Checks issueUrl of the board page rules; prints OK.
const assert = require("assert");
const { issueUrl } = require("../src/tld/board/web/rules.js");

const url = (repo, n) => "https://github.com/" + repo + "/issues/" + n;
assert.strictEqual(issueUrl({ repo: "o/r", tracking_issue: 1 }), url("o/r", 1));
assert.strictEqual(issueUrl({ repo: "o/r", tracking_issue: 9999999999 }), url("o/r", 9999999999));
for (const n of [true, 0, -1, 1.5, "5", 10000000000, 2 ** 53, null, undefined]) {
  assert.strictEqual(issueUrl({ repo: "o/r", tracking_issue: n }), null, "tracking_issue " + String(n));
}
assert.strictEqual(issueUrl({ repo: "o/r" }), null, "missing field");
for (const repo of ["o/r/x", "../r", "o/..", "./r", "o/r\n", "", 5, null, undefined, ["o/r"]]) {
  assert.strictEqual(issueUrl({ repo: repo, tracking_issue: 1 }), null, "repo " + JSON.stringify(repo));
}
assert.strictEqual(issueUrl(null), null);
console.log("OK");
