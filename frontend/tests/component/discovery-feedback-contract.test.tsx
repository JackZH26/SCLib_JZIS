import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FEEDBACK_AUTHORITY, FEEDBACK_REQUEST_VERSION, feedbackChildFromDetail, feedbackRecordHref, knownFeedbackCapabilities, knownFeedbackContext, knownFeedbackPage, knownFeedbackReceipt, knownFeedbackRecovery, knownFeedbackRequest, type FeedbackRequest } from "@/lib/discovery-feedback";
import { knownDesignDetail } from "@/lib/discovery-designs";
import { expressionCanonical, expressionSha } from "@/lib/source-expressions";
import { nativeFeedbackWithChildDetail, syntheticChild, syntheticFeedbackReceipt, syntheticFeedbackWire } from "../fixtures/discovery-feedback.synthetic";

beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const clone = <T,>(value: T): T => structuredClone(value);

it("accepts the closed retained source-review capability and preserves raw evidence type without origin inference", async () => {
  const wire = await syntheticFeedbackWire();
  expect(knownFeedbackCapabilities(wire.cap, wire.designCapabilities)).toEqual(wire.cap);
  const result = await knownFeedbackContext(wire.context, wire.cap, { design: wire.context.design, materialId: wire.context.evidence.material_id, recordIndex: 2 });
  expect(result?.projection?.record.evidence_type).toBe("primary_experimental");
  expect(result?.projection?.record.knowledge_origin).toBeNull();
  expect(result?.projection?.physical_association).toBe("unestablished");
  for (const changes of [{ scientific_acceptance: true }, { experiment_executed: true }, { physical_association_established: true }, { canonical_promotions: 1 }, { baseline_kinds: ["native_property"] }, { operations: ["return_evidence"] }, { extra: "private excerpt" }]) expect(knownFeedbackCapabilities({ ...wire.cap, ...changes }, wire.designCapabilities)).toBeNull();
});

it("allows comparative material selectors but rejects manufactured execution claims and duplicate unknowns", async () => {
  const wire = await syntheticFeedbackWire();
  expect(wire.entry.baseline.material_id).not.toBe(wire.context.evidence.material_id);
  expect(knownFeedbackRequest(wire.request)).toBe(true);
  expect(knownFeedbackRequest({ ...wire.request, payload: { ...wire.request.payload, experiment_executed: true } })).toBe(false);
  expect(knownFeedbackRequest({ ...wire.request, payload: { ...wire.request.payload, unknowns: ["unresolved", "unresolved"] } })).toBe(false);
  expect(knownFeedbackRequest({ ...wire.request, payload: { ...wire.request.payload, decision: "accepted" } })).toBe(false);
});

it("checks the original source selector, canonical projection hash and finite allowlist without clipping", async () => {
  const wire = await syntheticFeedbackWire(), expected = { design: wire.context.design, materialId: wire.context.evidence.material_id, recordIndex: 2 };
  expect(await knownFeedbackContext({ ...wire.context, projection_sha256: "0".repeat(64) }, wire.cap, expected)).toBeNull();
  expect(await knownFeedbackContext({ ...wire.context, source_excerpt: "private" }, wire.cap, expected)).toBeNull();
  for (const change of [ { source_snapshot_sha256: "0".repeat(64) }, { physical_association: "equivalent" }, { record: { ...wire.context.projection!.record, tc_criterion: "x".repeat(2001) } }, { record: { ...wire.context.projection!.record, sample_id: "invented" } } ]) {
    const projection = { ...wire.context.projection, ...change }, text = expressionCanonical(projection);
    expect(await knownFeedbackContext({ ...wire.context, projection, projection_canonical_json: text, projection_sha256: await expressionSha(text) }, wire.cap, expected)).toBeNull();
  }
});

