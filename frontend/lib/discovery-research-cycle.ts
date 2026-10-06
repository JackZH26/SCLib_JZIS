import type { QeResultReading } from "@/lib/discovery-qe-result";
import type { ResearchCatalogue } from "@/lib/discovery-research-catalogue";

export const RESEARCH_CYCLE_VERSION = "discovery-research-cycle/1.0.0";
export const RESEARCH_CYCLE_MAX_BYTES = 512 * 1024;
export const RESEARCH_TARGET = { temperature_k: 300, pressure_gpa: 0.000101325, pressure_label: "1 atm", role: "research_target_not_observation" } as const;
export const RESEARCH_AXES = ["stability", "electronic", "pairing", "coherence", "geometry", "competing_order"] as const;
export type ResearchAxis = typeof RESEARCH_AXES[number];
export type ResearchStrategy = "high_bandwidth" | "high_carrier_density" | "geometry_construction";
export type ResearchOutcome = "continue" | "stop" | "redirect";
export type ResearchDirection = "review_sources" | "refine_method" | "prepare_model" | "assess_physics" | "pause";

/** Search hypotheses, not inferred measurements, scores or a universal Tc model. */
export const RESEARCH_STRATEGIES = [
  { id: "high_bandwidth", label: "High electronic bandwidth", question: "Can a defined modification change the relevant orbital bandwidth while preserving an appropriate interaction and coherence regime?",
    search_terms: ["orbital-resolved bandwidth", "dispersion", "effective mass", "strain", "orbital overlap"],
    needed_evidence: ["Defined phase, structure and orbital window", "Comparable electronic methods and conditions", "Interaction and competing-order evidence"],
    competing_explanations: ["Wider dispersion supports mobile electronic states", "The same change weakens relevant interactions or alters competing order"],
    ml_role: "Use source- and material-grouped models to identify informative bandwidth changes; retain held-out validation and uncertainty.",
    boundary: "Bandwidth is not DOS(EF), carrier density or superconductivity probability. A larger value is not universally better." },
  { id: "high_carrier_density", label: "High carrier density", question: "Does an explicit substitution or vacancy produce mobile carriers rather than localization, compensation or damaging disorder?",
    search_terms: ["Hall coefficient", "carrier density", "charge compensation", "oxygen vacancy", "localization"],
    needed_evidence: ["Explicit composition, site fraction and charge model", "Carrier measurement or a defined electronic model", "Compensation, disorder and mobility limitations"],
    competing_explanations: ["The modification introduces itinerant carriers", "Carriers localize or compensate; disorder limits coherence"],
    ml_role: "Search measured or calculated carrier responses within comparable states; a nominal dopant fraction is not a carrier label.",
    boundary: "Dopant fraction and total valence-electron count are not measured mobile-carrier density. More carriers need not improve pairing." },
  { id: "geometry_construction", label: "Geometry construction", question: "Can a specified lattice, interface or dimensional modification change useful electronic or interaction features without losing stability or coherence?",
    search_terms: ["lattice geometry", "strain", "interface", "dimensionality", "phase stiffness"],
    needed_evidence: ["Full coordinates and boundary conditions", "Defined geometry changes and reference state", "Stability and coherence checks appropriate to the mechanism"],
    competing_explanations: ["The geometry change creates the intended electronic or interaction feature", "Structural instability or reduced coherence prevents the intended benefit"],
    ml_role: "Propose bounded geometry changes from source-linked structures; validate by held-out structures and explicit physical checks.",
    boundary: "A flat band, low dimension or generated coordinate model alone does not establish pairing, phase coherence or stable synthesis." },
] as const satisfies readonly { id: ResearchStrategy; label: string; question: string; search_terms: readonly string[]; needed_evidence: readonly string[]; competing_explanations: readonly string[]; ml_role: string; boundary: string }[];

