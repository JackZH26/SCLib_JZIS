import { createHash, webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getResearchCatalogue } from "@/lib/discovery-research-catalogue";
import { readQeNativeOutput, type QeResultReading } from "@/lib/discovery-qe-result";
import type { PreparedQe } from "@/lib/discovery-qe-input";
import {
  RESEARCH_AXES, RESEARCH_STRATEGIES, RESEARCH_CYCLE_PILOTS, RESEARCH_CYCLE_MAX_BYTES,
  researchStateFromCatalogue, createResearchCaseInput, prepareResearchCase, verifyResearchCase,
  exportResearchCase, importResearchCase, attachResearchReturn, recordResearchDecision,
  deriveResearchCase, prepareQeStudyReturn, researchCaseReadiness, researchDecisionBranches, unknownResearchEvidence,
  type ResearchCase, type ResearchReturnInput, type ResearchStateInput,
} from "@/lib/discovery-research-cycle";

const sha = (text: string) => createHash("sha256").update(text).digest("hex");
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") return `{${Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(",")}}`;
  return JSON.stringify(value);
}
beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function draft() {
  const catalog = getResearchCatalogue();
  return createResearchCaseInput(await researchStateFromCatalogue(catalog, catalog.states[0].id), "high_bandwidth");
}
function sourceReturn(c: ResearchCase): ResearchReturnInput {
  return { binding: { ...c.binding }, kind: "source_review", artifacts: structuredClone(c.definition.state.source_pins), model_cif_sha256: null,
    findings: "The retained coordinate source supplies a host reference, not electronic evidence for this modified state.",
    remaining_unknowns: ["State-specific electronic evidence remains unresolved."], numerical_assessment: "not_assessed", association: "researcher_linked_unverified" };
}
function native(k: number, width = 0.02): QeResultReading {
  const stem = width === 0.02 ? `tests/fixtures/qe-convergence/k${k}-` : `tests/fixtures/qe-joint-refinement/k${k}-s${width}-`;
  const report = JSON.parse(readFileSync(`${stem}reading.json`, "utf8"));
  const json = JSON.stringify(report, null, 2) + "\n", digest = sha(json);
  return { report, json, sha256: digest, filename: `sclib-qe-output-${digest.slice(0, 16)}.json` };
}
async function computationalCase(readings: QeResultReading[], kind: "mesh" | "mesh_smearing") {
  const first = readings[0].report;
  const selected: ResearchStateInput = { formula: "AlB2", host_formula: "MgB2", catalogue_reference: null,
    source_pins: [{ artifact_id: first.source_reference.id, version: String(first.source_reference.source.captured_revision), sha256: first.source_reference.source.file_sha256 }],
    structure: { artifact_id: first.candidate_id, version: "discovery-combined-site-candidates/1.0.0", sha256: first.candidate_cif_sha256 },
    modifications: [{ kind: "substitution", description: "Replace the primitive-cell Mg site with Al." }, { kind: "strain", description: "Increase lattice lengths by 2%." }],
    conditions: { pressure_gpa: null, temperature_k: null, charge_state: 0, magnetic_state: "nonmagnetic" }, relation_to_catalogue: "source_reference" };
  const input = createResearchCaseInput(selected, "high_bandwidth");
  input.action.kind = "computational_review";
  input.action.question = "Can the retained numerical window support a subsequent electronic comparison?";
  input.action.input_artifacts = readings.map(r => ({ artifact_id: r.filename, version: r.report.version, sha256: r.sha256 }));
  input.action.numerical_protocol = { kind, tolerance_hartree_per_atom: 1e-4 };
  input.action.branches = [
    { id: "within_window", observable: "The declared finite window is within tolerance; remaining checks are explicit.", decision: "continue", next_direction: "refine_method" },
    { id: "outside_window", observable: "The finite window exceeds tolerance or is incomplete.", decision: "redirect", next_direction: "refine_method" },
    { id: "insufficient_samples", observable: "Too few distinct samples remain to assess the joint window.", decision: "stop", next_direction: "pause" },
  ];
  return prepareResearchCase(input);
}

