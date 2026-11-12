// Builds the board page with the fixture, opens it at 400 px in light and dark, and prints OK
// when the page matches the fixture table. Needs the pre-installed Playwright and Chromium.
const assert = require("assert");
const { execFileSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { chromium } = require("playwright");

const ROOT = path.join(__dirname, "..");
const FIXTURE = path.join(__dirname, "fixtures", "board-records.json");
const NOW = "2026-11-09T12:00:00Z";
const EXPECTED = {
  "f-starting": "running",
  "f-running-ok": "running",
  "f-running-silent": "running",
  "f-running-nocheck": "running",
  "f-waiting": "needs_you",
  "f-reviewing": "running",
  "f-pr-open": "pr_open",
  "f-done-recent": "done",
  "f-done-old": "hidden",
  "f-failed": "needs_you",
  "f-stale-quiet": "hidden",
  "f-stale-needs": "needs_you",
  "f-maint-deps": "needs_you",
  "f-legacy-needs": "needs_you",
};

async function check(browser, file, scheme) {
  const context = await browser.newContext({ viewport: { width: 400, height: 800 }, colorScheme: scheme });
  const page = await context.newPage();
  const errors = [];
  page.on("console", (msg) => { if (msg.type() === "error") errors.push(msg.text()); });
  page.on("pageerror", (err) => errors.push(String(err)));
  await page.goto("file://" + file);
  await page.waitForSelector("[data-section]");
  const label = scheme + ": ";

  assert.deepStrictEqual(errors, [], label + "console errors");
  const width = await page.evaluate(() => document.documentElement.scrollWidth);
  assert.ok(width <= 400, label + "scrollWidth " + width);

  const first = await page.evaluate(() => document.querySelector("main > section").getAttribute("data-section"));
  assert.strictEqual(first, "needs_you", label + "first section");
  assert.ok((await page.textContent("main > section h2")).startsWith("Needs you"), label + "first heading");

  const found = await page.evaluate(() =>
    Array.from(document.querySelectorAll("[data-project]")).map((n) => [
      n.getAttribute("data-project"),
      n.closest("[data-section]").getAttribute("data-section"),
    ]));
  assert.strictEqual(found.length, Object.keys(EXPECTED).length, label + "one row per project");
  for (const [project, sec] of found) assert.strictEqual(sec, EXPECTED[project], label + project + " section");

  const silent = await page.evaluate(() =>
    Array.from(document.querySelectorAll(".badge.silent")).map((n) => n.closest("[data-project]").getAttribute("data-project")));
  assert.deepStrictEqual(silent, ["f-running-silent"], label + "silent badge");
  assert.ok((await page.textContent("body")).includes("Hidden: 2"), label + "Hidden: 2");

  // Drift indicator on the chips: count only, no path.
  const drift = await page.evaluate(() =>
    Array.from(document.querySelectorAll(".chip .drift")).map((n) => n.textContent));
  assert.deepStrictEqual(drift, ["· scope ?", "· drift 3"], label + "drift indicators");
  assert.ok(!(await page.innerText("main")).includes("src/shared.py"), label + "no paths on the board");

  // The per-project detail opens on tap and shows the phases.
  await page.click('[data-project="f-running-ok"] > summary');
  assert.ok(await page.isVisible('[data-project="f-running-ok"] .detail'), label + "detail opens");
  assert.ok((await page.evaluate(() => document.documentElement.scrollWidth)) <= 400, label + "scrollWidth after open");
  await context.close();
}

(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "board-"));
  const file = path.join(dir, "board.html");
  execFileSync("python3", [path.join(ROOT, "cli/tld"), "board", "build", "--title", "tld Board",
    "--out", file, "--fixture", FIXTURE, "--now", NOW], { stdio: "pipe" });
  const browser = await chromium.launch();
  try {
    await check(browser, file, "light");
    await check(browser, file, "dark");
  } finally {
    await browser.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
  console.log("OK");
})().catch((err) => { console.error(err); process.exit(1); });
