// Drives the served board page in Chromium for the cards that wait: an open ask hides its record's card, the answer
// moves the record to Running with "answer received", Dismiss moves a "needs you" card (and a "PR open", Running or
// Done card) to Hidden, Restore brings it back, a session rewrite after a dismissal brings it back too, and a 409
// shows the notice and keeps the card.
// Usage: node board_links_page_check.js BASE TOKEN PASSPHRASE
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

function needsRecord(base_, id) {
  const rec = JSON.parse(JSON.stringify(base_));
  rec.project = id;
  rec.repo = "example-org/" + id;
  rec.plan_slug = "plan-" + id;
  rec.plan_url = "https://example.com/example-org/" + id + "/blob/plan/docs/plan.md";
  rec.orchestrator_session = "session_" + id;
  rec.needs_you = true;
  rec.needs_you_since = now();
  rec.updated_at = now();
  return rec;
}

(async () => {
  const docs = JSON.parse(fs.readFileSync(FIXTURE, "utf8"));
  const template = docs.find((d) => d.data.project === "f-waiting").data;
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    const errors = [];
    page.on("console", (msg) => {
      // The stubbed 409 below is a failed resource the browser logs; that one is expected.
      if (msg.type() === "error" && !/409/.test(msg.text())) errors.push(msg.text());
    });
    page.on("pageerror", (err) => errors.push(String(err)));
    page.on("dialog", (d) => { errors.push("dialog: " + d.message()); d.dismiss(); });

    // R1 asks a question on the board.
    await api("PUT", "/api/records/links-one--run--plan-links-one", { data: needsRecord(template, "links-one") });
    const ask = await api("POST", "/api/asks", {
      schema: 1, kind: "ask", project: "links-one", repo: "example-org/links-one",
      title: "Pick one", created_by: "session_links-one", record: "links-one--run--plan-links-one",
      questions: [{ id: "go", text: "Run the commands?", kind: "confirm" }],
    });
    const askRow = '[data-ask="' + ask.id + '"]';

    await page.goto(base + "/?poll=500");
    await page.waitForSelector("#login:not(.hidden-view)", { timeout: 5000 });
    await page.fill("#passphrase", passphrase);
    await page.click("#login-button");
    await page.waitForSelector('[data-section="needs_you"] ' + askRow, { timeout: 5000 });
    assert.strictEqual(await page.locator('[data-doc="links-one--run--plan-links-one"]').count(), 0, "the open ask is the one card of the wait");
    assert.ok((await page.textContent("#counts")).includes("needs you 0"), "counts: " + (await page.textContent("#counts")));

    // The answer moves the record to Running with "answer received".
    await page.click(askRow);
    await page.waitForSelector("#ask-form", { timeout: 5000 });
    await page.check("#askview input[name=q0][value=yes]");
    await page.click("#ask-submit");
    await page.waitForSelector("#main:not(.hidden-view)", { timeout: 5000 });
    await page.waitForSelector('[data-section="running"] [data-doc="links-one--run--plan-links-one"]', { timeout: 5000 });
    assert.ok((await page.textContent('[data-doc="links-one--run--plan-links-one"]')).includes("answer received"), "answer received");
    assert.strictEqual(await page.locator('[data-section="needs_you"] [data-doc="links-one--run--plan-links-one"]').count(), 0);

    // R2: Dismiss, Restore, and a session rewrite.
    await api("PUT", "/api/records/links-two--run--plan-links-two", { data: needsRecord(template, "links-two") });
    const two = '[data-section="needs_you"] [data-doc="links-two--run--plan-links-two"]';
    await page.waitForSelector(two, { timeout: 5000 });
    assert.strictEqual(await page.locator('[data-doc="links-two--run--plan-links-two"] > summary [data-action="dismiss"]').count(), 0,
      "the button is not in the summary");
    await page.click(two + " > summary");
    assert.strictEqual(await page.locator(two + " .detail [data-action=\"dismiss\"]").count(), 1, "Dismiss is in the details");

    // A 409 shows the notice and keeps the card.
    await page.route("**/api/records/links-two--run--plan-links-two/dismiss", (route) =>
      route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: "version_conflict" }) }));
    await page.click(two + ' [data-action="dismiss"]');
    await page.waitForFunction(() => { const n = document.getElementById("status"); return n && n.textContent.includes("The record changed"); },
      null, { timeout: 5000 });
    await page.waitForSelector(two, { timeout: 5000 });
    await page.unroute("**/api/records/links-two--run--plan-links-two/dismiss");

    const hidden = '[data-section="hidden"] [data-doc="links-two--run--plan-links-two"]';
    await page.click(two + ' [data-action="dismiss"]');
    await page.waitForSelector(hidden, { state: "attached", timeout: 5000 });
    assert.ok((await page.textContent(hidden)).includes("dismissed"), "dismissed badge");
    assert.strictEqual(await page.locator(two).count(), 0, "gone from Needs you");
    // An opened row stays open across renders, so open each only when it is closed.
    for (const sel of ['[data-section="hidden"]', hidden]) {
      if (!(await page.evaluate((s) => document.querySelector(s).open, sel))) await page.click(sel + " > summary");
    }
    await page.click(hidden + ' [data-action="restore"]');
    await page.waitForSelector(two, { timeout: 5000 });

    await page.click(two + ' [data-action="dismiss"]');
    await page.waitForSelector(hidden, { state: "attached", timeout: 5000 });
    const rewrite = needsRecord(template, "links-two");
    await api("PUT", "/api/records/links-two--run--plan-links-two", { data: rewrite, if_version: 1 });
    await page.waitForSelector(two, { timeout: 5000 });

    // R3: Dismiss on a "PR open" card.
    const quiet = (id) => {
      const rec = needsRecord(template, id);
      rec.needs_you = false;
      rec.needs_you_reason = "";
      rec.needs_you_since = null;
      return rec;
    };
    const prRec = quiet("links-pr");
    prRec.status = "pr_open";
    prRec.finished_at = prRec.updated_at;
    prRec.pr = { number: 16, url: "https://github.com/example-org/links-pr/pull/16", state: "open", ci: "success", awaiting: "none" };
    await api("PUT", "/api/records/links-pr--run--plan-links-pr", { data: prRec });
    const prCard = '[data-section="pr_open"] [data-doc="links-pr--run--plan-links-pr"]';
    await page.waitForSelector(prCard, { timeout: 5000 });
    // Open it by its name: the summary centre holds a github.com link.
    await page.click(prCard + " > summary .name");
    await page.click(prCard + ' [data-action="dismiss"]');
    const prHidden = '[data-section="hidden"] [data-doc="links-pr--run--plan-links-pr"]';
    await page.waitForSelector(prHidden, { state: "attached", timeout: 5000 });
    assert.ok((await page.textContent(prHidden)).includes("dismissed"), "PR open card: dismissed badge");
    assert.strictEqual(await page.locator(prCard).count(), 0, "gone from PR open");
    for (const sel of ['[data-section="hidden"]', prHidden]) {
      if (!(await page.evaluate((s) => document.querySelector(s).open, sel))) await page.click(sel + " > summary");
    }
    await page.click(prHidden + ' [data-action="restore"]');
    await page.waitForSelector(prCard, { timeout: 5000 });

    // R4: every card outside Hidden has Dismiss.
    const runRec = quiet("links-run");
    runRec.status = "running";
    runRec.finished_at = null;
    runRec.pr = { number: null, url: null, state: null, ci: null, awaiting: null };
    runRec.next_check_at = new Date(Date.now() + 10 * 60 * 1000).toISOString().replace(/\.\d+Z$/, "Z");
    await api("PUT", "/api/records/links-run--run--plan-links-run", { data: runRec });
    const doneRec = quiet("links-done");
    doneRec.status = "done";
    doneRec.finished_at = doneRec.updated_at;
    doneRec.next_check_at = null;
    await api("PUT", "/api/records/links-done--run--plan-links-done", { data: doneRec });
    const doneCard = '[data-section="done"] [data-doc="links-done--run--plan-links-done"]';
    for (const card of ['[data-section="running"] [data-doc="links-one--run--plan-links-one"]', '[data-section="running"] [data-doc="links-run--run--plan-links-run"]', doneCard]) {
      await page.waitForSelector(card, { timeout: 5000 });
      if (!(await page.evaluate((s) => document.querySelector(s).open, card))) await page.click(card + " > summary .name");
      assert.strictEqual(await page.locator(card + ' .detail [data-action="dismiss"]').count(), 1, "Dismiss on " + card);
    }
    await page.click(doneCard + ' [data-action="dismiss"]');
    const doneHidden = '[data-section="hidden"] [data-doc="links-done--run--plan-links-done"]';
    await page.waitForSelector(doneHidden, { state: "attached", timeout: 5000 });
    assert.ok((await page.textContent(doneHidden)).includes("dismissed"), "Done card: dismissed badge");
    assert.strictEqual(await page.locator('[data-section="done"] > [data-doc="links-done--run--plan-links-done"]').count(), 0, "gone from Done");

    assert.deepStrictEqual(errors, [], "console errors");
    await context.close();
  } finally {
    await browser.close();
  }
  console.log("OK");
})().catch((err) => { console.error(err); process.exit(1); });
