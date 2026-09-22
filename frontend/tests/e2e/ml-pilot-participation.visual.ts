import { expect, test, type Page } from "@playwright/test";
import type { PilotInput } from "@/lib/ml-pilot-participation";
import { canonical, http, syntheticReply } from "../helpers/ml-pilot-wire";

async function syntheticOnly(page: Page, baseURL: string) {
  const state = { inspection: http.initial, denied: false, previews: 0, commits: 0, outcomes: 0, loseReply: true, blocked: [] as string[], unexpected: [] as string[] };
  const origin = new URL(baseURL).origin, prefix = "/__synthetic_api/v1/ml/pilots";
  let input: PilotInput | null = null, request: unknown = null;
  await page.context().route("**/*", async route => {
    const req = route.request(), url = new URL(req.url());
    if (url.origin !== origin) { state.blocked.push(url.origin); return route.abort("blockedbyclient"); }
    if (!url.pathname.startsWith("/__synthetic_api/")) return route.continue();
    const fulfill = (raw: string, status = 200) => route.fulfill({ status, contentType: "application/json", headers: { "cache-control": "private, no-store" }, body: raw });
    if (url.pathname === "/__synthetic_api/v1/auth/me") return fulfill(JSON.stringify({ id: http.participant_id,
      email: "synthetic-pilot@example.invalid", name: "Synthetic Pilot Participant", email_verified: true, is_active: true, is_admin: false,
      is_reviewer: false, auth_provider: "local", avatar_url: null, scopes: [], institution: null, created_at: "2026-09-01T00:00:00Z" }));
    if (url.pathname === prefix + "/participant-access") { expect(req.method()).toBe("GET"); return state.denied ? fulfill('{"detail":"PRIVATE_CANARY"}', 403) : fulfill(http.access); }
    expect(req.method()).toBe("POST"); expect(url.search).toBe("");
    if (url.pathname === prefix + "/inspect") { expect(req.postDataJSON()).toEqual(http.query); return fulfill(state.inspection); }
    if ([prefix + "/participation/accept", prefix + "/participation/decisions"].includes(url.pathname)) {
      const body = req.postDataJSON(), isAccept = url.pathname.endsWith("/accept"), params = isAccept ? body.parameters : body;
      if (isAccept) {
        expect(body).toEqual({ version: "ml08-registration-upload/1.0.0", operation: "accept", selection_base64: http.selection_base64, protocol_base64: http.protocol_base64,
          selection_file_sha256: JSON.parse(http.initial).registration.selection_file_sha256, protocol_file_sha256: JSON.parse(http.initial).registration.protocol_file_sha256,
          selection_sha256: JSON.parse(http.initial).registration.selection_sha256, parameters: params });
        expect(req.headers()["x-sclib-participant-id"]).toBe(http.accept_input.participant_id); expect(req.headers()["x-sclib-participant-sha256"]).toBe(http.accept_input.participant_sha256);
      }
      if (params.dry_run) {
        state.previews++; const { dry_run: _dry, expected_intent_sha256: pin, ...fields } = params; expect(pin).toBeNull();
        input = { ...fields, decision: isAccept ? "accept" : fields.decision }; request = body;
        // Random browser request-key transport adapter only. These replies
        // are synthetic, not new database or scientific validation evidence.
        return fulfill(syntheticReply(input!, false));
      }
      state.commits++; const saved = syntheticReply(input!, true), intentSha = JSON.parse(saved).result.intent_sha256;
      const expected = JSON.parse(JSON.stringify(request)); const controls = isAccept ? expected.parameters : expected;
      controls.dry_run = false; controls.expected_intent_sha256 = intentSha; expect(body).toEqual(expected);
      return state.loseReply ? fulfill('{"detail":"SYNTHETIC_LOST_REPLY"}', 503) : fulfill(saved);
    }
    if (url.pathname === prefix + "/participation/outcome") {
      state.outcomes++; const raw = syntheticReply(input!, true, true), result = JSON.parse(raw).result;
      expect(req.postDataJSON()).toEqual({ request_key: input!.request_key, expected_intent_sha256: result.intent_sha256 });
      if (state.outcomes === 1) return fulfill('{"detail":"NOT_OBSERVED"}', 404); return fulfill(raw);
    }
    state.unexpected.push(url.pathname); return fulfill(canonical({ detail: "NO_FIXTURE" }), 503);
  });
  return state;
}
async function open(page: Page) {
  await page.goto("/dashboard/research/ml-pilots");
  const reject = page.getByRole("button", { name: /Reject optional|Reject all|Reject/i }); if (await reject.count()) await reject.first().click();
  await page.getByLabel("Registration UUID", { exact: true }).fill(http.query.registration_id);
  await page.getByLabel("Registration record SHA-256", { exact: true }).fill(http.query.registration_sha256);
  const button = page.getByRole("button", { name: "Inspect invitation", exact: true }); await button.focus(); await button.press("Enter");
  const heading = page.getByRole("heading", { name: "Current account participation", exact: true }); await expect(heading).toBeFocused();
  await expect(heading).toBeInViewport({ ratio: 1 }); const box = await heading.boundingBox(), banner = await page.getByRole("banner").boundingBox();
  expect(box!.y).toBeGreaterThanOrEqual(banner!.y + banner!.height);
}
async function prepare(page: Page, choice = "accept") {
  await page.getByRole("combobox", { name: "Participation decision" }).selectOption(choice);
  await page.getByLabel(/^Reason code/).fill("synthetic_protocol_participation");
  if (choice === "accept") {
    await page.getByLabel("Original selection file").setInputFiles({ name: "selection.json", mimeType: "application/json", buffer: Buffer.from(http.selection_base64, "base64") });
    await page.getByLabel("Original protocol file").setInputFiles({ name: "protocol.json", mimeType: "application/json", buffer: Buffer.from(http.protocol_base64, "base64") });
  }
  await page.getByRole("checkbox").check(); await page.getByRole("button", { name: "Preview participation decision" }).click();
  await expect(page.getByRole("button", { name: "Commit exact participation preview" })).toBeVisible();
}
async function noOverflow(page: Page, width: number) {
  const measured = await page.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth,
    outside: Array.from(document.querySelectorAll<HTMLElement>("main input, main select, main section"))
      .filter(n => { const r = n.getBoundingClientRect(); return r.width > 0 && (r.left < -1 || r.right > innerWidth + 1); }).map(n => n.tagName) }));
  expect(measured.width).toBe(width); expect(measured.document).toBeLessThanOrEqual(width); expect(measured.outside).toEqual([]);
}
for (const view of [{ name: "desktop", width: 1440, height: 1000 }, { name: "mobile", width: 390, height: 844 }]) {
  test(`${view.name}: exact-file acceptance and read-only lost-reply recovery`, async ({ page, baseURL }, info) => {
    await page.setViewportSize(view); const state = await syntheticOnly(page, baseURL!), errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
    await open(page); await noOverflow(page, view.width); await page.screenshot({ path: info.outputPath(view.name + "-inspection.png") });
    await prepare(page); await noOverflow(page, view.width); expect(state.previews).toBe(1); expect(state.commits).toBe(0);
    await page.getByRole("button", { name: "Commit exact participation preview" }).scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath(view.name + "-preview.png") });
    await page.getByRole("button", { name: "Commit exact participation preview" }).click();
    await page.getByRole("button", { name: "Check original outcome" }).click(); await expect(page.getByText(/No outcome was observed/)).toBeVisible();
    await expect(page.getByLabel("Registration UUID", { exact: true })).toBeDisabled(); await noOverflow(page, view.width);
    await page.screenshot({ path: info.outputPath(view.name + "-unknown.png") }); await page.getByRole("button", { name: "Check original outcome" }).click();
    await expect(page.getByRole("heading", { name: "Historical participation receipt" })).toBeVisible(); await noOverflow(page, view.width);
    await page.screenshot({ path: info.outputPath(view.name + "-recovered.png") }); expect(state.commits).toBe(1); expect(state.outcomes).toBe(2);
    expect(state.blocked).toEqual([]); expect(state.unexpected).toEqual([]); expect(errors).toEqual([]);
    console.log(`${view.name} pilot screenshots: ${info.outputDir}`);
  });
  test(`${view.name}: withdrawal remains available after role revocation`, async ({ page, baseURL }, info) => {
    await page.setViewportSize(view); const state = await syntheticOnly(page, baseURL!); state.inspection = http.revoked_inspection; state.loseReply = false;
    await open(page); await expect(page.getByRole("option", { name: "Accept exact protocol" })).toHaveJSProperty("disabled", true); await prepare(page, "withdraw");
    await expect(page.getByLabel("Original selection file")).toHaveCount(0); await noOverflow(page, view.width);
    await page.getByRole("button", { name: "Commit exact participation preview" }).click(); await expect(page.getByRole("heading", { name: "Historical participation receipt" })).toBeVisible();
    await noOverflow(page, view.width); await page.screenshot({ path: info.outputPath(view.name + "-withdrawn.png") });
    expect(state.commits).toBe(1); expect(state.blocked).toEqual([]); expect(state.unexpected).toEqual([]);
  });
  test(`${view.name}: session change clears private files and preview`, async ({ page, baseURL }, info) => {
    await page.setViewportSize(view); const state = await syntheticOnly(page, baseURL!); await open(page); await prepare(page);
    await page.evaluate(() => window.dispatchEvent(new Event("sclib:auth-change"))); state.denied = true;
    await expect(page.getByLabel("Registration UUID", { exact: true })).toHaveValue(""); await expect(page.getByLabel("Original selection file")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Commit exact participation preview" })).toHaveCount(0); await page.getByRole("button", { name: "Refresh account access" }).click();
    await expect(page.getByText("PRIVATE_CANARY")).toHaveCount(0); await noOverflow(page, view.width); await page.screenshot({ path: info.outputPath(view.name + "-denied.png") });
    expect(state.commits).toBe(0); expect(state.blocked).toEqual([]); expect(state.unexpected).toEqual([]);
  });
}
