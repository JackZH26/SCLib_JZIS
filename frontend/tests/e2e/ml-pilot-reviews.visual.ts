import { expect, test, type Page } from "@playwright/test";
import type { ReviewAction, ReviewControl } from "@/lib/ml-pilot-reviews";
import { canonical, coverageReply, documents, own, reference, syntheticReply } from "../helpers/ml-review-wire";
import { evidenceNative, evidenceParts } from "../helpers/ml-evidence-wire";

async function syntheticOnly(page: Page, baseURL: string) {
  const state = { inspection: own.initial, denied: false, sourceIntake: true, checks: 0, previews: 0, commits: 0, outcomes: 0,
    loseReply: true, coverage: 0, coverageDenied: false, blocked: [] as string[], unexpected: [] as string[] };
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
    if (url.pathname === prefix + "/review-attestations/coverage") {
      state.coverage++; expect(state.sourceIntake).toBe(true);
      expect(req.postDataJSON()).toEqual({ version: "ml08-review-upload/1.0.0", ...documents(), parameters: reference() });
      expect(req.headers()["x-sclib-participant-id"]).toBe(reference().participant_id);
      expect(req.headers()["x-sclib-participant-sha256"]).toBe(reference().participant_sha256);
      return state.coverageDenied ? fulfill('{"detail":"PRIVATE_CANARY"}', 409) : fulfill(coverageReply());
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
  test(`${view.name}: actual native byte replay snapshot never implies scientific approval`, async ({ page, baseURL }, info) => {
    await page.setViewportSize(view); const origin = new URL(baseURL!).origin, blocked: string[] = [];
    let checks = 0, denied = false;
    await page.context().route("**/*", async route => {
      const req = route.request(), url = new URL(req.url());
      if (url.origin !== origin) { blocked.push(url.origin); return route.abort("blockedbyclient"); }
      if (!url.pathname.startsWith("/__synthetic_api/")) return route.continue();
      const reply = (body: string, status = 200) => route.fulfill({ status, contentType: "application/json", body, headers: { "cache-control": "private, no-store" } });
      if (url.pathname.endsWith("/auth/me")) return reply(JSON.stringify({ id: evidenceNative.actor_user_id, email: "synthetic@example.invalid", name: "Synthetic", email_verified: true, is_active: true, is_admin: false,
        is_reviewer: false, auth_provider: "local", avatar_url: null, scopes: [], institution: null, created_at: "2026-09-01T00:00:00Z" }));
      if (url.pathname.endsWith("/review-attestations/declaration")) return reply(evidenceNative.wording);
      if (url.pathname.endsWith("/review-attestations/inspect")) { expect(req.postDataJSON()).toEqual(evidenceNative.reference); return reply(evidenceNative.history); }
      if (url.pathname.endsWith("/review-preflight")) { expect(req.postDataJSON()).toEqual(evidenceNative.upload); return reply(evidenceNative.preflight); }
      if (url.pathname.endsWith("/review-attestations/evidence")) {
        checks++; expect(req.headers()["content-type"]).toBe("application/vnd.sclib.ml08-evidence-v1");
        expect(req.headers()["x-sclib-participant-id"]).toBe(evidenceNative.reference.participant_id);
        expect(req.postDataBuffer()).toEqual(evidenceParts().raw);
        return denied ? reply('{"detail":"PRIVATE_CANARY"}', 409) : reply(evidenceNative.complete);
      }
      blocked.push(url.pathname); return reply('{"detail":"UNEXPECTED"}', 503);
    });
    await page.goto("/dashboard/research/ml-pilot-reviews");
    const reject = page.getByRole("button", { name: /Reject optional|Reject all|Reject/i }); if (await reject.count()) await reject.first().click();
    const ref = evidenceNative.reference;
    await page.getByLabel("Participant UUID", { exact: true }).fill(ref.participant_id);
    await page.getByLabel("Participant record SHA-256", { exact: true }).fill(ref.participant_sha256);
    await page.getByLabel("Registration record SHA-256", { exact: true }).fill(ref.registration_sha256);
    await page.getByRole("button", { name: "Inspect own declaration history", exact: true }).click();
    await page.getByRole("combobox", { name: "Review action" }).selectOption("attest");
    for (const [k, label] of [["selection", "Original selection file"], ["protocol", "Original protocol file"], ["reviews", "Original review log"], ["conclusion", "Original conclusion file"]] as const)
      await page.getByLabel(label, { exact: true }).setInputFiles({ name: k, mimeType: "text/plain", buffer: evidenceParts().files[k] });
    await page.getByRole("button", { name: "Check original review documents", exact: true }).click();
    await expect(page.getByText(/Original documents checked for your account/)).toBeVisible();
    expect(checks).toBe(0); await page.getByLabel("Exact canary bundle").setInputFiles({ name: "canary.json", mimeType: "application/json", buffer: evidenceParts().files.canary });
    await page.getByRole("button", { name: "Verify canary and context bytes", exact: true }).click();
    const snapshot = page.getByRole("status", { name: "Byte integrity snapshot" });
    await expect(snapshot).toBeVisible(); await expect(snapshot.getByText(/No context files were required/)).toBeVisible();
    await expect(page.getByRole("checkbox", { name: /^I have/ })).not.toBeChecked(); await noOverflow(page, view.width);
    await snapshot.scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath(view.name + "-byte-integrity.png") });
    await page.getByRole("button", { name: "Show verified field report", exact: true }).click();
    const report = page.getByRole("region", { name: "Verified private field report" });
    const title = report.getByRole("heading", { name: "Pilot field recovery and curation effort", exact: true });
    await expect(title).toBeFocused(); await expect(title).toBeInViewport({ ratio: 1 });
    const titleBox = await title.boundingBox(), bannerBox = await page.getByRole("banner").boundingBox();
    expect(titleBox!.y).toBeGreaterThanOrEqual(bannerBox!.y + bannerBox!.height);
    await expect(report.getByText(/No atomic results were recovered/)).toBeVisible();
    expect(checks).toBe(1); await expect(page.getByRole("checkbox", { name: /^I have/ })).not.toBeChecked();
    await noOverflow(page, view.width); await title.scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath(view.name + "-field-report.png") });
    const availability = report.getByRole("region", { name: "Atomic field availability" });
    await availability.scrollIntoViewIfNeeded(); await availability.focus();
    if (view.name === "mobile") {
      await availability.press("ArrowRight");
      await expect.poll(() => availability.evaluate(n => n.scrollLeft)).toBeGreaterThan(0);
    }
    await page.screenshot({ path: info.outputPath(view.name + "-field-availability.png") });
    await report.getByText("Frozen-group recovery and effort", { exact: true }).click();
    await report.getByRole("combobox", { name: "Group dimension", exact: true }).selectOption("source_class");
    await expect(report.getByRole("combobox", { name: "Frozen selection group", exact: true })).toHaveValue("0");
    await noOverflow(page, view.width);
    await page.getByRole("button", { name: "Check original review documents", exact: true }).click();
    await expect(page.getByText(/Original documents checked for your account/)).toBeVisible();
    await expect(snapshot).toHaveCount(0);
    await expect(report).toHaveCount(0);
    await expect(page.getByLabel("Exact canary bundle")).toHaveValue("");
    await expect(page.getByRole("button", { name: "Verify canary and context bytes", exact: true })).toBeDisabled();
    await page.getByLabel("Exact canary bundle").setInputFiles({ name: "canary.json", mimeType: "application/json", buffer: evidenceParts().files.canary });
    denied = true; await page.getByRole("button", { name: "Verify canary and context bytes", exact: true }).click();
    await expect(page.getByText(/exact documents, response or current state could not be verified/)).toBeVisible();
    await expect(snapshot).toHaveCount(0); await expect(page.getByRole("status", { name: "Joint declaration snapshot" })).toHaveCount(0);
    expect(checks).toBe(2); expect(blocked).toEqual([]); console.log(`${view.name} field report screenshots: ${info.outputDir}`);
  });
  test(`${view.name}: joint coverage is a read-only snapshot removed after an invalidated recheck`, async ({ page, baseURL }, info) => {
    await page.setViewportSize(view); const state = await syntheticOnly(page, baseURL!); await open(page); await prepare(page);
    expect(state.coverage).toBe(0); await page.getByRole("button", { name: "Check joint declaration coverage", exact: true }).click();
    const snapshot = page.getByRole("status", { name: "Joint declaration snapshot" });
    await expect(snapshot).toBeVisible(); await expect(snapshot.getByText("Account declarations complete for this snapshot")).toBeVisible();
    await expect(page.getByRole("button", { name: "Commit exact review declaration" })).toHaveCount(0);
    await expect(page.getByRole("checkbox", { name: /^I have/ })).not.toBeChecked(); await noOverflow(page, view.width);
    await snapshot.scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath(view.name + "-joint-coverage.png") });
    state.coverageDenied = true; await page.getByRole("button", { name: "Check joint declaration coverage", exact: true }).click();
    await expect(page.getByText(/exact documents, response or current state could not be verified/)).toBeVisible();
    await expect(snapshot).toHaveCount(0); await expect(page.getByText("PRIVATE_CANARY")).toHaveCount(0);
    expect(state.coverage).toBe(2); expect(state.commits).toBe(0); expect(state.blocked).toEqual([]); expect(state.unexpected).toEqual([]);
  });
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
