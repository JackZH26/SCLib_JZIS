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