it("verifies preview, commit and original GET receipts; a dry-run cannot become a saved replay", async () => {
  const wire = await syntheticFeedbackWire();
  expect(knownFeedbackRecovery(wire.recovery)).toBe(true);
  expect(await knownFeedbackReceipt(wire.preview, wire.cap, wire.recovery, "preview")).toEqual(wire.preview);
  expect(await knownFeedbackReceipt(wire.commit, wire.cap, wire.recovery, "commit")).toEqual(wire.commit);
  expect(await knownFeedbackReceipt(wire.outcome, wire.cap, wire.recovery, "outcome")).toEqual(wire.outcome);
  expect(await knownFeedbackReceipt(wire.commit, wire.cap, wire.recovery, "outcome")).toBeNull();
  expect(await knownFeedbackReceipt({ ...wire.preview, replayed: true }, wire.cap, wire.recovery, "preview")).toBeNull();
  expect(await knownFeedbackReceipt({ ...wire.commit, receipt_sha256: "0".repeat(64) }, wire.cap, wire.recovery, "commit")).toBeNull();
  expect(await knownFeedbackReceipt({ ...wire.commit, context_json: "private full source" }, wire.cap, wire.recovery, "commit")).toBeNull();
  expect(await knownFeedbackReceipt(wire.commit, wire.cap, { ...wire.recovery, requestKey: "another-request" }, "outcome")).toBeNull();
});

it("accepts native finite decimal readings and keeps the original 65.0 proof bytes rather than canonical rewriting", async () => {
  const wire = await syntheticFeedbackWire(), context = clone(wire.context), expected = { design: context.design, materialId: context.evidence.material_id, recordIndex: 2 };
  context.projection!.record.tc_kelvin = 21.5;
  context.projection_canonical_json = JSON.stringify(context.projection).replace('"hc2_tesla":65', '"hc2_tesla":65.0');
  context.projection_sha256 = await expressionSha(context.projection_canonical_json);
  const result = await knownFeedbackContext(context, wire.cap, expected);
  expect(result?.projection?.record.tc_kelvin).toBe(21.5); expect(result?.projection_canonical_json).toBe(context.projection_canonical_json); expect(result?.projection_canonical_json).toContain('"hc2_tesla":65.0');
  const changed = clone(context); changed.projection!.record.tc_kelvin = 21.6;
  expect(await knownFeedbackContext(changed, wire.cap, expected)).toBeNull();
});

it("loads only a verified current initial child with the exact immutable feedback parent", async () => {
  const wire = nativeFeedbackWithChildDetail();
  const detail = await knownDesignDetail(wire.childDetail, wire.designCapabilities, wire.childDetail.design_id);
  expect(detail).not.toBeNull(); expect(feedbackChildFromDetail(detail!, wire.context.design)).toEqual({ design_id: wire.childDetail.design_id, revision_id: wire.childDetail.entries[0].id, record_sha256: wire.childDetail.entries[0].record_sha256 });
  for (const changes of [{ revision: 2 }, { is_head: false }, { operation: "revise" }, { eligibility: { eligible: false, reason_codes: ["source_context_changed"] } }, { parent: null }]) {
    const changed = clone(detail!); Object.assign(changed.entries[0], changes); expect(feedbackChildFromDetail(changed, wire.context.design)).toBeNull();
  }
});

it("verifies a maximum escaped-note receipt within the separate finite transport and proof limits", async () => {
  const wire = await syntheticFeedbackWire(), request = clone(wire.request);
  request.payload.findings = '"'.repeat(4000); request.payload.reason = '"'.repeat(2000); request.payload.unknowns = Array.from({ length: 9 }, (_, i) => `${i}${'"'.repeat(999)}`);
  expect(knownFeedbackRequest(request)).toBe(true);
  const preview = await syntheticFeedbackReceipt(request, wire.cap, wire.context.design, wire.context.projection_sha256), commit = { ...preview, dry_run: false, pending_ledger_written: true };
  expect(new TextEncoder().encode(JSON.stringify(commit)).length).toBeGreaterThan(256 * 1024);
  expect(new TextEncoder().encode(JSON.stringify(commit)).length).toBeLessThan(512 * 1024);
  const ref = { ...wire.recovery, requestKey: request.request_key, requestSha: commit.request_sha256, previewSha: commit.preview_sha256, receiptSha: commit.receipt_sha256, receiptId: commit.receipt_id };
  expect(await knownFeedbackReceipt(commit, wire.cap, ref, "commit")).toEqual(commit);
});

