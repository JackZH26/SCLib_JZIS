/** Actual native HTTP bytes, tested offline. Captured JSON string wrappers
 * are data, not regenerated response documents or real scientific pilot data. */
import { createHash, webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getCurrentInspection, getGovernanceHeader, getGovernanceOutcome, getOperatorAccess, getReviewPage,
  governanceCanonical, parseCurrentInspection, parseGovernanceHeader, parseGovernanceReceipt,
  parseOperatorAccess, parseReviewPage, postGovernance, prepareGovernanceDraft, readProjectionRights,
  verifyCompleteHistory, type GovernanceDraft,
} from "@/lib/discovery-governance";

const ROOT = process.cwd();
const ASSETS = resolve(ROOT, "tests/fixtures/discovery-governance");
const raw = (name: string): string => JSON.parse(readFileSync(resolve(ASSETS, name), "utf8"));
const parsed = (name: string) => JSON.parse(raw(name));
function localFile(text: string) {
  const file = new File([text], "rights.json");
  Object.defineProperty(file, "arrayBuffer", { value: async () => new TextEncoder().encode(text).buffer });
  return file;
}
const digest = (value: string | Buffer) => createHash("sha256").update(value).digest("hex");
const provenance = JSON.parse(readFileSync(resolve(ASSETS, "provenance.json"), "utf8"));
const mutate = (text: string, change: (value: any) => void) => { const v = JSON.parse(text); change(v); return JSON.stringify(v); };
const ACCESS = (role: "reviewer" | "publisher") => parseOperatorAccess(raw(`${role}-access.response.wire.json`));
const headerName = (phase: string, role: "reviewer" | "publisher") => `${phase}-${role === "publisher" ? "publisher-" : ""}governance.response.wire.json`;
const pageName = (phase: string, role: "reviewer" | "publisher") => `${phase}-${role === "publisher" ? "publisher-" : ""}reviews.response.wire.json`;
function history(phase: string, role: "reviewer" | "publisher") {
  const access = ACCESS(role), header = parseGovernanceHeader(raw(headerName(phase, role)), access, provenance.package_id);
  const page = parseReviewPage(raw(pageName(phase, role)), access, header, null);
  return { access, header, page };
}
async function options(name: "review-approve" | "publish" | "review-reject" | "withdraw") {
  const body = parsed(`${name}-preview.request.wire.json`);
  const role = name.startsWith("review") ? "reviewer" : "publisher";
  const phase = { "review-approve": "initial", publish: "approved", "review-reject": "held", withdraw: "rejected" }[name];
  const h = history(phase, role);
  await verifyCompleteHistory(h.header, h.page.reviews);
  const positive = name === "review-approve" || name === "publish";
  return { access: h.access, header: h.header, decision: (body.decision ?? body.kind) as GovernanceDraft["decision"],
    reasonCode: body.reason_code, requestKey: body.request_key, rights: body.rights ?? [],
    representativeApproved: body.representative_selection_approved ?? false,
    disclosureApproved: body.disclosure_approved ?? false,
    current: positive ? await parseCurrentInspection(raw("current-inspection.response.wire.json"), h.header) : null,
    historyComplete: positive,
    review: body.review_id ? h.page.reviews.find(r => r.id === body.review_id)! : null };
}
async function draft(name: "review-approve" | "publish" | "review-reject" | "withdraw") {
  return prepareGovernanceDraft(await options(name));
}

