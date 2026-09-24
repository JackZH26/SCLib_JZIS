import { expect, restrictToLocalOrigin, test } from "./public-site-fixture";

test("production pages retain English, root-mounted assets and the real restrictive CSP", async ({ page }) => {
  const response = await page.goto("login");
  expect(response?.status()).toBe(200);
  const headers = response!.headers();
  expect(headers["content-security-policy"]).toContain("connect-src 'self' https://api.jzis.org");
  expect(headers["content-security-policy"]).not.toContain("'unsafe-eval'");
  expect(headers["content-security-policy"]).not.toContain("127.0.0.1");
  expect(headers["x-robots-tag"]).toBe("noindex, nofollow");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  const assets = await page.locator('script[src], link[rel="stylesheet"]').evaluateAll(nodes =>
    nodes.map(node => node.getAttribute("src") ?? node.getAttribute("href")),
  );
  expect(assets.length).toBeGreaterThan(0);
  for (const asset of assets) expect(asset).toMatch(/^\/_next\/static\//);
});

test("the browser restriction actually blocks an attempted external API request", async ({ browser, baseURL }) => {
  const context = await browser.newContext({ serviceWorkers: "block" });
  try {
    const blocked = await restrictToLocalOrigin(context, new URL(baseURL!).origin);
    const page = await context.newPage();
    await page.goto(`${baseURL}login`);
    const observed = await page.evaluate(async () => {
      const session = await fetch("https://api.jzis.org/sclib/v1/auth/me");
      const denied = [];
      for (const [url, method] of [
        ["https://api.jzis.org/sclib/v1/__synthetic_egress_probe__", "GET"],
        ["https://api.jzis.org/sclib/v1/auth/me", "POST"],
      ]) {
        try { await fetch(url, { method }); denied.push(false); }
        catch { denied.push(true); }
      }
      return { session: session.status, denied };
    });
    expect(observed).toEqual({ session: 401, denied: [true, true] });
    expect(blocked).toEqual(["https://api.jzis.org/sclib/v1/__synthetic_egress_probe__",
      "https://api.jzis.org/sclib/v1/auth/me"]);
  } finally {
    await context.close();
  }
});
