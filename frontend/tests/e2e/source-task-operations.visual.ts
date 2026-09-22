import { expect, test, type Page } from "@playwright/test";
import { createHash } from "node:crypto";
import captured from "../fixtures/source-task-operations-http.json";

type Json = Record<string, any>;
function canonical(value: unknown): string {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value !== null && typeof value === "object") return "{" + Object.keys(value).sort().map(key => JSON.stringify(key) + ":" + canonical((value as Json)[key])).join(",") + "}";
  return JSON.stringify(value);
}
const digest = (value: unknown) => createHash("sha256").update(canonical(value)).digest("hex");
function recordHash(value: Json) {
  return digest(Object.fromEntries(Object.entries(value).filter(([key]) => !["created_at", "record_sha256", "inventory_json"].includes(key))));
}

async function syntheticOnly(page: Page, baseURL: string) {
  const state = { denied: false, previewCalls: 0, commitCalls: 0, outcomeCalls: 0,
    blockedExternal: [] as string[], unexpectedApi: [] as string[] };
  let prepared: { request: Json; preview: Json; receipt: Json } | null = null;
  let queued: Json | null = null, executed: Json | null = null;
  const origin = new URL(baseURL).origin;
  const prefix = "/__synthetic_api/v1/ml/source-lifecycle";
  await page.context().route("**/*", async route => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) { state.blockedExternal.push(url.origin); return route.abort("blockedbyclient"); }
    if (!url.pathname.startsWith("/__synthetic_api/")) return route.continue();
    const fulfill = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json",
      headers: { "cache-control": "private, no-store" }, body: JSON.stringify(body) });
    if (url.pathname === "/__synthetic_api/v1/auth/me") return fulfill({
      id: captured.capabilities.actor_user_id, email: "curator@example.invalid", email_verified: true,
      name: "Synthetic Curator", institution: null, country: null, age: null, research_area: null, purpose: null,
      bio: null, orcid: null, created_at: "2026-09-01T00:00:00Z", is_active: true, is_admin: false,
      is_reviewer: false, auth_provider: "local", avatar_url: null, scopes: [],
    });
    if (url.pathname === prefix + "/task-operations/capabilities") return state.denied
      ? fulfill({ detail: "PRIVATE_DIAGNOSTIC_MUST_NOT_RENDER" }, 403) : fulfill(captured.capabilities);
    if (url.pathname === prefix) {
      expect(url.searchParams.get("paper_id")).toBe(captured.source_id);
      return fulfill(captured.source_history);
    }
    if (url.pathname === prefix + "/" + captured.source_impact.event.id + "/impact") {
      expect(url.searchParams.get("expected_event_sha256")).toBe(captured.source_impact.event.record_sha256);
      return fulfill(captured.source_impact);
    }
    if (url.pathname === prefix + "/task-operations/preview") {
      state.previewCalls += 1;
      const request = route.request().postDataJSON();
      const enqueue = request.operation === "enqueue";
      // Actual guarded HTTP fixtures supply the scientific and receipt shape.
      // Only browser-generated keys and their derived hashes are remapped in
      // this explicitly synthetic browser transport; this is not a live API.
      const original = enqueue ? captured.enqueue_request : captured.execution_request;
      const key = enqueue ? "request_key" : "execution_key";
      expect(request).toEqual({ ...original, [key]: request[key],
        ...(enqueue ? {} : { expected_request_sha256: queued!.request.record_sha256 }) });
      const base = enqueue ? captured.enqueue_preview : captured.execution_preview;
      const binding = { version: base.version, operation: request.operation, actor_user_id: base.actor_user_id,
        actor_grant_id: base.actor_grant_id, operation_sha256: digest(request), predicted_status: base.predicted_status,
        predicted_outcome_code: base.predicted_outcome_code, receipt_semantics: base.receipt_semantics };
      const preview = { ...base, ...binding, preview_sha256: digest(binding) };
      const receipt: Json = structuredClone(enqueue ? captured.enqueue_receipt : captured.execution_receipt);
      receipt.operation_sha256 = preview.operation_sha256; receipt.preview_sha256 = preview.preview_sha256;
      if (enqueue) { receipt.request.request_key = request.request_key; receipt.request.record_sha256 = recordHash(receipt.request); }
      else { receipt.request = queued!.request; receipt.attempt.execution_key = request.execution_key;
        receipt.attempt.record_sha256 = recordHash(receipt.attempt); }
      prepared = { request, preview, receipt };
      return fulfill(preview);
    }
    if (url.pathname === prefix + "/task-operations/commit") {
      state.commitCalls += 1;
      expect(route.request().postDataJSON()).toEqual({ request: prepared!.request, expected_preview_sha256: prepared!.preview.preview_sha256 });
      if (prepared!.request.operation === "enqueue") { queued = prepared!.receipt; return fulfill(queued); }
      executed = prepared!.receipt;
      return fulfill({ detail: "SYNTHETIC_UNKNOWN_ACK" }, 503);
    }
    if (url.pathname === prefix + "/tasks/" + captured.enqueue_receipt.request.id) {
      return fulfill({ ...(executed ? captured.task_history : captured.queued_task_history), request: queued!.request,
        attempts: executed ? [executed.attempt] : [] });
    }
    if (prepared?.request.operation === "execute" && url.pathname === prefix + "/task-operations/requests/" +
      prepared.request.request_id + "/executions/" + encodeURIComponent(prepared.request.execution_key)) {
      state.outcomeCalls += 1;
      return state.outcomeCalls === 1 ? fulfill({ detail: "SYNTHETIC_NOT_FOUND_NOW" }, 404)
        : fulfill({ ...executed, replayed: true, executed_now: false });
    }
    state.unexpectedApi.push(url.pathname); return fulfill({ detail: "No synthetic fixture available" }, 503);
  });
  return state;
}

