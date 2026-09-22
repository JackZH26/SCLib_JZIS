import { expect, test, type Page } from "@playwright/test";
import { canonical, http, reviewText, syntheticReply, wire } from "../helpers/ml-run-wire";

type Json = Record<string, any>;
const actor = { owner: JSON.parse(http.requester_access), reviewer: JSON.parse(http.approver_access) };
const browserReviewText = reviewText + '\nΔTc / 数据 / 🧪 <script>window.__unsafeEvidence = true</script>';
// In-memory browser double, not a DB, permission grant, actual-worker check or
// new native capture. Original host-document strings remain byte-for-byte.
function backend() {
  return { plan: JSON.parse(http.plan_committed).result.plan as Json, head: null as Json | null,
    previews: [] as Json[], commits: [] as Json[], receipts: new Map<string, Json>(), outcomes: 0, checks: 0,
    evidence: new Map<string, { decision: Json; text: string }>(), purged: new Set<string>(), purgeCalls: 0,
    losePurgeReply: false, loseReply: false, denyOwner: false, denyReviewer: false, blocked: [] as string[], unexpected: [] as string[] };
}
async function syntheticOnly(page: Page, baseURL: string, who: "owner" | "reviewer", state: ReturnType<typeof backend>) {
  const origin = new URL(baseURL).origin, prefix = "/__synthetic_api/v1/ml/use/runs";
  await page.clock.setFixedTime(new Date(JSON.parse(http.plan_committed).result.plan.created_at));
  await page.context().route("**/*", async route => {
    const req = route.request(), url = new URL(req.url());
    if (url.origin !== origin) { state.blocked.push(url.origin); return route.abort("blockedbyclient"); }
    if (!url.pathname.startsWith("/__synthetic_api/")) return route.continue();
    const fulfill = (raw: string, status = 200) => route.fulfill({ status, contentType: "application/json", headers: { "cache-control": "private, no-store" }, body: raw });
    if (url.pathname === "/__synthetic_api/v1/auth/me") return fulfill(JSON.stringify({ id: actor[who].actor_user_id,
      email: `synthetic-${who}@example.invalid`, name: `Synthetic ${who}`, email_verified: true, is_active: true, is_admin: true,
      is_reviewer: false, auth_provider: "local", avatar_url: null, scopes: [], institution: null, created_at: "2026-09-01T00:00:00Z" }));
    const endpoint = url.pathname.slice(prefix.length);
    if (!url.pathname.startsWith(prefix)) { state.unexpected.push(url.pathname); return fulfill("{}", 503); }
    if (endpoint.endsWith("-access")) {
      expect(req.method()).toBe("GET");
      const permitted = who === "owner" ? endpoint === "/requester-access" && !state.denyOwner : endpoint === "/approver-access" && !state.denyReviewer;
      return permitted ? fulfill(who === "owner" ? http.requester_access : http.approver_access) : fulfill('{"detail":"PRIVATE_CANARY"}', 403);
    }
    expect(req.method()).toBe("POST"); expect(url.search).toBe(""); const body = req.postDataJSON();
    const ref = { plan_id: state.plan.id, plan_sha256: state.plan.record_sha256 };
    if (endpoint === "/evidence/read" || endpoint === "/evidence/purge") {
      expect(who).toBe("reviewer"); const stored = state.evidence.get(body.decision_id); expect(stored).toBeDefined();
      expect(body).toEqual({ decision_id: stored!.decision.id, decision_sha256: stored!.decision.record_sha256 });
      if (endpoint === "/evidence/read") {
        if (state.purged.has(body.decision_id)) return fulfill('{"detail":"NOT_OBSERVED"}', 404);
        const v = JSON.parse(wire("evidence_read")); Object.assign(v, body, { decision: stored!.decision, text: stored!.text,
          content_sha256: stored!.decision.evidence_sha256, size_bytes: new TextEncoder().encode(stored!.text).length, ...ref });
        return fulfill(canonical(v));
      }
      const replayed = state.purged.has(body.decision_id); state.purged.add(body.decision_id); state.purgeCalls++;
      if (state.losePurgeReply) { state.losePurgeReply = false; return fulfill('{"detail":"SYNTHETIC_LOST_PURGE_REPLY"}', 503); }
      const v = JSON.parse(wire("evidence_purge")); Object.assign(v.result, body, { replayed }); return fulfill(canonical(v));
    }
    if (endpoint === "/context") { expect(who).toBe("owner"); expect(body).toEqual(http.submission_query); return fulfill(http.context); }
    if (endpoint === "/inspect") {
      expect(who).toBe("reviewer"); expect(body).toEqual(ref);
      const v = JSON.parse(http.unreviewed); v.plan = state.plan; v.head = state.head;
      v.recorded_approval_status = state.head === null ? "unreviewed" : state.head.decision === "approve" ? (state.purged.has(state.head.id) ? "evidence_unavailable" : "conditional_approval_recorded") : state.head.decision === "revoke" ? "revoked" : "denied";
      return fulfill(canonical(v));
    }
    if (endpoint === "/plans" || endpoint === "/decisions") {
      const kind = endpoint === "/plans" ? "plan" : "decision"; expect(who).toBe(kind === "plan" ? "owner" : "reviewer");
      const { dry_run, expected_intent_sha256, ...input } = body;
      if (dry_run) {
        expect(expected_intent_sha256).toBeUndefined();
        if (kind === "plan") expect(input).toEqual({ ...http.plan_input, request_key: input.request_key });
        else { expect(input.plan_id).toBe(ref.plan_id); expect(input.plan_sha256).toBe(ref.plan_sha256);
          expect(input.approver_grant_id).toBe(actor.reviewer.approver_grant_id); expect(input.curator_grant_id).toBe(actor.reviewer.curator_grant_id);
          expect(input.supersedes_id).toBe(state.head?.id ?? null); expect(input.supersedes_sha256).toBe(state.head?.record_sha256 ?? null); }
        state.previews.push({ kind, input }); return fulfill(syntheticReply(kind, input, false));
      }
      expect(state.previews.at(-1)).toEqual({ kind, input }); const saved = JSON.parse(syntheticReply(kind, input, true));
      expect(expected_intent_sha256).toBe(saved.result.intent_sha256); state.commits.push({ kind, input });
      state.receipts.set(input.request_key, saved);
      if (kind === "plan") { state.plan = saved.result.plan; state.head = null; } else state.head = saved.result.decision;
      if (kind === "decision" && input.decision === "approve") state.evidence.set(saved.result.decision.id, { decision: saved.result.decision, text: input.evidence_text });
      if (state.loseReply) { state.loseReply = false; return fulfill('{"detail":"SYNTHETIC_LOST_REPLY"}', 503); }
      return fulfill(canonical(saved));
    }
    if (endpoint.endsWith("/outcome")) {
      expect(endpoint).toBe(who === "owner" ? "/plans/outcome" : "/decisions/outcome"); state.outcomes++;
      const saved = state.receipts.get(body.request_key); expect(saved).toBeDefined(); expect(body).toEqual({ request_key: saved!.result.intent.request_key, expected_intent_sha256: saved!.result.intent_sha256 });
      if (state.outcomes === 1) return fulfill('{"detail":"NOT_OBSERVED"}', 404);
      const copy = structuredClone(saved); copy.result.replayed = true; return fulfill(canonical(copy));
    }
    if (endpoint === "/check") {
      expect(who).toBe("owner"); expect(body).toEqual(ref); state.checks++;
      // Use the native snapshot from this decision stage, not the earlier
      // unreviewed timestamp, which would predate the recorded decision.
      const missing = state.head?.decision === "approve" && state.purged.has(state.head.id);
      const v = JSON.parse(missing ? wire("readiness_evidence_missing") : state.head ? wire("readiness_" + state.head.decision) : http.readiness_unreviewed); Object.assign(v, ref); v.approval = state.head;
      v.approval_status = state.head === null ? "unreviewed" : state.head.decision === "approve" ? (missing ? "evidence_unavailable" : "conditional_approval_recorded") : state.head.decision === "revoke" ? "revoked" : "denied";
      v.conditional_run_approval_current = state.head?.decision === "approve" && !missing;
      v.blockers = v.blockers.filter((s: string) => !s.startsWith("exact_plan_approval_"));
      if (!v.conditional_run_approval_current) v.blockers.push("exact_plan_approval_" + v.approval_status);
      return fulfill(canonical(v));
    }
    state.unexpected.push(endpoint); return fulfill("{}", 503);
  });
}
async function open(page: Page, who: "owner" | "reviewer") {
  await page.goto("/dashboard/research/ml-runs"); const reject = page.getByRole("button", { name: /Reject optional|Reject all|Reject/i });
  if (await reject.count()) await reject.first().click();
  await expect(page.getByRole("button", { name: "Refresh workflow access" })).toBeEnabled();
  if (who === "reviewer") await page.getByRole("combobox", { name: "Workflow role", exact: true }).selectOption("decision");
  await expect(page.getByLabel(who === "owner" ? "Submission UUID" : "Run plan UUID", { exact: true })).toBeEnabled();
}
async function focusVisible(page: Page, name: string) {
  const heading = page.getByRole("heading", { name, exact: true }); await expect(heading).toBeFocused(); await expect(heading).toBeInViewport({ ratio: 1 });
  const box = await heading.boundingBox(), banner = await page.getByRole("banner").boundingBox(); expect(box!.y).toBeGreaterThanOrEqual(banner!.y + banner!.height);
}
async function ownerPreview(page: Page) {
  await page.getByLabel("Submission UUID", { exact: true }).fill(http.submission_query.submission_id);
  await page.getByLabel("Submission record SHA-256", { exact: true }).fill(http.submission_query.submission_sha256);
  await page.getByLabel("Inventory SHA-256", { exact: true }).fill(http.submission_query.inventory_sha256);
  const load = page.getByRole("button", { name: "Load run context" }); await load.focus(); await load.press("Enter");
  await focusVisible(page, "Review exact run inputs");
  await expect(page.getByLabel(/^CPU budget/)).toHaveValue("");
  await page.getByLabel(/^CPU budget/).fill(String(http.plan_input.cpu_seconds)); await page.getByLabel(/^Wall-time budget/).fill(String(http.plan_input.wall_seconds));
  await page.getByLabel(/^Memory budget/).fill(String(http.plan_input.memory_mib));
  await page.getByRole("checkbox").check(); await page.getByRole("button", { name: "Preview run plan", exact: true }).click();
  await expect(page.getByRole("button", { name: "Commit exact run preview" })).toBeVisible();
}
async function reviewPreview(page: Page, state: ReturnType<typeof backend>, decision: "approve" | "revoke" | "deny") {
  await page.getByLabel("Run plan UUID", { exact: true }).fill(state.plan.id);
  await page.getByLabel("Run plan record SHA-256", { exact: true }).fill(state.plan.record_sha256);
  const load = page.getByRole("button", { name: "Inspect exact run plan" }); await load.focus(); await load.press("Enter");
  await focusVisible(page, "Review independent run contract");
  await expect(page.getByRole("combobox", { name: "Review decision", exact: true })).toHaveValue("");
  await page.getByRole("combobox", { name: "Review decision", exact: true }).selectOption(decision);
  await page.getByLabel(/^Review reason code/).fill(http.approve_input.reason_code);
  if (decision === "approve") { await page.getByLabel(/^Private run-review text/).fill(browserReviewText); await page.getByLabel(/^Approval expiry/).fill(String(http.approve_input.expires_epoch)); }
  await page.getByRole("checkbox").check(); await page.getByRole("button", { name: "Preview run decision", exact: true }).click();
  await expect(page.getByRole("button", { name: "Commit exact run preview" })).toBeVisible();
}
async function noOverflow(page: Page, width: number) {
  const measured = await page.evaluate(() => ({ width: innerWidth, doc: document.documentElement.scrollWidth,
    outside: Array.from(document.querySelectorAll<HTMLElement>("main input, main select, main section"))
      .filter(n => { const r = n.getBoundingClientRect(); return r.width > 0 && (r.left < -1 || r.right > innerWidth + 1); }).map(n => n.tagName) }));
  expect(measured.width).toBe(width); expect(measured.doc).toBeLessThanOrEqual(width); expect(measured.outside).toEqual([]);
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  // The English-default rule permits verbatim user-authored review text.
  // Exempt only this exact synthetic source, not arbitrary preformatted/UI text.
  let ownedText = await page.locator("main").innerText();
  for (const source of await page.getByRole("region", { name: "Private review evidence", exact: true }).locator("pre").allTextContents()) {
    expect(source).toBe(browserReviewText); ownedText = ownedText.replace(source, "");
  }
  expect(ownedText).not.toMatch(/[\u4e00-\u9fff]/);
}
for (const view of [{ name: "desktop", width: 1440, height: 1000 }, { name: "mobile", width: 390, height: 844 }]) {
  test(`${view.name}: independent-account handoff, conditional approval, revocation and denial`, async ({ page, browser, baseURL }, info) => {
    const state = backend(), errors: string[] = []; await page.setViewportSize(view); page.on("pageerror", e => errors.push(e.message));
    await syntheticOnly(page, baseURL!, "owner", state); await open(page, "owner"); await ownerPreview(page); await noOverflow(page, view.width);
    await page.getByRole("button", { name: "Commit exact run preview" }).scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath(view.name + "-owner-preview.png") });
    expect(state.commits).toHaveLength(0); await page.getByRole("button", { name: "Commit exact run preview" }).click();
    await expect(page.getByRole("heading", { name: "Historical run receipt" })).toBeVisible(); expect(state.checks).toBe(0);
    const reviewerContext = await browser.newContext({ viewport: view, serviceWorkers: "block", baseURL });
    try {
      const reviewer = await reviewerContext.newPage(); reviewer.on("pageerror", e => errors.push(e.message));
      await syntheticOnly(reviewer, baseURL!, "reviewer", state); await open(reviewer, "reviewer");
      expect(actor.owner.actor_user_id).not.toBe(actor.reviewer.actor_user_id);
      for (const decision of ["approve", "revoke", "deny"] as const) {
        await reviewPreview(reviewer, state, decision); await noOverflow(reviewer, view.width);
        await reviewer.getByRole("button", { name: "Commit exact run preview" }).scrollIntoViewIfNeeded();
        await reviewer.screenshot({ path: info.outputPath(view.name + "-" + decision + "-preview.png") });
        await reviewer.getByRole("button", { name: "Commit exact run preview" }).click(); await expect(reviewer.getByRole("heading", { name: "Historical run receipt" })).toBeVisible();
        await page.getByRole("button", { name: "Check current run readiness" }).click();
        const region = page.getByRole("region", { name: "Current run readiness" });
        await expect(region.getByText(decision === "approve" ? "Conditional approval recorded" : decision === "revoke" ? "Revoked" : "Denied", { exact: true })).toBeVisible();
        await expect(region.getByText("Not satisfied", { exact: true })).toBeVisible(); await expect(region.getByText("guarded execution consumer unavailable")).toBeVisible();
        await noOverflow(page, view.width); await region.scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath(view.name + "-" + decision + "-readiness.png") });
        if (decision === "approve") {
          await reviewer.getByRole("button", { name: "Manage private review evidence" }).click();
          const evidence = reviewer.getByRole("region", { name: "Private review evidence", exact: true });
          await evidence.getByLabel("Evidence decision UUID", { exact: true }).fill(state.head!.id);
          await evidence.getByLabel("Evidence decision record SHA-256", { exact: true }).fill(state.head!.record_sha256);
          await evidence.getByRole("button", { name: "Read exact private review" }).click();
          await expect(evidence.locator("pre")).toHaveText(browserReviewText); await noOverflow(reviewer, view.width);
          expect(await reviewer.evaluate(() => "__unsafeEvidence" in window)).toBe(false);
          await evidence.scrollIntoViewIfNeeded(); await reviewer.screenshot({ path: info.outputPath(view.name + "-private-evidence.png") });
          state.losePurgeReply = true; await evidence.getByRole("checkbox").check();
          await evidence.getByRole("button", { name: "Purge exact private review" }).click(); await expect(evidence.getByText(/Purge outcome is unknown/)).toBeVisible();
          await expect(evidence.getByLabel("Evidence decision UUID", { exact: true })).toBeDisabled(); expect(state.purgeCalls).toBe(1);
          await evidence.getByRole("button", { name: "Retry identical evidence purge" }).click();
          await expect(evidence.getByText(/Private text purge verified \(existing receipt\)/)).toBeVisible(); expect(state.purgeCalls).toBe(2);
          await page.getByRole("button", { name: "Check current run readiness" }).click();
          await expect(region.getByText("Review evidence unavailable", { exact: true })).toBeVisible();
          await evidence.getByRole("button", { name: "Close and clear evidence panel" }).click();
        }
      }
    } finally { await reviewerContext.close(); }
    expect(state.commits).toHaveLength(4); expect(state.checks).toBe(4); expect(state.blocked).toEqual([]); expect(state.unexpected).toEqual([]); expect(errors).toEqual([]);
    console.log(`${view.name} ML run handoff screenshots: ${info.outputDir}`);
  });
  test(`${view.name}: lost commit reply, ambiguous read, exact recovery and admission clearing`, async ({ page, baseURL }, info) => {
    const state = backend(); state.loseReply = true; await page.setViewportSize(view); await syntheticOnly(page, baseURL!, "owner", state); await open(page, "owner"); await ownerPreview(page);
    await page.getByRole("button", { name: "Commit exact run preview" }).click(); await expect(page.getByText(/Commit outcome is unknown/)).toBeVisible();
    await page.getByRole("button", { name: "Check original run outcome" }).click(); await expect(page.getByText(/No outcome was observed/)).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Workflow role", exact: true })).toBeDisabled(); await noOverflow(page, view.width);
    await page.screenshot({ path: info.outputPath(view.name + "-unknown.png") });
    await page.getByRole("button", { name: "Check original run outcome" }).click(); await expect(page.getByRole("heading", { name: "Historical run receipt" })).toBeVisible();
    expect(state.commits).toHaveLength(1); expect(state.outcomes).toBe(2); state.denyOwner = true;
    await page.getByRole("button", { name: "Refresh workflow access" }).click(); await expect(page.getByText(/Access changed/)).toBeVisible();
    await expect(page.getByLabel("Submission UUID", { exact: true })).toHaveValue(""); await expect(page.getByRole("heading", { name: "Historical run receipt" })).toHaveCount(0);
    await expect(page.getByText("PRIVATE_CANARY", { exact: true })).toHaveCount(0); await noOverflow(page, view.width);
    await page.screenshot({ path: info.outputPath(view.name + "-denied.png") }); expect(state.blocked).toEqual([]); expect(state.unexpected).toEqual([]);
  });
}