describe("Research loop source and state custody", () => {
  it("projects all 19 retained states without turning eight compositions into 19 new materials", async () => {
    const catalog = getResearchCatalogue(), ids = new Set<string>();
    expect(catalog.groups).toHaveLength(8); expect(catalog.states).toHaveLength(19);
    for (const model of catalog.states) {
      const state = await researchStateFromCatalogue(catalog, model.id);
      const occurrence = catalog.occurrences.find(o => o.id === model.primary_occurrence_id)!;
      expect(state.catalogue_reference?.catalog_state_id).toBe(model.id);
      expect(state.catalogue_reference?.catalog_group_id).toBe(model.group_id);
      expect(state.structure).toMatchObject({ artifact_id: occurrence.id, sha256: sha(occurrence.cif_text) });
      expect(Object.values(state.conditions)).toEqual([null, null, null, null]);
      const c = await prepareResearchCase(createResearchCaseInput(state, "geometry_construction"));
      ids.add(c.binding.case_id);
      expect(await importResearchCase((await exportResearchCase(c)).json)).toEqual(c);
      expect(researchCaseReadiness(c)).toMatchObject({ stage: "model_ready", can_execute: false, rps_score: null, scientific_acceptance: false });
      expect(c.authority.native_state_id).toBeNull();
    }
    expect(ids.size).toBe(19);
  });
  it("rejects a broken occurrence relationship or changed coordinate bytes", async () => {
    const catalog = getResearchCatalogue(), state = catalog.states[0];
    state.primary_occurrence_id = "missing";
    await expect(researchStateFromCatalogue(catalog, state.id)).rejects.toThrow(/lineage/);
    const other = getResearchCatalogue(), occurrence = other.occurrences.find(o => o.id === other.states[0].primary_occurrence_id)!;
    occurrence.cif_text += "\n";
    await expect(researchStateFromCatalogue(other, other.states[0].id)).rejects.toThrow(/changed/);
  });
  it("retains exact catalogue identity when conditions change but changes the research-state pin", async () => {
    const a = await draft(), baseline = await prepareResearchCase(a);
    a.state.conditions.charge_state = 1;
    await expect(prepareResearchCase(a)).rejects.toThrow(/derived research state/);
    a.state.relation_to_catalogue = "proposed_conditions";
    const derived = await prepareResearchCase(a);
    expect(derived.definition.state.catalogue_reference).toEqual(baseline.definition.state.catalogue_reference);
    expect(derived.binding.state_sha256).not.toBe(baseline.binding.state_sha256);
    expect(derived.binding.case_id).not.toBe(baseline.binding.case_id);
  });
  it("requires all six axes, keeps reference readings separate, and rejects invented score/approval fields", async () => {
    const a = await draft();
    expect(Object.keys(a.evidence)).toEqual([...RESEARCH_AXES]);
    a.evidence.electronic = { status: "source_reported", readings: [{ source: a.state.source_pins[0], quantity_label: "source electronic statement", raw_value: "reported", unit: null, locator: "source page 1", origin: "source_unspecified", applicability: "reference_only" }], limitation: "The source has not been matched to the modified model." };
    expect((await prepareResearchCase(a)).definition.evidence.electronic.readings[0].applicability).toBe("reference_only");
    for (const mutate of [
      (v: Record<string, unknown>) => { v.score = 6500; },
      (v: Record<string, unknown>) => { delete (v.evidence as Record<string, unknown>).pairing; },
      (v: Record<string, unknown>) => { (v.evidence as typeof a.evidence).stability.status = "reviewed" as never; },
    ]) { const v = structuredClone(a); mutate(v as unknown as Record<string, unknown>); await expect(prepareResearchCase(v)).rejects.toThrow(); }
  });
  it("snapshots inputs before asynchronous hashing and rejects forged authority on import", async () => {
    const a = await draft(), original = a.state.formula, pending = prepareResearchCase(a);
    a.state.formula = "ChangedAfterDispatch";
    const c = await pending; expect(c.definition.state.formula).toBe(original);
    const parsed = JSON.parse((await exportResearchCase(c)).json); parsed.record.authority.scientific_acceptance = true;
    await expect(importResearchCase(JSON.stringify(parsed, null, 2) + "\n")).rejects.toThrow();
  });
  it("refuses truncated, duplicate-key, oversized, unknown-field and changed-hash imports", async () => {
    const c = await prepareResearchCase(await draft()), out = await exportResearchCase(c);
    expect(out.sha256).toBe(sha(out.json));
    const changed = JSON.parse(out.json); changed.record.definition.title += " changed";
    for (const json of [out.json.slice(0, -4), out.json.replace('{\n', '{\n  "version": "ignored",\n'), " ".repeat(RESEARCH_CYCLE_MAX_BYTES + 1), JSON.stringify({ ...JSON.parse(out.json), other: true }, null, 2) + "\n", JSON.stringify(changed, null, 2) + "\n"]) await expect(importResearchCase(json)).rejects.toThrow();
  });
});

