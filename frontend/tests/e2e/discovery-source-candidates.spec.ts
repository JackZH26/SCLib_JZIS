import { readFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { expect, test } from "./public-site-fixture";

const source = JSON.parse(readFileSync(path.join(process.cwd(), "public/research-hypotheses/source-computed-candidates-2026-10-07.json"), "utf8"));
const order = new Intl.Collator("en-US", { numeric: true, sensitivity: "base" });
const expected = [...source.candidates].sort((a, b) => order.compare(a.formula, b.formula) || order.compare(a.source_state, b.source_state));

for (const viewport of [{ name: "desktop", width: 1440, height: 1000 }, { name: "mobile", width: 390, height: 844 }]) {
  test(`${viewport.name}: real source103 directory, lazy evidence and separate research tab`, async ({ page }, info) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    // These tests use the real static research dataset. Optional legacy API requests are kept offline.
    await page.route("https://api.jzis.org/**", route => route.abort("blockedbyclient"));
    const detailRequests: string[] = [], pageErrors: string[] = [];
    page.on("request", request => { if (new URL(request.url()).pathname.startsWith("/research-hypotheses/details/")) detailRequests.push(request.url()); });
    page.on("pageerror", error => pageErrors.push(error.message));
    await page.goto("/discovery");
    await expect(page.getByRole("heading", { name: "Source-computed candidate materials" })).toBeVisible();
    await page.getByRole("button", { name: "Reject all", exact: true }).click();
    const directory = page.locator("#discovery-source-candidates");
    await expect(directory.getByRole("status")).toContainText("103 / 103 materials · Showing 1–24 · Formula A–Z");
    await expect(directory.locator("tr[data-source-candidate]")).toHaveCount(24);
    await expect(directory.locator(".discovery-source-detail-row")).toHaveCount(0);
    expect(detailRequests).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
    for (const field of await directory.locator(".discovery-source-filters input, .discovery-source-filters select").all()) {
      const box = (await field.boundingBox())!;
      expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);
    }
    const screenshotDirectory = process.env.SCLIB_DISCOVERY_SCREENSHOT_DIR || info.outputDir;
    mkdirSync(screenshotDirectory, { recursive: true });
    await page.screenshot({ path: path.join(screenshotDirectory, `${viewport.name}-default.png`) });
    const visited: string[] = [];
    for (let current = 1; current <= 5; current++) {
      await expect(directory.getByText(`Page ${current} of 5`, { exact: true })).toBeVisible();
      visited.push(...await directory.locator("tr[data-source-candidate]").evaluateAll(rows => rows.map(row => row.getAttribute("data-source-candidate")!)));
      if (current < 5) await directory.getByRole("button", { name: "Next materials" }).click();
    }
    expect(visited).toEqual(expected.map(candidate => candidate.id)); expect(new Set(visited).size).toBe(103);
    expect(detailRequests).toEqual([]);
    await directory.getByRole("searchbox", { name: "Find a source candidate" }).fill("Ti₃Ge");
    await expect(directory.locator("tr[data-source-candidate]")).toHaveCount(1);
    await directory.getByRole("button", { name: "Show details for Ti3Ge" }).click();
    await expect(directory.getByRole("heading", { name: "Source calculation and selected control" })).toBeVisible();
    await expect(directory.locator(".discovery-source-detail-row")).toHaveCount(1);
    expect(detailRequests).toHaveLength(1);
    await directory.getByRole("heading", { name: "Source calculation and selected control" }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(screenshotDirectory, viewport.name === "desktop" ? "expanded-Ti3Ge.png" : "mobile-expanded-Ti3Ge.png") });
    await directory.getByRole("button", { name: "Close details for Ti3Ge" }).click();
    await expect(directory.getByRole("button", { name: "Show details for Ti3Ge" })).toBeFocused();
    await page.getByRole("tab", { name: "Research & tools", exact: true }).click();
    await expect(page.locator("#discovery-formal-assessments")).toBeVisible();
    await expect(page.locator("#discovery-coordinate-proposals")).toBeVisible();
    await expect(page.locator("#discovery-methodology")).toBeVisible();
    await expect(directory).toBeHidden();
    await page.getByRole("tab", { name: "Candidates", exact: true }).click();
    await expect(directory.getByRole("searchbox", { name: "Find a source candidate" })).toHaveValue("Ti₃Ge");
    await directory.getByRole("button", { name: "Clear filters" }).click();
    await directory.getByRole("combobox", { name: "Composition or model concern" }).selectOption("technetium");
    const tagCount = source.candidates.filter(candidate => candidate.risk_tags.includes("technetium")).length;
    await expect(directory.getByRole("status")).toContainText(`${tagCount} / 103 materials`);
    expect(pageErrors).toEqual([]);
    console.log(`${viewport.name} real source103 screenshots: ${screenshotDirectory}`);
  });
}

