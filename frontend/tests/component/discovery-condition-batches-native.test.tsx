import { webcrypto, createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { createConditionSweep, type ConditionSweepAxes } from "@/lib/discovery-condition-sweep";
import { knownDesignCapabilities, knownDesignPage } from "@/lib/discovery-designs";
import { knownConditionBatchCapabilities, knownConditionBatchDetail, knownConditionBatchManifest, knownConditionBatchOutcome, knownConditionBatchPage, knownConditionBatchReceipt, knownConditionBatchRequest, knownConditionBatchSaveRecovery, type ConditionBatchExpected, type ConditionBatchSaveRecovery } from "@/lib/discovery-condition-batches";
import { expressionCanonical } from "@/lib/source-expressions";
import wire from "../fixtures/discovery-condition-batches-native.synthetic.json";
import provenance from "../fixtures/discovery-condition-batches-native.synthetic.provenance.json";

beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it("pins the original synthetic native SQL/HTTP capture bytes without reserialization", () => {
  const bytes = readFileSync("tests/fixtures/discovery-condition-batches-native.synthetic.json");
  expect(bytes.byteLength).toBe(provenance.wire_bytes); expect(createHash("sha256").update(bytes).digest("hex")).toBe(provenance.wire_sha256);
  expect(wire.synthetic_native_fixture).toBe(true); expect(provenance.scientific_validation).toBe(false); expect(provenance.calculation_executed).toBe(false);
});
it.each([false, true])("recovers the exact original native seal using only finite preview pins (child=%s)", async child => {
  const design = knownDesignCapabilities(wire.parent.capabilities, wire.parent.capabilities.actor_user_id)!;
  const cap = knownConditionBatchCapabilities(wire.capabilities, design)!, preview = child ? wire.child_preview : wire.preview, outcome = child ? wire.child_outcome : wire.outcome;
  const pins: ConditionBatchSaveRecovery = { actorId: cap.actor_user_id, requestKey: preview.request_key, requestSha: preview.request_sha256, previewSha: preview.preview_sha256, receiptSha: preview.receipt_sha256, receiptId: preview.receipt_id, inputSha: preview.input_sha256 };
  expect(knownConditionBatchSaveRecovery(pins)).toBe(true);
  expect(Object.values(pins).every(v => typeof v === "string")).toBe(true);
  expect(await knownConditionBatchOutcome(outcome, cap, design, pins)).toEqual(outcome);
  const grant = "00000000-0000-0000-0000-000000000008", refreshedDesign = { ...design, session_version: design.session_version + 1, curator_grant_id: grant }, refreshedCap = { ...cap, session_version: cap.session_version + 1, curator_grant_id: grant };
  expect(await knownConditionBatchOutcome(outcome, refreshedCap, refreshedDesign, pins)).toEqual(outcome);
  for (const key of ["actorId", "requestKey", "requestSha", "previewSha", "receiptSha", "receiptId", "inputSha"] as const) {
    const changed = { ...pins, [key]: key.endsWith("Id") ? "00000000-0000-0000-0000-000000000001" : key === "requestKey" ? "unknown-original-request" : "a".repeat(64) };
    expect(await knownConditionBatchOutcome(outcome, cap, design, changed)).toBeNull();
  }
  expect(knownConditionBatchSaveRecovery({ ...pins, manifest: wire.manifest_canonical_json })).toBe(false);
  expect(await knownConditionBatchOutcome(outcome, cap, design, { ...pins, manifest: wire.manifest_canonical_json } as ConditionBatchSaveRecovery)).toBeNull();
  expect(await knownConditionBatchOutcome(preview, cap, design, pins)).toBeNull();
  expect(await knownConditionBatchOutcome({ ...outcome, input_sha256: "a".repeat(64) }, cap, design, pins)).toBeNull();
  expect(await knownConditionBatchOutcome({ ...outcome, replayed: false }, cap, design, pins)).toBeNull();
  expect(await knownConditionBatchOutcome(outcome, { ...cap, actor_user_id: "00000000-0000-0000-0000-000000000001" }, design, pins)).toBeNull();
});
it("requires the full native child proof even when the outer original seal matches", async () => {
  const design = knownDesignCapabilities(wire.parent.capabilities, wire.parent.capabilities.actor_user_id)!, cap = knownConditionBatchCapabilities(wire.capabilities, design)!;
  const p = wire.child_preview, pins: ConditionBatchSaveRecovery = { actorId: cap.actor_user_id, requestKey: p.request_key, requestSha: p.request_sha256, previewSha: p.preview_sha256, receiptSha: p.receipt_sha256, receiptId: p.receipt_id, inputSha: p.input_sha256 };
  for (const change of [
    { child: { ...wire.child_outcome.child, receipt_sha256: "a".repeat(64) } },
    { child: { ...wire.child_outcome.child, context_canonical_json: "{}" } },
    { child: { ...wire.child_outcome.child, receipt_canonical_json: `${wire.child_outcome.child.receipt_canonical_json} ` } },
    { child: wire.parent.commit },
    { child: { ...wire.child_outcome.child, scientific_acceptance: true } },
    { candidate_sha256: "a".repeat(64) },
  ]) expect(await knownConditionBatchOutcome({ ...wire.child_outcome, ...change }, cap, design, pins)).toBeNull();
});
it("independently reconstructs the exact native 15→12 manifest and replays both receipt seals", async () => {
  const design = knownDesignCapabilities(wire.parent.capabilities, wire.parent.capabilities.actor_user_id)!;
  const parent = await knownDesignPage(wire.parent.page, design, 0); expect(parent).not.toBeNull();
  const manifest = await createConditionSweep({ capabilities: design, entry: parent!.entries[0], axes: wire.request.payload.axes as ConditionSweepAxes });
  expect(manifest.estimate).toMatchObject({ raw_cartesian_count: 15, unique_cartesian_count: 12 }); expect(expressionCanonical(manifest)).toBe(wire.manifest_canonical_json);
  const cap = knownConditionBatchCapabilities(wire.capabilities, design)!; expect(cap).not.toBeNull(); expect(knownConditionBatchRequest(wire.request)).toBe(true); expect(knownConditionBatchRequest(wire.child_request)).toBe(true);
  const page = await knownConditionBatchPage(wire.page, cap, design, 0); expect(page).not.toBeNull();
  const batch = page!.entries[0], scenario = manifest.scenarios.find(s => s.candidate_sha256 === wire.child_request.payload.candidate_sha256)!;
  expect(await knownConditionBatchManifest(wire.manifest_canonical_json, batch)).toEqual(manifest);
  expect(await knownConditionBatchDetail(wire.detail, cap, design, batch.id, 0, manifest)).not.toBeNull();
  const linked = await knownConditionBatchDetail(wire.linked_detail, cap, design, batch.id, 0, manifest); expect(linked).not.toBeNull();
  expect(linked!.scenarios.find(s => s.candidate_sha256 === scenario.candidate_sha256)?.child).toEqual({ design_id: wire.child_commit.child.design_id, revision_id: wire.child_commit.child.receipt_id, record_sha256: wire.child_commit.child.receipt_sha256 });
  for (const child of [false, true]) {
    const preview = child ? wire.child_preview : wire.preview, request = child ? wire.child_request : wire.request;
    if (!knownConditionBatchRequest(request)) throw new Error("Native request failed its closed contract");
    const expected: ConditionBatchExpected = { request, manifest, ...(child ? { batch, scenario } : {}), recovery: { actorId: cap.actor_user_id, requestKey: request.request_key, requestSha: preview.request_sha256, previewSha: preview.preview_sha256, receiptSha: preview.receipt_sha256, receiptId: preview.receipt_id } };
    expect(await knownConditionBatchReceipt(preview, cap, design, expected, "preview")).not.toBeNull();
    expect(await knownConditionBatchReceipt(child ? wire.child_commit : wire.commit, cap, design, expected, "commit")).not.toBeNull();
    expect(await knownConditionBatchReceipt(child ? wire.child_outcome : wire.outcome, cap, design, expected, "outcome")).not.toBeNull();
  }
});
