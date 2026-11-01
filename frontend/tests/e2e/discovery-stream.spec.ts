import { expect, test } from "./public-site-fixture";

for (const viewport of [{ name: "desktop", width: 1440, height: 1000 }, { name: "mobile", width: 390, height: 844 }]) {
  test(`${viewport.name}: compact research entries and a single Discovery page with folded documentation`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto("/");
    await page.getByRole("button", { name: "Reject all", exact: true }).click();
    const explore = page.locator('section[aria-labelledby="explore-heading"]');
    await expect(explore.getByRole("link")).toHaveCount(2);
    await expect(explore.getByRole("link", { name: /Materials/ })).toHaveAttribute("href", "/materials");
    await expect(explore.getByRole("link", { name: /Discovery/ })).toHaveAttribute("href", "/discovery");
    await expect(explore.locator('a[href="/timeline"]')).toHaveCount(0);
    const entries = await explore.locator(".research-entry").all();
    if (viewport.name === "desktop") {
      const left = (await entries[0].boundingBox())!, right = (await entries[1].boundingBox())!;
      expect(left.y).toBe(right.y); expect(left.x + left.width).toBeLessThan(right.x);
      expect(Math.max(left.height, right.height)).toBeLessThan(160);
    }
    const navigations: string[] = [];
    page.on("request", request => { if (request.isNavigationRequest() && request.frame() === page.mainFrame()) navigations.push(request.url()); });
    await page.goto("/discovery");
    const main = page.locator("main.discovery-stream"), nav = page.getByRole("navigation", { name: "Discovery", exact: true });
    await expect(main.locator(":scope > section")).toHaveCount(3);
    expect(await main.locator(":scope > section").evaluateAll(nodes => nodes.map(node => node.id))).toEqual(["candidates", "data-methodology", "api-reference"]);
    await expect(main.locator('a[href="/timeline"]')).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "Candidates", exact: true })).toHaveAttribute("href", "#candidates");
    const directory = main.locator("#discovery-source-candidates");
    await expect(directory.locator("tr[data-source-candidate]")).toHaveCount(24);
    await directory.getByRole("searchbox", { name: "Find a source candidate" }).fill("Ti3Ge");
    await expect(directory.locator("tr[data-source-candidate]")).toHaveCount(1);
    const data = main.locator("#discovery-data-details"), api = main.locator("#discovery-api-details");
    expect(await data.evaluate(node => (node as HTMLDetailsElement).open)).toBe(false);
    expect(await api.evaluate(node => (node as HTMLDetailsElement).open)).toBe(false);
    await nav.getByRole("link", { name: "Data & methodology", exact: true }).click();
    await expect(page).toHaveURL(/\/discovery#data-methodology$/);
    expect(await data.evaluate(node => (node as HTMLDetailsElement).open)).toBe(false);
    const target = (await main.locator("#data-methodology").boundingBox())!, navigation = (await nav.boundingBox())!;
    expect(target.y).toBeGreaterThanOrEqual(navigation.y + navigation.height - 2);
    await data.locator(":scope > summary").click();
    await expect(data.getByRole("heading", { name: "Coverage and updates", exact: true })).toBeVisible();
    await nav.getByRole("link", { name: "API reference", exact: true }).click();
    await expect(page).toHaveURL(/\/discovery#api-reference$/);
    expect(await api.evaluate(node => (node as HTMLDetailsElement).open)).toBe(false);
    await api.locator(":scope > summary").click();
    await expect(api.getByRole("heading", { name: "Quick start", exact: true })).toBeVisible();
    const endpoint = api.locator("details").first();
    expect(await endpoint.evaluate(node => (node as HTMLDetailsElement).open)).toBe(false);
    await endpoint.locator(":scope > summary").click();
    expect(await endpoint.evaluate(node => (node as HTMLDetailsElement).open)).toBe(true);
    await nav.getByRole("link", { name: "Candidates", exact: true }).click();
    await expect(directory.getByRole("searchbox", { name: "Find a source candidate" })).toHaveValue("Ti3Ge");
    await expect(directory.locator("tr[data-source-candidate]")).toHaveCount(1);
    expect(navigations.filter(url => new URL(url).pathname === "/discovery")).toHaveLength(1);
    expect(navigations.some(url => /\/(?:docs\/|discovery\/candidates)/.test(new URL(url).pathname))).toBe(false);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
  });
}
