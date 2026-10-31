import { expect, test, type Page } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { access, detail, evidence, queue } from "../helpers/materials-proposal-test-data";
import type { AmendmentDetail, AmendmentList, ProposalDetail, ProposalEvidence, ProposalExport, ProposalQueue } from "../../lib/materials-proposal-review";

type Capture = { capabilities: unknown; queue: ProposalQueue; cases: { run_id: string; pages: ProposalDetail[]; evidence: Record<string, ProposalEvidence[]>; amendments?: { listing: AmendmentList; details: Record<string, AmendmentDetail> }; export?: { descriptor: ProposalExport; package_base64: string } }[] };
const capture: Capture = process.env.SCLIB_PROPOSAL_HTTP_CAPTURE
  ? JSON.parse(readFileSync(process.env.SCLIB_PROPOSAL_HTTP_CAPTURE, "utf8"))
  : { capabilities: access, queue, cases: [{ run_id: detail.run.run_id, pages: [detail], evidence: { I1: [evidence] } }] };
const canonicalCapture: { cases: { work_id: string; result_id: string; targets: { parent_run_id: string; amendment_id: string; items: { id: string }[] }; context: { target: { result_id: string }; source_occurrences: { provider_revision: string }[] } }[] } | null = process.env.SCLIB_CANONICAL_REPLAY ? JSON.parse(readFileSync(process.env.SCLIB_CANONICAL_REPLAY, "utf8")) : null;
const selectedCase = capture.cases.find(c => {
  const accounting = c.pages[0].coverage.source_item_accounting;
  return accounting && typeof accounting === "object" && !Array.isArray(accounting)
    && Array.isArray(accounting.observation_hold_history) && accounting.observation_hold_history.length > 0;
}) ?? capture.cases.find(c => c.pages[0].entities.samples.some(s => s.payload.formula_raw === null)
  && c.pages[0].entities.condition_supports.length > 0) ?? capture.cases[0];
const selectedPage = selectedCase.pages[0], selectedResult = selectedPage.results[0];

