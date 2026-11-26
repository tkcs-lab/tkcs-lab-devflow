// Builds the board page with the issue-link fixture, opens it at 400 px and prints OK when each card's
// first detail link is its tracking issue and no other link changed. Needs Playwright and Chromium.
const assert = require("assert");
const { execFileSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { chromium } = require("playwright");

const ROOT = path.join(__dirname, "..");
const NOW = "2026-11-20T12:00:00Z";
const FIXTURE = path.join(__dirname, "fixtures", "board-records-issue.json");
const docs = JSON.parse(fs.readFileSync(FIXTURE, "utf8"));
const idOf = (pred) => docs.find((d) => pred(d.data)).id;
const slug = (s) => idOf((r) => r.plan_slug === s);
const CARDS = [[slug("demo-plan"), 42], [slug("issue-7"), 7], [idOf((r) => r.command === "make-plan"), 100]];
const NONE = [slug("no-issue"), slug("null-issue")];
const REPO = "https://github.com/tkcs-lab/tkcs-lab-devflow/issues/";

function build(dir, name, file) {
  const out = path.join(dir, name);
  execFileSync("python3", [path.join(ROOT, "cli/tld"), "board", "build", "--title", "tld Board", "--out", out,
    "--fixture", file, "--now", NOW], { stdio: "pipe" });
  return out;
}

(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "board-issue-"));
  const stripped = path.join(dir, "stripped.json");
  fs.writeFileSync(stripped, JSON.stringify(docs.map((d) => {
    const data = Object.assign({}, d.data);
    delete data.tracking_issue;
    return { id: d.id, data: data };
  })));
  const withIssue = build(dir, "with.html", FIXTURE);
  const without = build(dir, "without.html", stripped);
  const browser = await chromium.launch();
  const errors = [];
  const pairs = async (file, id, open) => {
    const context = await browser.newContext({ viewport: { width: 400, height: 800 } });
    const page = await context.newPage();
    page.on("console", (msg) => { if (msg.type() === "error") errors.push(msg.text()); });
    page.on("pageerror", (err) => errors.push(String(err)));
    await page.goto("file://" + file);
    await page.waitForSelector("[data-section]");
    const card = page.locator(`details.row[data-doc="${id}"]`);
    assert.strictEqual(await card.count(), 1, "one card " + id);
    if (open) await card.locator("summary").click();
    const anchors = card.locator(".detail .links a");
    const list = await anchors.evaluateAll((n) => n.map((x) => [x.textContent, x.getAttribute("href")]));
    const first = list.length ? await anchors.first().evaluate((x) => [x.target, x.rel]) : null;
    const width = await page.evaluate(() => document.documentElement.scrollWidth);
    assert.ok(width <= 400, "scrollWidth " + width);
    await context.close();
    return { list: list, first: first };
  };
  try {
    for (const [id, n] of CARDS) {
      const a = await pairs(withIssue, id, true);
      const b = await pairs(without, id, true);
      const href = REPO + n;
      assert.deepStrictEqual(a.list[0], ["issue #" + n, href], id + ": first link");
      assert.deepStrictEqual(a.first, ["_blank", "noopener noreferrer"], id + ": target and rel");
      assert.deepStrictEqual(a.list, [["issue #" + n, href]].concat(b.list), id + ": no other link changed or moved");
    }
    for (const id of NONE) {
      const a = await pairs(withIssue, id, true);
      const b = await pairs(without, id, true);
      assert.ok(!a.list.some((l) => l[0].startsWith("issue")), id + ": no issue link");
      assert.deepStrictEqual(a.list, b.list, id + ": links equal");
    }
    assert.deepStrictEqual(errors, [], "console errors");
  } finally {
    await browser.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
  console.log("OK");
})().catch((err) => { console.error(err); process.exit(1); });
