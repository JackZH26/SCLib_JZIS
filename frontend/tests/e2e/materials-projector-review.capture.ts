import { expect, test, type Page } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import type { AmendmentList, ProposalDetail, ProposalEvidence, ProposalExport, ProposalQueue } from "../../lib/materials-proposal-review";
import { projectorReview } from "../../lib/materials-proposal-review";

type Capture = { real_postgres: boolean; real_asgi_http: boolean; capabilities: unknown; queue: ProposalQueue;
  cases: { name: string; run_id: string; pages: ProposalDetail[]; evidence: Record<string, ProposalEvidence[]>;
    amendments: { listing: AmendmentList }; export: { descriptor: ProposalExport; package_base64: string } }[] };
// Require an explicit real HTTP capture; a missing fixture is never a passing real-paper test.
if (!process.env.SCLIB_PROPOSAL_HTTP_CAPTURE) throw new Error("SCLIB_PROPOSAL_HTTP_CAPTURE is required");
const capture: Capture = JSON.parse(readFileSync(process.env.SCLIB_PROPOSAL_HTTP_CAPTURE, "utf8"));
if (!capture.real_postgres || !capture.real_asgi_http || capture.cases.length !== 3) throw new Error("Real PostgreSQL / HTTP capture required");

async function replay(page: Page, origin: string) {
  const state = { denied: false, writes: [] as string[], unexpected: [] as string[], blockedExternal: [] as string[] };
  await page.context().route("**/*", async route => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) { state.blockedExternal.push(url.origin); return route.abort("blockedbyclient"); }
    if (!url.pathname.startsWith("/__synthetic_api/")) return route.continue();
    const reply = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", headers: { "cache-control": "private, no-store" }, body: JSON.stringify(body) });
    if (route.request().method() !== "GET") { state.writes.push(url.pathname); return reply({}, 405); }
    if (url.pathname.endsWith("/auth/me")) return reply({ id: "00000000-0000-4000-8000-000000000001", email: "reviewer@example.invalid", email_verified: true, name: "Private Review QA", is_active: true, is_admin: false, is_reviewer: false, scopes: [], institution: null, country: null, age: null, research_area: null, purpose: null, bio: null, orcid: null, created_at: "2026-10-26T00:00:00Z", auth_provider: "local", avatar_url: null });
    const prefix = "/__synthetic_api/v1/research/materials-ner/";
    if (url.pathname.startsWith(prefix)) {
      if (state.denied) return reply({ detail: "PRIVATE_ERROR_DO_NOT_DISPLAY" }, 403);
      const path = url.pathname.slice(prefix.length);
      if (path === "capabilities") return reply(capture.capabilities);
      if (path === "runs") return reply(capture.queue);
      const [, id, tail] = path.split("/");
      const run = capture.cases.find(c => c.run_id === id);
      if (run && tail === "amendments") return reply(run.amendments.listing);
      if (run && tail === "export") {
        if (path.endsWith("/package")) {
          if (url.searchParams.get("expected_sha256") !== run.export.descriptor.sha256) return reply({}, 409);
          return route.fulfill({ contentType: "application/zip", headers: { "cache-control": "private, no-store" }, body: Buffer.from(run.export.package_base64, "base64") });
        }
        return reply(run.export.descriptor);
      }
      if (run && !tail) {
        const found = run.pages.find(p => p.after === url.searchParams.get("after"));
        if (found) return reply(found);
      }
      if (run && tail === "evidence") {
        const found = run.evidence[url.searchParams.get("result_id") ?? ""]?.find(p => p.after === Number(url.searchParams.get("after") ?? -1));
        if (found) return reply(found);
      }
    }
    state.unexpected.push(url.pathname); return reply({}, 404);
  });
  return state;
}