async function replay(page: Page, origin: string) {
  const state = { denied: false, writes: [] as string[], unexpected: [] as string[], blockedExternal: [] as string[] };
  await page.context().route("**/*", async route => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) { state.blockedExternal.push(url.origin); return route.abort("blockedbyclient"); }
    if (!url.pathname.startsWith("/__synthetic_api/")) return route.continue();
    const reply = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", headers: { "cache-control": "private, no-store" }, body: JSON.stringify(body) });
    if (route.request().method() !== "GET") { state.writes.push(url.pathname); return reply({}, 405); }
    if (url.pathname.endsWith("/auth/me")) return reply({ id: "00000000-0000-4000-8000-000000000001", email: "reviewer@example.invalid", email_verified: true, name: "Private Review QA", is_active: true, is_admin: false, is_reviewer: false, scopes: [], institution: null, country: null, age: null, research_area: null, purpose: null, bio: null, orcid: null, created_at: "2026-10-22T00:00:00Z", auth_provider: "local", avatar_url: null });
    if (url.pathname.startsWith("/__synthetic_api/v1/ml/scientific-review/targets/claim/")) {
      if (state.denied) return reply({ detail: "PRIVATE_ERROR_DO_NOT_DISPLAY" }, 403);
      const matched = canonicalCapture?.cases.find(c => c.context.target.result_id === url.pathname.split("/").at(-1));
      if (matched) return reply(matched.context);
    }
    const prefix = "/__synthetic_api/v1/research/materials-ner/";
    if (url.pathname.startsWith(prefix)) {
      if (state.denied) return reply({ detail: "PRIVATE_ERROR_DO_NOT_DISPLAY" }, 403);
      const path = url.pathname.slice(prefix.length);
      if (path === "capabilities") return reply(capture.capabilities);
      if (path === "runs") return reply(capture.queue);
      const [, id, tail, amendmentId] = path.split("/");
      const run = capture.cases.find(c => c.run_id === id);
      if (run?.amendments && tail === "amendments") {
        if (!amendmentId) return reply(run.amendments.listing);
        const amended = run.amendments.details[amendmentId];
        if (amended && path.endsWith("/canonical-targets")) {
          const matched = canonicalCapture?.cases.find(c => c.targets.parent_run_id === id && c.targets.amendment_id === amendmentId && c.result_id === url.searchParams.get("result_id"));
          if (matched) return reply(matched.targets);
        }
        if (amended) return reply(amended);
      }
      if (run?.export && tail === "export") {
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
  test(`${viewport.name}: captured source review, download parity and refusal`, async ({ page, baseURL }, info) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const state = await replay(page, new URL(baseURL!).origin), errors: string[] = [];
    page.on("pageerror", e => errors.push(e.message));
    await page.goto("/dashboard/research/materials-ner");
    const reject = page.getByRole("button", { name: /Reject optional|Reject all|Reject/i });
    if (await reject.count()) await reject.first().click();
    await page.getByRole("button", { name: new RegExp(selectedCase.run_id.slice(0, 12)) }).click();
    await page.getByRole("button", { name: `${selectedResult.local_id} · ${selectedResult.payload.quantity_kind}`, exact: true }).click();
    await expect(page.getByRole("heading", { name: "Captured source passages" })).toBeVisible();
    for (const [label, value] of [["Source quantity name", selectedResult.payload.quantity_name_raw], ["Component / direction", selectedResult.payload.component_raw]]) {
      if (typeof value === "string" && value.trim()) {
        await expect(page.getByRole("article").getByText(label, { exact: true })).toBeVisible();
        await expect(page.getByRole("article").getByText(value, { exact: true })).toBeVisible();
      }
    }
    await expect(page.getByText("Formula availability", { exact: true })).toBeVisible();
    const selectedSample = selectedPage.entities.samples.find(s => s.local_id === selectedResult.payload.sample_id)!;
    if (selectedSample.payload.formula_raw === null) {
      await expect(page.getByText("Formula missingness:", { exact: false })).toBeVisible();
    } else {
      await expect(page.getByRole("article").getByText(String(selectedSample.payload.formula_raw), { exact: true })).toBeVisible();
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
    const accounting = selectedPage.coverage.source_item_accounting;
    if (accounting && typeof accounting === "object" && !Array.isArray(accounting) && accounting.available === true) {
      const section = page.getByRole("region", { name: "Source item accounting" });
      await expect(section).toBeVisible();
      const history = accounting.observation_hold_history;
      if (Array.isArray(history) && history.length) {
        const heldStatus = section.getByText("Held for review", { exact: true }).first();
        await heldStatus.scrollIntoViewIfNeeded();
        await expect(heldStatus).toBeInViewport();
        const bounds = await heldStatus.boundingBox();
        expect(bounds!.x).toBeGreaterThanOrEqual(0);
        expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport.width);
        await page.screenshot({ path: info.outputPath(`${viewport.name}-held-disposition.png`), fullPage: false });
        const first = history[0] as Record<string, unknown>;
        await section.getByText(`${first.observation_id} · original candidate and source`, { exact: true }).click();
        const quotes = first.source_quotes as { quote: string }[];
        await expect(section.getByText(quotes[0].quote, { exact: true })).toBeVisible();
        await expect(section.getByText(/not an accepted scientific exclusion or a negative measurement/)).toBeVisible();
        await section.getByRole("heading", { name: "Held candidate history" }).scrollIntoViewIfNeeded();
        await page.screenshot({ path: info.outputPath(`${viewport.name}-held-candidate.png`), fullPage: false });
      }
      await section.getByRole("heading", { name: "Source item accounting" }).scrollIntoViewIfNeeded();
      await page.screenshot({ path: info.outputPath(`${viewport.name}-source-items.png`), fullPage: false });
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
    }
    await page.getByRole("heading", { name: /^Reported result/ }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath(`${viewport.name}-result.png`), fullPage: false });
    await page.getByRole("heading", { name: "Captured source passages" }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath(`${viewport.name}-source.png`), fullPage: false });
    const pending = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download visible review (JSON)" }).click();
    const download = await pending;
    const exported = JSON.parse(readFileSync((await download.path())!, "utf8"));
    expect(exported).toEqual({ version: "materials-proposal-review-export/1", scope: "visible_review_pages", detail: selectedPage, evidence: selectedCase.evidence[selectedResult.local_id][0] });
    writeFileSync(info.outputPath(`${viewport.name}-review-export.json`), JSON.stringify(exported, null, 2));
    if (selectedCase.export) {
      const pendingArchive = page.waitForEvent("download");
      await page.getByRole("button", { name: "Download complete run (ZIP)" }).click();
      const archive = await pendingArchive, bytes = readFileSync((await archive.path())!);
      expect(archive.suggestedFilename()).toBe(selectedCase.export.descriptor.filename);
      expect(bytes).toEqual(Buffer.from(selectedCase.export.package_base64, "base64"));
      expect(createHash("sha256").update(bytes).digest("hex")).toBe(selectedCase.export.descriptor.sha256);
      writeFileSync(info.outputPath(`${viewport.name}-complete-run.zip`), bytes);
      await page.getByRole("button", { name: "Download complete run (ZIP)" }).scrollIntoViewIfNeeded();
      await page.screenshot({ path: info.outputPath(`${viewport.name}-complete-export.png`), fullPage: false });
    }
    state.denied = true;
    await page.getByRole("button", { name: "Refresh access and search" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "active curator or reviewer" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Captured source passages" })).toHaveCount(0);
    await expect(page.getByText("PRIVATE_ERROR_DO_NOT_DISPLAY")).toHaveCount(0);
    expect(state.writes).toEqual([]); expect(state.unexpected).toEqual([]); expect(errors).toEqual([]);
    writeFileSync(info.outputPath(`${viewport.name}-observations.json`), JSON.stringify({ ...state, viewport, errors, run_id: selectedCase.run_id, result_id: selectedResult.local_id, captured_http_replay: Boolean(process.env.SCLIB_PROPOSAL_HTTP_CAPTURE), export_matches_http_pages: true, complete_archive_matches_http: Boolean(selectedCase.export) }, null, 2));
    console.log(`Retained browser artifacts: ${info.outputDir}`);
  });
  for (const choice of capture.cases.flatMap(candidate => {
    const summary = candidate.amendments?.listing.items[0];
    if (!summary) return [];
    const mapping = candidate.amendments!.details[summary.id].mapping;
    return (mapping.schema === "materials-reviewed-result-mapping/1" ? summary.selected_result_ids : [summary.selected_result_ids[0]])
      .map(resultId => ({ candidate, resultId }));
  })) {
    const { candidate, resultId } = choice;
    test(`${viewport.name}: ${candidate.pages[0].run.work_id} ${resultId} amendment evidence, download and refusal`, async ({ page, baseURL }, info) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      const state = await replay(page, new URL(baseURL!).origin), errors: string[] = [];
      page.on("pageerror", e => errors.push(e.message));
      const summary = candidate.amendments!.listing.items[0], dto = candidate.amendments!.details[summary.id];
      const pageIndex = candidate.pages.findIndex(p => p.results.some(r => r.local_id === resultId));
      const result = candidate.pages[pageIndex].results.find(r => r.local_id === resultId)!;
      await page.goto("/dashboard/research/materials-ner");
      const reject = page.getByRole("button", { name: /Reject optional|Reject all|Reject/i });
      if (await reject.count()) await reject.first().click();
      await page.getByRole("button", { name: new RegExp(candidate.run_id.slice(0, 12)) }).click();
      for (let i = 0; i < pageIndex; i++) {
        await expect(page.getByRole("button", { name: "Next result page" })).toBeEnabled();
        await page.getByRole("button", { name: "Next result page" }).click();
      }
      await page.getByRole("button", { name: `${resultId} · ${result.payload.quantity_kind}`, exact: true }).click();
      await expect(page.getByRole("heading", { name: "Captured source passages" })).toBeVisible();
      await page.getByRole("button", { name: "Load source-backed amendments" }).click();
      await page.getByRole("button", { name: new RegExp(`^Inspect amendment ${summary.id.slice(0, 12)}`) }).click();
      const reading = page.getByTestId("amendment-reading");
      await expect(reading).toBeVisible();
      await expect(reading.getByText(/Retained source descriptors can differ/)).toBeVisible();
      await expect(reading.getByText(/Canonical identity: independent review pending/)).toBeVisible();
      if (dto.mapping.schema === "materials-reviewed-result-mapping/1") {
        await expect(reading.getByText(/Canonical quantity mapping is pending/)).toBeVisible();
        await expect(reading.getByRole("button", { name: "Find stored candidates" })).toHaveCount(0);
        const source = reading.getByRole("region", { name: "Source findings pending reassessment" });
        await expect(source.getByRole("listitem")).toHaveCount(dto.amendment.source_review!.findings.length);
        await expect(source.getByRole("heading", { name: "Missing from draft", exact: true })).toHaveCount(2);
        expect(await source.locator("blockquote").allTextContents()).toEqual(dto.amendment.source_review!.findings.flatMap(f => f.anchors.map(a => a.quote)));
        await source.getByRole("heading", { name: "Source findings pending reassessment" }).scrollIntoViewIfNeeded();
        await page.screenshot({ path: info.outputPath(`${viewport.name}-pending-source-findings.png`), fullPage: false });
        const conditions = reading.getByRole("region", { name: "Conditions", exact: true });
        await expect(conditions.getByText("Role: measurement", { exact: true })).toBeVisible();
        const state = dto.amendment.graph.states[0];
        const revisedRole = (state.conditions as { role: string }[])[0].role.replaceAll("_", " ");
        await expect(conditions.getByText(`Role: ${revisedRole}`, { exact: true })).toBeVisible();
        await expect(conditions.getByText("Unit: K", { exact: true })).toHaveCount(2);
        const amendedResult = dto.amendment.graph.results.find(r => r.id === resultId)!;
        const dependencies = amendedResult.dependencies as { result_id: string; relation: string }[];
        if (dependencies.length) {
          const region = reading.getByRole("region", { name: "Result dependencies", exact: true });
          for (const dependency of dependencies) {
            await expect(region.getByText(`Result: ${dependency.result_id}`, { exact: true })).toHaveCount(2);
            await expect(region.getByText(`Relation: ${dependency.relation.replaceAll("_", " ")}`, { exact: true })).toHaveCount(2);
          }
        }
        await conditions.scrollIntoViewIfNeeded();
        await page.screenshot({ path: info.outputPath(`${viewport.name}-condition-correction.png`), fullPage: false });
      }
      const canonical = canonicalCapture?.cases.find(c => c.work_id === candidate.pages[0].run.work_id && c.result_id === resultId);
      if (canonical) {
        await reading.getByRole("button", { name: "Find stored candidates" }).click();
        await reading.getByRole("button", { name: /^Read registered sources/ }).click();
        const sources = reading.getByTestId("canonical-source-reading");
        await expect(sources).toBeVisible();
        await expect(sources.getByText(new RegExp(`Registered version: ${canonical.context.source_occurrences[0].provider_revision}`))).toBeVisible();
        await expect(sources.getByText(/Source binding: pending/)).toBeVisible();
        await sources.scrollIntoViewIfNeeded();
        await page.screenshot({ path: info.outputPath(`${viewport.name}-registered-sources.png`), fullPage: false });
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
      }
      await reading.getByRole("heading", { name: "Prediction and revision" }).scrollIntoViewIfNeeded();
      await page.screenshot({ path: info.outputPath(`${viewport.name}-comparison.png`), fullPage: false });
      const [fieldName, field] = Object.entries(dto.amendment.reviews.find(r => r.result_id === resultId)!.fields).find(([, value]) => value.anchors.length)!;
      const summaryElement = reading.locator("summary").filter({ hasText: `${fieldName.replaceAll("_", " ")} · ${field.disposition.replaceAll("_", " ")}` });
      await summaryElement.click();
      const quoteElement = summaryElement.locator("..").locator("blockquote").first();
      expect(await quoteElement.textContent()).toBe(field.anchors[0].quote);
      await summaryElement.scrollIntoViewIfNeeded();
      await expect(quoteElement).toBeVisible();
      await page.screenshot({ path: info.outputPath(`${viewport.name}-field-source.png`), fullPage: false });
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
      const pending = page.waitForEvent("download");
      await reading.getByRole("button", { name: "Download amendment (JSON)" }).click();
      const download = await pending, bytes = readFileSync((await download.path())!);
      expect(download.suggestedFilename()).toBe(`materials-amendment-${summary.id}.json`);
      expect(JSON.parse(bytes.toString("utf8"))).toEqual(dto);
      writeFileSync(info.outputPath(`${viewport.name}-amendment.json`), bytes);
      state.denied = true;
      await reading.getByRole("button", { name: canonical ? "Find stored candidates" : "Download amendment (JSON)" }).click();
      await expect(page.getByRole("alert").filter({ hasText: "active curator or reviewer" })).toBeVisible();
      await expect(page.getByTestId("amendment-reading")).toHaveCount(0);
      await expect(page.getByRole("heading", { name: "Captured source passages" })).toHaveCount(0);
      expect(state.writes).toEqual([]); expect(state.unexpected).toEqual([]); expect(errors).toEqual([]);
      writeFileSync(info.outputPath(`${viewport.name}-observations.json`), JSON.stringify({ ...state, errors, viewport, run_id: candidate.run_id,
        result_id: resultId, amendment_id: summary.id, fixture_replay: true, fresh_download_matches_amendment_dto: true }, null, 2));
      console.log(`Retained amendment browser artifacts: ${info.outputDir}`);
    });
  }
}