beforeEach(() => { vi.stubGlobal("crypto", webcrypto); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("actual captured Discovery governance", () => {
  it("verifies all actual HTTP wire hashes and unchanged captured backend inputs", () => {
    expect(provenance.files).toHaveLength(55);
    for (const file of provenance.files) {
      const text = raw(file.file);
      expect(digest(text), file.file).toBe(file.sha256);
      expect(Buffer.byteLength(text), file.file).toBe(file.size_bytes);
    }
    for (const [file, hash] of Object.entries(provenance.source_pins)) {
      expect(digest(readFileSync(resolve(ROOT, "..", file))), file).toBe(hash);
    }
    expect(provenance.real_scientific_pilot).toBe(false);
    expect(provenance.production_publication_performed).toBe(false);
    expect(digest(readFileSync(resolve(ROOT, "tests/fixtures/capture-discovery-operators.py")))).toBe(provenance.asset_writer_sha256);
  });

  it.each(["initial", "approved", "published", "held", "rejected", "withdrawn"])("verifies complete %s histories independently for both actors", async phase => {
    for (const role of ["reviewer", "publisher"] as const) {
      const h = history(phase, role);
      await verifyCompleteHistory(h.header, h.page.reviews);
      expect(h.header.actor_user_id).toBe(h.access.actor_user_id);
      expect(h.header.current_publication_eligibility).toBe("not_checked");
      expect(h.header.has_rejection).toBe(["rejected", "withdrawn"].includes(phase));
      expect(h.header.has_withdrawal).toBe(phase === "withdrawn");
    }
  });

  it("does not equate a stable historical pin with live eligibility after a hold", async () => {
    expect(history("held", "reviewer").header.history_sha256).toBe(history("published", "reviewer").header.history_sha256);
    await expect(parseCurrentInspection(raw("held-inspection.response.wire.json"), history("held", "reviewer").header)).rejects.toThrow();
    expect(parsed("held-governance.response.wire.json")).not.toHaveProperty("payload");
    expect(parsed("held-reviews.response.wire.json")).not.toHaveProperty("rights_json");
  });

  it("verifies exact raw payload and all 31 rights targets without float reserialization", async () => {
    const inspection = await parseCurrentInspection(raw("current-inspection.response.wire.json"), history("initial", "reviewer").header);
    expect(digest(raw("current-payload.exact.json"))).toBe(inspection.payload_sha256);
    expect(inspection.rights_targets).toHaveLength(31);
    const observations = inspection.payload.rows.flatMap(r => r.cells.flatMap(c => c.observations));
    expect(observations).toHaveLength(1);
    expect(observations[0].scientific_scope_accepted).toBe(true);
    expect(observations[0].quantity.value).toBe(-0.125);
    await expect(parseCurrentInspection(mutate(raw("current-inspection.response.wire.json"), v => {
      v.payload.rows[0].cells.find((c: any) => c.observations.length).observations[0].quantity.value = 0;
    }), history("initial", "reviewer").header)).rejects.toThrow();
  });

  it.each(["review-approve", "publish", "review-reject", "withdraw"] as const)("reconstructs exact %s commands and actual backend request hash", async name => {
    const d = await draft(name);
    expect(d.previewJSON).toBe(raw(`${name}-preview.request.wire.json`));
    expect(d.commitJSON).toBe(raw(`${name}-commit.request.wire.json`));
    expect(d.recovery.requestSha256).toBe(provenance.operations[name].request_sha256);
    const preview = parseGovernanceReceipt(raw(`${name}-preview.response.wire.json`), d.recovery, false);
    const committed = parseGovernanceReceipt(raw(`${name}-commit.response.wire.json`), d.recovery, true);
    const outcome = parseGovernanceReceipt(raw(`${name}-outcome.response.wire.json`), d.recovery, true, true);
    expect(committed.id).toBe(provenance.operations[name].record_id);
    expect(outcome.id).toBe(committed.id); expect(outcome.replayed).toBe(true);
    expect(preview.request_sha256).toBe(committed.request_sha256);
    if (name === "review-approve" || name === "publish") {
      expect(parseGovernanceReceipt(raw(`${name}-held-outcome.response.wire.json`), d.recovery, true, true)).toEqual(outcome);
    }
  });

  it("keeps protective rejection and withdrawal available without current raw inspection", async () => {
    for (const name of ["review-reject", "withdraw"] as const) {
      const o = await options(name); expect(o.current).toBeNull(); expect(o.historyComplete).toBe(false);
      await expect(prepareGovernanceDraft(o)).resolves.toBeDefined();
    }
    for (const name of ["review-approve", "publish"] as const) {
      await expect(prepareGovernanceDraft({ ...await options(name), current: null })).rejects.toThrow();
      await expect(prepareGovernanceDraft({ ...await options(name), historyComplete: false })).rejects.toThrow();
    }
  });

  it.each(["foreign_actor", "unknown_field", "authority", "grant_duplicate", "wrong_scope"])("rejects access/header %s", kind => {
    const change = (v: any) => {
      if (kind === "foreign_actor") v.actor_user_id = "00000000-0000-0000-0000-000000000000";
      else if (kind === "unknown_field") v.payload = { secret: "PRIVATE_CANARY" };
      else if (kind === "authority") v.scientific_acceptance = true;
      else if (kind === "wrong_scope") v.scope = "rps_structured_bundle";
      else v.grants.push(v.grants[0]);
    };
    if (kind === "grant_duplicate") expect(() => parseOperatorAccess(mutate(raw("reviewer-access.response.wire.json"), change))).toThrow();
    else expect(() => parseGovernanceHeader(mutate(raw("initial-governance.response.wire.json"), change), ACCESS("reviewer"), provenance.package_id)).toThrow();
  });

  it("rejects cross-actor pages, truncated complete history and a forged recomputed history hash", async () => {
    const h = history("approved", "reviewer");
    expect(() => parseReviewPage(raw("approved-publisher-reviews.response.wire.json"), h.access, h.header, null)).toThrow();
    await expect(verifyCompleteHistory(h.header, h.page.reviews.slice(1))).rejects.toThrow();
    await expect(verifyCompleteHistory({ ...h.header, history_sha256: "0".repeat(64) }, h.page.reviews)).rejects.toThrow();
  });

  it.each(["2026-02-30T00:00:00.000001Z", "2026-09-09T24:00:00.000000Z", "2026-09-09T19:00:00Z"])("rejects a noncanonical or nonexistent timestamp %s", created_at => {
    expect(() => parseGovernanceHeader(mutate(raw("initial-governance.response.wire.json"), v => { v.package.created_at = created_at; }), ACCESS("reviewer"), provenance.package_id)).toThrow();
  });

  it.each(["missing", "extra", "reordered", "row_hash", "license", "basis_bool", "scope"])("rejects rights file %s", async kind => {
    const o = await options("review-approve"), rows = structuredClone(o.rights);
    if (kind === "missing") rows.pop();
    else if (kind === "extra") rows.push(rows[0]);
    else if (kind === "reordered") rows.reverse();
    else if (kind === "row_hash") rows[0].row_sha256 = "0".repeat(64);
    else if (kind === "license") rows[0].license_code = "MIT";
    else if (kind === "basis_bool") rows[0].basis_code = true;
    else rows[0].scope = "rps_structured_bundle";
    await expect(readProjectionRights(localFile(JSON.stringify(rows)), o.current!.rights_targets)).rejects.toThrow();
  });

  it("accepts the actual complete reviewed rights file and requires two independent approvals", async () => {
    const o = await options("review-approve");
    await expect(readProjectionRights(localFile(governanceCanonical(o.rights)), o.current!.rights_targets)).resolves.toEqual(o.rights);
    await expect(prepareGovernanceDraft({ ...o, representativeApproved: false })).rejects.toThrow();
    await expect(prepareGovernanceDraft({ ...o, disclosureApproved: false })).rejects.toThrow();
  });

  it.each(["package", "selection", "request", "authority", "outer_commit", "replayed"])("rejects recovered receipt %s substitution", async kind => {
    const d = await draft("publish");
    const changed = mutate(raw("publish-outcome.response.wire.json"), v => {
      if (kind === "package") v.result.package_id = "00000000-0000-0000-0000-000000000000";
      else if (kind === "selection") v.result.selection_sha256 = "0".repeat(64);
      else if (kind === "request") v.result.request_sha256 = "0".repeat(64);
      else if (kind === "authority") v.result.current_authorization_checked = true;
      else if (kind === "outer_commit") v.committed = false;
      else v.result.replayed = false;
    });
    expect(() => parseGovernanceReceipt(changed, d.recovery, true, true)).toThrow();
  });

  it.each(["{\"version\":1,\"version\":2}", "{\"__proto__\":{}}", "{\"x\":1e999}", "[]", "null"])("rejects malformed/hostile closed transport JSON %s", value => {
    expect(() => parseOperatorAccess(value)).toThrow();
  });
});

describe("mocked offline operator transport", () => {
  const response = (body: string) => new Response(body, { status: 200, headers: { "Content-Type": "application/json", "Cache-Control": "private, no-store" } });
  it("uses fixed credentialed no-store paths and exact original command bytes", async () => {
    const fetcher = vi.fn(async () => response("{}")); vi.stubGlobal("fetch", fetcher);
    const d = await draft("review-approve"), h = history("initial", "reviewer").header;
    await getOperatorAccess(); await getGovernanceHeader(h.package.id); await getReviewPage(h, null);
    await getCurrentInspection(h.package.id); await postGovernance(d, false); await postGovernance(d, true); await getGovernanceOutcome(d.recovery);
    expect(fetcher).toHaveBeenCalledTimes(7);
    for (const [url, init] of fetcher.mock.calls as unknown as [string, RequestInit][]) {
      expect(url).toContain("/ml/discovery-projections/");
      expect(init.credentials).toBe("include"); expect(init.cache).toBe("no-store"); expect(init.redirect).toBe("error");
    }
    const calls = fetcher.mock.calls as unknown as [string, RequestInit][];
    expect(calls[4][1].body).toBe(raw("review-approve-preview.request.wire.json"));
    expect(calls[5][1].body).toBe(raw("review-approve-commit.request.wire.json"));
    const outcome = new URL(calls[6][0], "https://example.invalid");
    expect(Object.fromEntries(outcome.searchParams)).toEqual(parsed("review-approve-outcome.query.json"));
    expect(calls[6][1].method).toBe("GET");
  });
  it.each([401, 403, 404, 409, 503])("does not retry %s or expose response body", async status => {
    const fetcher = vi.fn(async () => new Response("PRIVATE_REMOTE_DETAIL", { status })); vi.stubGlobal("fetch", fetcher);
    const d = await draft("withdraw");
    await expect(getGovernanceOutcome(d.recovery)).rejects.toMatchObject({ status });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("rejects invalid locators before fetch and honors pre-aborted reads", async () => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    expect(() => getGovernanceHeader("https://example.invalid/private")).toThrow();
    const controller = new AbortController(); controller.abort();
    await expect(getOperatorAccess(controller.signal)).rejects.toThrow(); expect(fetcher).not.toHaveBeenCalled();
  });
  it("enforces bounded response bytes rather than trusting a successful status", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response("x".repeat(8193))));
    await expect(getOperatorAccess()).rejects.toThrow();
  });
  it.each(["content_type", "utf8", "chunk_count"])("rejects streamed transport %s violations", async mode => {
    let value: Response;
    if (mode === "content_type") value = new Response("{}", { headers: { "Content-Type": "text/html" } });
    else if (mode === "utf8") value = new Response(new Uint8Array([0xc3, 0x28]), { headers: { "Content-Type": "application/json" } });
    else {
      let chunks = 0;
      value = new Response(new ReadableStream<Uint8Array>({ pull(controller) {
        if (++chunks <= 4097) controller.enqueue(new Uint8Array()); else controller.close();
      } }), { headers: { "Content-Type": "application/json" } });
    }
    vi.stubGlobal("fetch", vi.fn(async () => value));
    await expect(getOperatorAccess()).rejects.toThrow();
  });
});