export type ResearchArtifactPin = { artifact_id: string; version: string; sha256: string };
export type ResearchStateInput = {
  formula: string; host_formula: string;
  catalogue_reference: { catalogue_version: string; catalog_group_id: string; catalog_state_id: string } | null;
  source_pins: ResearchArtifactPin[];
  structure: ResearchArtifactPin | null;
  modifications: { kind: "substitution" | "vacancy" | "strain" | "interface" | "layer" | "twist" | "pressure" | "reference"; description: string }[];
  conditions: { pressure_gpa: number | null; temperature_k: number | null; charge_state: number | null; magnetic_state: "nonmagnetic" | "spin_polarized" | null };
  relation_to_catalogue: "catalogue_model" | "proposed_conditions" | "source_reference";
};
export type ResearchEvidence = Record<ResearchAxis, {
  status: "unknown" | "source_reported" | "conflicted" | "not_applicable";
  readings: { source: ResearchArtifactPin; quantity_label: string; raw_value: string; unit: string | null; locator: string; origin: "observed_in_source" | "computed_in_source" | "source_unspecified"; applicability: "reference_only" | "same_state_claimed_unverified" }[];
  limitation: string;
}>;
export type ResearchBranch = { id: string; observable: string; decision: ResearchOutcome; next_direction: ResearchDirection };
export type ResearchAction = {
  kind: "source_review" | "computational_review" | "calculation" | "ml_analysis" | "external_experiment";
  question: string; input_artifacts: ResearchArtifactPin[];
  prerequisites: { description: string; status: "met" | "unknown" | "unmet" }[];
  resources: { access: "available" | "unconfirmed" | "unavailable"; cpu_hours: number | null; gpu_hours: number | null; memory_gib: number | null; storage_gib: number | null; human_hours: number | null };
  branches: ResearchBranch[];
  numerical_protocol: { kind: "mesh" | "mesh_smearing"; tolerance_hartree_per_atom: number } | null;
  ml: { dataset: ResearchArtifactPin; split: "material_and_source_grouped"; leakage_review: "pending" | "documented"; training_permission: "unknown" | "documented"; external_validation: "pending" | "documented" } | null;
};
export type ResearchCaseInput = { title: string; strategy: ResearchStrategy; state: ResearchStateInput; evidence: ResearchEvidence; hypothesis: { statement: string; competing_explanations: string[]; critical_unknown: string }; action: ResearchAction };
export type ResearchBinding = { case_id: string; definition_sha256: string; state_sha256: string; action_sha256: string };
export type ResearchReturnInput = {
  binding: ResearchBinding;
  kind: "source_review" | "qe_sampled_study" | "calculation_receipt_link" | "experimental_source_link" | "ml_report_link";
  artifacts: ResearchArtifactPin[]; model_cif_sha256: string | null;
  findings: string; remaining_unknowns: string[];
  numerical_assessment: "not_assessed" | "sampled_window_within_tolerance" | "sampled_window_outside_tolerance" | "scf_precision_insufficient" | "incomplete_grid" | "insufficient_axis_samples";
  association: "researcher_linked_unverified";
};
export type ResearchReturn = ResearchReturnInput & { return_sha256: string };
export type ResearchDecision = { return_sha256: string; branch_id: string; decision: ResearchOutcome; next_direction: ResearchDirection; reason: string; decision_sha256: string };
export type ResearchCase = {
  version: typeof RESEARCH_CYCLE_VERSION; target: typeof RESEARCH_TARGET; binding: ResearchBinding; definition: ResearchCaseInput;
  parent: { case_id: string; definition_sha256: string; decision_sha256: string; relation: "research_follow_up"; properties_inherited: false } | null;
  returns: ResearchReturn[]; decision: ResearchDecision | null;
  authority: { scientific_acceptance: false; execution_authenticated: false; database_write: false; public_release: false; rps_score: null; rank: null; native_material_id: null; native_state_id: null };
};
const AUTHORITY: ResearchCase["authority"] = { scientific_acceptance: false, execution_authenticated: false, database_write: false, public_release: false, rps_score: null, rank: null, native_material_id: null, native_state_id: null };
const fail = (message = "Invalid research-cycle data."): never => { throw new Error(message); };
function requireValue(value: unknown, message?: string): asserts value { if (!value) fail(message); }
const hashPattern = /^[a-f0-9]{64}$/;
const casePattern = /^research-case:[a-f0-9]{64}$/;
const text = (v: unknown, max = 2000): v is string => typeof v === "string" && !!v.trim() && v.length <= max && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(v);
const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v) && !Object.is(v, -0);
const nullableNumber = (v: unknown, nonnegative = false) => v === null || finite(v) && (!nonnegative || v >= 0);
const one = (v: unknown, values: readonly string[]) => typeof v === "string" && values.includes(v);
const list = (v: unknown, min: number, max: number): v is unknown[] => Array.isArray(v) && v.length >= min && v.length <= max;
function closed(v: unknown, keys: string): Record<string, unknown> {
  if (!v || typeof v !== "object" || Array.isArray(v) || ![Object.prototype, null].includes(Object.getPrototypeOf(v))) return fail();
  const names = keys.split(" "), obj = v as Record<string, unknown>;
  requireValue(Object.keys(obj).length === names.length && names.every(k => Object.hasOwn(obj, k)));
  return obj;
}
function bounded(v: unknown) {
  let count = 0;
  const visit = (item: unknown, depth: number): void => {
    requireValue(++count <= 14000 && depth <= 18, "Research-cycle data exceeds its structural limit.");
    if (typeof item === "number") requireValue(finite(item));
    else if (typeof item === "string") requireValue(item.length <= 16000);
    else if (item !== null && typeof item === "object") {
      requireValue(Array.isArray(item) || [Object.prototype, null].includes(Object.getPrototypeOf(item)));
      requireValue(Object.keys(item).length <= 128);
      for (const [key, child] of Object.entries(item)) { requireValue(!["__proto__", "constructor", "prototype"].includes(key)); visit(child, depth + 1); }
    } else requireValue(item === null || typeof item === "boolean");
  };
  visit(v, 0);
  requireValue(new TextEncoder().encode(JSON.stringify(v)).length <= RESEARCH_CYCLE_MAX_BYTES, "Research-cycle data exceeds 512 KiB.");
}
function canonical(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(canonical).join(",")}]`;
  if (v !== null && typeof v === "object") return `{${Object.entries(v).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([k, x]) => `${JSON.stringify(k)}:${canonical(x)}`).join(",")}}`;
  return JSON.stringify(v);
}
// Keep the case editor independent of the coordinate inventory and QE parser bundles.
const textHash = async (value: string) => Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)))).map(n => n.toString(16).padStart(2, "0")).join("");
const hash = (v: unknown) => textHash(canonical(v));
const same = (a: unknown, b: unknown) => canonical(a) === canonical(b);
function pin(v: unknown): void {
  const o = closed(v, "artifact_id version sha256");
  requireValue(text(o.artifact_id, 200) && text(o.version, 200) && typeof o.sha256 === "string" && hashPattern.test(o.sha256));
}
function pins(v: unknown, min = 0): void {
  requireValue(list(v, min, 32)); (v as unknown[]).forEach(pin);
  requireValue(new Set((v as ResearchArtifactPin[]).map(p => `${p.artifact_id}|${p.version}`)).size === (v as unknown[]).length, "Duplicate artifact identities are ambiguous.");
}
function state(v: unknown): void {
  const o = closed(v, "formula host_formula catalogue_reference source_pins structure modifications conditions relation_to_catalogue");
  requireValue(text(o.formula, 160) && text(o.host_formula, 160)); pins(o.source_pins, 1);
  if (o.structure !== null) pin(o.structure);
  if (o.catalogue_reference !== null) {
    const c = closed(o.catalogue_reference, "catalogue_version catalog_group_id catalog_state_id");
    requireValue(text(c.catalogue_version, 160) && /^proposal-group:[a-f0-9]{64}$/.test(String(c.catalog_group_id)) && /^proposal-state:[a-f0-9]{64}$/.test(String(c.catalog_state_id)));
    requireValue(o.structure !== null && o.relation_to_catalogue !== "source_reference");
  } else requireValue(o.relation_to_catalogue === "source_reference");
  requireValue(one(o.relation_to_catalogue, ["catalogue_model", "proposed_conditions", "source_reference"]));
  requireValue(list(o.modifications, 0, 8));
  (o.modifications as unknown[]).forEach(v => { const m = closed(v, "kind description"); requireValue(one(m.kind, ["substitution", "vacancy", "strain", "interface", "layer", "twist", "pressure", "reference"]) && text(m.description)); });
  const c = closed(o.conditions, "pressure_gpa temperature_k charge_state magnetic_state");
  requireValue(nullableNumber(c.pressure_gpa, true) && nullableNumber(c.temperature_k, true) && nullableNumber(c.charge_state) && (c.magnetic_state === null || one(c.magnetic_state, ["nonmagnetic", "spin_polarized"])));
  if (o.relation_to_catalogue === "catalogue_model") requireValue(Object.values(c).every(x => x === null), "Assigned conditions describe a derived research state, not the unassigned catalogue model.");
}
function evidence(v: unknown): void {
  const o = closed(v, RESEARCH_AXES.join(" "));
  for (const axis of RESEARCH_AXES) {
    const e = closed(o[axis], "status readings limitation");
    requireValue(one(e.status, ["unknown", "source_reported", "conflicted", "not_applicable"]) && text(e.limitation));
    requireValue(list(e.readings, 0, 8));
    requireValue(["unknown", "not_applicable"].includes(String(e.status)) ? e.readings.length === 0 : e.readings.length > 0);
    e.readings.forEach(v => { const r = closed(v, "source quantity_label raw_value unit locator origin applicability"); pin(r.source);
      requireValue(text(r.quantity_label, 160) && text(r.raw_value, 500) && (r.unit === null || text(r.unit, 100)) && text(r.locator, 500)
        && one(r.origin, ["observed_in_source", "computed_in_source", "source_unspecified"]) && one(r.applicability, ["reference_only", "same_state_claimed_unverified"])); });
  }
}
function action(v: unknown): void {
  const o = closed(v, "kind question input_artifacts prerequisites resources branches numerical_protocol ml");
  requireValue(one(o.kind, ["source_review", "computational_review", "calculation", "ml_analysis", "external_experiment"]) && text(o.question)); pins(o.input_artifacts, 1);
  requireValue(list(o.prerequisites, 1, 12));
  (o.prerequisites as unknown[]).forEach(v => { const p = closed(v, "description status"); requireValue(text(p.description) && one(p.status, ["met", "unknown", "unmet"])); });
  const r = closed(o.resources, "access cpu_hours gpu_hours memory_gib storage_gib human_hours");
  requireValue(one(r.access, ["available", "unconfirmed", "unavailable"]));
  for (const k of ["cpu_hours", "gpu_hours", "memory_gib", "storage_gib", "human_hours"]) requireValue(nullableNumber(r[k], true));
  requireValue(list(o.branches, 2, 8));
  (o.branches as unknown[]).forEach(v => { const b = closed(v, "id observable decision next_direction"); requireValue(typeof b.id === "string" && /^[a-z][a-z0-9_]{0,63}$/.test(b.id) && text(b.observable) && one(b.decision, ["continue", "stop", "redirect"]) && one(b.next_direction, ["review_sources", "refine_method", "prepare_model", "assess_physics", "pause"])); });
  const branches = o.branches as ResearchBranch[];
  requireValue(new Set(branches.map(b => b.id)).size === branches.length && new Set(branches.map(b => b.observable.trim().toLowerCase())).size === branches.length && new Set(branches.map(b => b.decision)).size >= 2, "Define distinct observable outcomes with different decisions.");
  if (o.numerical_protocol !== null) {
    const p = closed(o.numerical_protocol, "kind tolerance_hartree_per_atom");
    requireValue(o.kind === "computational_review" && one(p.kind, ["mesh", "mesh_smearing"]) && finite(p.tolerance_hartree_per_atom) && p.tolerance_hartree_per_atom > 0);
  }
  if (o.kind === "ml_analysis") {
    const m = closed(o.ml, "dataset split leakage_review training_permission external_validation"); pin(m.dataset);
    requireValue(m.split === "material_and_source_grouped" && one(m.leakage_review, ["pending", "documented"]) && one(m.training_permission, ["unknown", "documented"]) && one(m.external_validation, ["pending", "documented"]));
  } else requireValue(o.ml === null);
}
function input(v: unknown): asserts v is ResearchCaseInput {
  bounded(v); const o = closed(v, "title strategy state evidence hypothesis action");
  requireValue(text(o.title, 240) && RESEARCH_STRATEGIES.some(s => s.id === o.strategy)); state(o.state); evidence(o.evidence); action(o.action);
  const h = closed(o.hypothesis, "statement competing_explanations critical_unknown");
  requireValue(text(h.statement) && text(h.critical_unknown) && list(h.competing_explanations, 2, 6) && h.competing_explanations.every(x => text(x)) && new Set(h.competing_explanations).size === h.competing_explanations.length);
}
function binding(v: unknown): void {
  const b = closed(v, "case_id definition_sha256 state_sha256 action_sha256");
  requireValue(typeof b.case_id === "string" && casePattern.test(b.case_id) && [b.definition_sha256, b.state_sha256, b.action_sha256].every(h => typeof h === "string" && hashPattern.test(h)) && b.case_id === `research-case:${b.definition_sha256}`);
}
function returned(v: unknown, c: ResearchCase): asserts v is ResearchReturnInput {
  const r = closed(v, "binding kind artifacts model_cif_sha256 findings remaining_unknowns numerical_assessment association"); binding(r.binding);
  requireValue(same(r.binding, c.binding), "Return case, state or action pins do not match this research case."); pins(r.artifacts, 1);
  requireValue(one(r.kind, ["source_review", "qe_sampled_study", "calculation_receipt_link", "experimental_source_link", "ml_report_link"]) && text(r.findings) && list(r.remaining_unknowns, 1, 12) && r.remaining_unknowns.every(x => text(x)) && r.association === "researcher_linked_unverified");
  const expected: Record<ResearchReturnInput["kind"], ResearchAction["kind"][]> = { source_review: ["source_review"], qe_sampled_study: ["computational_review"], calculation_receipt_link: ["calculation", "computational_review"], experimental_source_link: ["source_review", "external_experiment"], ml_report_link: ["ml_analysis"] };
  requireValue(expected[r.kind as ResearchReturnInput["kind"]].includes(c.definition.action.kind), "The return kind does not answer this action.");
  requireValue(one(r.numerical_assessment, ["not_assessed", "sampled_window_within_tolerance", "sampled_window_outside_tolerance", "scf_precision_insufficient", "incomplete_grid", "insufficient_axis_samples"]));
  if (r.kind === "qe_sampled_study" || r.kind === "calculation_receipt_link") requireValue(c.definition.state.structure !== null && r.model_cif_sha256 === c.definition.state.structure.sha256, "The calculation refers to another coordinate model.");
  else requireValue(r.model_cif_sha256 === null && r.numerical_assessment === "not_assessed");
  if (r.kind === "qe_sampled_study") {
    const protocol = c.definition.action.numerical_protocol;
    requireValue(protocol !== null && r.numerical_assessment !== "not_assessed" && (r.artifacts as ResearchArtifactPin[]).length === 1
      && (r.artifacts as ResearchArtifactPin[])[0].version === (protocol.kind === "mesh" ? "discovery-qe-sampled-convergence/1.0.0" : "discovery-qe-mesh-smearing-study/1.0.0"), "Link the declared existing QE study contract.");
  } else requireValue(r.numerical_assessment === "not_assessed");
}
const badNumerics = (r: ResearchReturn) => !["not_assessed", "sampled_window_within_tolerance"].includes(r.numerical_assessment);

/** Validate before every mutation/export. JSON custody cannot authenticate an external scientific record. */
export async function verifyResearchCase(value: unknown): Promise<ResearchCase> {
  bounded(value); const detached: unknown = structuredClone(value);
  const c = closed(detached, "version target binding definition parent returns decision authority");
  requireValue(c.version === RESEARCH_CYCLE_VERSION && same(c.target, RESEARCH_TARGET) && same(c.authority, AUTHORITY)); input(c.definition); binding(c.binding);
  const record = detached as ResearchCase;
  if (c.parent !== null) {
    const p = closed(c.parent, "case_id definition_sha256 decision_sha256 relation properties_inherited");
    requireValue(typeof p.case_id === "string" && casePattern.test(p.case_id) && p.case_id === `research-case:${p.definition_sha256}` && [p.definition_sha256, p.decision_sha256].every(x => typeof x === "string" && hashPattern.test(x)) && p.relation === "research_follow_up" && p.properties_inherited === false && p.case_id !== record.binding.case_id);
  }
  const expected = await hash({ definition: c.definition, parent: c.parent });
  requireValue(record.binding.definition_sha256 === expected && record.binding.state_sha256 === await hash(record.definition.state) && record.binding.action_sha256 === await hash(record.definition.action), "Research case contents differ from their pins.");
  requireValue(list(c.returns, 0, 16));
  for (const item of record.returns) {
    closed(item, "binding kind artifacts model_cif_sha256 findings remaining_unknowns numerical_assessment association return_sha256");
    const { return_sha256: digest, ...payload } = item; returned(payload, record);
    requireValue(digest === await hash(payload), "A research return has changed.");
  }
  requireValue(new Set(record.returns.map(r => r.return_sha256)).size === record.returns.length, "Repeated return bytes are not new evidence.");
  if (record.decision !== null) {
    closed(record.decision, "return_sha256 branch_id decision next_direction reason decision_sha256");
    const { decision_sha256: digest, ...payload } = record.decision;
    validateDecision(record, payload); requireValue(digest === await hash(payload));
  }
  return record;
}

export function unknownResearchEvidence(): ResearchEvidence {
  return Object.fromEntries(RESEARCH_AXES.map(axis => [axis, { status: "unknown", readings: [], limitation: "No state-specific evidence has been assigned." }])) as unknown as ResearchEvidence;
}

/** Project a server-validated catalogue without duplicating its atom model or inventing native IDs. */
export async function researchStateFromCatalogue(value: ResearchCatalogue, stateId: string): Promise<ResearchStateInput> {
  const catalog = structuredClone(value);
  const model = catalog.states.find(s => s.id === stateId);
  requireValue(model, "Choose an existing catalogue state.");
  const group = catalog.groups.find(g => g.id === model.group_id);
  const parent = catalog.parents.find(p => p.id === model.parent_id);
  const source = catalog.sources.find(s => s.id === parent?.source_id);
  const occurrence = catalog.occurrences.find(o => o.id === model.primary_occurrence_id);
  requireValue(group && parent && source && occurrence && group.state_ids.includes(model.id) && group.source_id === source.id && occurrence.state_id === model.id && model.occurrence_ids.includes(occurrence.id), "The catalogue state lineage is incomplete.");
  requireValue(await textHash(occurrence.cif_text) === occurrence.cif_sha256, "The selected coordinate artifact changed.");
  const result: ResearchStateInput = { formula: model.formula, host_formula: group.host_formula,
    catalogue_reference: { catalogue_version: catalog.version, catalog_group_id: group.id, catalog_state_id: model.id },
    source_pins: [{ artifact_id: source.id, version: `COD revision ${source.revision}`, sha256: source.cif_sha256 }],
    structure: { artifact_id: occurrence.id, version: catalog.version, sha256: occurrence.cif_sha256 },
    modifications: [...model.edits.map(edit => ({ kind: edit.kind, description: `${edit.kind === "vacancy" ? `Remove ${edit.original_element}` : `${edit.original_element} to ${edit.element}`} at ${edit.target_id} (source site ${edit.source_site_label}).` })),
      ...(model.strain_micro_percent ? [{ kind: "strain" as const, description: `Uniform lattice-length change: ${model.strain_micro_percent / 1_000_000}%; fractional coordinates fixed; pressure is not assigned.` }] : [])],
    conditions: structuredClone(model.conditions), relation_to_catalogue: "catalogue_model" };
  state(result); return result;
}

/** A reviewable starting question; it assigns no physical result, native ID, budget or RPS. */
export function createResearchCaseInput(selected: ResearchStateInput, strategy: ResearchStrategy): ResearchCaseInput {
  state(selected); const profile = RESEARCH_STRATEGIES.find(p => p.id === strategy) ?? fail("Choose a research strategy.");
  return { title: `${selected.formula}: ${profile.label}`, strategy, state: structuredClone(selected), evidence: unknownResearchEvidence(),
    hypothesis: { statement: profile.question, competing_explanations: [...profile.competing_explanations], critical_unknown: profile.needed_evidence.join("; ") },
    action: { kind: "source_review", question: `Review exact-state evidence for ${selected.formula}: ${profile.question}`, input_artifacts: structuredClone(selected.source_pins),
      prerequisites: [{ description: "Resolve source applicability to the specific model and conditions.", status: "unknown" }],
      resources: { access: "unconfirmed", cpu_hours: null, gpu_hours: null, memory_gib: null, storage_gib: null, human_hours: null },
      branches: [
        { id: "supported_comparison", observable: "Comparable source evidence supports a specific discriminating model or calculation.", decision: "continue", next_direction: "prepare_model" },
        { id: "contradictory_or_incompatible", observable: "Evidence contradicts the premise or belongs to an incompatible state.", decision: "redirect", next_direction: "review_sources" },
        { id: "unresolved", observable: "The checked sources cannot resolve the critical unknown.", decision: "stop", next_direction: "pause" },
      ], numerical_protocol: null, ml: null } };
}

async function prepare(inputValue: ResearchCaseInput, parent: ResearchCase["parent"]): Promise<ResearchCase> {
  input(inputValue); const definition = structuredClone(inputValue), parentPin = structuredClone(parent);
  const definition_sha256 = await hash({ definition, parent: parentPin });
  return verifyResearchCase({ version: RESEARCH_CYCLE_VERSION, target: { ...RESEARCH_TARGET }, binding: { case_id: `research-case:${definition_sha256}`, definition_sha256, state_sha256: await hash(definition.state), action_sha256: await hash(definition.action) }, definition, parent: parentPin, returns: [], decision: null, authority: { ...AUTHORITY } });
}
export const prepareResearchCase = (value: ResearchCaseInput): Promise<ResearchCase> => prepare(value, null);

export async function attachResearchReturn(value: ResearchCase, supplied: ResearchReturnInput): Promise<ResearchCase> {
  bounded(supplied); const payload = structuredClone(supplied), record = await verifyResearchCase(value);
  requireValue(record.decision === null, "Start a follow-up case after recording a decision."); returned(payload, record);
  const return_sha256 = await hash(payload);
  if (record.returns.some(r => r.return_sha256 === return_sha256)) return record;
  record.returns.push({ ...payload, return_sha256 }); return verifyResearchCase(record);
}

export type ResearchDecisionInput = Omit<ResearchDecision, "decision_sha256">;
/** Numerical outcomes determine the permitted decision; other returns retain researcher-selected branches. */
export function researchDecisionBranches(record: ResearchCase, returnSha256?: string): ResearchBranch[] {
  const result = returnSha256 === undefined ? record.returns.at(-1) : record.returns.find(r => r.return_sha256 === returnSha256);
  if (!result) return [];
  if (result.kind !== "qe_sampled_study") return [...record.definition.action.branches];
  const assessment = result.numerical_assessment;
  const outcome: [ResearchOutcome, ResearchDirection] | null = assessment === "sampled_window_within_tolerance" ? ["continue", "refine_method"]
    : ["sampled_window_outside_tolerance", "scf_precision_insufficient", "incomplete_grid"].includes(assessment) ? ["redirect", "refine_method"]
      : assessment === "insufficient_axis_samples" ? ["stop", "pause"] : null;
  return outcome ? record.definition.action.branches.filter(branch => branch.decision === outcome[0] && branch.next_direction === outcome[1]) : [];
}
function validateDecision(record: ResearchCase, supplied: ResearchDecisionInput): void {
  closed(supplied, "return_sha256 branch_id decision next_direction reason");
  const result = record.returns.find(r => r.return_sha256 === supplied.return_sha256);
  const branch = record.definition.action.branches.find(b => b.id === supplied.branch_id);
  requireValue(result && branch && branch.decision === supplied.decision && branch.next_direction === supplied.next_direction && text(supplied.reason), "Choose a declared outcome for an exact retained return and explain the decision.");
  if (result && badNumerics(result)) requireValue(supplied.next_direction !== "assess_physics", "An unresolved numerical window cannot advance to physical interpretation.");
  requireValue(researchDecisionBranches(record, supplied.return_sha256).some(allowed => allowed.id === supplied.branch_id), "The decision and next direction must match the retained QE numerical assessment.");
}
export async function recordResearchDecision(value: ResearchCase, supplied: ResearchDecisionInput): Promise<ResearchCase> {
  bounded(supplied); const payload = structuredClone(supplied), record = await verifyResearchCase(value);
  requireValue(record.decision === null, "A recorded decision is immutable; start a follow-up case."); validateDecision(record, payload);
  record.decision = { ...payload, decision_sha256: await hash(payload) }; return verifyResearchCase(record);
}
export async function deriveResearchCase(value: ResearchCase, next: ResearchCaseInput): Promise<ResearchCase> {
  input(next); const definition = structuredClone(next), parent = await verifyResearchCase(value);
  requireValue(parent.decision !== null, "Record a decision before preparing a linked follow-up.");
  // Follow-up evidence is deliberately empty. Source evidence can be assigned explicitly in a new case.
  requireValue(RESEARCH_AXES.every(axis => definition.evidence[axis].status === "unknown" && definition.evidence[axis].readings.length === 0), "A follow-up cannot inherit physical evidence from its parent.");
  return prepare(definition, { case_id: parent.binding.case_id, definition_sha256: parent.binding.definition_sha256, decision_sha256: parent.decision!.decision_sha256, relation: "research_follow_up", properties_inherited: false });
}

export async function exportResearchCase(value: ResearchCase) {
  const record = await verifyResearchCase(value), payload_sha256 = await hash(record);
  const json = JSON.stringify({ version: "discovery-research-cycle-export/1.0.0", payload_sha256, record }, null, 2) + "\n";
  requireValue(new TextEncoder().encode(json).length <= RESEARCH_CYCLE_MAX_BYTES);
  const sha256 = await textHash(json); return { json, sha256, filename: `sclib-research-case-${sha256.slice(0, 16)}.json` };
}
export async function importResearchCase(source: string): Promise<ResearchCase> {
  requireValue(typeof source === "string" && new TextEncoder().encode(source).length <= RESEARCH_CYCLE_MAX_BYTES, "Choose a research-case export of at most 512 KiB.");
  let parsed: unknown; try { parsed = JSON.parse(source); } catch { return fail("Choose a complete research-case JSON export."); }
  bounded(parsed); const envelope = closed(parsed, "version payload_sha256 record");
  requireValue(envelope.version === "discovery-research-cycle-export/1.0.0" && source === JSON.stringify(parsed, null, 2) + "\n", "Choose the unchanged research-case export, including its complete JSON bytes.");
  const record = await verifyResearchCase(envelope.record); requireValue(envelope.payload_sha256 === await hash(record), "The research-case export digest does not match.");
  return record;
}

export function researchCaseReadiness(record: ResearchCase) {
  const a = record.definition.action, reasons: string[] = [];
  if (a.resources.access !== "available") reasons.push("Execution access is not confirmed.");
  if (Object.entries(a.resources).some(([k, v]) => k !== "access" && v === null)) reasons.push("The resource budget is incomplete.");
  if (a.prerequisites.some(p => p.status !== "met")) reasons.push("Action prerequisites remain unresolved.");
  if (a.kind === "external_experiment") reasons.push("No experimental facility is configured in this research workspace.");
  if (a.kind === "ml_analysis" && a.ml && (a.ml.leakage_review !== "documented" || a.ml.training_permission !== "documented" || a.ml.external_validation !== "documented")) reasons.push("ML data rights, leakage review or external validation remain incomplete.");
  if (a.kind === "calculation" && !record.definition.state.structure) reasons.push("An exact coordinate model is required for this calculation.");
  return { stage: record.decision ? "decision_recorded" as const : record.returns.length ? "returned" as const : reasons.length ? record.definition.state.structure ? "model_ready" as const : "source_ready" as const : "action_ready" as const,
    can_execute: false as const, execution_readiness: reasons.length ? "blocked" as const : "prerequisites_declared" as const, reasons,
    rps_score: null, rank: null, scientific_acceptance: false as const,
    research_value: "Decision-changing outcomes are specified; this is not a superconductivity probability or an evaluated RPS." };
}

/** Reuse the existing verified-reading comparison. No new QE parse, job, or scalar promotion. */
export async function prepareQeStudyReturn(value: ResearchCase, supplied: QeResultReading[], options: { kind: "mesh" | "mesh_smearing"; tolerance: number }, findings: string): Promise<ResearchReturnInput> {
  const readings = structuredClone(supplied), settings = structuredClone(options), note = findings;
  const record = await verifyResearchCase(value);
  requireValue(record.definition.action.kind === "computational_review" && text(note));
  requireValue(settings.kind === "mesh" || settings.kind === "mesh_smearing");
  requireValue(same(record.definition.action.numerical_protocol, { kind: settings.kind, tolerance_hartree_per_atom: settings.tolerance }), "Use the numerical window and tolerance declared before this action.");
  const study = settings.kind === "mesh"
    ? await (await import("@/lib/discovery-qe-convergence")).compareQeReadings(readings, "mesh", settings.tolerance)
    : await (await import("@/lib/discovery-qe-joint-refinement")).compareQeMeshSmearing(readings, settings.tolerance);
  requireValue(record.definition.state.structure?.sha256 === study.report.candidate_cif_sha256, "The QE study belongs to another coordinate model.");
  const declared = new Set(record.definition.action.input_artifacts.map(p => p.sha256));
  requireValue(readings.every(r => declared.has(r.sha256)), "Every original QE reading must be pinned in the research action.");
  const conditions = record.definition.state.conditions;
  requireValue(readings.every(r => conditions.charge_state === r.report.settings.charge && conditions.magnetic_state === (r.report.settings.nspin === 1 ? "nonmagnetic" : "spin_polarized")), "The research charge and magnetic model must match the original prepared readings.");
  const result: ResearchReturnInput = { binding: { ...record.binding }, kind: "qe_sampled_study",
    artifacts: [{ artifact_id: study.filename, version: study.report.version, sha256: study.sha256 }], model_cif_sha256: study.report.candidate_cif_sha256,
    findings: note, remaining_unknowns: ["A finite numerical sensitivity window does not establish a numerical limit.", "Physical stability, pairing and Tc are not established by this study."],
    numerical_assessment: study.report.sampled_window.assessment, association: "researcher_linked_unverified" };
  returned(result, record); return result;
}

/** Reproducible research recipes, not newly executed calculations or published candidates. */
export const RESEARCH_CYCLE_PILOTS = [
  { key: "alb2_numerical_counterexample", formula: "AlB2", strategy: "high_bandwidth", stage: "retained_calculation_review",
    question: "Is numerical sensitivity small enough to interpret a proposed bandwidth comparison?",
    source: "MgB2 COD 1526507; replace the primitive-cell Mg with Al and scale lattice lengths by +2%.",
    evidence: "Retained QE 7.5 SCF readings exist. The 4/6/8 mesh window and the joint mesh–smearing window exceed the example 1e-4 Hartree/atom tolerance.",
    next_action: "Link exact original readings, replay the existing convergence tool, and redirect unresolved numerical work before physical interpretation.",
    tool_href: "/discovery/calculations", new_computation_required_for_this_review: false },
  { key: "srtio3_vacancy_activation", formula: "Sr8Ti8O23", strategy: "high_carrier_density", stage: "recipe_not_generated",
    question: "Would a specified oxygen vacancy produce itinerant carriers, or localized/compensated states?",
    source: "SrTiO3 COD 9006864, revision 291455, x=0 source endpoint; a proposed 2×2×2 model has one explicitly selected oxygen removed.",
    evidence: "The host reference is captured. No vacancy model or carrier result is supplied by this recipe; CIF default occupancy is not a measurement.",
    next_action: "Generate and check the 40-to-39 atom model, specify charge/spin and a pristine control, and inspect applicable source evidence before commissioning a calculation.",
    tool_href: "/discovery/structures/candidates", new_computation_required_for_this_review: false },
  { key: "lah10_pressure_teacher", formula: "LaH10", strategy: "geometry_construction", stage: "source_comparison",
    question: "Which pressure-related geometry and interaction changes merit an explicit ambient-condition modification hypothesis?",
    source: "arXiv:1907.11916v1, Extended Data Table I, PDF page 11; LaH10 and LaD10 remain separate series.",
    evidence: "Four LaH10 and three LaD10 source rows exist. Solver conventions and quantum-energy pressure must remain distinct; coordinate/run identity and ambient survival are unresolved.",
    next_action: "Replay one compound and one solver, retain contrary stability evidence, and record continue/stop/redirect before proposing any structural translation.",
    tool_href: "/discovery#discovery-pressure-response", new_computation_required_for_this_review: false },
] as const;
