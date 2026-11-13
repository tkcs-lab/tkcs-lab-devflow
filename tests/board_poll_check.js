// Drives the served board page in Chromium: the login form (a wrong passphrase, then the right one), polling
// at 500 ms (a record written through the API appears without a reload, an opened row stays open), an ask
// posted with the session token shows in "Needs you", is answered through its form controls, the page returns to the inbox with a text-only confirmation that survives a poll,
// the answered ask opens read-only from the answered list with the back link above the card, a second ask is cancelled
// the same way, a failed send keeps the form, and logging out returns to the login form and clears the confirmation.
// Usage: node board_poll_check.js BASE TOKEN PASSPHRASE
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const [base, token, passphrase] = process.argv.slice(2);
const FIXTURE = path.join(__dirname, "fixtures", "board-records.json");
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
  const waiting = docs.find((d) => d.data.project === "f-waiting").data;
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    const errors = [];
    page.on("console", (msg) => {
      // The wrong passphrase (401) and the send to an ask closed elsewhere (409) are logged by the browser as failed
      // resources; those two are expected.
      if (msg.type() === "error" && !/status of (401|409)\b/.test(msg.text())) errors.push(msg.text());
    });
    page.on("pageerror", (err) => errors.push(String(err)));
    page.on("dialog", (d) => { errors.push("dialog: " + d.message()); d.dismiss(); });

    // Login.
    await page.goto(base + "/?poll=500");
    await page.waitForSelector("#login:not(.hidden-view)", { timeout: 5000 });
    assert.strictEqual(await page.locator('[data-project="f-running-ok"]').count(), 0, "no data before login");
    await page.fill("#passphrase", "not the passphrase at all");
    await page.click("#login-button");
    await page.waitForFunction(() => document.getElementById("login-status").textContent.includes("Wrong"), null, { timeout: 5000 });
    await page.fill("#passphrase", passphrase);
    await page.click("#login-button");
    await page.waitForSelector('[data-project="f-running-ok"]', { timeout: 5000 });
    const cookies = await context.cookies();
    assert.ok(cookies.length === 1 && cookies[0].httpOnly && cookies[0].sameSite === "Strict", "cookie flags");
    assert.strictEqual(await page.evaluate(() => document.cookie), "", "the cookie is not readable by script");

    // Polling.
    assert.strictEqual(await page.locator('[data-project="f-waiting"]').count(), 0);
    waiting.updated_at = now();
    waiting.needs_you_since = now();
    await api("PUT", "/api/records/f-waiting--run--plan-f-waiting", { data: waiting });
    await page.waitForSelector('[data-project="f-waiting"]', { timeout: 5000 });
    await page.click('[data-project="f-running-ok"] > summary');
    assert.ok(await page.isVisible('[data-project="f-running-ok"] .detail'), "row opens");
    waiting.last_event = "changed";
    await api("PUT", "/api/records/f-waiting--run--plan-f-waiting", { data: waiting, if_version: 1 });
    await page.waitForFunction(() => document.body.textContent.includes("changed"), null, { timeout: 5000 });
    assert.ok(await page.isVisible('[data-project="f-running-ok"] .detail'), "row is still open after a render");

    // An ask, posted by a session, answered by the owner.
    const ask = await api("POST", "/api/asks", {
      schema: 1, kind: "ask", project: "example-project", repo: "example/example-project",
      title: "Decide <b>two</b> items", created_by: "session_example",
      questions: [
        { id: "SEC-1", text: "<img src=x onerror=alert(1)> Fix the token leak?", kind: "choice",
          options: [{ value: "plan", label: "plan (recommended)" }, { value: "issue" }, { value: "drop" }] },
        { id: "go", text: "Run the commands?", kind: "confirm" },
        { id: "notes", text: "Anything else?", kind: "text", required: false },
      ],
    });
    const row = '[data-ask="' + ask.id + '"]';
    await page.waitForSelector('[data-section="needs_you"] ' + row, { timeout: 5000 });
    const first = await page.evaluate(() => document.querySelector('[data-section="needs_you"] .row').getAttribute("data-ask"));
    assert.strictEqual(first, ask.id, "open asks come first in Needs you");
    await page.click(row);
    await page.waitForSelector("#ask-form", { timeout: 5000 });
    assert.strictEqual(await page.locator("#askview > a.back").count(), 1);
    assert.strictEqual(await page.locator("#askview .card a.back").count(), 0);
    assert.strictEqual(await page.locator("#askview > a.back:first-child + .card").count(), 1);
    assert.strictEqual(await page.locator("#askview img").count(), 0, "question text is not HTML");
    assert.strictEqual(await page.locator("#askview b").count(), 0, "title is not HTML");
    assert.ok((await page.textContent("#askview")).includes("<img src=x onerror=alert(1)>"), "shown as text");
    assert.strictEqual(await page.locator('#askview input[type=radio][name=q0]').count(), 3, "choice: three radios");
    assert.strictEqual(await page.locator('#askview input[type=radio][name=q1]').count(), 2, "confirm: yes and no");
    assert.strictEqual(await page.locator("#askview textarea").count(), 1, "text: a textarea");

    await page.check('#askview input[name=q0][value=issue]');
    await page.check('#askview input[name=q1][value=yes]');
    await page.fill("#askview textarea", "Owner note: link the old issue.");
    await page.click("#ask-submit");
    await page.waitForSelector("#askview.hidden-view", { state: "attached", timeout: 5000 });
    await page.waitForSelector("#main:not(.hidden-view)", { timeout: 5000 });
    await page.waitForSelector('[data-section="answered"] ' + row, { state: "attached", timeout: 5000 });
    assert.strictEqual(await page.locator('[data-section="needs_you"] ' + row).count(), 0);
    await page.waitForSelector("#flash:not(.hidden-view)", { timeout: 5000 });
    assert.strictEqual(await page.textContent("#flash"), "Answers sent: Decide <b>two</b> items");
    assert.strictEqual(await page.locator("#flash b").count(), 0);
    assert.strictEqual(await page.locator("#askview #ask-form").count(), 0, "no stale form");
    assert.strictEqual(await page.getAttribute("#flash", "role"), "status");
    const stored = await api("GET", "/api/asks/" + ask.id);
    assert.strictEqual(stored.state, "answered");
    assert.deepStrictEqual(stored.answers, { "SEC-1": "issue", go: true, notes: "Owner note: link the old issue." });
    // The confirmation survives a poll.
    waiting.last_event = "after-flash";
    await api("PUT", "/api/records/f-waiting--run--plan-f-waiting", { data: waiting, if_version: 2 });
    await page.waitForFunction(() => document.body.textContent.includes("after-flash"), null, { timeout: 5000 });
    assert.strictEqual(await page.textContent("#flash"), "Answers sent: Decide <b>two</b> items");

    // The answered ask opens read-only from the answered list.
    await page.click('[data-section="answered"] > summary');
    await page.click('[data-section="answered"] ' + row);
    await page.waitForSelector('#askview [data-ask-view="' + ask.id + '"]', { timeout: 5000 });
    const shown = await page.textContent("#askview");
    assert.ok(shown.includes("Answered") && shown.includes("issue"), "read-only answers");
    assert.strictEqual(await page.locator("#askview #ask-form").count(), 0);
    assert.strictEqual(await page.locator("#askview > a.back").count(), 1);
    assert.strictEqual(await page.locator("#askview .card a.back").count(), 0);
    assert.strictEqual(await page.locator("#askview > a.back:first-child + .card").count(), 1);
    assert.ok(await page.isHidden("#flash"));
    await page.click("#askview > a.back");
    await page.waitForSelector("#main:not(.hidden-view)", { timeout: 5000 });
    assert.ok(await page.isHidden("#flash"));

    // A send to an ask closed elsewhere fails and keeps the form.
    const third = await api("POST", "/api/asks", { schema: 1, kind: "ask", project: "example-project", repo: "example/example-project", title: "Closed elsewhere", created_by: "session_example", questions: [{ id: "ok", text: "Fine?", kind: "confirm" }] });
    const trow = '[data-ask="' + third.id + '"]';
    await page.waitForSelector('[data-section="needs_you"] ' + trow, { timeout: 5000 });
    await page.click(trow);
    await page.waitForSelector("#ask-form", { timeout: 5000 });
    await api("POST", "/api/asks/" + third.id + "/cancel");
    await page.check("#askview input[name=q0][value=yes]");
    await page.click("#ask-submit");
    await page.waitForFunction(() => document.getElementById("ask-status").textContent.includes("Not sent"), null, { timeout: 5000 });
    assert.strictEqual(await page.textContent("#ask-status"), "Not sent: not_open");
    assert.strictEqual(await page.locator("#ask-form").count(), 1);
    assert.ok(await page.evaluate(() => document.getElementById("main").classList.contains("hidden-view")));
    assert.ok(await page.isHidden("#flash"));
    assert.ok((await page.evaluate(() => location.hash)).startsWith("#ask="));
    // A real server cannot fail a cancel (cancelling a cancelled ask is a 200 no-op), so fake the 409.
    await page.route("**/api/asks/" + third.id + "/cancel", (r) => r.fulfill({ status: 409, contentType: "application/json", body: '{"error":"not_open"}' }));
    await page.click("#ask-cancel");
    await page.waitForFunction(() => document.getElementById("ask-status").textContent === "Not cancelled: HTTP 409", null, { timeout: 5000 });
    assert.strictEqual(await page.locator("#ask-form").count(), 1);
    assert.ok(await page.isEnabled("#ask-cancel"));
    assert.ok(await page.evaluate(() => document.getElementById("main").classList.contains("hidden-view")));
    assert.ok(await page.isHidden("#flash"));
    await page.unroute("**/api/asks/" + third.id + "/cancel");
    await page.click("#askview > a.back");
    await page.waitForSelector("#main:not(.hidden-view)", { timeout: 5000 });

    // Cancelling an ask returns to the inbox the same way.
    const cancelAsk = await api("POST", "/api/asks", { schema: 1, kind: "ask", project: "example-project", repo: "example/example-project", title: "Cancel me", created_by: "session_example", questions: [{ id: "ok", text: "Cancel this?", kind: "confirm" }] });
    const crow = '[data-ask="' + cancelAsk.id + '"]';
    await page.waitForSelector('[data-section="needs_you"] ' + crow, { timeout: 5000 });
    await page.click(crow);
    await page.waitForSelector("#ask-cancel", { timeout: 5000 });
    await page.click("#ask-cancel");
    await page.waitForSelector("#askview.hidden-view", { state: "attached", timeout: 5000 });
    await page.waitForSelector("#main:not(.hidden-view)", { timeout: 5000 });
    await page.waitForSelector('[data-section="answered"] ' + crow, { state: "attached", timeout: 5000 });
    await page.waitForSelector("#flash:not(.hidden-view)", { timeout: 5000 });
    assert.strictEqual(await page.locator("#askview #ask-form").count(), 0);
    assert.strictEqual(await page.locator('[data-section="needs_you"] ' + crow).count(), 0);
    assert.strictEqual(await page.textContent("#flash"), "Ask cancelled: Cancel me");
    assert.strictEqual((await api("GET", "/api/asks/" + cancelAsk.id)).state, "cancelled");

    // Logout.
    await page.click("#logout");
    await page.waitForSelector("#login:not(.hidden-view)", { timeout: 5000 });
    assert.ok(await page.isHidden("#flash"));
    assert.strictEqual(await page.textContent("#flash"), "");
    const after = await page.evaluate(() => fetch("api/records").then((r) => r.status));
    assert.strictEqual(after, 401, "the session ended");

    assert.deepStrictEqual(errors, [], "console errors");
    await context.close();
  } finally {
    await browser.close();
  }
  console.log("OK");
})().catch((err) => { console.error(err); process.exit(1); });
