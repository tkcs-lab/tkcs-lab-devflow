// Opens the served board page with polling at 500 ms and checks that a record written through the API
// appears without a reload and that a row the reader opened stays open. Usage: node board_poll_check.js BASE TOKEN
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const [base, token] = process.argv.slice(2);
const FIXTURE = path.join(__dirname, "fixtures", "board-records.json");
const now = () => new Date().toISOString().replace(/\.\d+Z$/, "Z");

async function put(id, data, ifVersion) {
  const resp = await fetch(base + "/api/records/" + id, {
    method: "PUT",
    headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
    body: JSON.stringify(ifVersion ? { data, if_version: ifVersion } : { data }),
  });
  assert.ok(resp.ok, "PUT " + id + " answered " + resp.status);
}

(async () => {
  const docs = JSON.parse(fs.readFileSync(FIXTURE, "utf8"));
  const waiting = docs.find((d) => d.id === "f-waiting").data;
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext({ httpCredentials: { username: "x", password: token } });
    const page = await context.newPage();
    const errors = [];
    page.on("console", (msg) => { if (msg.type() === "error") errors.push(msg.text()); });
    page.on("pageerror", (err) => errors.push(String(err)));
    await page.goto(base + "/?poll=500");
    await page.waitForSelector('[data-project="f-running-ok"]', { timeout: 5000 });
    assert.strictEqual(await page.locator('[data-project="f-waiting"]').count(), 0);

    waiting.updated_at = now();
    waiting.needs_you_since = now();
    await put("f-waiting", waiting);
    await page.waitForSelector('[data-project="f-waiting"]', { timeout: 5000 });

    await page.click('[data-project="f-running-ok"] > summary');
    assert.ok(await page.isVisible('[data-project="f-running-ok"] .detail'), "row opens");

    waiting.last_event = "changed";
    await put("f-waiting", waiting, 1);
    await page.waitForFunction(() => document.body.textContent.includes("changed"), null, { timeout: 5000 });
    assert.ok(await page.isVisible('[data-project="f-running-ok"] .detail'), "row is still open after a render");

    assert.deepStrictEqual(errors, [], "console errors");
    await context.close();
  } finally {
    await browser.close();
  }
  console.log("OK");
})().catch((err) => { console.error(err); process.exit(1); });
