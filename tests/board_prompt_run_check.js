// Builds the board page with two single-session prompt runs (no plan link, no phases), opens it at 400 px and
// prints OK when the page shows them as it should. Needs the pre-installed Playwright and Chromium.
const assert = require("assert");
const { execFileSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { chromium } = require("playwright");

const ROOT = path.join(__dirname, "..");
const NOW = "2026-11-09T12:00:00Z";
const ID1 = "tkcs-lab-devflow--run--issue-42";
const ID2 = "tkcs-lab-devflow--run--issue-43";

(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "board-prompt-"));
  const file = path.join(dir, "board.html");
  const list = path.join(dir, "docs.json");
  const first = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "status-records", "good-run-prompt.json"), "utf8"));
  const second = Object.assign({}, first, {
    plan_slug: "issue-43", status: "running", needs_you: false, needs_you_reason: "", needs_you_since: null,
    pr: { number: null, url: null, state: null, ci: null, awaiting: null }, finished_at: null,
    updated_at: "2026-11-09T11:30:00Z", last_event: "running",
  });
  fs.writeFileSync(list, JSON.stringify([{ id: ID1, data: first }, { id: ID2, data: second }]));
  execFileSync("python3", [path.join(ROOT, "cli/tld"), "board", "build", "--title", "tld Board",
    "--out", file, "--fixture", list, "--now", NOW], { stdio: "pipe" });
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext({ viewport: { width: 400, height: 800 } });
    const page = await context.newPage();
    const errors = [];
    page.on("console", (msg) => { if (msg.type() === "error") errors.push(msg.text()); });
    page.on("pageerror", (err) => errors.push(String(err)));
    await page.goto("file://" + file);
    await page.waitForSelector("[data-section]");
    assert.deepStrictEqual(errors, [], "console errors");
    assert.ok((await page.evaluate(() => document.documentElement.scrollWidth)) <= 400, "scrollWidth");

    const a = page.locator(`[data-section="needs_you"] [data-doc="${ID1}"]`);
    assert.strictEqual(await a.count(), 1, "PR run is under Needs you");
    assert.ok((await a.locator("summary").innerText()).includes("Review PR #12"), "summary reason");
    assert.strictEqual((await a.locator(".tag").first().innerText()).trim(), "issue-42", "tag");

    const b = page.locator(`[data-section="running"] [data-doc="${ID2}"]`);
    assert.strictEqual(await b.count(), 1, "running run is under Running");
    assert.strictEqual(await b.locator(".chips").count(), 0, "no chips");
    assert.strictEqual(await b.locator(".badge.silent").count(), 0, "no silent badge");
    assert.strictEqual((await b.locator(".tag").first().innerText()).trim(), "issue-43", "second tag");
    assert.ok((await b.locator("summary").innerText()).includes("running"), "second summary");
    await b.locator("summary").click();
    assert.ok((await b.locator(".detail").innerText()).includes("No phases yet."), "second detail text");
    assert.strictEqual(await b.locator(".detail a", { hasText: /^plan$/ }).count(), 0, "second: no plan link");

    await a.locator("summary").click();
    const detail = a.locator(".detail");
    assert.ok(await detail.locator("a", { hasText: "PR #12" }).count() >= 1, "PR link");
    assert.strictEqual(await detail.locator("a", { hasText: /^plan$/ }).count(), 0, "no plan link");
    assert.ok((await detail.innerText()).includes("No phases yet."), "No phases yet.");
    assert.ok((await page.evaluate(() => document.documentElement.scrollWidth)) <= 400, "scrollWidth after open");
    await context.close();
  } finally {
    await browser.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
  console.log("OK");
})().catch((err) => { console.error(err); process.exit(1); });
