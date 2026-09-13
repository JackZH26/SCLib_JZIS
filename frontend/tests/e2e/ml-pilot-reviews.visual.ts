import { expect, test, type Page } from "@playwright/test";
import type { ReviewAction, ReviewControl } from "@/lib/ml-pilot-reviews";
import { canonical, documents, own, reference, syntheticReply } from "../helpers/ml-review-wire";

async function syntheticOnly(page: Page, baseURL: string) {
  const state = { inspection: own.initial, denied: false, sourceIntake: true, checks: 0, previews: 0, commits: 0, outcomes: 0,
    loseReply: true, blocked: [] as string[], unexpected: [] as string[] };
  const origin = new URL(baseURL).origin, prefix = "/__synthetic_api/v1/ml/pilots";
  let controls: ReviewControl | null = null, action: ReviewAction = "attest", original: any;
  await page.context().route("**/*", async route => {
    const req = route.request(), url = new URL(req.url());
    if (url.origin !== origin) { state.blocked.push(url.origin); return route.abort("blockedbyclient"); }
    if (!url.pathname.startsWith("/__synthetic_api/")) return route.continue();
    const fulfill = (raw: string, status = 200) => route.fulfill({ status, contentType: "application/json", headers: { "cache-control": "private, no-store" }, body: raw });
    if (url.pathname === "/__synthetic_api/v1/auth/me") return fulfill(JSON.stringify({ id: own.actor_user_id,
      email: "synthetic-review@example.invalid", name: "Synthetic Review Participant", email_verified: true, is_active: true, is_admin: false,
      is_reviewer: false, auth_provider: "local", avatar_url: null, scopes: [], institution: null, created_at: "2026-09-01T00:00:00Z" }));
    if (url.pathname === prefix + "/review-attestations/declaration") { expect(req.method()).toBe("GET"); return state.denied ? fulfill('{"detail":"PRIVATE_CANARY"}', 403) : fulfill(own.declaration_wording); }
    expect(req.method()).toBe("POST"); expect(url.search).toBe("");
    if (url.pathname === prefix + "/review-attestations/inspect") { expect(req.postDataJSON()).toEqual(reference()); return fulfill(state.inspection); }
    if (url.pathname === prefix + "/review-preflight") {
      state.checks++; expect(state.sourceIntake).toBe(true);
      expect(req.postDataJSON()).toEqual({ version: "ml08-review-upload/1.0.0", ...documents(), parameters: reference() });
      expect(req.headers()["x-sclib-participant-id"]).toBe(reference().participant_id);
      expect(req.headers()["x-sclib-participant-sha256"]).toBe(reference().participant_sha256); return fulfill(own.preflight);
    }
    if ([prefix + "/review-attestations", prefix + "/review-attestations/withdraw"].includes(url.pathname)) {
      const body = req.postDataJSON(), withdrawal = url.pathname.endsWith("/withdraw"), params = withdrawal ? body : body.parameters;
      if (!withdrawal) { expect(state.sourceIntake).toBe(true); expect(body).toEqual({ version: "ml08-review-attestation-upload/1.0.0", ...documents(), parameters: params });
        expect(req.headers()["x-sclib-participant-id"]).toBe(reference().participant_id); expect(req.headers()["x-sclib-participant-sha256"]).toBe(reference().participant_sha256); }
      if (params.dry_run) {
        state.previews++; const { dry_run: _dry, expected_intent_sha256: pin, ...input } = params; expect(pin).toBeNull(); expect(input.declaration_acknowledged).toBe(true);
        controls = input; action = withdrawal ? "withdraw" : "attest"; original = body;
        // Adapter for the browser-generated operation key. These are not new
        // SQL receipts or real scientific declarations.
        return fulfill(syntheticReply(controls!, action, false));
      }
      state.commits++; const saved = syntheticReply(controls!, action, true), pin = JSON.parse(saved).result.intent_sha256;
      const expected = JSON.parse(JSON.stringify(original)), p = withdrawal ? expected : expected.parameters;
      p.dry_run = false; p.expected_intent_sha256 = pin; expect(body).toEqual(expected);
      return state.loseReply ? fulfill('{"detail":"SYNTHETIC_LOST_REPLY"}', 503) : fulfill(saved);
    }
    if (url.pathname === prefix + "/review-attestations/outcome") {
      state.outcomes++; const saved = syntheticReply(controls!, action, true, true), r = JSON.parse(saved).result;
      expect(req.postDataJSON()).toEqual({ request_key: controls!.request_key, expected_intent_sha256: r.intent_sha256 });
      return state.outcomes === 1 ? fulfill('{"detail":"NOT_OBSERVED"}', 404) : fulfill(saved);
    }
    state.unexpected.push(url.pathname); return fulfill(canonical({ detail: "NO_FIXTURE" }), 503);
  });
  return state;
}
async function open(page: Page) {
  await page.goto("/dashboard/research/ml-pilot-reviews");
  const reject = page.getByRole("button", { name: /Reject optional|Reject all|Reject/i }); if (await reject.count()) await reject.first().click();
  const ref = reference();
  await page.getByLabel("Participant UUID", { exact: true }).fill(ref.participant_id);
  await page.getByLabel("Participant record SHA-256", { exact: true }).fill(ref.participant_sha256);
  await page.getByLabel("Registration record SHA-256", { exact: true }).fill(ref.registration_sha256);
  const button = page.getByRole("button", { name: "Inspect own declaration history", exact: true }); await button.focus(); await button.press("Enter");
  const h = page.getByRole("heading", { name: "Your declaration history", exact: true }); await expect(h).toBeFocused(); await expect(h).toBeInViewport({ ratio: 1 });
  const box = await h.boundingBox(), banner = await page.getByRole("banner").boundingBox(); expect(box!.y).toBeGreaterThanOrEqual(banner!.y + banner!.height);
}
async function prepare(page: Page, action: ReviewAction = "attest") {
  await page.getByRole("combobox", { name: "Review action" }).selectOption(action); await page.getByLabel(/^Reason code/).fill("synthetic_review");
  if (action === "attest") {
    for (const [k, label] of [["selection", "Original selection file"], ["protocol", "Original protocol file"], ["reviews", "Original review log"], ["conclusion", "Original conclusion file"]] as const)
      await page.getByLabel(label, { exact: true }).setInputFiles({ name: k, mimeType: "text/plain", buffer: Buffer.from(own.upload[`${k}_base64`], "base64") });
    await page.getByRole("button", { name: "Check original review documents", exact: true }).click(); await expect(page.getByText(/Original documents checked for your account/)).toBeVisible();
  }
  const consent = page.getByRole("checkbox", { name: /^I have/ }); await expect(consent).not.toBeChecked(); await consent.check();
  await page.getByRole("button", { name: "Preview review declaration", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Exact preview — not yet committed", exact: true })).toBeFocused();
  const button = page.getByRole("button", { name: "Commit exact review declaration", exact: true }); await expect(button).toBeDisabled();
  const confirm = page.getByRole("checkbox", { name: "I confirm this exact preview and want to record this action." }); await expect(confirm).not.toBeChecked(); await confirm.check();
}
async function noOverflow(page: Page, width: number) {
  const v = await page.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth,
    outside: Array.from(document.querySelectorAll<HTMLElement>("main input, main select, main section"))
      .filter(n => { const r = n.getBoundingClientRect(); return r.width > 0 && (r.left < -1 || r.right > innerWidth + 1); }).map(n => n.tagName) }));
  expect(v.width).toBe(width); expect(v.document).toBeLessThanOrEqual(width); expect(v.outside).toEqual([]);
}
for (const view of [{ name: "desktop", width: 1440, height: 1000 }, { name: "mobile", width: 390, height: 844 }]) {
  test(`${view.name}: four-file scope, explicit declaration and read-only lost-reply recovery`, async ({ page, baseURL }, info) => {
    await page.setViewportSize(view); const state = await syntheticOnly(page, baseURL!), errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
    await open(page); await prepare(page); await noOverflow(page, view.width); expect(state.checks).toBe(1); expect(state.previews).toBe(1); expect(state.commits).toBe(0);
    await page.getByRole("button", { name: "Commit exact review declaration" }).scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath(view.name + "-preview.png") });
    await page.getByRole("button", { name: "Commit exact review declaration" }).click(); await page.getByRole("button", { name: "Check original review outcome" }).click();
    await expect(page.getByText(/No outcome was observed/)).toBeVisible(); await expect(page.getByLabel("Participant UUID", { exact: true })).toBeDisabled();
    await noOverflow(page, view.width); await page.screenshot({ path: info.outputPath(view.name + "-unknown.png") });
    await page.getByRole("button", { name: "Check original review outcome" }).click();
    await expect(page.getByRole("heading", { name: "Historical review declaration receipt" })).toBeFocused(); await noOverflow(page, view.width);
    await page.screenshot({ path: info.outputPath(view.name + "-recovered.png") }); expect(state.commits).toBe(1); expect(state.outcomes).toBe(2);
    expect(state.blocked).toEqual([]); expect(state.unexpected).toEqual([]); expect(errors).toEqual([]); console.log(`${view.name} review screenshots: ${info.outputDir}`);
  });
  test(`${view.name}: protective withdrawal works without source intake`, async ({ page, baseURL }, info) => {
    await page.setViewportSize(view); const state = await syntheticOnly(page, baseURL!); state.inspection = own.attested_inspection; state.sourceIntake = false; state.loseReply = false;
    await open(page); await prepare(page, "withdraw"); await expect(page.getByLabel("Original review log")).toHaveCount(0); await noOverflow(page, view.width);
    await page.getByRole("button", { name: "Commit exact review declaration" }).click(); await expect(page.getByRole("heading", { name: "Historical review declaration receipt" })).toBeFocused();
    await noOverflow(page, view.width); await page.screenshot({ path: info.outputPath(view.name + "-withdrawn.png") });
    expect(state.checks).toBe(0); expect(state.commits).toBe(1); expect(state.blocked).toEqual([]); expect(state.unexpected).toEqual([]);
  });
  test(`${view.name}: session change clears original files, consent and preview`, async ({ page, baseURL }, info) => {
    await page.setViewportSize(view); const state = await syntheticOnly(page, baseURL!); await open(page); await prepare(page);
    await page.evaluate(() => window.dispatchEvent(new Event("sclib:auth-change"))); state.denied = true;
    await expect(page.getByLabel("Participant UUID", { exact: true })).toHaveValue(""); await expect(page.getByLabel("Original review log")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Commit exact review declaration" })).toHaveCount(0); await page.getByRole("button", { name: "Refresh review access" }).click();
    await expect(page.getByText("PRIVATE_CANARY")).toHaveCount(0); await noOverflow(page, view.width); await page.screenshot({ path: info.outputPath(view.name + "-denied.png") });
    expect(state.commits).toBe(0); expect(state.blocked).toEqual([]); expect(state.unexpected).toEqual([]);
  });
}
