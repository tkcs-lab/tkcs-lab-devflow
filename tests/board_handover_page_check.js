// Builds the board page with the hand-over fixture, opens it at 400 px and prints OK when the Plan ready
// section and its copy control behave as they should. Needs the pre-installed Playwright and Chromium.
const assert = require("assert");
const { execFileSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { chromium } = require("playwright");

const ROOT = path.join(__dirname, "..");
const NOW = "2026-11-09T12:00:00Z";
const docs = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "board-records-handover.json"), "utf8"));
const idOf = (pred) => docs.find((d) => pred(d.data)).id;
const A = idOf((r) => r.handover && r.handover.plan_slug === "demo-plan");
const I = idOf((r) => r.handover && r.handover.plan_slug === "re-planned");
const B = idOf((r) => r.handover && r.handover.plan_slug === "issue-12");
const C = idOf((r) => r.handover && r.handover.plan_slug === "other-plan");
const K = idOf((r) => r.handover && r.handover.plan_slug === "same-time");
const recA = docs.find((d) => d.id === A).data;
const recB = docs.find((d) => d.id === B).data;
const INSECURE = 'Object.defineProperty(window,"isSecureContext",{get:()=>false})';
const SECURE = 'Object.defineProperty(navigator,"clipboard",{value:{writeText:async t=>{window.__copied=t}}})';
const REJECT = 'Object.defineProperty(navigator,"clipboard",{value:{writeText:()=>Promise.reject(new Error("no"))}})';

