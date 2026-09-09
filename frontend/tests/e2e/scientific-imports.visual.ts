/** Actual browser file APIs against captured synthetic SQL/HTTP only. */
import { expect, test, type Page } from "@playwright/test";

import http from "../fixtures/scientific-import-recovery-http.json";

type Json = Record<string, any>;
function canonical(value: unknown): string {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value !== null && typeof value === "object") return "{" + Object.keys(value).sort().map(key =>
    JSON.stringify(key) + ":" + canonical((value as Json)[key])).join(",") + "}";
  return JSON.stringify(value);
}
const pin = http.preview.result.request_sha256;
async function syntheticOnly(page: Page, baseURL: string) {
  const state = { denied: false, previewCalls: 0, commitCalls: 0, outcomeCalls: 0,
    blockedExternal: [] as string[], unexpectedApi: [] as string[] };
  const origin = new URL(baseURL).origin, prefix = "/__synthetic_api/v1/ml/scientific-program-imports";
  let prepared: Json | null = null;
  await page.context().route("**/*", async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin !== origin) { state.blockedExternal.push(url.origin); return route.abort("blockedbyclient"); }
    if (!url.pathname.startsWith("/__synthetic_api/")) return route.continue();
    const fulfill = (value: unknown, status = 200) => route.fulfill({ status, contentType: "application/json",
      headers: { "cache-control": "private, no-store" }, body: JSON.stringify(value) });
    if (url.pathname === "/__synthetic_api/v1/auth/me") return fulfill({
      id: http.capabilities.actor_user_id, email: "curator@example.invalid", email_verified: true,
      name: "Synthetic Curator", institution: null, country: null, age: null, research_area: null,
      purpose: null, bio: null, orcid: null, created_at: "2026-09-01T00:00:00Z", is_active: true,
      is_admin: false, is_reviewer: false, auth_provider: "local", avatar_url: null, scopes: [],
    });
    if (url.pathname === prefix + "/capabilities") {
      expect(request.method()).toBe("GET");
      return state.denied ? fulfill({ detail: "PRIVATE_DIAGNOSTIC_MUST_NOT_RENDER" }, 403) : fulfill(http.capabilities);
    }
    if (url.pathname === prefix + "/material-bindings/" + encodeURIComponent(http.material_binding.material_id)) {
      expect(request.method()).toBe("GET"); return fulfill(http.material_binding);
    }
    if (url.pathname === prefix && request.method() === "POST") {
      const body = request.postDataJSON() as Json;
      if (body.dry_run === true) {
        state.previewCalls += 1;
        // Only a browser-generated request key is substituted; native bytes,
        // manifest/material/compiler pins and scientific quantities are exact.
        expect(body).toEqual({ ...http.request, request_key: body.request_key, dry_run: true, expected_request_sha256: pin });
        prepared = body; return fulfill(http.preview);
      }
      state.commitCalls += 1; expect(body).toEqual({ ...prepared!, dry_run: false });
      return fulfill({ detail: "SYNTHETIC_LOST_ACK" }, 503);
    }
    if (url.pathname === prefix + "/outcome") {
      state.outcomeCalls += 1; expect(request.method()).toBe("GET"); expect(request.postData()).toBeNull();
      expect(url.searchParams.get("request_key")).toBe(prepared!.request_key);
      expect(url.searchParams.get("expected_request_sha256")).toBe(pin);
      if (state.outcomeCalls === 1) return fulfill(http.absent, 404);
      if (state.outcomeCalls === 2) return fulfill(http.outcome_unknown);
      return fulfill(http.outcome);
    }
    state.unexpectedApi.push(url.pathname); return fulfill({ detail: "No synthetic fixture available" }, 503);
  });
  return state;
}
async function openTarget(page: Page) {
  await page.goto("/dashboard/research/imports");
  const reject = page.getByRole("button", { name: /Reject optional|Reject all|Reject/i });
  if (await reject.count()) await reject.first().click();
  await expect(page.getByLabel("Material ID", { exact: true })).toBeEnabled();
  await page.getByLabel("Material ID", { exact: true }).fill(http.material_binding.material_id);
  const inspect = page.getByRole("button", { name: "Inspect material", exact: true });
  await inspect.focus(); await inspect.press("Enter");
  await expect(page.getByText(/Current formula: AlAs/)).toBeVisible();
}
async function prepare(page: Page) {
  await openTarget(page);
  await page.getByLabel("Canonical manifest file", { exact: true }).setInputFiles({ name: "manifest.json", mimeType: "application/json", buffer: Buffer.from(canonical(http.request.manifest)) });
  await page.getByLabel("Independent manifest SHA-256", { exact: true }).fill(http.request.expected_manifest_sha256);
  const load = page.getByRole("button", { name: "Load local manifest", exact: true }); await load.focus(); await load.press("Enter");
  for (const entry of http.request.manifest.files) {
    await page.getByLabel("Source file: " + entry.logical_name, { exact: true }).setInputFiles({ name: "arbitrary-name.bin", mimeType: "application/octet-stream",
      buffer: Buffer.from(http.request.artifact_bytes_base64[entry.sha256 as keyof typeof http.request.artifact_bytes_base64], "base64") });
  }
  await page.getByLabel("Force-constant file (optional)", { exact: true }).setInputFiles({ name: "fc-other-name.bin", mimeType: "application/octet-stream", buffer: Buffer.from(http.request.force_constants_bytes_base64, "base64") });
  await page.getByLabel("Force-constant logical name", { exact: true }).fill(http.request.context.force_constants.logical_name);
  await page.getByLabel("Independent force-constant SHA-256", { exact: true }).fill(http.request.context.force_constants.sha256);
  await page.getByRole("button", { name: "Preview pending import", exact: true }).click();
  const heading = page.getByRole("heading", { name: "Review before importing", exact: true });
  await expect(heading).toBeFocused(); await expect(heading).toBeInViewport({ ratio: 1 });
  const box = await heading.boundingBox(), header = await page.getByRole("banner").boundingBox();
  expect(box!.y).toBeGreaterThanOrEqual(header!.y + header!.height);
  await expect(page.getByText(/proposed IDs are not evidence of saved records/)).toBeVisible();
  await expect(page.getByText(http.preview.result.row_ids.property, { exact: true })).toHaveCount(0);
}
async function noOverflow(page: Page, width: number) {
  const measured = await page.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth,
    outside: Array.from(document.querySelectorAll<HTMLElement>("main input, main button, main section"))
      .filter(node => { const box = node.getBoundingClientRect(); return box.width > 0 && (box.left < -1 || box.right > innerWidth + 1); })
      .map(node => node.tagName + ":" + node.textContent?.slice(0, 60)),
  }));
  expect(measured.width).toBe(width); expect(measured.document).toBeLessThanOrEqual(width); expect(measured.outside).toEqual([]);
}
for (const viewport of [{ name: "desktop", width: 1440, height: 1000 }, { name: "mobile", width: 390, height: 844 }]) {
  test(`${viewport.name}: local files, exact preview and GET-only unknown recovery`, async ({ page, baseURL }, info) => {
    await page.setViewportSize(viewport); const state = await syntheticOnly(page, baseURL!);
    const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
    await prepare(page); expect(state.previewCalls).toBe(1); expect(state.commitCalls).toBe(0);
    await noOverflow(page, viewport.width);
    await page.screenshot({ path: info.outputPath(viewport.name + "-preview.png") });
    await page.getByRole("button", { name: "Commit exact preview" }).click();
    await expect(page.getByText(/Import outcome is unknown/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Commit exact preview" })).toHaveCount(0);
    await expect(page.getByLabel("Material ID", { exact: true })).toBeDisabled();
    await expect(page.getByLabel("Material ID", { exact: true })).toHaveValue("");
    await expect(page.getByText(/Current formula:/)).toHaveCount(0);
    await expect(page.getByText(/Material row SHA-256:/)).toHaveCount(0);
    await page.getByRole("button", { name: "Check original outcome" }).click();
    await expect(page.getByText(/No attempt was observed in this snapshot/)).toBeVisible();
    await noOverflow(page, viewport.width);
    await page.screenshot({ path: info.outputPath(viewport.name + "-unknown.png") });
    await page.getByRole("button", { name: "Check original outcome" }).click();
    await expect(page.getByText(/A durable start exists, but its terminal outcome is unknown/)).toBeVisible();
    await expect(page.getByRole("link", { name: "Open scientific evidence workbench" })).toHaveCount(0);
    await page.getByRole("button", { name: "Check original outcome" }).click();
    await expect(page.getByText(http.committed.result.row_ids.property, { exact: true })).toBeVisible();
    const heading = page.getByRole("heading", { name: "Durable import receipt" });
    await expect(heading).toBeFocused(); await expect(heading).toBeInViewport({ ratio: 1 });
    await expect(page.getByRole("link", { name: "Open scientific evidence workbench" })).toHaveAttribute("href", "/dashboard/research/review");
    await expect(page.getByText(/Calculation wall time, CPU time and monetary cost: not reported, not zero/)).toBeVisible();
    await noOverflow(page, viewport.width);
    await page.screenshot({ path: info.outputPath(viewport.name + "-recovered.png") });
    expect(state.previewCalls).toBe(1); expect(state.commitCalls).toBe(1); expect(state.outcomeCalls).toBe(3);
    expect(state.blockedExternal).toEqual([]); expect(state.unexpectedApi).toEqual([]); expect(errors).toEqual([]);
    console.log(`${viewport.name} import screenshots: ${info.outputDir}`);
  });
  test(`${viewport.name}: refreshed denial clears selected files and preview`, async ({ page, baseURL }, info) => {
    await page.setViewportSize(viewport); const state = await syntheticOnly(page, baseURL!);
    await prepare(page); state.denied = true;
    await page.getByRole("button", { name: "Refresh curator access" }).click();
    await expect(page.getByRole("button", { name: "Commit exact preview" })).toHaveCount(0);
    await expect(page.getByLabel("Material ID", { exact: true })).toHaveValue("");
    await expect(page.getByLabel("Canonical manifest file", { exact: true })).toHaveValue("");
    await expect(page.getByLabel("Independent manifest SHA-256", { exact: true })).toHaveValue("");
    await expect(page.getByText(http.material_binding.material_row_sha256, { exact: false })).toHaveCount(0);
    await expect(page.getByText("PRIVATE_DIAGNOSTIC_MUST_NOT_RENDER")).toHaveCount(0);
    await noOverflow(page, viewport.width); await page.screenshot({ path: info.outputPath(viewport.name + "-denied.png") });
    expect(state.commitCalls).toBe(0); expect(state.blockedExternal).toEqual([]); expect(state.unexpectedApi).toEqual([]);
  });
}
