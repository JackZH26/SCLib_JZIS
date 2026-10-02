import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { expressionSha } from "@/lib/source-expressions";
import { knownReviewCapabilities, knownReviewContext, knownReviewEffective, knownReviewReceipt, knownReviewRequest, reviewRecovery, reviewSourceValue, reviewFieldSourceSelection, loadReviewRecovery, retainReviewRecovery, clearReviewRecovery } from "@/lib/material-field-review";
import { reviewActor, reviewCap, reviewExpression, reviewTarget, syntheticReviewCanonical, syntheticReviewContext, syntheticReviewEffective, syntheticReviewReceipt, syntheticReviewRequest } from "../helpers/material-field-review-test-data";
beforeEach(() => { sessionStorage.clear(); vi.stubGlobal("crypto", webcrypto); });
afterEach(() => vi.unstubAllGlobals());
const selector = { targetId: reviewTarget, expressionId: reviewExpression, fieldId: "tc_criterion" as const, componentKind: "condition" as const, componentIndex: 0 };
describe("Source-scoped field fidelity contracts", () => {
  it("maps genuine frozen source field names to their distinct retained targets and exact component positions", () => {
    // Field names and positions from the synthetic Python/native source-v2 Tc fixture.
    const projection = { field_id: "tc_kelvin", conditions: ["method_statement", "criterion_statement", "pressure_gpa"].map(field_id => ({ field_id, role: "reported_result_condition" })) };
    expect(reviewFieldSourceSelection("tc_criterion", projection)).toEqual({ field: "tc_criterion", kind: "condition", index: "1" });
    expect(reviewFieldSourceSelection("measurement_method", projection)).toEqual({ field: "measurement_method", kind: "condition", index: "0" });
    expect(reviewFieldSourceSelection("pressure_gpa", projection)).toEqual({ field: "pressure_gpa", kind: "condition", index: "2" });
    expect(reviewFieldSourceSelection("measurement_method", { field_id: "method_statement", conditions: [] })).toEqual({ field: "measurement_method", kind: "value", index: "0" });
    expect(reviewFieldSourceSelection("hc2_tesla", projection)).toBeNull();
    expect(reviewFieldSourceSelection("tc_criterion", { ...projection, conditions: [...projection.conditions, projection.conditions[1]] })).toBeNull();
    expect(reviewFieldSourceSelection("pressure_gpa", { ...projection, conditions: [{ field_id: "pressure_gpa", role: "study_extent" }] })).toBeNull();
    expect(reviewFieldSourceSelection("measurement_method", { field_id: "measurement_method", conditions: [] })).toBeNull();
  });
  it("preserves inline units from the frozen Python quantity compiler and appends only separately selected printed units", () => {
    // Frozen quantity('2 GPa', None, 'pressure_gpa') and quantity('2', 'GPa', 'pressure_gpa').
    const value = { raw_value: "2 GPa", raw_unit: "GPa", value: 2, unit: "GPa", uncertainty: null, uncertainty_interpretation: null, approximate: false, relation: "exact", status: "parsed", unit_basis: "source_printed" };
    expect(reviewSourceValue({ value, unit_spans: [] })).toBe("2 GPa");
    expect(reviewSourceValue({ value, unit_spans: [{ start: 2, end: 5, sha256: "a".repeat(64) }] })).toBe("2 GPa");
    expect(reviewSourceValue({ value: { ...value, raw_value: "2" }, unit_spans: [{ start: 2, end: 5, sha256: "a".repeat(64) }] })).toBe("2 GPa");
    expect(reviewSourceValue({ value: { ...value, raw_value: "2" }, unit_spans: [] })).toBe("2");
  });
  it("requires a Tc companion only for a standalone method value", async () => {
    const original = await syntheticReviewRequest();
    const item = { ...original.items[0], field_id: "measurement_method" as const, component: { kind: "value" as const, index: null, field_id: "method_statement", role: null } };
    expect(knownReviewRequest({ ...original, items: [item] })).toBe(false);
    expect(knownReviewRequest({ ...original, items: [{ ...item, tc_expression: { id: reviewTarget, record_sha256: "a".repeat(64), projection_sha256: "b".repeat(64) } }] })).toBe(true);
  });
  it("retains only closed actor-scoped recovery pins and rejects injected payloads", async () => {
    const request = await syntheticReviewRequest(), preview = await syntheticReviewReceipt(request);
    const ref = { ...await reviewRecovery(request, reviewCap), previewSha: preview.preview_sha256, receiptId: preview.receipt_id, receiptSha: preview.receipt_sha256 };
    retainReviewRecovery(ref);
    expect(loadReviewRecovery(reviewActor)).toEqual(ref);
    expect(loadReviewRecovery(reviewTarget)).toBeNull();
    expect(sessionStorage.getItem(sessionStorage.key(0)!)).not.toContain("resistive onset");
    sessionStorage.setItem(sessionStorage.key(0)!, JSON.stringify({ ...ref, source_value: "private source" }));
    expect(() => loadReviewRecovery(reviewActor)).toThrow();
    clearReviewRecovery(reviewActor);
    expect(loadReviewRecovery(reviewActor)).toBeNull();
  });
  it("accepts only exact actor, profile, closed capabilities and false scientific authorities", () => { expect(knownReviewCapabilities(reviewCap, reviewActor)).toEqual(reviewCap); for (const patch of [{ actor_user_id: reviewTarget }, { session_version: -1 }, { scientific_acceptance: true }, { canonical_promotions: 1 }, { ml_training_approved: true }, { public_release_authorized: true }, { profile_version: "unknown" }, { field_ids: ["tc_criterion"] }, { extra: true }]) expect(knownReviewCapabilities({ ...reviewCap, ...patch }, reviewActor)).toBeNull(); });
  it("binds the original target, selected condition and all three exact member hashes", async () => { const context = await syntheticReviewContext(); expect(await knownReviewContext(context, reviewCap, selector)).toEqual(context); for (const patch of [{ targetId: reviewExpression }, { expressionId: reviewTarget }, { componentIndex: 1 }, { componentKind: "value" as const }, { associationId: reviewTarget }]) expect(await knownReviewContext(context, reviewCap, { ...selector, ...patch })).toBeNull(); const tampered = structuredClone(context); tampered.subject.candidate = { ...tampered.subject.candidate, field_id: "pressure_gpa" }; expect(await knownReviewContext(tampered, reviewCap, selector)).toBeNull(); });
  it("retains noninteger canonical source lexemes and printed qualifiers without normalizing units", async () => { const context = await syntheticReviewContext("pressure_gpa"); expect(context.subject_canonical_json).toContain('"value":1.500'); expect(await knownReviewContext(context, reviewCap, { ...selector, fieldId: "pressure_gpa" })).toEqual(context); expect(reviewSourceValue(context.subject.candidate)).toBe("about 1.500 GPa"); });
  it("rejects rehashed inconsistent candidate/member proofs and duplicate JSON keys", async () => { const context = await syntheticReviewContext(); context.subject.candidate_sha256 = "0".repeat(64); context.subject_canonical_json = syntheticReviewCanonical(context.subject); context.subject_sha256 = await expressionSha(context.subject_canonical_json); context.item_template.expected_subject_sha256 = context.subject_sha256; context.item_template.expected_candidate_sha256 = "0".repeat(64); expect(await knownReviewContext(context, reviewCap, selector)).toBeNull(); const duplicate = await syntheticReviewContext(); duplicate.subject_canonical_json = duplicate.subject_canonical_json.replace('{"admission":', '{"field_id":"pressure_gpa","admission":'); duplicate.subject_sha256 = await expressionSha(duplicate.subject_canonical_json); expect(await knownReviewContext(duplicate, reviewCap, selector)).toBeNull(); });
  it("requires explicit source inspection, all four checks, exact predecessor and a rationale for acceptance", async () => { const request = await syntheticReviewRequest(true); expect(knownReviewRequest(request)).toBe(true); for (const patch of [{ source_inspection_attested: false }, { tc_expression: { id: reviewExpression, record_sha256: "a".repeat(64), projection_sha256: "b".repeat(64) } }, { checks: { ...request.items[0].checks, field_value_and_unit_boundary: "unresolved" } }, { rationale: "Looks good" }, { resolves_decision_id: reviewTarget }, { component: { ...request.items[0].component, role: "study_extent" } }]) expect(knownReviewRequest({ ...request, items: [{ ...request.items[0], ...patch }] })).toBe(false); expect(knownReviewRequest({ ...request, items: [...request.items, ...request.items] })).toBe(false); });
  it("binds preview, commit and GET outcome to one original request and receipt without scientific promotion", async () => { const request = await syntheticReviewRequest(), ref = await reviewRecovery(request, reviewCap), preview = await syntheticReviewReceipt(request); expect(await knownReviewReceipt(preview, reviewCap, ref, "preview")).toEqual(preview); const pinned = { ...ref, previewSha: preview.preview_sha256, receiptId: preview.receipt_id, receiptSha: preview.receipt_sha256 }, saved = await syntheticReviewReceipt(request, false); expect(await knownReviewReceipt(saved, reviewCap, pinned, "commit")).toEqual(saved); expect(await knownReviewReceipt({ ...saved, replayed: true }, reviewCap, pinned, "outcome")).not.toBeNull(); for (const patch of [{ request_key: "different" }, { request_sha256: "0".repeat(64) }, { receipt_id: reviewTarget }, { review_ledger_written: false }, { dry_run: true }, { scientific_acceptance: true }]) expect(await knownReviewReceipt({ ...saved, ...patch }, reviewCap, pinned, "commit")).toBeNull(); expect(await knownReviewReceipt(saved, reviewCap, pinned, "outcome")).toBeNull(); expect(await knownReviewReceipt({ ...preview, replayed: true }, reviewCap, ref, "preview")).toBeNull(); });
  it("allows genuine field-fidelity acceptance while scientific, canonical, ML and public approval stay false", async () => { const value = await syntheticReviewEffective(true); expect(await knownReviewEffective(value, reviewCap, reviewTarget, "tc_criterion")).toEqual(value); expect(value.field_fidelity_accepted).toBe(true); expect(value.scientific_acceptance).toBe(false); expect(value.canonical_promotions).toBe(0); expect(value.ml_training_approved).toBe(false); expect(value.public_release_authorized).toBe(false); });
  it("withholds previously accepted values after a late hold and rejects forged effective values or false head claims", async () => { const held = await syntheticReviewEffective(true, true); expect(await knownReviewEffective(held, reviewCap, reviewTarget, "tc_criterion")).toEqual(held); expect(held.effective_value).toBeNull(); const accepted = await syntheticReviewEffective(true); for (const patch of [{ effective_value: { field_id: "tc_criterion", value: { raw_value: "invented" } } }, { field_fidelity_accepted: false }, { scientific_acceptance: true }, { decision: { ...accepted.decision!, is_head: false } }, { decision: { ...accepted.decision!, effective_value_canonical_json: '{"invented":true}' } }]) expect(await knownReviewEffective({ ...accepted, ...patch }, reviewCap, reviewTarget, "tc_criterion")).toBeNull(); });
});
