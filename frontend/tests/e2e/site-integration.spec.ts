import { expect, test } from "./public-site-fixture";

for (const [path, heading] of [
  ["", "The superconductivity research library"], ["about", "About JZ Institute of Science"],
  ["about/join", "Join & contribute"], ["research", "Superconductivity research"],
  ["docs", "Resources & documentation"], ["docs/data", "Data & methodology"],
]) {
  test(`unified page ${path || "home"} is accessible and free of retired product content`, async ({ page }) => {
    await page.goto(path || "/");
    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
    expect(await page.locator("body").innerText()).not.toMatch(/ASRP|Agent Science Research Platform/i);
    expect(await page.locator('a[href*="asrp"], a[href*="www.jzis.org"]').count()).toBe(0);
    expect(new URL((await page.locator('link[rel="canonical"]').getAttribute("href"))!).href).toBe(`https://jzis.org/${path}`);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  });
}

test("root navigation links reach resources and the institution", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("searchbox")).toBeVisible();
  await page.getByRole("button", { name: "Open navigation" }).click();
  const menu = page.getByRole("navigation", { name: "Mobile navigation" });
  await menu.getByRole("link", { name: "Resources", exact: true }).click();
  await expect(page).toHaveURL(/\/docs$/);
  await expect(page.getByRole("button", { name: "Open navigation" })).toHaveAttribute("aria-expanded", "false");
  await page.goto("/#about");
  await expect(page).toHaveURL(/\/about$/);
});

test("legacy routes preserve query parameters, encoded IDs and private response headers", async ({ request }) => {
  for (const [path, expectedPath, status] of [
    ["/sclib/materials?page=2&family=cuprate", "/materials?page=2&family=cuprate", 308],
    ["/sclib/materials/mat%3AFe%2FSe%252B", "/materials/mat%3AFe%2FSe%252B", 308],
    ["/sclib/auth/verify?token=synthetic%2Btoken", "/verify?token=synthetic%2Btoken", 307],
    ["/sclib/auth/callback?error=oauth_failed", "/auth/callback?error=oauth_failed", 307],
    ["/sclib/api-docs", "/docs/api", 308],
  ] as const) {
    const response = await request.get(path, { maxRedirects: 0 });
    expect(response.status()).toBe(status);
    expect(new URL(response.headers().location, "http://127.0.0.1:3102").pathname + new URL(response.headers().location, "http://127.0.0.1:3102").search).toBe(expectedPath);
    if (status === 307) {
      expect(response.headers()["cache-control"]).toContain("no-store");
      expect(response.headers()["referrer-policy"]).toBe("no-referrer");
    }
  }
  expect((await request.get("/sclib/not-a-real-page")).status()).toBe(404);
});

test("authentication pages cannot be shared-cached or leak referrers", async ({ request }) => {
  const response = await request.get("/verify?token=synthetic-only");
  expect(response.headers()["cache-control"]).toContain("no-store");
  expect(response.headers()["referrer-policy"]).toBe("no-referrer");
  expect(response.headers()["x-robots-tag"]).toContain("noindex");
});

test("proxy Host determines the public redirect destination, never the loopback upstream", async ({ request }) => {
  for (const host of ["www.jzis.org", "jzis.org"]) {
    const response = await request.get("/sclib/materials?page=2", { headers: { Host: host }, maxRedirects: 0 });
    expect(response.status()).toBe(308);
    expect(response.headers().location).toBe("https://jzis.org/materials?page=2");
  }
});