describe("Decision-changing actions and immutable follow-up", () => {
  it("keeps unknown resources distinct from zero and never computes a score", async () => {
    const a = await draft(), first = await prepareResearchCase(a);
    expect(researchCaseReadiness(first).reasons).toContain("The resource budget is incomplete.");
    a.action.prerequisites.forEach(p => { p.status = "met"; });
    a.action.resources = { access: "available", cpu_hours: 0, gpu_hours: 0, memory_gib: 0, storage_gib: 0, human_hours: 1 };
    const ready = await prepareResearchCase(a);
    expect(researchCaseReadiness(ready)).toMatchObject({ stage: "action_ready", execution_readiness: "prerequisites_declared", can_execute: false, rps_score: null, rank: null });
    a.action.kind = "external_experiment";
    expect(researchCaseReadiness(await prepareResearchCase(a)).reasons).toContain("No experimental facility is configured in this research workspace.");
  });
  it("requires distinguishable outcomes with different decisions, and ML rights/split/validation declarations", async () => {
    const a = await draft(); a.action.branches.forEach(b => { b.decision = "continue"; });
    await expect(prepareResearchCase(a)).rejects.toThrow(/different decisions/);
    const ml = await draft(); ml.action.kind = "ml_analysis";
    await expect(prepareResearchCase(ml)).rejects.toThrow();
    ml.action.ml = { dataset: ml.state.source_pins[0], split: "material_and_source_grouped", leakage_review: "pending", training_permission: "unknown", external_validation: "pending" };
    expect(researchCaseReadiness(await prepareResearchCase(ml)).reasons.some(x => x.startsWith("ML data rights"))).toBe(true);
  });
  it.each(["case_id", "definition_sha256", "state_sha256", "action_sha256"] as const)("refuses a return bound to another %s", async field => {
    const c = await prepareResearchCase(await draft()), r = sourceReturn(c);
    r.binding[field] = field === "case_id" ? `research-case:${"0".repeat(64)}` : "0".repeat(64);
    await expect(attachResearchReturn(c, r)).rejects.toThrow();
  });
  it("makes replay idempotent, requires a retained return, and preserves history in a child without inheriting evidence", async () => {
    const original = await prepareResearchCase(await draft());
    expect(researchDecisionBranches(original)).toEqual([]);
    await expect(recordResearchDecision(original, { return_sha256: "0".repeat(64), branch_id: "unresolved", decision: "stop", next_direction: "pause", reason: "No returned evidence." })).rejects.toThrow();
    const returned = await attachResearchReturn(original, sourceReturn(original));
    expect(researchDecisionBranches(returned)).toEqual(original.definition.action.branches);
    expect(researchDecisionBranches(returned, "0".repeat(64))).toEqual([]);
    expect(await attachResearchReturn(returned, sourceReturn(original))).toEqual(returned);
    expect(original.returns).toHaveLength(0); expect(researchCaseReadiness(returned).stage).toBe("returned");
    const decided = await recordResearchDecision(returned, { return_sha256: returned.returns[0].return_sha256, branch_id: "contradictory_or_incompatible", decision: "redirect", next_direction: "review_sources", reason: "The reference does not answer the modified-state question." });
    await expect(attachResearchReturn(decided, sourceReturn(original))).rejects.toThrow(/follow-up/);
    const next = structuredClone(decided.definition); next.title = "Review a narrower source question";
    const child = await deriveResearchCase(decided, next);
    expect(child.parent).toMatchObject({ case_id: original.binding.case_id, decision_sha256: decided.decision!.decision_sha256, properties_inherited: false });
    expect(child.returns).toEqual([]); expect(child.decision).toBeNull(); expect(child.definition.evidence).toEqual(unknownResearchEvidence());
    expect(await importResearchCase((await exportResearchCase(child)).json)).toEqual(child);
    next.evidence.stability = { status: "source_reported", readings: [{ source: next.state.source_pins[0], quantity_label: "claimed property", raw_value: "1", unit: null, locator: "parent", origin: "source_unspecified", applicability: "reference_only" }], limitation: "Parent evidence." };
    await expect(deriveResearchCase(decided, next)).rejects.toThrow(/inherit/);
  });
});

