// Drives the Usage page in Chromium: two readings from the usage fixture are posted (the server clock is fixed at
// 1794570000), the owner logs in and opens #usage; the page shows the title, both bars, "(limit passed)" for the
// 130% Standard bar, and no console error.
// Usage: node board_usage_page_check.js BASE TOKEN PASSPHRASE
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const [base, token, passphrase] = process.argv.slice(2);
const EVENT = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "usage-event.json"), "utf8"));

async function post(body) {
  const resp = await fetch(base + "/api/usage", {
    method: "POST",
    headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await resp.json();
  assert.ok(resp.ok, "POST /api/usage answered " + resp.status + " " + JSON.stringify(data));
}

(async () => {
  const w = EVENT.unifiedWindows;
  for (let i = 0; i < 2; i++) {
    await post({
      five_hour: { utilization: w.five_hour.utilization, resets_at: w.five_hour.resetsAt },
      seven_day: { utilization: w.seven_day.utilization, resets_at: w.seven_day.resetsAt },
      source: "final",
    });
  }
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    const errors = [];
    page.on("console", (msg) => { if (msg.type() === "error") errors.push(msg.text()); });
    page.on("pageerror", (err) => errors.push(String(err)));
    page.on("dialog", (d) => { errors.push("dialog: " + d.message()); d.dismiss(); });

    await page.goto(base + "/?poll=500");
    await page.waitForSelector("#login:not(.hidden-view)", { timeout: 5000 });
    await page.fill("#passphrase", passphrase);
    await page.click("#login-button");
    await page.waitForSelector("#usage-link:not(.hidden-view)", { timeout: 5000 });
    await page.click("#usage-link");
    await page.waitForSelector("#usageview:not(.hidden-view) .usage-card", { timeout: 5000 });

    const text = await page.textContent("#usageview");
    for (const want of ["Subscription usage", "Standard", "Max", "You are on Max (5x).", "5-hour window", "Weekly window",
      "(limit passed)", "130%", "26%", "resets in", "last reading"]) {
      assert.ok(text.includes(want), "missing " + JSON.stringify(want) + " in " + text);
    }
    // Weekly: 0.46 on Max = 230% of Standard, 46% of Max.
    assert.ok(text.includes("230%") && text.includes("46%"), "weekly bars: " + text);
    assert.strictEqual(await page.locator("#usageview .fill.over").count(), 2, "both Standard bars passed their limit");
    assert.strictEqual(await page.locator('#usageview [aria-label="Standard: 130 percent of the limit"]').count(), 1);
    assert.strictEqual(await page.locator('#usageview [aria-label="Max: 26 percent of the limit"]').count(), 1);
    assert.strictEqual(await page.isVisible("#main"), false, "the inbox is hidden");

    // Leaving the view shows the inbox again and hides the usage view.
    await page.click("#usageview a.back");
    await page.waitForSelector("#main:not(.hidden-view)", { timeout: 5000 });
    assert.strictEqual(await page.isVisible("#usageview"), false);

    assert.deepStrictEqual(errors, [], "console errors");
    await context.close();
  } finally {
    await browser.close();
  }
  console.log("OK");
})().catch((err) => { console.error(err); process.exit(1); });