test("desktop header stays on one line and the search remains in the first viewport", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const navigation = page.getByRole("navigation", { name: "Primary", exact: true });
  await expect(navigation).toBeVisible();
  expect((await page.locator("header").boundingBox())!.height).toBeLessThanOrEqual(80);
  expect((await page.getByRole("searchbox").boundingBox())!.y).toBeLessThan(600);
  await page.getByRole("button", { name: "Reject all", exact: true }).click();
  await page.screenshot({ path: "test-results/integration-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "test-results/integration-mobile.png", fullPage: true });
});

test("redesigned search has a visible label and retains the query contract", async ({ page }) => {
  const queries: string[] = [];
  // This one request receives a synthetic empty result entirely in memory.
  // The public fixture still denies every other external request.
  await page.route("https://api.jzis.org/sclib/v1/search", async route => {
    expect(route.request().method()).toBe("POST");
    queries.push(route.request().postDataJSON().query);
    await route.fulfill({ status: 200, contentType: "application/json",
      headers: { "access-control-allow-origin": "http://127.0.0.1:3102", "access-control-allow-credentials": "true" },
      body: JSON.stringify({ results: [], query_time_ms: 0 }) });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Reject all", exact: true }).click();
  await expect(page.locator('label[for]')).toContainText("Search the library");
  const input = page.getByRole("searchbox");
  await expect(input).toHaveAttribute("name", "q");
  await input.fill("FeSe + FeTe");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page).toHaveURL(/\/search\?q=FeSe%20%2B%20FeTe$/);
  await expect(page.getByRole("heading", { name: "Search", exact: true })).toBeVisible();
  await expect(page.getByRole("searchbox")).toHaveValue("FeSe + FeTe");
  await expect.poll(() => queries).toEqual(["FeSe + FeTe"]);
});

test("keyboard navigation skips the shell and restores focus after menu escape", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Reject all", exact: true }).click();
  await page.getByRole("link", { name: "Skip to content" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();
  const toggle = page.getByRole("button", { name: "Open navigation" });
  await toggle.click();
  await page.getByRole("navigation", { name: "Mobile navigation" }).getByRole("link", { name: "Resources", exact: true }).focus();
  await page.keyboard.press("Escape");
  await expect(toggle).toBeFocused();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
});

test("information-page contents reach preserved anchors without covering the heading", async ({ page }) => {
  await page.goto("about");
  await page.getByRole("button", { name: "Reject all", exact: true }).click();
  const contents = page.getByRole("navigation", { name: "On this page" });
  await contents.getByRole("link", { name: "Contact", exact: true }).click();
  await expect(page).toHaveURL(/\/about#contact$/);
  const contact = page.locator("h2#contact");
  await expect(contact).toBeInViewport();
  expect((await contact.boundingBox())!.y).toBeGreaterThanOrEqual(73);
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(page.getByRole("navigation", { name: "Primary", exact: true }).getByRole("link", { name: "About JZIS", exact: true })).toHaveAttribute("aria-current", "page");
});

test("hero asset is local, bounded and labelled as conceptual at every layout size", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Reject all", exact: true }).click();
  const artwork = page.getByRole("img", { name: /AI-generated conceptual illustration/ });
  await expect(artwork).toBeVisible();
  await expect(artwork).toHaveJSProperty("complete", true);
  expect(await artwork.evaluate(img => (img as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  for (const width of [320, 390, 768, 1024, 1280, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    const layout = await page.evaluate(() => {
      const heading = document.querySelector("h1")!;
      return { width: document.documentElement.scrollWidth,
        lines: heading.getBoundingClientRect().height / parseFloat(getComputedStyle(heading).lineHeight),
        searchBottom: document.querySelector('button[type="submit"]')!.getBoundingClientRect().bottom };
    });
    expect(layout.width).toBeLessThanOrEqual(width);
    expect(layout.lines).toBeLessThanOrEqual(2.01);
    expect(layout.searchBottom).toBeLessThan(700);
  }
  await page.emulateMedia({ reducedMotion: "reduce" });
  const arrow = page.locator(".entry-arrow").first();
  await arrow.hover();
  expect(await arrow.evaluate(el => getComputedStyle(el).transform)).toBe("none");
});

test("the preserved light theme and image budget do not depend on OS preferences", async ({ page, request }) => {
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
  await page.goto("/");
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe("light");
  expect(await page.locator("body").evaluate(el => getComputedStyle(el).backgroundColor)).toBe("rgb(240, 245, 240)");
  for (const width of [640, 1120]) {
    const response = await request.get(`/images/layered-material-concept-${width}.webp`);
    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toContain("image/webp");
    expect((await response.body()).length).toBeLessThan(100_000);
  }
});
