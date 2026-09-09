import { createHash } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";

import http from "../fixtures/distribution-rights-http.json";

type Json = Record<string, any>;
function canonical(value: unknown): string {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value !== null && typeof value === "object") return "{" + Object.keys(value).sort().map(key =>
    JSON.stringify(key) + ":" + canonical((value as Json)[key])).join(",") + "}";
  return JSON.stringify(value);
}
const digest = (value: unknown) => createHash("sha256").update(canonical(value)).digest("hex");

async function syntheticOnly(page: Page, baseURL: string) {
  const state = { denied: false, unknown: true, previewCalls: 0, commitCalls: 0, outcomeCalls: 0,
    blockedExternal: [] as string[], unexpectedApi: [] as string[] };
  let prepared: { request: Json; preview: Json; committed: Json } | null = null;
  const origin = new URL(baseURL).origin;
  const prefix = "/__synthetic_api/v1/ml/distributions";
  const target = prefix + "/" + http.selected.package_id + "/rights/" + http.selected.dependency.dependency_id;
  await page.context().route("**/*", async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin !== origin) { state.blockedExternal.push(url.origin); return route.abort("blockedbyclient"); }
    if (!url.pathname.startsWith("/__synthetic_api/")) return route.continue();
    const fulfill = (value: unknown, status = 200) => route.fulfill({ status, contentType: "application/json",
      headers: { "cache-control": "private, no-store" }, body: JSON.stringify(value) });
    if (url.pathname === "/__synthetic_api/v1/auth/me") return fulfill({
      id: http.capabilities.actor_user_id, email: "reviewer@example.invalid", email_verified: true,
      name: "Synthetic Reviewer", institution: null, country: null, age: null, research_area: null,
      purpose: null, bio: null, orcid: null, created_at: "2026-09-01T00:00:00Z", is_active: true,
      is_admin: false, is_reviewer: false, auth_provider: "local", avatar_url: null, scopes: [],
    });
    if (url.pathname === prefix + "/operator/capabilities") {
      expect(request.method()).toBe("GET");
      return state.denied ? fulfill({ detail: "PRIVATE_DIAGNOSTIC_MUST_NOT_RENDER" }, 403) : fulfill(http.capabilities);
    }
    if (url.pathname === prefix + "/" + http.selected.package_id + "/rights") {
      expect(request.method()).toBe("GET"); return fulfill(http.listing);
    }
    if (url.pathname === target && request.method() === "GET") return fulfill(http.selected);
    if (url.pathname === target && request.method() === "POST") {
      const body = request.postDataJSON() as Json;
      if (body.dry_run !== false) {
        state.previewCalls += 1;
        // These data originate from actual guarded SQL/HTTP. Transport changes
        // only the browser-generated request key and its derived intent hash.
        expect(body).toEqual({ ...http.request, request_key: body.request_key, dry_run: true });
        const preview = structuredClone(http.preview), committed = structuredClone(http.committed);
        for (const value of [preview, committed]) {
          value.result.intent.request_key = body.request_key;
          value.result.intent_sha256 = digest(value.result.intent);
        }
        prepared = { request: body, preview, committed }; return fulfill(preview);
      }
      state.commitCalls += 1;
      expect(body).toEqual({ ...prepared!.request, dry_run: false, expected_intent_sha256: prepared!.preview.result.intent_sha256 });
      return state.unknown ? fulfill({ detail: "SYNTHETIC_LOST_ACK" }, 503) : fulfill(prepared!.committed);
    }
    if (url.pathname === target + "/outcome") {
      state.outcomeCalls += 1; expect(request.method()).toBe("GET");
      expect(request.postData()).toBeNull();
      expect(url.searchParams.get("request_key")).toBe(prepared!.request.request_key);
      expect(url.searchParams.get("expected_intent_sha256")).toBe(prepared!.preview.result.intent_sha256);
      if (state.outcomeCalls === 1) return fulfill({ detail: "NOT_OBSERVED_NOW" }, 404);
      return fulfill({ ...prepared!.committed, result: { ...prepared!.committed.result, replayed: true } });
    }
    state.unexpectedApi.push(url.pathname); return fulfill({ detail: "No synthetic fixture available" }, 503);
  });
  return state;
}