describe("Native AlB2 numerical counterexample, using the existing QE comparison", () => {
  it("replays retained native outputs and routes an outside-tolerance return to a method follow-up", async () => {
    const readings = [2, 4, 6].map(k => native(k));
    for (const k of [2, 4, 6]) {
      const stem = `tests/fixtures/qe-convergence/k${k}-`, manifest = JSON.parse(readFileSync(stem + "manifest.json", "utf8"));
      const reread = readQeNativeOutput({ manifest } as PreparedQe, "execution", readFileSync(stem + "data-file-schema.xml", "utf8"), readFileSync(stem + "pw.out", "utf8"));
      expect(native(k).report).toMatchObject(reread);
    }
    const c = await computationalCase(readings, "mesh"), result = await prepareQeStudyReturn(c, readings, { kind: "mesh", tolerance: 1e-4 }, "The retained AlB2 mesh window exceeds the declared tolerance.");
    expect(c.definition.state.formula).toBe("AlB2"); expect(c.definition.state.host_formula).toBe("MgB2");
    expect(result.numerical_assessment).toBe("sampled_window_outside_tolerance");
    const returned = await attachResearchReturn(c, result), ref = returned.returns[0].return_sha256;
    await expect(recordResearchDecision(returned, { return_sha256: ref, branch_id: "within_window", decision: "continue", next_direction: "refine_method", reason: "Mislabel the outside-tolerance window as within tolerance." })).rejects.toThrow(/numerical assessment/);
    const decided = await recordResearchDecision(returned, { return_sha256: ref, branch_id: "outside_window", decision: "redirect", next_direction: "refine_method", reason: "Resolve the numerical sensitivity before interpreting a bandwidth change." });
    const next = structuredClone(decided.definition); next.title = "Prepare the next declared numerical check"; next.action.kind = "calculation"; next.action.numerical_protocol = null;
    const child = await deriveResearchCase(decided, next);
    expect(researchCaseReadiness(child)).toMatchObject({ stage: "model_ready", execution_readiness: "blocked", rps_score: null });
    expect(await importResearchCase((await exportResearchCase(decided)).json)).toEqual(decided);
  });
  it("preserves the actual nine-reading joint failure and rejects a relaxed tolerance or wrong model", async () => {
    const readings = [2, 4, 6].flatMap(k => [0.04, 0.02, 0.01].map(w => native(k, w))), c = await computationalCase(readings, "mesh_smearing");
    const result = await prepareQeStudyReturn(c, readings, { kind: "mesh_smearing", tolerance: 1e-4 }, "The retained joint mesh-smearing window remains outside tolerance.");
    expect(result.numerical_assessment).toBe("sampled_window_outside_tolerance");
    await expect(prepareQeStudyReturn(c, readings, { kind: "mesh_smearing", tolerance: 0.1 }, "Raise the threshold after seeing results.")).rejects.toThrow(/declared before/);
    const different = structuredClone(c.definition); different.state.structure!.sha256 = "0".repeat(64);
    await expect(prepareQeStudyReturn(await prepareResearchCase(different), readings, { kind: "mesh_smearing", tolerance: 1e-4 }, "Wrong model.")).rejects.toThrow(/another coordinate/);
    const noPins = structuredClone(c.definition); noPins.action.input_artifacts.pop();
    await expect(prepareQeStudyReturn(await prepareResearchCase(noPins), readings, { kind: "mesh_smearing", tolerance: 1e-4 }, "Missing input.")).rejects.toThrow(/Every original/);
  });
  it("does not accept a changed charge model or mutate input evidence into native properties", async () => {
    const readings = [2, 4, 6].map(k => native(k)), original = await computationalCase(readings, "mesh"), changed = structuredClone(original.definition);
    changed.state.conditions.charge_state = 1;
    await expect(prepareQeStudyReturn(await prepareResearchCase(changed), readings, { kind: "mesh", tolerance: 1e-4 }, "Wrong charge.")).rejects.toThrow(/charge and magnetic/);
    expect((await verifyResearchCase(original)).definition.evidence).toEqual(unknownResearchEvidence());
  });
  it.each([
    ["mesh", "full", 0.02, "sampled_window_within_tolerance", "within_window"],
    ["mesh", "full", 1e-10, "scf_precision_insufficient", "outside_window"],
    ["mesh_smearing", "missing", 1e-4, "incomplete_grid", "outside_window"],
    ["mesh_smearing", "two_by_two", 1e-4, "insufficient_axis_samples", "insufficient_samples"],
  ] as const)("binds %s/%s native assessment at tolerance %s to its permitted decision", async (kind, sample, tolerance, assessment, branchId) => {
    const all = kind === "mesh" ? [2, 4, 6].map(k => native(k)) : [2, 4, 6].flatMap(k => [0.04, 0.02, 0.01].map(w => native(k, w)));
    const readings = sample === "missing" ? all.slice(1) : sample === "two_by_two" ? all.filter(r => r.report.settings.mesh[0] !== 6 && r.report.settings.degauss !== 0.01) : all;
    const input = structuredClone((await computationalCase(readings, kind)).definition);
    input.action.numerical_protocol!.tolerance_hartree_per_atom = tolerance;
    const record = await prepareResearchCase(input), result = await prepareQeStudyReturn(record, readings, { kind, tolerance }, "Reassess retained native output without assigning physical validity.");
    const returned = await attachResearchReturn(record, result), allowed = researchDecisionBranches(returned);
    expect(result.numerical_assessment).toBe(assessment);
    expect(allowed.map(b => b.id)).toEqual([branchId]);
    for (const branch of returned.definition.action.branches) {
      const choice = { return_sha256: returned.returns[0].return_sha256, branch_id: branch.id, decision: branch.decision, next_direction: branch.next_direction, reason: "Record the finite-window outcome." };
      if (branch.id === branchId) expect((await recordResearchDecision(returned, choice)).decision).toMatchObject(choice);
      else await expect(recordResearchDecision(returned, choice)).rejects.toThrow(/numerical assessment/);
    }
  });
  it("uses the selected return hash, not another later assessment, for a decision", async () => {
    const readings = [2, 4, 6].flatMap(k => [0.04, 0.02, 0.01].map(w => native(k, w)));
    const original = await computationalCase(readings, "mesh_smearing");
    const first = await attachResearchReturn(original, await prepareQeStudyReturn(original, readings, { kind: "mesh_smearing", tolerance: 1e-4 }, "Complete retained grid remains outside tolerance."));
    const partial = readings.filter(r => r.report.settings.mesh[0] !== 6 && r.report.settings.degauss !== 0.01);
    const latest = await attachResearchReturn(first, await prepareQeStudyReturn(first, partial, { kind: "mesh_smearing", tolerance: 1e-4 }, "A complete two-by-two subset is insufficient to assess the required window."));
    expect(researchDecisionBranches(latest).map(b => b.id)).toEqual(["insufficient_samples"]);
    expect(researchDecisionBranches(latest, first.returns[0].return_sha256).map(b => b.id)).toEqual(["outside_window"]);
    expect((await recordResearchDecision(latest, { return_sha256: first.returns[0].return_sha256, branch_id: "outside_window", decision: "redirect", next_direction: "refine_method", reason: "Choose the exact complete-grid return, retaining the later subset as separate evidence." })).decision?.return_sha256).toBe(first.returns[0].return_sha256);
  });
  it.each(["outside_as_within", "within_as_physics"])("rejects %s even when an imported decision and envelope have matching recomputed hashes", async bypass => {
    const readings = [2, 4, 6].map(k => native(k));
    const input = structuredClone((await computationalCase(readings, "mesh")).definition);
    const tolerance = bypass === "within_as_physics" ? 0.02 : 1e-4;
    input.action.numerical_protocol!.tolerance_hartree_per_atom = tolerance;
    if (bypass === "within_as_physics") input.action.branches[0].next_direction = "assess_physics";
    const original = await prepareResearchCase(input), returned = await attachResearchReturn(original,
      await prepareQeStudyReturn(original, readings, { kind: "mesh", tolerance }, "Original native samples, with retained numerical assessment."));
    const choice = { return_sha256: returned.returns[0].return_sha256, branch_id: "within_window", decision: "continue" as const,
      next_direction: bypass === "within_as_physics" ? "assess_physics" as const : "refine_method" as const, reason: "Attempt to bypass the outcome rule using consistent custody hashes." };
    await expect(recordResearchDecision(returned, choice)).rejects.toThrow(/numerical assessment/);
    const forged: ResearchCase = { ...returned, decision: { ...choice, decision_sha256: sha(canonical(choice)) } };
    const json = JSON.stringify({ version: "discovery-research-cycle-export/1.0.0", payload_sha256: sha(canonical(forged)), record: forged }, null, 2) + "\n";
    await expect(verifyResearchCase(forged)).rejects.toThrow(/numerical assessment/);
    await expect(importResearchCase(json)).rejects.toThrow(/numerical assessment/);
  });
});

it("uses the three requested strategies and labels each pilot's actual stage in English", () => {
  expect(RESEARCH_STRATEGIES.map(x => x.id)).toEqual(["high_bandwidth", "high_carrier_density", "geometry_construction"]);
  expect(RESEARCH_CYCLE_PILOTS.map(p => p.stage)).toEqual(["retained_calculation_review", "recipe_not_generated", "source_comparison"]);
  expect(RESEARCH_CYCLE_PILOTS.every(p => !p.new_computation_required_for_this_review)).toBe(true);
  expect(JSON.stringify([RESEARCH_STRATEGIES, RESEARCH_CYCLE_PILOTS])).not.toMatch(/[\u4e00-\u9fff]/);
});