(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "board-handover-"));
  const file = path.join(dir, "board.html");
  execFileSync("python3", [path.join(ROOT, "cli/tld"), "board", "build", "--title", "tld Board", "--out", file,
    "--fixture", path.join(__dirname, "fixtures", "board-records-handover.json"), "--now", NOW], { stdio: "pipe" });
  const browser = await chromium.launch();
  const open = async (init) => {
    const context = await browser.newContext({ viewport: { width: 400, height: 800 } });
    if (init) await context.addInitScript(init);
    const page = await context.newPage();
    const errors = [];
    page.on("console", (msg) => { if (msg.type() === "error") errors.push(msg.text()); });
    page.on("pageerror", (err) => errors.push(String(err)));
    await page.goto("file://" + file);
    await page.waitForSelector("[data-section]");
    return { context, page, errors };
  };
  try {
    const { context, page, errors } = await open(SECURE);
    const ready = page.locator('[data-section="ready"]');
    assert.deepStrictEqual(await ready.locator("details.row").evaluateAll((n) => n.map((x) => x.getAttribute("data-doc"))), [A, I, B], "ready cards, newest first");
    const order = await page.evaluate(() => Array.from(document.querySelectorAll("section[data-section]")).map((s) => s.getAttribute("data-section")));
    assert.ok(order.indexOf("pr_open") < order.indexOf("ready") && order.indexOf("ready") < order.indexOf("running"), "section order " + order);
    const counts = await page.locator("#counts").innerText();
    assert.ok(counts.includes("✓ plan ready 3"), counts);
    assert.strictEqual(await page.locator('[data-section="pr_open"] details.row').count(), 1, "one PR open card");
    for (const id of [C, K]) {
      assert.strictEqual(await page.locator(`[data-section="done"] [data-doc="${id}"]`).count(), 1, "under Done");
      assert.strictEqual(await ready.locator(`[data-doc="${id}"]`).count(), 0, "not under Plan ready");
    }

    const a = ready.locator(`[data-doc="${A}"]`);
    const strongs = await a.locator("summary strong").allInnerTexts();
    assert.deepStrictEqual(strongs, ["Use it:", "Scope:", "Review focus:"]);
    const links = await a.locator("summary div.links a").evaluateAll((n) => n.map((x) => [x.textContent, x.getAttribute("href")]));
    assert.deepStrictEqual(links, [["issue", recA.handover.issue_url], ["plan", recA.handover.plan_url], ["spec", recA.handover.spec_url]]);
    assert.strictEqual(await a.locator("input.cmd").inputValue(), recA.handover.next_command);
    assert.strictEqual(await a.locator("span.meta", { hasText: /^for / }).first().innerText(), "for tkcs-lab/tkcs-lab-devflow");
    assert.ok(await a.evaluate((n) => {
      const meta = Array.from(n.querySelectorAll("span.meta")).find((x) => x.textContent === "for tkcs-lab/tkcs-lab-devflow");
      return !!(meta.compareDocumentPosition(n.querySelector("input.cmd")) & Node.DOCUMENT_POSITION_FOLLOWING);
    }), "for-line comes before the input");
    assert.strictEqual(await a.locator("div.handover img").count(), 0, "no img");
    assert.strictEqual(await a.locator("div.handover a").count(), 0, "no a");
    assert.strictEqual(await page.evaluate(() => window.__xss), undefined, "no script run");
    const text = await a.locator("div.handover").innerText();
    assert.ok(text.includes("<img src=x") && text.includes("https://example.com/page"), "markup and URL are text");

    const b = ready.locator(`[data-doc="${B}"]`);
    assert.strictEqual(await b.locator("summary span.meta", { hasText: /^for / }).count(), 0, "b: no for-line");
    assert.strictEqual(await b.locator("summary div.copy").count(), 0, "b: no copy");
    assert.strictEqual(await b.locator("summary input.cmd").count(), 0, "b: no input");
    assert.deepStrictEqual(await b.locator("summary div.links a").evaluateAll((n) => n.map((x) => [x.textContent, x.getAttribute("href")])), [["issue", recB.handover.issue_url]]);

    // Copy: closed card.
    const sel = (loc) => loc.locator("input.cmd").evaluate((i) => [i.selectionStart, i.selectionEnd, i.value.length]);
    const prevented = await a.evaluate((n) => {
      const out = [];
      for (const sel of ["button[data-action=copy]", "input.cmd"]) {
        const ev = new MouseEvent("click", { bubbles: true, cancelable: true });
        n.querySelector(sel).dispatchEvent(ev);
        out.push(ev.defaultPrevented);
      }
      return out;
    });
    assert.deepStrictEqual(prevented, [true, true], "click defaultPrevented");
    await a.locator("button[data-action=copy]").click();
    await page.waitForFunction(() => window.__copied !== undefined);
    assert.strictEqual(await page.evaluate(() => window.__copied), recA.handover.next_command);
    assert.strictEqual((await a.locator("button[data-action=copy]").innerText()).trim(), "Copied");
    assert.strictEqual(await a.evaluate((n) => n.open), false, "closed after Copy");
    // Input: click, Enter, Space keep it closed and select all.
    await a.locator("input.cmd").click();
    await page.waitForTimeout(50);
    assert.strictEqual(await a.evaluate((n) => n.open), false);
    let s = await sel(a); assert.deepStrictEqual([s[0], s[1]], [0, s[2]], "click selects");
    for (const key of ["Enter", " "]) {
      await a.locator("input.cmd").evaluate((i) => i.setSelectionRange(0, 0));
      await a.locator("input.cmd").press(key);
      assert.strictEqual(await a.evaluate((n) => n.open), false, key + " keeps it closed");
      s = await sel(a); assert.deepStrictEqual([s[0], s[1]], [0, s[2]], key + " selects");
    }
    // Open card: stays open after Copy.
    await a.locator("summary .head").click();
    assert.strictEqual(await a.evaluate((n) => n.open), true, "opened by the summary");
    await a.locator("button[data-action=copy]").click();
    assert.strictEqual(await a.evaluate((n) => n.open), true, "stays open after Copy");
    assert.ok((await page.evaluate(() => document.documentElement.scrollWidth)) <= 400, "scrollWidth");
    assert.deepStrictEqual(errors, [], "console errors");
    await context.close();

    for (const [init, name] of [[INSECURE, "insecure"], [REJECT, "rejecting"]]) {
      const c = await open(init);
      const card = c.page.locator(`[data-section="ready"] [data-doc="${A}"]`);
      await card.locator("button[data-action=copy]").click();
      await c.page.waitForFunction(() => document.querySelector("button[data-action=copy]").textContent !== "Copy");
      assert.strictEqual((await card.locator("button[data-action=copy]").innerText()).trim(), "Selected: copy it", name);
      const r = await sel(card);
      assert.deepStrictEqual([r[0], r[1]], [0, r[2]], name + ": text selected");
      assert.strictEqual(await card.evaluate((n) => n.open), false, name + ": closed");
      assert.deepStrictEqual(c.errors, [], name + " console errors");
      await c.context.close();
    }
  } finally {
    await browser.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
  console.log("OK");
})().catch((err) => { console.error(err); process.exit(1); });
