import { expect, test, type Page } from "@playwright/test";
import { createHash } from "node:crypto";
import captured from "../fixtures/scientific-review-http.json";
import adjudication from "../fixtures/scientific-adjudication-http.json";
import type { AdjudicationRequest } from "../../lib/scientific-review-decision";

function canonical(value: unknown): string {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value !== null && typeof value === "object") return "{" + Object.keys(value).sort().map(key => JSON.stringify(key) + ":" + canonical((value as Record<string, unknown>)[key])).join(",") + "}";
  return JSON.stringify(value);
}
const digest = (value: unknown) => createHash("sha256").update(canonical(value)).digest("hex");

async function syntheticOnly(page: Page, baseURL: string, reviewActions = false) {
  const state = { denied: false, queueCalls: 0, capabilityCalls: 0, previewCalls: 0, commitCalls: 0, outcomeCalls: 0,
    blockedExternal: [] as string[], unexpectedApi: [] as string[] };
  const dossier = reviewActions ? adjudication.context.targets[0].dossier : captured.dossier;
  const queue = reviewActions ? { ...captured.queue, items: [{ ...dossier.target, material_id: dossier.material.id,
    formula: dossier.material.formula, property_key: dossier.result.property_key, unit: dossier.result.unit,
    knowledge_origin: dossier.event.knowledge_origin, review_status: dossier.event.review_status, validity_status: dossier.event.validity_status }] } : captured.queue;
  let prepared: { request: AdjudicationRequest; sha256: string } | null = null;
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
      id: reviewActions ? adjudication.context.actor_user_id : "00000000-0000-4000-8000-000000000001", email: "reviewer@example.invalid", email_verified: true,
      name: "Synthetic Research Reviewer", institution: null, country: null, age: null, research_area: null,
      purpose: null, bio: null, orcid: null, created_at: "2026-09-01T00:00:00Z", is_active: true,
      is_admin: false, is_reviewer: false, auth_provider: "local", avatar_url: null, scopes: [],
    });
    if (url.pathname === "/__synthetic_api/v1/ml/scientific-review/capabilities") {
      state.capabilityCalls += 1;
      return state.denied ? fulfill({ detail: "PRIVATE_ERROR_MUST_NOT_RENDER" }, 403) : fulfill(captured.capabilities);
    }
    if (url.pathname === "/__synthetic_api/v1/ml/scientific-review/results") {
      state.queueCalls += 1; return fulfill(queue);
    }
    if (url.pathname === `/__synthetic_api/v1/ml/scientific-review/results/${dossier.target.property_id}`) return fulfill(dossier);
    const prefix = "/__synthetic_api/v1/ml/scientific-review/adjudication/";
    if (reviewActions && url.pathname === prefix + "context") return fulfill(adjudication.context);
    if (reviewActions && url.pathname === prefix + "preview") {
      state.previewCalls += 1;
      const request = route.request().postDataJSON() as AdjudicationRequest;
      const requestSha256 = digest(request);
      const previewSha256 = digest({ version: adjudication.preview.version, request_sha256: requestSha256,
        actor_user_id: adjudication.context.actor_user_id, actor_grant_id: adjudication.context.actor_grant_id });
      prepared = { request, sha256: previewSha256 };
      // Only the browser-generated IDs/rationale change; this transport is explicitly synthetic.
      return fulfill({ ...adjudication.preview, request_key: request.request_key, request_sha256: requestSha256,
        preview_sha256: previewSha256, items: request.items.map(item => ({ decision_id: item.decision_id,
          subject_id: item.subject_id, property_id: item.property_id, scope: item.scope, profile_version: item.profile_version,
          decision: item.decision, subject_sha256: item.expected_subject_sha256,
          expected_previous_decision_id: item.expected_previous_decision_id, impact_sha256: item.expected_impact_sha256 })) });
    }
    if (reviewActions && url.pathname === prefix + "commit") {
      state.commitCalls += 1;
      const body = route.request().postDataJSON();
      expect(body).toEqual({ request: prepared!.request, expected_preview_sha256: prepared!.sha256 });
      return fulfill({ detail: "SYNTHETIC_COMMIT_OUTCOME_UNKNOWN" }, 503);
    }
    if (reviewActions && url.pathname === prefix + "requests/" + encodeURIComponent(prepared?.request.request_key ?? "")) {
      state.outcomeCalls += 1;
      return fulfill({ detail: "SYNTHETIC_NO_RECEIPT_YET" }, 404);
    }
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
  test(`${viewport.name}: explicit scoped preview and unknown-outcome recovery, synthetic transport only`, async ({ page, baseURL }, testInfo) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const state = await syntheticOnly(page, baseURL!, true);
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto("/dashboard/research/review");
    const reject = page.getByRole("button", { name: /Reject optional|Reject all|Reject/i });
    if (await reject.count()) await reject.first().click();
    await page.getByRole("checkbox", { name: /Select for review: AlAs/ }).check();
    await page.getByRole("button", { name: "Load review context for 1 selected results" }).click();
    const target = adjudication.context.targets[0];
    await expect(page.getByText("phonon min frequency: -0.0299792458 THz")).toBeVisible();
    await expect(page.getByText(/Unknown pressure, temperature and method remain unknown/)).toBeVisible();
    expect(state.previewCalls).toBe(0); expect(state.commitCalls).toBe(0);
    await page.getByLabel("Profile for " + target.property_id).selectOption("native-sampled-frequency-extraction/1.0.0");
    await page.getByLabel(/Shared rationale/).fill("Synthetic visual test only: upstream method remains unresolved.");
    await page.getByRole("button", { name: "Preview complete request" }).click();
    await expect(page.getByRole("heading", { name: "Exact request preview · no database mutation" })).toBeVisible();
    await assertNoOverflow(page, viewport.width);
    await page.screenshot({ path: testInfo.outputPath(`${viewport.name}-adjudication-preview.png`) });
    await page.getByText("phonon min frequency: -0.0299792458 THz").evaluate(node => node.scrollIntoView({ block: "center" }));
    await page.screenshot({ path: testInfo.outputPath(`${viewport.name}-adjudication-evidence.png`) });
    await page.getByRole("button", { name: "Commit exactly these 1 decisions" }).click();
    await expect(page.getByRole("button", { name: "Check outcome" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Refresh access" })).toBeDisabled();
    await expect(page.getByText("phonon min frequency: -0.0299792458 THz")).toHaveCount(0);
    await page.getByRole("button", { name: "Check outcome" }).click();
    await expect(page.getByText(/not proof that the original request cannot still complete/)).toBeVisible();
    await expect(page.getByText("SYNTHETIC_COMMIT_OUTCOME_UNKNOWN")).toHaveCount(0);
    await assertNoOverflow(page, viewport.width);
    await page.screenshot({ path: testInfo.outputPath(`${viewport.name}-adjudication-unknown.png`) });
    expect(state.previewCalls).toBe(1); expect(state.commitCalls).toBe(1); expect(state.outcomeCalls).toBe(1);
    expect(state.blockedExternal).toEqual([]); expect(state.unexpectedApi).toEqual([]); expect(errors).toEqual([]);
    console.log(`${viewport.name} adjudication screenshots: ${testInfo.outputDir}`);
  });
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
