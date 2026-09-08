import { expect, test, type Page } from "@playwright/test";
import captured from "../fixtures/scientific-review-http.json";

async function syntheticOnly(page: Page, baseURL: string) {
  const state = { denied: false, queueCalls: 0, capabilityCalls: 0, blockedExternal: [] as string[], unexpectedApi: [] as string[] };
  const origin = new URL(baseURL).origin;
  await page.context().route("**/*", async route => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) {
      state.blockedExternal.push(url.origin);
      return route.abort("blockedbyclient");
    }
    if (!url.pathname.startsWith("/__synthetic_api/")) return route.continue();
    const fulfill = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json",
      headers: { "cache-control": "private, no-store" }, body: JSON.stringify(body) });
    if (url.pathname === "/__synthetic_api/v1/auth/me") return fulfill({
      id: "00000000-0000-4000-8000-000000000001", email: "reviewer@example.invalid", email_verified: true,
      name: "Synthetic Research Reviewer", institution: null, country: null, age: null, research_area: null,
      purpose: null, bio: null, orcid: null, created_at: "2026-09-01T00:00:00Z", is_active: true,
      is_admin: false, is_reviewer: false, auth_provider: "local", avatar_url: null, scopes: [],
    });
    if (url.pathname === "/__synthetic_api/v1/ml/scientific-review/capabilities") {
      state.capabilityCalls += 1;
      return state.denied ? fulfill({ detail: "PRIVATE_ERROR_MUST_NOT_RENDER" }, 403) : fulfill(captured.capabilities);
    }
    if (url.pathname === "/__synthetic_api/v1/ml/scientific-review/results") {
      state.queueCalls += 1; return fulfill(captured.queue);
    }
    if (url.pathname === `/__synthetic_api/v1/ml/scientific-review/results/${captured.dossier.target.property_id}`) return fulfill(captured.dossier);
    state.unexpectedApi.push(url.pathname);
    return fulfill({ detail: "No synthetic fixture for this endpoint" }, 503);
  });
  return state;
}

async function assertNoOverflow(page: Page, width: number) {
  const observation = await page.evaluate(() => ({
    viewport: innerWidth,
    documentWidth: document.documentElement.scrollWidth,
    overflowing: Array.from(document.querySelectorAll<HTMLElement>("main button, main a, #scientific-evidence-detail section"))
      .filter(node => { const box = node.getBoundingClientRect(); return box.width > 0 && (box.left < -1 || box.right > innerWidth + 1); })
      .map(node => ({ element: node.tagName, text: node.textContent?.slice(0, 100), box: node.getBoundingClientRect().toJSON() })),
  }));
  expect(observation.viewport).toBe(width);
  expect(observation.overflowing).toEqual([]);
  expect(observation.documentWidth).toBeLessThanOrEqual(width);
}

for (const viewport of [{ name: "desktop", width: 1440, height: 1000 }, { name: "mobile", width: 390, height: 844 }]) {
  test(`${viewport.name}: exact evidence, bounded impact and denial clearing in an isolated real browser`, async ({ page, baseURL }, testInfo) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const state = await syntheticOnly(page, baseURL!);
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto("/dashboard/research/review");
    // Reject optional analytics; no external script or endpoint is permitted.
    const reject = page.getByRole("button", { name: /Reject optional|Reject all|Reject/i });
    if (await reject.count()) await reject.first().click();
    const select = page.getByRole("button", { name: /AlAs · phonon min frequency/ });
    await expect(select).toBeVisible();
    await select.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "Exact result · AlAs" })).toBeVisible();
    await expect(page.getByText("phonon min frequency: -0.0299792458 THz")).toBeVisible();
    await expect(page.getByText("Line 3; byte range 51–58")).toBeVisible();
    await expect(page.getByText(/Not reported \/ unresolved · not reported/)).toBeVisible();
    await expect(page.getByText(/This inspection does not approve, refresh, publish or change/)).toBeVisible();
    await assertNoOverflow(page, viewport.width);
    await page.getByRole("heading", { name: "Exact result · AlAs" }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath(`${viewport.name}-result.png`) });
    await page.getByText("phonon min frequency: -0.0299792458 THz").evaluate(node => node.scrollIntoView({ block: "center" }));
    await page.screenshot({ path: testInfo.outputPath(`${viewport.name}-quantity.png`) });
    await page.getByRole("heading", { name: "Source bindings and locators" }).evaluate(node => node.scrollIntoView({ block: "center" }));
    await page.screenshot({ path: testInfo.outputPath(`${viewport.name}-sources.png`) });
    await page.getByRole("heading", { name: "Bounded dependency relationships" }).scrollIntoViewIfNeeded();
    await page.getByText("Inspect 2 declared relationship entries").click();
    await assertNoOverflow(page, viewport.width);
    await page.screenshot({ path: testInfo.outputPath(`${viewport.name}-impact.png`) });
    state.denied = true;
    const previousQueues = state.queueCalls;
    await page.getByRole("button", { name: "Refresh access", exact: true }).click();
    await expect(page.getByRole("alert").filter({ hasText: "An active curator or reviewer research grant" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Exact result · AlAs" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Result inventory" })).toHaveCount(0);
    await expect(page.getByText(captured.dossier.descriptor_sha256)).toHaveCount(0);
    await expect(page.getByText("PRIVATE_ERROR_MUST_NOT_RENDER")).toHaveCount(0);
    expect(state.queueCalls).toBe(previousQueues);
    await assertNoOverflow(page, viewport.width);
    await page.screenshot({ path: testInfo.outputPath(`${viewport.name}-denied.png`) });
    expect(state.blockedExternal).toEqual([]);
    expect(state.unexpectedApi).toEqual([]);
    expect(errors).toEqual([]);
    console.log(`${viewport.name} screenshots: ${testInfo.outputDir}`);
  });
}
