import { createHash } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";
import http from "../fixtures/ml-use-rights-native.wire.json";

type Json = Record<string, any>;
function canonical(v: any): string { if (Array.isArray(v)) return `[${v.map(canonical).join(",")}]`;
  if (v && typeof v === "object") return `{${Object.keys(v).sort().map(k => `${JSON.stringify(k)}:${canonical(v[k])}`).join(",")}}`; return JSON.stringify(v); }
const hash = (v: unknown) => createHash("sha256").update(canonical(v)).digest("hex");
const access = JSON.parse(http.access);

async function syntheticOnly(page: Page, baseURL: string) {
  const state = { denied: false, previews: 0, commits: 0, outcomes: 0, blocked: [] as string[], unexpected: [] as string[] };
  const origin = new URL(baseURL).origin, prefix = "/__synthetic_api/v1/ml/use/rights";
  let request: Json | null = null, saved: Json | null = null;
  await page.clock.setFixedTime(new Date(JSON.parse(http.allow_committed).result.decision.created_at));
  await page.context().route("**/*", async route => {
    const req = route.request(), url = new URL(req.url());
    if (url.origin !== origin) { state.blocked.push(url.origin); return route.abort("blockedbyclient"); }
    if (!url.pathname.startsWith("/__synthetic_api/")) return route.continue();
    const fulfill = (raw: string, status = 200) => route.fulfill({ status, contentType: "application/json", headers: { "cache-control": "private, no-store" }, body: raw });
    if (url.pathname === "/__synthetic_api/v1/auth/me") return fulfill(JSON.stringify({ id: access.actor_user_id,
      email: "synthetic-rights@example.invalid", name: "Synthetic Rights Reviewer", email_verified: true, is_active: true, is_admin: true,
      is_reviewer: false, auth_provider: "local", avatar_url: null, scopes: [], institution: null, created_at: "2026-09-01T00:00:00Z" }));
    if (url.pathname === prefix + "/access") { expect(req.method()).toBe("GET"); return state.denied ? fulfill('{"detail":"PRIVATE_CANARY"}', 403) : fulfill(http.access); }
    expect(req.method()).toBe("POST"); expect(url.search).toBe("");
    if (url.pathname === prefix + "/inspect") { expect(req.postDataJSON()).toEqual({ ...http.query, after: null }); return fulfill(http.unreviewed); }
    if (url.pathname === prefix + "/decisions") {
      const body = req.postDataJSON();
      if (body.dry_run) {
        state.previews++; expect(body).toEqual({ ...http.allow_input, request_key: body.request_key, dry_run: true }); request = body;
        // Explicit browser transport resealing of the random key only. Not a
        // new SQL receipt, legal decision or additional independent evidence.
        const preview = JSON.parse(http.allow_preview); saved = JSON.parse(http.allow_committed);
        for (const v of [preview, saved!]) { v.result.intent.request_key = body.request_key; v.result.intent_sha256 = hash(v.result.intent); }
        saved!.result.decision.request_key = body.request_key; saved!.result.decision.intent_sha256 = saved!.result.intent_sha256;
        const { created_at: _created, record_sha256: _hash, ...record } = saved!.result.decision;
        saved!.result.decision.record_sha256 = hash(record); return fulfill(JSON.stringify(preview));
      }
      state.commits++; expect(body).toEqual({ ...request, dry_run: false, expected_intent_sha256: saved!.result.intent_sha256 });
      return fulfill('{"detail":"SYNTHETIC_LOST_REPLY"}', 503);
    }
    if (url.pathname === prefix + "/outcome") {
      state.outcomes++; expect(req.postDataJSON()).toEqual({ request_key: request!.request_key, expected_intent_sha256: saved!.result.intent_sha256 });
      if (state.outcomes === 1) return fulfill('{"detail":"NOT_OBSERVED"}', 404);
      saved!.result.replayed = true; return fulfill(JSON.stringify(saved));
    }
    state.unexpected.push(url.pathname); return fulfill('{"detail":"NO_FIXTURE"}', 503);
  });
  return state;
}
async function open(page: Page) {
  await page.goto("/dashboard/research/ml-rights");
  const reject = page.getByRole("button", { name: /Reject optional|Reject all|Reject/i }); if (await reject.count()) await reject.first().click();
  await page.getByLabel("Submission UUID", { exact: true }).fill(http.query.submission_id);
  await page.getByLabel("Submission record SHA-256", { exact: true }).fill(http.query.submission_sha256);
  await page.getByLabel("Inventory SHA-256", { exact: true }).fill(http.query.inventory_sha256);
  await page.getByRole("button", { name: "Inspect inventory", exact: true }).click();
  await expect(page.getByRole("button", { name: "Review resource 1", exact: true })).toBeVisible();
}
async function prepare(page: Page) {
  const review = page.getByRole("button", { name: "Review resource 1", exact: true }); await review.focus(); await review.press("Enter");
  const heading = page.getByRole("heading", { name: "Review exact resource", exact: true });
  await expect(heading).toBeFocused(); await expect(heading).toBeInViewport({ ratio: 1 });
  const box = await heading.boundingBox(), banner = await page.getByRole("banner").boundingBox(); expect(box!.y).toBeGreaterThanOrEqual(banner!.y + banner!.height);
  await page.getByRole("combobox", { name: "Decision", exact: true }).selectOption("allow");
  await page.getByRole("combobox", { name: "Documented basis", exact: true }).selectOption("documented_permission");
  await page.getByLabel("Evidence document SHA-256", { exact: true }).fill(http.allow_input.evidence_sha256);
  await page.getByLabel(/Allow expiry/).fill(String(http.allow_input.expires_epoch)); await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Preview ML rights decision" }).click();
  await expect(page.getByRole("button", { name: "Commit exact ML preview" })).toBeVisible();
}
async function noOverflow(page: Page, width: number) {
  const measured = await page.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth,
    outside: Array.from(document.querySelectorAll<HTMLElement>("main input, main select, main section"))
      .filter(n => { const r = n.getBoundingClientRect(); return r.width > 0 && (r.left < -1 || r.right > innerWidth + 1); }).map(n => n.tagName) }));
  expect(measured.width).toBe(width); expect(measured.document).toBeLessThanOrEqual(width); expect(measured.outside).toEqual([]);
}
for (const view of [{ name: "desktop", width: 1440, height: 1000 }, { name: "mobile", width: 390, height: 844 }]) {
  test(`${view.name}: inventory, keyboard preview and read-only lost-reply recovery`, async ({ page, baseURL }, info) => {
    await page.setViewportSize(view); const state = await syntheticOnly(page, baseURL!), errors: string[] = [];
    page.on("pageerror", e => errors.push(e.message)); await open(page); await noOverflow(page, view.width);
    await page.getByRole("button", { name: "Review resource 1", exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath(view.name + "-inventory.png") });
    await prepare(page); await noOverflow(page, view.width); expect(state.previews).toBe(1); expect(state.commits).toBe(0);
    await page.getByRole("button", { name: "Commit exact ML preview" }).scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath(view.name + "-preview.png") });
    await page.getByRole("button", { name: "Commit exact ML preview" }).click();
    await page.getByRole("button", { name: "Check original outcome" }).click(); await expect(page.getByText(/No outcome was observed/)).toBeVisible();
    await noOverflow(page, view.width); await page.screenshot({ path: info.outputPath(view.name + "-unknown.png") });
    await page.getByRole("button", { name: "Check original outcome" }).click();
    await expect(page.getByRole("heading", { name: "Historical decision receipt" })).toBeVisible(); await noOverflow(page, view.width);
    await page.screenshot({ path: info.outputPath(view.name + "-recovered.png") });
    expect(state.commits).toBe(1); expect(state.outcomes).toBe(2); expect(state.blocked).toEqual([]); expect(state.unexpected).toEqual([]); expect(errors).toEqual([]);
    console.log(`${view.name} ML rights screenshots: ${info.outputDir}`);
  });
  test(`${view.name}: admission refresh clears private data`, async ({ page, baseURL }, info) => {
    await page.setViewportSize(view); const state = await syntheticOnly(page, baseURL!); await open(page); await prepare(page); state.denied = true;
    await page.getByRole("button", { name: "Refresh reviewer access" }).click();
    await expect(page.getByRole("button", { name: "Commit exact ML preview" })).toHaveCount(0);
    await expect(page.getByLabel("Submission UUID")).toHaveValue(""); await expect(page.getByText("PRIVATE_CANARY")).toHaveCount(0);
    await noOverflow(page, view.width); await page.screenshot({ path: info.outputPath(view.name + "-denied.png") });
    expect(state.commits).toBe(0); expect(state.blocked).toEqual([]); expect(state.unexpected).toEqual([]);
  });
}
