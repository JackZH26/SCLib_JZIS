/** Local inert report QA. Input must be an owned synthetic test report, not private source data. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { chromium } = require("@playwright/test");

async function main() {
  assert.equal(process.argv.length, 4, "Supply synthetic HTML and an existing owned artifact directory");
  const input = fs.realpathSync(process.argv[2]), artifacts = fs.realpathSync(process.argv[3]);
  assert.equal(path.extname(input), ".html");
  assert.ok(fs.statSync(artifacts).isDirectory());
  assert.ok(fs.readFileSync(input, "utf8").includes("SYNTHETIC TEST ONLY"), "Synthetic input is required");
  const url = pathToFileURL(input).href, browser = await chromium.launch({ headless: true });
  const outcomes = [];
  try {
    for (const [name, viewport] of [["desktop", { width: 1440, height: 1000 }], ["mobile", { width: 390, height: 844 }]]) {
      const context = await browser.newContext({ viewport, serviceWorkers: "block" });
      const page = await context.newPage(), unexpected = [], errors = [];
      page.on("pageerror", e => errors.push(e.message));
      await page.route("**/*", route => {
        if (route.request().url() === url) return route.continue();
        unexpected.push(route.request().url());
        return route.abort();
      });
      await page.goto(url, { waitUntil: "load" });
      assert.equal(await page.locator("html").getAttribute("lang"), "en");
      assert.equal(await page.locator("script,img,iframe,object,embed,form,input,link").count(), 0);
      assert.deepEqual(await page.locator("a").evaluateAll(nodes => nodes.map(el => el.getAttribute("href"))),
        ["#summary", "#fields", "#events", "#provenance"]);
      assert.equal(await page.locator('details[id^="event-"]').count(), 60);
      assert.equal(await page.evaluate(() => window.PWNED), undefined);
      assert.ok(await page.getByText("Private documentary review — not scientific acceptance.", { exact: true }).isVisible());
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.screenshot({ path: path.join(artifacts, `${name}-overview.png`) });
      const matrix = page.getByRole("region", { name: "Priority fields: different denominators remain explicit", exact: true });
      await page.getByRole("link", { name: "Field recovery and effort", exact: true }).click();
      await matrix.scrollIntoViewIfNeeded();
      await matrix.focus();
      assert.equal(await matrix.evaluate(el => document.activeElement === el), true);
      assert.equal(await matrix.locator("tbody tr").count(), 11);
      const needsScroll = await matrix.evaluate(el => el.scrollWidth > el.clientWidth);
      if (name === "mobile") assert.ok(needsScroll);
      await page.screenshot({ path: path.join(artifacts, `${name}-field-matrix.png`) });
      if (needsScroll) {
        await matrix.evaluate(el => { el.scrollLeft = el.scrollWidth; });
        assert.ok(await matrix.evaluate(el => el.scrollLeft > 0));
      }
      const candidate = page.locator("#event-2");
      await candidate.locator(":scope > summary").click();
      await candidate.scrollIntoViewIfNeeded();
      assert.ok(await candidate.getByText("Effective outcome reason:", { exact: false }).isVisible());
      assert.ok((await candidate.innerText()).includes("window.PWNED=1"));
      const retained = candidate.locator(":scope > details").last();
      await retained.locator(":scope > summary").click();
      assert.ok(await retained.locator("pre").isVisible());
      await candidate.evaluate(el => el.scrollIntoView({ block: "start" }));
      await page.screenshot({ path: path.join(artifacts, `${name}-event-history.png`) });
      assert.equal(await page.evaluate(() => window.PWNED), undefined);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      assert.deepEqual(unexpected, []); assert.deepEqual(errors, []);
      outcomes.push({ viewport: name, selectedEvents: 60, fields: 11, externalRequests: 0, pageErrors: 0, documentOverflow: false });
      await context.close();
    }
  } finally { await browser.close(); }
  console.log(JSON.stringify({ status: "passed", scope: "synthetic_local_report_browser_QA_not_scientific_acceptance", outcomes }));
}
main().catch(() => { console.error("Synthetic pilot report browser verification failed"); process.exitCode = 1; });