for (const viewport of [{ name: "desktop", width: 1440, height: 1000 }, { name: "mobile", width: 390, height: 844 }]) {
  for (const candidate of capture.cases) {
    test(`${viewport.name}: ${candidate.name} source findings, diagnostic export and refusal`, async ({ page, baseURL }, info) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      const state = await replay(page, new URL(baseURL!).origin), errors: string[] = [];
      page.on("pageerror", e => errors.push(e.message));
      const first = candidate.pages[0], context = projectorReview(first.coverage.projector_review, first.run)!;
      expect(context).toBeTruthy();
      await page.goto("/dashboard/research/materials-ner");
      const reject = page.getByRole("button", { name: /Reject optional|Reject all|Reject/i });
      if (await reject.count()) await reject.first().click();
      await page.getByRole("button", { name: new RegExp(candidate.run_id.slice(0, 12)) }).click();
      const section = page.getByRole("region", { name: "Model draft and source review" });
      await expect(section).toBeVisible();
      await expect(section.getByText(/Graph authored by gpt-6-luna/)).toBeVisible();
      await expect(section.getByText(/Whole-paper reading and independent scientific review are incomplete/)).toBeVisible();
      await expect(section.getByRole("heading", { name: "Missing from draft", exact: true })).toHaveCount(context.source_completeness_findings);
      const quotes = context.findings.flatMap(f => f.source_quotes.map(q => q.quote));
      expect(await section.locator("blockquote").allTextContents()).toEqual(quotes);
      const findingItems = section.getByRole("listitem");
      await expect(findingItems).toHaveCount(context.findings.length);
      for (const [index, finding] of context.findings.entries()) {
        await expect(findingItems.nth(index).getByText(finding.note, { exact: true })).toBeVisible();
        await expect(findingItems.nth(index).getByText(`Scope: ${finding.path}`, { exact: true })).toBeVisible();
      }
      if (context.disposition === "unparsed_model_graph") {
        await expect(section.getByText(/8 raw result objects remain in the diagnostic download/)).toBeVisible();
        await expect(section.getByText(/This is not evidence that the paper reports no results/)).toBeVisible();
        await expect(page.getByRole("heading", { name: /^Reported result/ })).toHaveCount(0);
      } else {
        await expect(section.getByText(/retained draft results require review/)).toBeVisible();
        const result = first.results[0];
        await page.getByRole("button", { name: `${result.local_id} · ${result.payload.quantity_kind}`, exact: true }).click();
        await expect(page.getByRole("heading", { name: "Captured source passages" })).toBeVisible();
        const pending = page.waitForEvent("download");
        await page.getByRole("button", { name: "Download visible review (JSON)" }).click();
        const downloaded = JSON.parse(readFileSync((await (await pending).path())!, "utf8"));
        expect(downloaded).toEqual({ version: "materials-proposal-review-export/1", scope: "visible_review_pages", detail: first, evidence: candidate.evidence[result.local_id][0] });
        writeFileSync(info.outputPath("visible-review.json"), JSON.stringify(downloaded, null, 2));
        await page.getByRole("button", { name: "Load source-backed amendments" }).click();
        await expect(page.getByText(/No amendment selects this result/)).toBeVisible();
      }
      await section.getByRole("heading", { name: "Model draft and source review" }).scrollIntoViewIfNeeded();
      await page.screenshot({ path: info.outputPath(`${viewport.name}-source-review.png`), fullPage: false });
      const missing = section.getByRole("heading", { name: "Missing from draft", exact: true });
      if (await missing.count()) {
        await missing.first().scrollIntoViewIfNeeded();
        await page.screenshot({ path: info.outputPath(`${viewport.name}-missing-results.png`), fullPage: false });
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
      const pendingArchive = page.waitForEvent("download");
      await page.getByRole("button", { name: "Download complete run (ZIP)" }).click();
      const archive = await pendingArchive, bytes = readFileSync((await archive.path())!);
      expect(archive.suggestedFilename()).toBe(candidate.export.descriptor.filename);
      expect(bytes).toEqual(Buffer.from(candidate.export.package_base64, "base64"));
      expect(createHash("sha256").update(bytes).digest("hex")).toBe(candidate.export.descriptor.sha256);
      writeFileSync(info.outputPath("complete-run.zip"), bytes);
      state.denied = true;
      await page.getByRole("button", { name: "Refresh access and search" }).click();
      await expect(page.getByRole("alert").filter({ hasText: "active curator or reviewer" })).toBeVisible();
      await expect(section).toHaveCount(0);
      await expect(page.getByRole("heading", { name: "Captured source passages" })).toHaveCount(0);
      await expect(page.getByText("PRIVATE_ERROR_DO_NOT_DISPLAY")).toHaveCount(0);
      expect(state.writes).toEqual([]); expect(state.unexpected).toEqual([]); expect(errors).toEqual([]);
      writeFileSync(info.outputPath("observations.json"), JSON.stringify({ ...state, viewport, errors, run_id: candidate.run_id,
        captured_http_replay: true, raw_result_objects: context.raw_result_objects, retained_rows: context.retained_result_rows,
        source_completeness_findings: context.source_completeness_findings, complete_archive_matches_http: true,
        scientific_acceptance: false, ml_training_eligible: false }, null, 2));
      console.log(`Retained projector browser artifacts: ${info.outputDir}`);
    });
  }
}
