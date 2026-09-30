import { expect, test } from "./public-site-fixture";

test("visible and hovered navigation links do not fetch destinations before a click", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const speculative: string[] = [];
  page.on("request", request => {
    if (request.headers()["next-router-prefetch"] === "1") speculative.push(request.url());
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Reject all", exact: true }).click();
  const resources = page.getByRole("navigation", { name: "Primary", exact: true })
    .getByRole("link", { name: "Resources", exact: true });
  await resources.hover();
  // Allow Next's viewport/hover prefetch scheduler to run in the production build.
  await page.waitForTimeout(1200);
  expect(speculative).toEqual([]);
  await resources.click();
  await expect(page).toHaveURL(/\/docs$/);
  await expect(page.getByRole("heading", { name: "Resources & documentation", exact: true })).toBeVisible();
});

test("scrolling search citations makes no paper requests until a result is opened", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const paperRequests: string[] = [];
  page.on("request", request => {
    if (new URL(request.url()).pathname.startsWith("/paper/")) paperRequests.push(request.url());
  });
  await page.route("https://api.jzis.org/sclib/v1/search", async route => {
    await route.fulfill({ status: 200, contentType: "application/json",
      headers: { "access-control-allow-origin": "http://127.0.0.1:3102", "access-control-allow-credentials": "true" },
      body: JSON.stringify({ total: 20, query_time_ms: 1, guest_remaining: 3, remaining: 3,
        results: Array.from({ length: 20 }, (_, i) => ({ paper_id: `synthetic:prefetch/${i}`,
          arxiv_id: null, title: `Synthetic navigation result ${i}`, authors: [], year: null,
          matched_chunk: "Synthetic navigation fixture, not a scientific record.", matched_section: null,
          relevance_score: 1, material_family: null, has_equation: false, has_table: false })) }) });
  });
  await page.goto("/search?q=synthetic-navigation-fixture");
  await page.getByRole("button", { name: "Reject all", exact: true }).click();
  const first = page.getByRole("link", { name: /^Synthetic navigation result 0 relevance/ });
  const last = page.getByRole("link", { name: /^Synthetic navigation result 19 relevance/ });
  await expect(first).toBeVisible();
  await first.hover();
  await last.scrollIntoViewIfNeeded();
  await last.hover();
  await page.waitForTimeout(1200);
  expect(paperRequests).toEqual([]);
  await first.click();
  await expect(page).toHaveURL(/\/paper\/synthetic%3Aprefetch%2F0$/);
  expect(paperRequests.length).toBeGreaterThan(0);
});
