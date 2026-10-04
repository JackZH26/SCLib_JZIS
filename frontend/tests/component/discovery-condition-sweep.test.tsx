import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  ConditionSweepError, createConditionSweep, estimateConditionSweep,
  type ConditionSweepAxes, type ConditionSweepInput,
} from "@/lib/discovery-condition-sweep";
import { knownDesignCapabilities, knownDesignPage } from "@/lib/discovery-designs";
import { expressionCanonical, expressionSha } from "@/lib/source-expressions";
import wire from "../fixtures/discovery-designs-native.synthetic.json";

beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const clone = <T,>(v: T): T => structuredClone(v);
const axes = (): ConditionSweepAxes => ({ pressures: [{ kind: "specified", raw_gpa: "10" }], temperatures_k: ["300"] });
async function input(chosen = axes()): Promise<ConditionSweepInput> {
  const capabilities = knownDesignCapabilities(clone(wire.capabilities), wire.capabilities.actor_user_id)!;
  const page = await knownDesignPage(clone(wire.page), capabilities, 0);
  expect(page).not.toBeNull();
  return { capabilities, entry: page!.entries[0], axes: chosen };
}
function expectCode(fn: () => unknown, code: string) {
  try { fn(); throw new Error("Expected rejection"); }
  catch (error) { expect(error).toBeInstanceOf(ConditionSweepError); expect((error as ConditionSweepError).code).toBe(code); }
}
// These changed, re-sealed receipts are test-owned proposals, not native SQL
// operations. The source reference remains the native synthetic fixture.
async function resealProposal(value: ConditionSweepInput) {
  const e = value.entry;
  const body = JSON.parse(e.receipt.receipt_canonical_json), request = JSON.parse(e.receipt.request_canonical_json), preview = JSON.parse(e.receipt.preview_canonical_json);
  body.design = clone(e.design); request.payload.design = clone(e.design); body.payload = clone(request.payload);
  body.request_json = expressionCanonical(request); body.request_sha256 = await expressionSha(body.request_json);
  preview.request_sha256 = body.request_sha256; body.preview_json = expressionCanonical(preview); body.preview_sha256 = await expressionSha(body.preview_json);
  e.receipt.request_canonical_json = body.request_json; e.receipt.request_sha256 = body.request_sha256;
  e.receipt.preview_canonical_json = body.preview_json; e.receipt.preview_sha256 = body.preview_sha256;
  e.receipt.receipt_canonical_json = expressionCanonical(body); e.receipt.receipt_sha256 = await expressionSha(e.receipt.receipt_canonical_json);
  e.record_sha256 = e.receipt.receipt_sha256;
  return value;
}
async function estimatedBudget(value: ConditionSweepInput) {
  value.entry.design.next_action.budget[0] = { ...value.entry.design.next_action.budget[0], status: "estimated", raw_upper: "0" };
  return resealProposal(value);
}
it("estimates and generates exactly twelve explicit condition proposals", async () => {
  const chosen: ConditionSweepAxes = { pressures: ["10", "50", "100", "200"].map(raw_gpa => ({ kind: "specified", raw_gpa })), temperatures_k: ["250", "300", "350"] };
  const before = await input(chosen), original = clone(before), manifest = await createConditionSweep(before);
  expect(manifest.estimate.raw_cartesian_count).toBe(12); expect(manifest.estimate.unique_cartesian_count).toBe(12);
  expect(manifest.scenarios).toHaveLength(12); expect(new Set(manifest.scenarios.map(s => s.candidate_id)).size).toBe(12);
  expect(before).toEqual(original);
  for (const s of manifest.scenarios) {
    expect(s.proposal.target_conditions).toEqual(s.conditions);
    expect(s.proposal.next_action).toEqual(before.entry.design.next_action);
    expect(s.proposal.modifications).toEqual(before.entry.design.modifications);
  }
  expect(manifest.parent).toEqual({ design_id: before.entry.design_id, revision_id: before.entry.id, revision: before.entry.revision, record_sha256: before.entry.record_sha256 });
  expect(manifest.source_pins.baseline).toEqual(before.entry.baseline);
  expect(manifest.source_pins).not.toHaveProperty("values"); expect(manifest.source_pins).not.toHaveProperty("context_json");
  expect(manifest).toMatchObject({ scope: "local_private_condition_sweep", scientific_acceptance: false, canonical_promotions: 0,
    ml_training_approved: false, public_release: false, calculation_executed: false, database_changed: false, batch_saved: false, atomic_sites_generated: false });
  const { manifest_sha256, ...body } = manifest;
  expect(manifest_sha256).toBe(await expressionSha(expressionCanonical(body)));
  expect(manifest.input_sha256).toBe(await expressionSha(manifest.input_canonical_json));
});
it("collapses exact numeric aliases but preserves their first raw spellings and input bytes", async () => {
  const chosen: ConditionSweepAxes = { pressures: ["01.00", "1e0", "1", ".10e1"].map(raw_gpa => ({ kind: "specified", raw_gpa })), temperatures_k: ["0300.0", "3e2", "300"] };
  expect(estimateConditionSweep(chosen)).toMatchObject({ raw_cartesian_count: 12, unique_cartesian_count: 1,
    pressure: { collapsed_count: 3 }, temperature: { collapsed_count: 2 }, collapsed_reason_codes: ["pressure_aliases_collapsed", "temperature_aliases_collapsed"] });
  const manifest = await createConditionSweep(await input(chosen));
  expect(JSON.parse(manifest.input_canonical_json).axes).toEqual(chosen);
  expect(manifest.scenarios[0].conditions).toEqual({ pressure: { kind: "specified", raw_gpa: "01.00" }, temperature_k: "0300.0" });
});
it("keeps decimal values distinct when Number would lose integer or fractional precision", () => {
  const chosen: ConditionSweepAxes = { pressures: ["9007199254740992", "9007199254740993", "1.00000000000000000000000001", "1.00000000000000000000000002"].map(raw_gpa => ({ kind: "specified", raw_gpa })), temperatures_k: ["300"] };
  expect(Number(chosen.pressures[0].raw_gpa)).toBe(Number(chosen.pressures[1].raw_gpa));
  expect(estimateConditionSweep(chosen).unique_cartesian_count).toBe(4);
});
it("keeps unspecified, ambient and specified zero pressure distinct, and unknown temperature distinct from zero", async () => {
  const chosen: ConditionSweepAxes = { pressures: [{ kind: "unspecified", raw_gpa: null }, { kind: "ambient", raw_gpa: null }, { kind: "specified", raw_gpa: "0" }, { kind: "specified", raw_gpa: "0.000e999999999999999999" }], temperatures_k: [null, "0", "0e-999999999999999999"] };
  const manifest = await createConditionSweep(await input(chosen));
  expect(manifest.estimate.unique_cartesian_count).toBe(6);
  expect(new Set(manifest.scenarios.map(s => s.conditions.pressure.kind)).size).toBe(3);
  expect(manifest.scenarios.filter(s => s.conditions.temperature_k === null)).toHaveLength(3);
});
it("has stable candidate IDs for aliases, reordering and renewed actor sessions while sealing original input separately", async () => {
  const first = await input({ pressures: [{ kind: "specified", raw_gpa: "10" }, { kind: "ambient", raw_gpa: null }], temperatures_k: ["300", null] });
  const second = clone(first); second.axes = { pressures: [{ kind: "ambient", raw_gpa: null }, { kind: "specified", raw_gpa: "1e1" }], temperatures_k: [null, "0300.0"] };
  second.capabilities.session_version += 1; second.capabilities.curator_grant_id = "00000000-0000-0000-0000-000000000001";
  const a = await createConditionSweep(first), b = await createConditionSweep(second);
  expect(a.scenarios.map(s => s.candidate_id)).toEqual(b.scenarios.map(s => s.candidate_id));
  expect(a.input_sha256).not.toBe(b.input_sha256); expect(a.manifest_sha256).not.toBe(b.manifest_sha256);
  const renewed = clone(first); renewed.capabilities.session_version += 1;
  const c = await createConditionSweep(renewed);
  expect(c.input_sha256).toBe(a.input_sha256); expect(c.scenarios.map(s => s.candidate_id)).toEqual(a.scenarios.map(s => s.candidate_id));
  expect(c.manifest_sha256).not.toBe(a.manifest_sha256);
});
it.each(["0e1000000000000000000", "0e-1999999999999999998", "0.0e-1999999999999999997", `0e${"9".repeat(61)}`])("rejects zero exponent %s outside the native design decimal representation", raw_gpa => {
  expectCode(() => estimateConditionSweep({ pressures: [{ kind: "specified", raw_gpa }], temperatures_k: ["300"] }), "sweep_decimal_invalid");
  expectCode(() => estimateConditionSweep({ pressures: axes().pressures, temperatures_k: [raw_gpa] }), "sweep_decimal_invalid");
});
it("accepts native zero exponent boundaries after the fractional offset without changing the raw input", async () => {
  const spellings = ["0e999999999999999999", "0e-1999999999999999997", "0.0e1000000000000000000", "0.00e1000000000000000001"];
  const manifest = await createConditionSweep(await input({ pressures: spellings.map(raw_gpa => ({ kind: "specified", raw_gpa })), temperatures_k: ["0"] }));
  expect(manifest.estimate.unique_cartesian_count).toBe(1);
  expect(JSON.parse(manifest.input_canonical_json).axes.pressures.map((p: { raw_gpa: string }) => p.raw_gpa)).toEqual(spellings);
});
it("changes candidate identities when the immutable parent proposal changes", async () => {
  const first = await input(), second = clone(first);
  second.entry.design.next_action.question = "A different question with the same requested conditions";
  await resealProposal(second);
  const a = await createConditionSweep(first), b = await createConditionSweep(second);
  expect(a.scenarios[0].conditions).toEqual(b.scenarios[0].conditions);
  expect(a.scenarios[0].candidate_id).not.toBe(b.scenarios[0].candidate_id);
});
it("allows the full 8×8 bound and rejects a ninth option before silently truncating", async () => {
  const chosen: ConditionSweepAxes = { pressures: Array.from({ length: 8 }, (_, i) => ({ kind: "specified", raw_gpa: String(i) })), temperatures_k: Array.from({ length: 8 }, (_, i) => String(i + 290)) };
  expect(estimateConditionSweep(chosen).unique_cartesian_count).toBe(64);
  expect((await createConditionSweep(await input(chosen))).scenarios).toHaveLength(64);
  chosen.pressures.push({ kind: "specified", raw_gpa: "8" }); expectCode(() => estimateConditionSweep(chosen), "sweep_axis_limit");
});
it.each(["-1", "-0", "+1", "NaN", "Infinity", "0x10", "1e999", "1e-999", " 1", "1 ", "", "1".repeat(65)])("rejects invalid pressure %s as a whole rather than manufacturing a partial sweep", raw_gpa => {
  expectCode(() => estimateConditionSweep({ pressures: [{ kind: "specified", raw_gpa: "10" }, { kind: "specified", raw_gpa }], temperatures_k: ["300"] }), "sweep_decimal_invalid");
});
it("accepts finite nonzero subnormal decimals without collapsing them through binary rounding", () => {
  expect(estimateConditionSweep({ pressures: [{ kind: "specified", raw_gpa: "3e-324" }, { kind: "specified", raw_gpa: "4e-324" }], temperatures_k: ["300"] }).unique_cartesian_count).toBe(2);
});
it("rejects empty axes, missing controls, false pressure typing and open-schema data", () => {
  expectCode(() => estimateConditionSweep({ pressures: [], temperatures_k: [null] }), "sweep_empty_axis");
  expectCode(() => estimateConditionSweep({ pressures: axes().pressures, temperatures_k: [] }), "sweep_empty_axis");
  expectCode(() => estimateConditionSweep({ pressures: axes().pressures }), "sweep_axes_invalid");
  expectCode(() => estimateConditionSweep({ ...axes(), atomic_sites: [] }), "sweep_axes_invalid");
  expectCode(() => estimateConditionSweep({ pressures: [{ kind: "ambient", raw_gpa: "0" }], temperatures_k: ["300"] }), "sweep_pressure_invalid");
  expectCode(() => estimateConditionSweep({ pressures: [{ kind: "specified", raw_gpa: "0", units: "GPa" }], temperatures_k: ["300"] }), "sweep_pressure_invalid");
  expectCode(() => estimateConditionSweep({ pressures: axes().pressures, temperatures_k: [300] }), "sweep_temperature_invalid");
});
it("keeps unknown and explicit zero per-candidate resources without claiming an aggregated total", async () => {
  const chosen = await estimatedBudget(await input()), manifest = await createConditionSweep(chosen);
  expect(manifest.scenarios[0].proposal.next_action.budget[0]).toMatchObject({ status: "estimated", raw_upper: "0" });
  expect(manifest.budget_totals[0]).toMatchObject({ status: "not_aggregated", total: null });
  expect(manifest.budget_totals.slice(1).every(b => b.status === "unknown" && b.total === null)).toBe(true);
});
it("rejects unverified authority, corrupted source proof, wrong owner and historical parents", async () => {
  const original = await input();
  const authority = clone(original); authority.entry.scientific_acceptance = true as never;
  await expect(createConditionSweep(authority)).rejects.toMatchObject({ code: "sweep_parent_invalid" });
  const capability = clone(original); capability.capabilities.public_release = true as never;
  await expect(createConditionSweep(capability)).rejects.toMatchObject({ code: "sweep_capability_invalid" });
  const source = clone(original); source.entry.projection!.values[0].value = 999;
  await expect(createConditionSweep(source)).rejects.toMatchObject({ code: "sweep_parent_invalid" });
  const owner = clone(original); owner.capabilities.actor_user_id = "00000000-0000-0000-0000-000000000001";
  await expect(createConditionSweep(owner)).rejects.toMatchObject({ code: "sweep_parent_invalid" });
  const historical = clone(original); historical.entry.is_head = false;
  await expect(createConditionSweep(historical)).rejects.toMatchObject({ code: "sweep_parent_invalid" });
  await expect(createConditionSweep({ ...original, calculation_executed: true })).rejects.toMatchObject({ code: "sweep_input_invalid" });
});
it("rejects held references without silently substituting an unanchored host", async () => {
  const held = await input(); held.entry.eligibility = { eligible: false, reason_codes: ["source_context_changed"] };
  held.entry.projection = null; held.entry.projection_canonical_json = null;
  await expect(createConditionSweep(held)).rejects.toMatchObject({ code: "sweep_source_unavailable" });
});
it("cannot claim a generated result when local checksums are unavailable", async () => {
  const chosen = await input();
  vi.stubGlobal("crypto", { subtle: { digest: vi.fn(() => Promise.reject(new Error("PRIVATE DRIVER ERROR"))) } });
  await expect(createConditionSweep(chosen)).rejects.toMatchObject({ code: "sweep_parent_invalid", message: "sweep_parent_invalid" });
});
it("detaches parent, next action, actor and raw axes before the first asynchronous digest", async () => {
  const chosen = await input(), original = clone(chosen);
  let release!: () => Promise<void>, first = true;
  vi.stubGlobal("crypto", { subtle: { digest: vi.fn((algorithm: string, bytes: Uint8Array) => {
    const captured = new Uint8Array(bytes);
    if (!first) return webcrypto.subtle.digest(algorithm, captured);
    first = false; return new Promise<ArrayBuffer>(resolve => { release = async () => resolve(await webcrypto.subtle.digest(algorithm, captured)); });
  }) } });
  const pending = createConditionSweep(chosen);
  chosen.entry.design.next_action.question = "Changed during verification"; chosen.entry.scientific_acceptance = true as never;
  chosen.axes.pressures[0].raw_gpa = "999"; chosen.capabilities.actor_user_id = "00000000-0000-0000-0000-000000000001";
  await release(); const manifest = await pending;
  expect(JSON.parse(manifest.input_canonical_json).axes).toEqual(original.axes);
  expect(manifest.scenarios[0].proposal.next_action).toEqual(original.entry.design.next_action);
  expect(manifest.actor.actor_user_id).toBe(original.capabilities.actor_user_id); expect(manifest.scientific_acceptance).toBe(false);
});
it("returns independent candidate proposal objects so one edited draft cannot change another", async () => {
  const chosen = await input({ pressures: [{ kind: "specified", raw_gpa: "10" }, { kind: "specified", raw_gpa: "50" }], temperatures_k: ["300"] });
  const manifest = await createConditionSweep(chosen), original = clone(manifest.scenarios[1].proposal);
  manifest.scenarios[0].proposal.next_action.prerequisites[0] = "User edited prerequisite";
  manifest.scenarios[0].proposal.target_conditions.pressure.raw_gpa = "999";
  expect(manifest.scenarios[1].proposal).toEqual(original);
  expect(manifest.scenarios[0].conditions.pressure.raw_gpa).not.toBe("999");
  expect(chosen.entry.design.next_action.prerequisites).not.toContain("User edited prerequisite");
});