async function openTarget(page: Page) {
  await page.goto("/dashboard/research/distributions");
  const reject = page.getByRole("button", { name: /Reject optional|Reject all|Reject/i });
  if (await reject.count()) await reject.first().click();
  await page.getByLabel("Package UUID", { exact: true }).fill(http.selected.package_id);
  await page.getByRole("button", { name: "Load dependencies", exact: true }).click();
  const inspect = page.getByRole("button", { name: "Inspect dependency", exact: true }).first();
  await inspect.focus(); await inspect.press("Enter");
  const heading = page.getByRole("heading", { name: "Exact dependency", exact: true });
  await expect(heading).toBeFocused(); await expect(heading).toBeInViewport({ ratio: 1 });
  const box = await heading.boundingBox(), header = await page.getByRole("banner").boundingBox();
  expect(box!.y).toBeGreaterThanOrEqual(header!.y + header!.height);
}
async function prepare(page: Page) {
  await openTarget(page);
  await expect(page.getByRole("combobox", { name: "Decision", exact: true })).toHaveValue("");
  await expect(page.getByRole("combobox", { name: "License or permission basis", exact: true })).toHaveValue("");
  await page.getByRole("combobox", { name: "Decision", exact: true }).selectOption("allow");
  await page.getByRole("combobox", { name: "License or permission basis", exact: true }).selectOption(http.request.license_code);
  await page.getByLabel("Basis code", { exact: true }).fill(http.request.basis_code);
  await page.getByLabel("Reason code", { exact: true }).fill(http.request.reason_code);
  await page.getByRole("button", { name: "Preview rights decision", exact: true }).click();
  await expect(page.getByRole("button", { name: "Commit exact preview", exact: true })).toBeVisible();
}
async function noOverflow(page: Page, width: number) {
  const measured = await page.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth,
    outside: Array.from(document.querySelectorAll<HTMLElement>("main input, main select, main button, main section"))
      .filter(node => { const box = node.getBoundingClientRect(); return box.width > 0 && (box.left < -1 || box.right > innerWidth + 1); })
      .map(node => node.tagName + ":" + node.textContent?.slice(0, 60)),
  }));
  expect(measured.width).toBe(width); expect(measured.document).toBeLessThanOrEqual(width); expect(measured.outside).toEqual([]);
}

for (const viewport of [{ name: "desktop", width: 1440, height: 1000 }, { name: "mobile", width: 390, height: 844 }]) {
  test(`${viewport.name}: explicit preview and same-key GET-only unknown recovery`, async ({ page, baseURL }, info) => {
    await page.setViewportSize(viewport);
    const state = await syntheticOnly(page, baseURL!);
    const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
    await prepare(page); expect(state.previewCalls).toBe(1); expect(state.commitCalls).toBe(0);
    await noOverflow(page, viewport.width);
    await page.getByRole("button", { name: "Commit exact preview" }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath(viewport.name + "-preview.png") });
    await page.getByRole("button", { name: "Commit exact preview" }).click();
    await expect(page.getByRole("button", { name: "Check original outcome" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Commit exact preview" })).toHaveCount(0);
    await page.getByRole("button", { name: "Check original outcome" }).click();
    await expect(page.getByText(/no rollback is inferred/)).toBeVisible();
    await noOverflow(page, viewport.width);
    await page.getByRole("button", { name: "Check original outcome" }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath(viewport.name + "-unknown.png") });
    await page.getByRole("button", { name: "Check original outcome" }).click();
    await expect(page.getByText(http.committed.result.permission.id, { exact: false })).toBeVisible();
    await noOverflow(page, viewport.width);
    await page.screenshot({ path: info.outputPath(viewport.name + "-recovered.png") });
    expect(state.previewCalls).toBe(1); expect(state.commitCalls).toBe(1); expect(state.outcomeCalls).toBe(2);
    expect(state.blockedExternal).toEqual([]); expect(state.unexpectedApi).toEqual([]); expect(errors).toEqual([]);
    console.log(`${viewport.name} rights screenshots: ${info.outputDir}`);
  });
  test(`${viewport.name}: refreshed denial clears private dependency evidence`, async ({ page, baseURL }, info) => {
    await page.setViewportSize(viewport); const state = await syntheticOnly(page, baseURL!);
    await prepare(page); state.denied = true;
    await page.getByRole("button", { name: "Refresh reviewer access" }).click();
    await expect(page.getByRole("button", { name: "Commit exact preview" })).toHaveCount(0);
    await expect(page.getByText(http.selected.inventory_sha256, { exact: false })).toHaveCount(0);
    await expect(page.getByText("PRIVATE_DIAGNOSTIC_MUST_NOT_RENDER")).toHaveCount(0);
    await noOverflow(page, viewport.width);
    await page.screenshot({ path: info.outputPath(viewport.name + "-denied.png") });
    expect(state.commitCalls).toBe(0); expect(state.blockedExternal).toEqual([]); expect(state.unexpectedApi).toEqual([]);
  });
}