it("keeps source drift history readable without exposing obsolete source readings", async () => {
  const wire = await syntheticFeedbackWire();
  expect(await knownFeedbackPage(wire.page, wire.cap, wire.context.design.design_id, 0)).toEqual(wire.page);
  const page = clone(wire.page); page.entries[0].eligibility = { eligible: false, reason_codes: ["evidence_source_context_changed"] }; page.entries[0].projection = null; page.entries[0].projection_canonical_json = null;
  expect((await knownFeedbackPage(page, wire.cap, page.design_id, 0))?.entries[0].reason).toBe(wire.item.reason);
  const leaked = clone(page); leaked.entries[0].projection = clone(wire.item.projection); leaked.entries[0].projection_canonical_json = wire.item.projection_canonical_json;
  // Ineligible histories must not be accepted as an automatic source reader.
  expect(await knownFeedbackPage(leaked, wire.cap, page.design_id, 0)).toBeNull();
});

it("binds the saved initial child and feedback pins through a separate immutable link receipt", async () => {
  const wire = await syntheticFeedbackWire();
  const request: FeedbackRequest = { version: FEEDBACK_REQUEST_VERSION, request_key: "synthetic-follow-up:original", operation: "link_follow_up", payload: { feedback: { id: wire.item.id, record_sha256: wire.item.record_sha256 }, child: syntheticChild } };
  const preview = await syntheticFeedbackReceipt(request, wire.cap, wire.context.design), commit = { ...preview, dry_run: false, pending_ledger_written: true };
  const pins = { ...wire.recovery, requestKey: request.request_key, requestSha: commit.request_sha256, previewSha: commit.preview_sha256, receiptSha: commit.receipt_sha256, receiptId: commit.receipt_id, operation: "link_follow_up" as const, feedback: request.payload.feedback, child: syntheticChild };
  expect(knownFeedbackRecovery(pins)).toBe(true);
  expect(await knownFeedbackReceipt(commit, wire.cap, pins, "commit")).toEqual(commit);
  expect(await knownFeedbackReceipt(commit, wire.cap, { ...pins, child: { ...syntheticChild, record_sha256: "a".repeat(64) } }, "outcome")).toBeNull();
  const page = clone(wire.page); page.entries[0].follow_ups = [{ ...FEEDBACK_AUTHORITY, id: commit.receipt_id, record_sha256: commit.receipt_sha256, child: syntheticChild, eligibility: { eligible: true, reason_codes: [] }, receipt: commit }];
  expect(await knownFeedbackPage(page, wire.cap, page.design_id, 0)).toEqual(page);
  page.entries[0].follow_ups[0].physical_association_established = true as never;
  expect(await knownFeedbackPage(page, wire.cap, page.design_id, 0)).toBeNull();
});

it.each(["context", "receipt", "page"] as const)("detaches %s payload and expected actor pins before the first asynchronous proof", async kind => {
  const wire = await syntheticFeedbackWire(), cap = clone(wire.cap), expected = { design: clone(wire.context.design), materialId: wire.context.evidence.material_id, recordIndex: 2 }, recovery = clone(wire.recovery);
  let release!: () => Promise<void>, first = true;
  vi.stubGlobal("crypto", { subtle: { digest: vi.fn((algorithm: string, bytes: Uint8Array) => {
    const captured = new Uint8Array(bytes); if (!first) return webcrypto.subtle.digest(algorithm, captured); first = false;
    return new Promise<ArrayBuffer>(resolve => { release = async () => resolve(await webcrypto.subtle.digest(algorithm, captured)); });
  }) } });
  const value = clone(kind === "context" ? wire.context : kind === "receipt" ? wire.commit : wire.page), original = clone(value);
  const pending = kind === "context" ? knownFeedbackContext(value, cap, expected) : kind === "receipt" ? knownFeedbackReceipt(value, cap, recovery, "commit") : knownFeedbackPage(value, cap, wire.page.design_id, 0);
  value.physical_association_established = true as never; cap.actor_user_id = "00000000-0000-0000-0000-000000000000"; expected.materialId = "changed while awaiting"; recovery.design.record_sha256 = "0".repeat(64);
  await release(); expect(await pending).toEqual(original);
});

it("builds an exact record fragment from the raw retained index, without a sample or formula comparison", () => {
  expect(feedbackRecordHref("Ca F/Fe", 2)).toBe("/materials/Ca%20F%2FFe#retained-record-2");
  expect(feedbackRecordHref("m", -1)).toBeNull(); expect(feedbackRecordHref("m", 5000)).toBeNull();
});
