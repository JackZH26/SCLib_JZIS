import { webcrypto } from "node:crypto";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { knownConditionBatchCapabilities, knownConditionBatchDetail, knownConditionBatchManifest, knownConditionBatchPage, knownConditionBatchReceipt, knownConditionBatchRequest, type ConditionBatchExpected } from "@/lib/discovery-condition-batches";
import { expressionCanonical } from "@/lib/source-expressions";
import { copy, syntheticBatch } from "./discovery-condition-batches.synthetic";

beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
function ref(f: Awaited<ReturnType<typeof syntheticBatch>>, child = false): ConditionBatchExpected {
  const r = child ? f.childPreview : f.preview, request = child ? f.childRequest : f.request;
  return { request, manifest: f.manifest, ...(child ? { batch: f.batch, scenario: f.scenario } : {}), recovery: { actorId: f.cap.actor_user_id, requestKey: request.request_key, requestSha: r.request_sha256, previewSha: r.preview_sha256, receiptSha: r.receipt_sha256, receiptId: r.receipt_id } };
}
it("replays test-owned batch and child proofs, 15→12 generation and eight-item windows", async () => {
  const f = await syntheticBatch();
  expect(knownConditionBatchCapabilities(f.cap, f.design)).not.toBeNull(); expect(knownConditionBatchRequest(f.request)).toBe(true);
  expect(f.manifest.estimate).toMatchObject({ raw_cartesian_count: 15, unique_cartesian_count: 12 });
  for (const child of [false, true]) {
    expect(await knownConditionBatchReceipt(child ? f.childPreview : f.preview, f.cap, f.design, ref(f, child), "preview")).not.toBeNull();
    expect(await knownConditionBatchReceipt(child ? f.childCommit : f.commit, f.cap, f.design, ref(f, child), "commit")).not.toBeNull();
    expect(await knownConditionBatchReceipt(child ? f.childOutcome : f.outcome, f.cap, f.design, ref(f, child), "outcome")).not.toBeNull();
  }
  expect(await knownConditionBatchPage(f.page, f.cap, f.design, 0)).not.toBeNull();
  expect(await knownConditionBatchDetail(f.detail(), f.cap, f.design, f.batch.id, 0, f.manifest)).not.toBeNull();
  expect((await knownConditionBatchDetail(f.detail(8), f.cap, f.design, f.batch.id, 8, f.manifest))?.scenarios).toHaveLength(4);
  expect(await knownConditionBatchManifest(f.text, f.batch)).toEqual(f.manifest);
});
it("rejects open shapes, false authority, wrong current pins and preview/save confusion", async () => {
  const f = await syntheticBatch();
  expect(knownConditionBatchCapabilities({ ...f.cap, source_values: [] }, f.design)).toBeNull();
  expect(knownConditionBatchCapabilities({ ...f.cap, session_version: f.cap.session_version + 1 }, f.design)).toBeNull();
  expect(knownConditionBatchRequest({ ...f.request, payload: { ...f.request.payload, candidates: [] } })).toBe(false);
  for (const patch of [{ calculation_executed: true }, { context_json: "PRIVATE" }, { receipt_sha256: "a".repeat(64) }, { actor_session_version: f.cap.session_version + 1 }, { replayed: true }, { dry_run: false, pending_ledger_written: true }]) expect(await knownConditionBatchReceipt({ ...f.preview, ...patch }, f.cap, f.design, ref(f), "preview")).toBeNull();
  expect(await knownConditionBatchReceipt(f.preview, f.cap, f.design, ref(f), "commit")).toBeNull();
  expect(await knownConditionBatchReceipt(f.commit, f.cap, f.design, ref(f), "outcome")).toBeNull();
  expect(await knownConditionBatchReceipt(f.commit, f.cap, f.design, { ...ref(f), recovery: { ...ref(f).recovery!, requestSha: "b".repeat(64) } }, "commit")).toBeNull();
});
it("does not accept an unrelated child or altered scenarios despite well-formed fields", async () => {
  const f = await syntheticBatch();
  expect(await knownConditionBatchReceipt(f.childPreview, f.cap, f.design, { ...ref(f, true), scenario: f.manifest.scenarios[1] }, "preview")).toBeNull();
  expect(await knownConditionBatchReceipt({ ...f.childPreview, child: f.commit.child }, f.cap, f.design, ref(f, true), "preview")).toBeNull();
  const detail = copy(f.detail()); detail.scenarios[0].proposal.hypothesis = "Changed outside original artifact";
  expect(await knownConditionBatchDetail(detail, f.cap, f.design, f.batch.id, 0, f.manifest)).toBeNull();
  detail.scenarios[0].conditions.pressure.raw_gpa = "999";
  expect(await knownConditionBatchDetail(detail, f.cap, f.design, f.batch.id, 0)).toBeNull();
});
it("holds child creation while keeping historical artifact actor pins and exact export bytes", async () => {
  const f = await syntheticBatch(), current = { ...f.cap, session_version: f.cap.session_version + 1, curator_grant_id: "00000000-0000-0000-0000-000000000001" }, design = { ...f.design, session_version: current.session_version, curator_grant_id: current.curator_grant_id };
  const page = { ...f.page, session_version: current.session_version, entries: [{ ...f.batch, eligibility: { eligible: false, reason_codes: ["parent_revision_changed"] } }] };
  expect(await knownConditionBatchPage(page, current, design, 0)).not.toBeNull();
  expect(await knownConditionBatchManifest(f.text, page.entries[0])).toEqual(f.manifest);
  expect(await knownConditionBatchReceipt(f.preview, current, design, ref(f), "preview")).toBeNull();
  expect(await knownConditionBatchReceipt(f.outcome, current, design, ref(f), "outcome")).not.toBeNull();
  const unknown = copy(page); unknown.entries[0].eligibility.reason_codes = ["anything_unreviewed"];
  expect(await knownConditionBatchPage(unknown, current, design, 0)).toBeNull();
  expect(await knownConditionBatchManifest(f.text + "\n", f.batch)).toBeNull();
  expect(await knownConditionBatchManifest(expressionCanonical({ ...f.manifest, batch_saved: true }), f.batch)).toBeNull();
});
it("verifies full 8×8 artifacts and precision, ambient, zero and unspecified identities", async () => {
  const full = await syntheticBatch({ pressures: Array.from({ length: 8 }, (_, i) => ({ kind: "specified", raw_gpa: String(i) })), temperatures_k: Array.from({ length: 8 }, (_, i) => String(290 + i)) });
  expect((await knownConditionBatchManifest(full.text, full.batch))?.scenarios).toHaveLength(64);
  const f = await syntheticBatch({ pressures: [{ kind: "ambient", raw_gpa: null }, { kind: "unspecified", raw_gpa: null }, ...["0", "9007199254740992", "9007199254740993", "1.00000000000000000000000001", "1.00000000000000000000000002"].map(raw_gpa => ({ kind: "specified" as const, raw_gpa }))], temperatures_k: [null, "0"] });
  expect((await knownConditionBatchManifest(f.text, f.batch))?.scenarios).toHaveLength(14);
});
it("detaches receipt, expected candidate and actor pins before asynchronous verification", async () => {
  const f = await syntheticBatch(), original = copy(f.childPreview), expected = ref(f, true), cap = copy(f.cap), design = copy(f.design);
  let release!: () => Promise<void>, first = true;
  vi.stubGlobal("crypto", { subtle: { digest: vi.fn((algorithm: string, bytes: Uint8Array) => { const captured = new Uint8Array(bytes); if (!first) return webcrypto.subtle.digest(algorithm, captured); first = false; return new Promise<ArrayBuffer>(resolve => { release = async () => resolve(await webcrypto.subtle.digest(algorithm, captured)); }); }) } });
  const pending = knownConditionBatchReceipt(f.childPreview, cap, design, expected, "preview");
  f.childPreview.scientific_acceptance = true as never; cap.session_version += 1; expected.scenario!.proposal.hypothesis = "Mutation during proof";
  await release(); expect(await pending).toEqual(original);
});