test("320px: horizontally scrolled Details keeps verified source evidence in view", async ({ page }, info) => {
  await page.setViewportSize({ width: 320, height: 844 });
  await page.route("https://api.jzis.org/**", route => route.abort("blockedbyclient"));
  await page.goto("/discovery");
  await page.getByRole("button", { name: "Reject all", exact: true }).click();
  const directory = page.locator("#discovery-source-candidates");
  await expect(directory.locator("tr[data-source-candidate]")).toHaveCount(24);
  await expect(directory.locator(".discovery-source-detail-row")).toHaveCount(0);
  expect(await directory.locator("tr[data-source-candidate] button").evaluateAll(buttons =>
    buttons.every(button => button.getAttribute("aria-expanded") === "false"))).toBe(true);

  await directory.getByRole("searchbox", { name: "Find a source candidate" }).fill("Ti3Ge");
  await expect(directory.locator("tr[data-source-candidate]")).toHaveCount(1);
  const tableScroll = directory.locator(".discovery-source-table-scroll");
  expect(await tableScroll.evaluate(element => element.scrollLeft)).toBe(0);
  // Clicking the offscreen last-column button must itself scroll the real table.
  // Do not scroll the detail into view: that would hide the horizontal-scroll bug.
  await directory.getByRole("button", { name: "Show details for Ti3Ge" }).click();
  const scrolledLeft = await tableScroll.evaluate(element => element.scrollLeft);
  expect(scrolledLeft).toBeGreaterThan(0);
  const detail = directory.locator(".discovery-source-detail");
  const evidenceHeading = detail.getByRole("heading", { name: "Source calculation and selected control" });
  await expect(evidenceHeading).toBeVisible();
  await expect(directory.locator(".discovery-source-detail-row")).toHaveCount(1);
  const detailBox = (await detail.boundingBox())!;
  expect(detailBox.width).toBeGreaterThan(0);
  expect(detailBox.x).toBeGreaterThanOrEqual(0);
  expect(detailBox.x + detailBox.width).toBeLessThanOrEqual(320);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);

  // Vertical document movement leaves the table's horizontal position intact.
  await evidenceHeading.evaluate(element => window.scrollBy({ top: element.getBoundingClientRect().top - 120, behavior: "instant" }));
  await expect(evidenceHeading).toBeInViewport({ ratio: 1 });
  const sourceValues = detail.getByText("16.928 / 13.176 K · Δ +3.752 K", { exact: true });
  await expect(sourceValues).toBeVisible();
  await expect(sourceValues).toBeInViewport({ ratio: 1 });
  const evidenceBox = (await sourceValues.boundingBox())!;
  expect(evidenceBox.x).toBeGreaterThanOrEqual(0);
  expect(evidenceBox.x + evidenceBox.width).toBeLessThanOrEqual(320);
  expect(await tableScroll.evaluate(element => element.scrollLeft)).toBe(scrolledLeft);
  const folder = process.env.SCLIB_DISCOVERY_SCREENSHOT_DIR || info.outputDir;
  mkdirSync(folder, { recursive: true });
  await page.screenshot({ path: path.join(folder, "mobile-320-scrolled-Ti3Ge-evidence.png") });

  await detail.getByRole("button", { name: "Close details for Ti3Ge" }).click();
  await expect(directory.locator(".discovery-source-detail-row")).toHaveCount(0);
  await expect(directory.getByRole("button", { name: "Show details for Ti3Ge" })).toHaveAttribute("aria-expanded", "false");
  await directory.getByRole("button", { name: "Clear filters" }).click();
  await expect(directory.locator("tr[data-source-candidate]")).toHaveCount(24);
  await expect(directory.locator(".discovery-source-detail-row")).toHaveCount(0);
});

test("specific source-state phase captions retain formula and source identity", async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.route("https://api.jzis.org/**", route => route.abort("blockedbyclient"));
  await page.goto("/discovery");
  await page.getByRole("button", { name: "Reject all", exact: true }).click();
  const directory = page.locator("#discovery-source-candidates");
  for (const [state, formula, caption] of [
    ["agm002028410", "Ti", "FCC source phase"],
    ["agm001192155", "MoH", "B1 / rock-salt source phase"],
    ["agm003157370", "TiZr", "Ordered tetragonal source phase"],
  ]) {
    await directory.getByRole("searchbox", { name: "Find a source candidate" }).fill(state);
    await expect(directory.locator("tr[data-source-candidate]")).toHaveCount(1);
    const row = directory.locator(`tr[data-source-candidate="source-hypothesis:${state}"]`);
    await expect(row).toHaveAttribute("data-formula", formula);
    await expect(row.locator(".discovery-source-phase")).toHaveText(caption);
    await expect(directory.locator(".discovery-source-detail-row")).toHaveCount(0);
  }
  const folder = process.env.SCLIB_DISCOVERY_SCREENSHOT_DIR || info.outputDir;
  mkdirSync(folder, { recursive: true });
  await page.screenshot({ path: path.join(folder, "TiZr-source-phase-caption.png") });
});