async function noOverflow(page: Page, width: number) {
  const measured = await page.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth,
    outside: Array.from(document.querySelectorAll<HTMLElement>("main input, main button, main section"))
      .filter(node => { const box = node.getBoundingClientRect(); return box.width > 0 && (box.left < -1 || box.right > innerWidth + 1); })
      .map(node => node.textContent?.slice(0, 80)),
  }));
  expect(measured.width).toBe(width); expect(measured.document).toBeLessThanOrEqual(width); expect(measured.outside).toEqual([]);
}

for (const viewport of [{ name: "desktop", width: 1440, height: 1000 }, { name: "mobile", width: 390, height: 844 }]) {
  test(`${viewport.name}: scoped source operation and original-key recovery, synthetic transport`, async ({ page, baseURL }, info) => {
    await page.setViewportSize(viewport);
    const state = await syntheticOnly(page, baseURL!);
    const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
    await page.goto("/dashboard/research/source-tasks");
    const reject = page.getByRole("button", { name: /Reject optional|Reject all|Reject/i });
    if (await reject.count()) await reject.first().click();
    await page.getByLabel("Source identifier").fill(captured.source_id);
    await page.getByRole("button", { name: "Inspect source", exact: true }).click();
    await page.getByRole("button", { name: /Inspect impact · revision/ }).first().click();
    await expect(page.getByRole("heading", { name: "Exact declared impact" })).toBeVisible();
    await page.getByText("Scope and exclusions", { exact: true }).click();
    await expect(page.getByText("Not covered", { exact: true })).toBeVisible();
    expect(state.previewCalls).toBe(0); expect(state.commitCalls).toBe(0);
    await page.getByRole("button", { name: "Preview enqueue", exact: true }).click();
    await expect(page.getByRole("heading", { name: "3. Confirm exact enqueue preview" })).toBeVisible();
    await noOverflow(page, viewport.width);
    await page.getByRole("heading", { name: "3. Confirm exact enqueue preview" }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath(viewport.name + "-enqueue-preview.png") });
    await page.getByRole("button", { name: "Commit exact preview" }).click();
    await expect(page.getByRole("heading", { name: "Committed historical receipt" })).toBeVisible();
    await page.getByRole("button", { name: "Inspect recorded task" }).click();
    await expect(page.getByRole("heading", { name: "Immutable task history" })).toBeVisible();
    await page.getByRole("button", { name: "Preview execution", exact: true }).click();
    await expect(page.getByRole("heading", { name: "3. Confirm exact execute preview" })).toBeVisible();
    await page.getByRole("button", { name: "Commit exact preview" }).click();
    await expect(page.getByRole("heading", { name: "Recover unknown commit" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Refresh curator access" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Commit exact preview" })).toHaveCount(0);
    await page.getByRole("button", { name: "Check original outcome" }).click();
    await expect(page.getByText(/absence is not proof of rollback/)).toBeVisible();
    await noOverflow(page, viewport.width);
    await page.getByRole("heading", { name: "Recover unknown commit" }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath(viewport.name + "-unknown.png") });
    await page.getByRole("button", { name: "Check original outcome" }).click();
    await expect(page.getByText(/Exact replay; no new execution/)).toBeVisible();
    await expect(page.getByText(/Timeline rebuilt: no. Complete propagation: no/)).toBeVisible();
    await page.getByRole("button", { name: "Inspect recorded task" }).click();
    await expect(page.getByRole("button", { name: "Preview execution", exact: true })).toBeDisabled();
    await noOverflow(page, viewport.width);
    await page.getByRole("heading", { name: "Immutable task history" }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath(viewport.name + "-terminal.png") });
    expect(state.previewCalls).toBe(2); expect(state.commitCalls).toBe(2); expect(state.outcomeCalls).toBe(2);
    expect(state.blockedExternal).toEqual([]); expect(state.unexpectedApi).toEqual([]); expect(errors).toEqual([]);
    console.log(`${viewport.name} source-task screenshots: ${info.outputDir}`);
  });

  test(`${viewport.name}: refreshed denial clears private source evidence`, async ({ page, baseURL }, info) => {
    await page.setViewportSize(viewport);
    const state = await syntheticOnly(page, baseURL!);
    await page.goto("/dashboard/research/source-tasks");
    const reject = page.getByRole("button", { name: /Reject optional|Reject all|Reject/i });
    if (await reject.count()) await reject.first().click();
    await page.getByLabel("Source identifier").fill(captured.source_id);
    await page.getByRole("button", { name: "Inspect source", exact: true }).click();
    await page.getByRole("button", { name: /Inspect impact · revision/ }).first().click();
    await expect(page.getByRole("heading", { name: "Exact declared impact" })).toBeVisible();
    state.denied = true;
    await page.getByRole("button", { name: "Refresh curator access" }).click();
    await expect(page.getByText(/Session or curator access is unavailable/)).toBeVisible();
    await expect(page.getByRole("heading", { name: "Exact declared impact" })).toHaveCount(0);
    await expect(page.getByText(captured.source_impact.inventory_sha256, { exact: false })).toHaveCount(0);
    await expect(page.getByText("PRIVATE_DIAGNOSTIC_MUST_NOT_RENDER")).toHaveCount(0);
    await noOverflow(page, viewport.width);
    await page.screenshot({ path: info.outputPath(viewport.name + "-denied.png") });
    expect(state.commitCalls).toBe(0); expect(state.blockedExternal).toEqual([]); expect(state.unexpectedApi).toEqual([]);
  });
}
