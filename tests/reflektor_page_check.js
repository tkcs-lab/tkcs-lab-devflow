// Opens a Reflektor report page from file:// and prints one JSON line:
// {"requests": [...], "errors": [...], "text": "<first 300 characters of the body text>"}.
// Usage: node tests/reflektor_page_check.js <path to report.html>. Needs the pre-installed Playwright and Chromium.
const { chromium } = require("playwright");

(async () => {
  const file = process.argv[2];
  if (!file) {
    console.error("usage: node reflektor_page_check.js <report.html>");
    process.exit(2);
  }
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    const requests = [];
    const errors = [];
    page.on("request", (req) => { if (!req.url().startsWith("data:")) requests.push(req.url()); });
    page.on("console", (msg) => { if (msg.type() === "error") errors.push(msg.text()); });
    page.on("pageerror", (err) => errors.push(String(err)));
    await page.goto("file://" + file);
    await page.waitForTimeout(2500);
    const text = (await page.evaluate(() => document.body.innerText)).slice(0, 300);
    console.log(JSON.stringify({ requests, errors, text }));
  } finally {
    await browser.close();
  }
})().catch((err) => { console.error(err); process.exit(1); });
