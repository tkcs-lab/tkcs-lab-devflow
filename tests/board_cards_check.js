// Drives the served board page in Chromium: cards of one project are separate documents (tagged with the
// session tail for an attended command), and the open card stays the only open one after a poll.
// Usage: node board_cards_check.js BASE TOKEN PASSPHRASE
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const [base, token, passphrase] = process.argv.slice(2);
const FIXTURE = path.join(__dirname, "fixtures", "board-records-sessions.json");
const now = () => new Date().toISOString().replace(/\.\d+Z$/, "Z");

async function api(method, route, body) {
  const resp = await fetch(base + route, {
    method,
    headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await resp.json();
  assert.ok(resp.ok, method + " " + route + " answered " + resp.status + " " + JSON.stringify(data));
  return data;
}

(async () => {
  const docs = JSON.parse(fs.readFileSync(FIXTURE, "utf8"));
  for (const d of docs) {
    d.data.updated_at = now();
    await api("PUT", "/api/records/" + d.id, { data: d.data });
  }
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    const errors = [];
    page.on("console", (msg) => { if (msg.type() === "error") errors.push(msg.text()); });
    page.on("pageerror", (err) => errors.push(String(err)));

    await page.goto(base + "/?poll=500");
    await page.waitForSelector("#login:not(.hidden-view)", { timeout: 5000 });
    await page.fill("#passphrase", passphrase);
    await page.click("#login-button");
    await page.waitForSelector('[data-doc="' + docs[0].id + '"]', { timeout: 5000 });

    const tag = (id) => page.textContent('[data-doc="' + id + '"] .tag');
    assert.strictEqual((await tag(docs[0].id)).trim(), "make-plan \u00b7 efghijkl");
    assert.strictEqual((await tag(docs[1].id)).trim(), "make-plan \u00b7 xxwwvvuu");
    assert.strictEqual((await tag(docs[2].id)).trim(), "deps");
    assert.strictEqual((await tag(docs[3].id)).trim(), "make-plan");

    await page.click('[data-doc="' + docs[0].id + '"] > summary');
    assert.ok(await page.evaluate((id) => document.querySelector('[data-doc="' + id + '"]').open, docs[0].id));
    const changed = docs[0].data;
    changed.last_event = "cards-poll-check";
    await api("PUT", "/api/records/" + docs[0].id, { data: changed, if_version: 1 });
    await page.waitForFunction(() => document.body.textContent.includes("cards-poll-check"), null, { timeout: 5000 });
    const open = await page.evaluate(() => Array.from(document.querySelectorAll("details.row[open]")).map((d) => d.getAttribute("data-doc")));
    assert.deepStrictEqual(open, [docs[0].id], "only the first card is open after a poll");

    assert.deepStrictEqual(errors, [], "console errors");
    await context.close();
  } finally {
    await browser.close();
  }
  console.log("OK");
})().catch((err) => { console.error(err); process.exit(1); });
