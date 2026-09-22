import { expect, test, type Page } from "@playwright/test";
import capturedMixed from "../fixtures/answer-history-http-mixed.json";
import capturedLegacy from "../fixtures/answer-history-http-legacy.json";

const historyId = capturedMixed.entry.id;

async function syntheticOnly(page: Page, baseURL: string) {
  const state = { mode: "mixed", calls: 0, readModes: [] as string[], blockedExternal: [] as string[], unexpectedApi: [] as string[] };
  const origin = new URL(baseURL).origin;
  await page.context().route("**/*", async route => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) { state.blockedExternal.push(url.origin); return route.abort("blockedbyclient"); }
    if (!url.pathname.startsWith("/__synthetic_api/")) return route.continue();
    const fulfill = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json",
      headers: { "cache-control": "private, no-store" }, body: JSON.stringify(body) });
    if (url.pathname === "/__synthetic_api/v1/auth/me") return fulfill({ id: historyId,
      email: "history-owner@example.invalid", email_verified: true, name: "Synthetic History Owner", institution: null,
      country: null, age: null, research_area: null, purpose: null, bio: null, orcid: null,
      created_at: "2026-09-01T00:00:00Z", is_active: true, is_admin: false, is_reviewer: false,
      auth_provider: "local", avatar_url: null, scopes: [] });
    if ([historyId, capturedLegacy.entry.id].some(id => url.pathname === `/__synthetic_api/v1/history/${id}`)) {
      state.calls++;
      state.readModes.push(state.mode);
      expect(route.request().method()).toBe("GET");
      expect(route.request().headers()["x-api-key"]).toBeUndefined();
      if (state.mode === "denied") return fulfill({ detail: "PRIVATE_DIAGNOSTIC_NOT_FOR_DISPLAY" }, 403);
      if (state.mode === "missing") return fulfill({ detail: "PRIVATE_DIAGNOSTIC_NOT_FOR_DISPLAY" }, 404);
      return fulfill(state.mode === "legacy" ? capturedLegacy : capturedMixed);
    }
    state.unexpectedApi.push(url.pathname); return fulfill({ detail: "No synthetic fixture" }, 503);
  });
  return state;
}

for (const viewport of [{ name: "desktop", width: 1440, height: 1000 }, { name: "mobile", width: 390, height: 844 }]) {
  test(`saved mixed receipt and legacy/private boundaries — ${viewport.name}`, async ({ page, baseURL }, testInfo) => {
    await page.setViewportSize(viewport);
    const state = await syntheticOnly(page, baseURL!);
    await page.goto(`/dashboard/history/${historyId}`);
    const rejectCookies = page.getByRole("button", { name: "Reject all", exact: true });
    if (await rejectCookies.isVisible()) await rejectCookies.click();
    await expect(page.getByRole("heading", { name: "Historical receipt integrity checked" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Structured extraction records" })).toContainText("39 K");
    await expect(page.getByRole("region", { name: "Original explanation candidates" })).toContainText("specimen U");
    await page.getByText("Recorded identity and generation pins", { exact: true }).click();
    await expect(page.getByText("Recorded activation event", { exact: true })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`receipt-${viewport.name}.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
    state.mode = "legacy"; await page.goto(`/dashboard/history/${capturedLegacy.entry.id}`);
    await expect(page.getByRole("heading", { name: "Legacy unpinned history" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Structured extraction records" })).toHaveCount(0);
    state.mode = "denied"; await page.reload();
    await expect(page.getByRole("alert", { name: "History detail unavailable" })).toContainText("Please sign in with the account that owns this history entry");
    await expect(page.getByText("PRIVATE_DIAGNOSTIC_NOT_FOR_DISPLAY")).toHaveCount(0);
    const callsBeforeRetry = state.calls;
    // Strict Mode starts two reads per mount, but an aborted read may never
    // reach the network interceptor. Each completed page must have one or two.
    for (const mode of ["mixed", "legacy", "denied"]) {
      const count = state.readModes.filter(value => value === mode).length;
      expect(count).toBeGreaterThanOrEqual(1); expect(count).toBeLessThanOrEqual(2);
    }
    expect(state.readModes).not.toContain("missing");
    state.mode = "missing"; await page.getByRole("button", { name: "Retry history read" }).click();
    await expect(page.getByRole("alert", { name: "History detail unavailable" })).toContainText("does not resolve an earlier unknown save outcome");
    // An explicit retry must issue exactly one new GET, even in Strict Mode.
    expect(state.calls).toBe(callsBeforeRetry + 1);
    expect(state.readModes.slice(callsBeforeRetry)).toEqual(["missing"]);
    expect(state.blockedExternal).toEqual([]); expect(state.unexpectedApi).toEqual([]);
  });
}
