import { PUBLIC_API_BASE } from "./api";

// This is the native rv2/1 registry, not the larger planned field dictionary.
export const SCIENTIFIC_FIELDS = {
  band_gap: { label: "Band gap", unit: "eV", group: "electronic" },
  dos_at_fermi: { label: "DOS at Fermi level", unit: "states/eV/formula_unit", group: "electronic" },
  electron_phonon_lambda: { label: "Electron–phonon λ", unit: "1", group: "pairing" },
  energy_above_hull: { label: "Energy above hull", unit: "eV/atom", group: "stability" },
  formation_energy_per_atom: { label: "Formation energy", unit: "eV/atom", group: "stability" },
  omega_log: { label: "ωlog", unit: "K", group: "pairing" },
  phonon_min_frequency: { label: "Sampled phonon minimum", unit: "THz", group: "stability" },
  superfluid_stiffness: { label: "Superfluid stiffness", unit: "K", group: "coherence" },
} as const;
export type ScientificKey = keyof typeof SCIENTIFIC_FIELDS;
export const SCIENTIFIC_KEYS = Object.keys(SCIENTIFIC_FIELDS) as ScientificKey[];
export const SCIENTIFIC_GROUPS = ["stability", "electronic", "pairing", "coherence", "geometry", "competing_order"] as const;
export const SCIENTIFIC_DISCLAIMER = "Policy-based research priority; empirical calibration pending";
export const SCIENTIFIC_FAILURE = "Scientific publication could not be verified at this read point. Materials and scores are hidden. Refresh the catalog to try again.";
export const SCIENTIFIC_MAX_BYTES = 4 * 1024 * 1024 + 64 * 1024;
const VERSION = "discovery-scientific-projection/1.0.0";
const VERSION_V2 = "discovery-scientific-projection/2.0.0";
const PROFILE = "sampled-phonon-minimum-review/1.0.0";
const PROFILES = ["common", "epc_hydride", "layered_correlated", "multiband", "flatband"];
const RESOURCES = ["cpu_core_hours", "gpu_hours", "memory_gib", "storage_gib", "human_hours"];

// A small closed-schema vocabulary keeps wire validation and TS types together.
type Check<T> = (value: unknown) => value is T;
type Value<C> = C extends Check<infer T> ? T : never;
const record = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
function object<S extends Record<string, Check<unknown>>>(s: S): Check<{ [K in keyof S]: Value<S[K]> }> {
  return (v): v is { [K in keyof S]: Value<S[K]> } => record(v) && Object.keys(v).length === Object.keys(s).length
    && Object.entries(s).every(([k, check]) => Object.hasOwn(v, k) && check(v[k]));
}
const literal = <T extends string | boolean | null>(wanted: T): Check<T> => (v): v is T => v === wanted;
const one = <const T extends string>(values: readonly T[]): Check<T> => (v): v is T => typeof v === "string" && values.includes(v as T);
const nullable = <T>(check: Check<T>): Check<T | null> => (v): v is T | null => v === null || check(v);
const list = <T>(check: Check<T>, max: number, min = 0): Check<T[]> => (v): v is T[] => Array.isArray(v)
  && v.length >= min && v.length <= max && v.every(check);
const union = <A, B>(a: Check<A>, b: Check<B>): Check<A | B> => (v): v is A | B => a(v) || b(v);
const str = (max: number): Check<string> => (v): v is string => typeof v === "string" && !!v.trim()
  && Array.from(v).length <= max && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(v);
const finite: Check<number> = (v): v is number => typeof v === "number" && Number.isFinite(v);
const range = (min: number, max: number): Check<number> => (v): v is number => finite(v) && v >= min && v <= max;
const integer = (min: number, max = Number.MAX_SAFE_INTEGER): Check<number> => (v): v is number => range(min, max)(v) && Number.isSafeInteger(v);
const sha: Check<string> = (v): v is string => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const uuid: Check<string> = (v): v is string => typeof v === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(v);
const identifier: Check<string> = (v): v is string => typeof v === "string" && /^[A-Za-z0-9_.:-]{1,120}$/.test(v) && v !== "." && v !== "..";
const code = str(200);
const falseFlag = literal(false);
const percent = range(0, 100);
const nonnegative = range(0, Number.MAX_VALUE);
function dictionary<T>(check: Check<T>, keys: Check<string>, min = 0, max = 200): Check<Record<string, T>> {
  return (v): v is Record<string, T> => record(v) && Object.keys(v).length >= min && Object.keys(v).length <= max
    && Object.entries(v).every(([k, value]) => keys(k) && check(value));
}
const dimensions = <T>(check: Check<T>) => object(Object.fromEntries(SCIENTIFIC_GROUPS.map(k => [k, check])));
const mix = dictionary(range(0, 1), one(PROFILES), 1, 5);
const pinFields = { id: uuid, row_sha256: sha };
const refFields = { id: identifier, sha256: sha };
const assessmentRef = object({ ...refFields, revision: integer(1) });
const rowRef = <T extends string>(tables: readonly T[]) => object({ table: one(tables), row_id: uuid, row_sha256: sha });
const materialRef = object({ table: literal("materials"), row_id: str(100), row_sha256: sha });
const artifact = object({ ...pinFields, kind: one(["literature_locator", "structure", "run_manifest", "policy", "review", "dataset", "other"]),
  bytes_sha256: nullable(sha), hash_status: one(["verified", "unavailable", "not_applicable"]) });
const locator = union(object({ line: integer(1, 1000000), start_byte: integer(0, 64 * 1024 * 1024), end_byte: integer(0, 64 * 1024 * 1024) }), object({ scope: literal("locator_not_disclosed") }));
const scope = object({ scope: one(["extraction_fidelity", "scientific_result"]), profile_version: nullable(str(120)),
  decision_id: nullable(uuid), decision_sha256: nullable(sha), decision: nullable(literal("accept")),
  effective_status: one(["unreviewed", "accepted"]), reason_codes: list(code, 0), scientific_scope_accepted: oneBoolean() });
function oneBoolean(): Check<boolean> { return (v): v is boolean => typeof v === "boolean"; }
const quantity = object({ relation: one(["exact", "interval", "lt", "le", "gt", "ge", "unreported"]),
  value: nullable(finite), lower: nullable(finite), upper: nullable(finite), unit: str(60) });
export type ScientificQuantity = Value<typeof quantity>;
const conditions = {
  pressure_status: one(["explicit_ambient", "reported", "not_reported", "ambiguous"]), pressure_gpa: nullable(nonnegative),
  temperature_role: one(["measurement", "synthesis", "simulation", "unknown"]), temperature_k: nullable(nonnegative),
};
const observation = object({
  version: literal("discovery-scientific-observation/1.0.0"),
  property: object({ ...pinFields, property_key: one(SCIENTIFIC_KEYS), registry_version: literal("rv2/1"), component_key: str(120) }),
  quantity,
  event: object({ ...pinFields, revision: integer(1), event_type: one(["measurement", "calculation", "extraction", "curation", "prediction", "priority_assessment"]),
    knowledge_origin: one(["Observed", "Computed", "Inferred", "AI-Proposed", "unknown"]) }),
  material: object({ id: str(100), row_sha256: sha }),
  state: object({ ...pinFields, ...conditions, resolution: one(["resolved", "source_scoped", "unresolved"]), context_sha256: sha, source_artifact: artifact }),
  sample: nullable(object(pinFields)),
  structure: nullable(object({ ...pinFields, structure_kind: one(["coordinates", "prototype", "literature_description", "unresolved"]), artifact_id: nullable(uuid) })),
  run: nullable(object({ ...pinFields, run_kind: one(["extraction", "composition_features", "structure_matching", "dft", "dfpt", "ml_prediction", "priority_assessment", "curation"]),
    status: one(["planned", "running", "completed", "failed", "cancelled"]), input_manifest: nullable(artifact), output_manifest: nullable(artifact) })),
  sources: list(object({ ...pinFields, table: literal("event_evidence"), owner_event_id: uuid,
    relation_scope: one(["selected_event", "forward_dependency"]), link_type: one(["source", "derives_from", "context", "supports", "refutes"]),
    artifact: nullable(artifact), input_event_id: nullable(uuid), input_property_id: nullable(uuid), input_claim_id: nullable(uuid), locator }), 2000),
  source_occurrences: list(union(
    object({ ...pinFields, table: literal("snapshot_event_memberships"), relation_scope: literal("event_snapshot_membership"), event_id: uuid, snapshot_id: uuid, locator }),
    object({ ...pinFields, table: literal("claim_source_occurrences"), relation_scope: literal("forward_claim_source_occurrence"), claim_id: uuid, source_revision_id: uuid, capture_id: uuid, locator }),
  ), 2000),
  review: object({ subject_sha256: sha, status_revision_sha256: sha, scopes: list(scope, 2, 2) }),
  normalization: object({ status: literal("not_asserted"), reason_code: literal("normalization_not_established_by_registry_unit") }),
  scientific_scope_accepted: oneBoolean(), ml_training_approved: falseFlag, public_release_authorized: falseFlag,
});
export type ScientificObservation = Value<typeof observation>;
const polarity = one(["supporting", "opposing", "mixed", "neutral", "unknown"]);
const assessment = object({
  id: identifier, revision: integer(1), rank: nullable(integer(1, 200)),
  material_id: identifier, state_id: identifier, action_id: identifier, formula: str(4000), family: str(4000),
  state_summary: str(4000), action_summary: str(4000),
  role: one(["new_candidate", "conditional_candidate", "mechanism_anchor", "reference_anchor", "benchmark_control", "negative_control"]),
  action_template: object({ id: identifier, version: identifier, sha256: sha, review_id: identifier }),
  dimensions: dimensions(object({ status: one(["assessed", "unknown"]), anchor: nullable(percent), lower: percent, upper: percent,
    missing_reason: nullable(str(4000)), evidence_polarity: polarity })),
  result: object({
    eligibility: one(["eligible", "pending", "ineligible", "reference_only"]), reason_codes: list(code, 200),
    rank_group: one(["discovery", "mechanism"]), policy_version: literal("RPS-v1.2"), policy_hash: sha,
    knowledge_origin: literal("Inferred"), run_kind: literal("priority_assessment"), action_contract_version: literal("rps-action-contract/1"),
    action_requirements_hash: sha, execution_constraint_reasons: list(code, 200),
    score_raw: nullable(range(1000, 10000)), score_display: nullable(integer(1000, 10000)), score_upper: nullable(range(1000, 10000)),
    p_lower: percent, p_upper: percent, g_lower: percent, g_upper: percent, a_lower: nullable(percent), a_upper: nullable(percent),
    affordability_lower: nullable(range(0, 1)), affordability_upper: nullable(range(0, 1)),
    assessed_weight: range(0, 1), effective_weights: dimensions(range(0, 1)),
    contributions: object({ baseline: finite, physical: finite, gain: finite, action: nullable(finite), rounding: nullable(finite),
      dimensions: dimensions(finite), dimension_reasons: dimensions(code),
      dimension_explanations: dimensions(object({ evidence_polarity: polarity, reason_codes: list(code, 200),
        anchor_contribution: nullable(finite), uncertainty_discount: nullable(finite), missing_support_contribution: finite })) }),
  }),
});
export type ScientificAssessment = Value<typeof assessment>;
const selectionCellFields = { property_key: one(SCIENTIFIC_KEYS), availability: one(["reported", "unknown", "not_computed", "not_applicable", "conflicted"]),
  reason_code: code, result_refs: list(rowRef(["event_properties"]), 8), evidence_refs: list(rowRef(["event_evidence", "research_runs", "evidence_artifacts"]), 20) };
const cell = object({ ...selectionCellFields, unit: str(60), group: one(SCIENTIFIC_GROUPS), observations: list(observation, 8),
  availability_basis: one(["explicit_review_required_declaration", "registered_result_inventory"]) });
export type ScientificCell = Value<typeof cell>;
export const MAIN_BARRIER_CATEGORIES = {
  evidence_gap: "Evidence gap", execution_constraint: "Execution constraint",
  scientific_hypothesis: "Scientific hypothesis", recorded_policy_reason: "Recorded policy reason",
} as const;
export type MainBarrierCategory = keyof typeof MAIN_BARRIER_CATEGORIES;
// Python's retained barrier contract uses Unicode White_Space, not JS trim
// (which treats FEFF as blank but misses U+0085). Do not change v1 text rules.
const barrierText = (max: number): Check<string> => (v): v is string => typeof v === "string" && /\P{White_Space}/u.test(v)
  && Array.from(v).length <= max && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(v)
  && Array.from(v).every(c => { const cp = c.codePointAt(0)!; return cp < 0xd800 || cp > 0xdfff; });
const mainBarrierBasis = union(union(object({ kind: literal("assessment_reason"), code: barrierText(200) }),
  object({ kind: literal("execution_constraint"), code: barrierText(200) })), object({ kind: literal("scientific_cell"), property_key: one(SCIENTIFIC_KEYS) }));
export type MainBarrierBasis = Value<typeof mainBarrierBasis>;
export const mainBarrierShape = union(object({ status: literal("not_declared") }), object({ status: literal("declared"),
  category: one(Object.keys(MAIN_BARRIER_CATEGORIES) as MainBarrierCategory[]), statement: barrierText(500), rationale: barrierText(2000),
  basis_refs: list(mainBarrierBasis, 8, 1) }));
export type MainBarrier = Value<typeof mainBarrierShape>;
export const mainBarrierBasisKey = (basis: MainBarrierBasis) => `${basis.kind}:${basis.kind === "scientific_cell" ? basis.property_key : basis.code}`;
export function compareMainBarrierBasis(a: MainBarrierBasis, b: MainBarrierBasis) {
  const left = Array.from(mainBarrierBasisKey(a), c => c.codePointAt(0)!), right = Array.from(mainBarrierBasisKey(b), c => c.codePointAt(0)!);
  for (let i = 0; i < Math.min(left.length, right.length); i++) if (left[i] !== right[i]) return left[i] - right[i];
  return left.length - right.length;
}
const materialRowFields = {
  material: materialRef, state: rowRef(["material_states"]), structure: nullable(rowRef(["structure_records"])),
  representative: assessmentRef, selection_rationale: str(2000), assessment, assessment_review: object(refFields),
  state_context: object({ material_id: identifier, ...conditions, phase: str(4000), sample_context: str(4000) }),
  profile_assignment: object({ campaign_hash: sha, mix }),
  alternatives: list(object({ reference: assessmentRef, assessment }), 199), cells: list(cell, 8, 8),
};
const materialRow = object(materialRowFields);
const materialRowV2 = object({ ...materialRowFields, main_barrier: mainBarrierShape });
export type ScientificMaterial = Value<typeof materialRow> | Value<typeof materialRowV2>;
const campaign = object({ id: identifier, version: identifier, objective: str(4000), target_pressure_max_gpa: nonnegative,
  budget: dictionary(nonnegative, one(RESOURCES), 0, 5), profile_mixes: dictionary(mix, identifier, 1),
  dimension_rules: dimensions(identifier), action_templates: dictionary(sha, identifier, 1) });
const representativeFields = { material: object(refFields), assessment: assessmentRef, structure: nullable(rowRef(["structure_records"])),
  rationale: str(2000), alternatives: list(assessmentRef, 199), cells: list(object(selectionCellFields), 8, 8) };
const selectionFields = { release_manifest_sha256: sha, public_bundle_sha256: sha };
const selection = object({ ...selectionFields, version: literal("discovery-scientific-selection/1.0.0"),
  representatives: list(object(representativeFields), 25, 1) });
const selectionV2 = object({ ...selectionFields, version: literal("discovery-scientific-selection/2.0.0"),
  representatives: list(object({ ...representativeFields, main_barrier: mainBarrierShape }), 25, 1) });
const payloadFields = { disclaimer: literal(SCIENTIFIC_DISCLAIMER),
  comparison_scope: literal("same_frozen_campaign_budget_policy_release"), evaluation_protocol: literal("https://github.com/JackZH26/SCLib_JZIS/issues/78"),
  base: object({ distribution_package_id: uuid, distribution_record_sha256: sha, inventory_sha256: sha, release_id: identifier,
    release_manifest_sha256: sha, public_bundle_sha256: sha }), campaign, campaign_sha256: sha, policy_sha256: sha, selection_sha256: sha,
  capabilities: object({ version: literal(VERSION), registry_version: literal("rv2/1"), groups: list(one(SCIENTIFIC_GROUPS), 6, 6),
    scientific_properties: list(object({ property_key: one(SCIENTIFIC_KEYS), unit: str(60), group: one(SCIENTIFIC_GROUPS),
      storage_supported: literal(true), quantity_projection_supported: literal(true), exact_scientific_review_supported: oneBoolean(),
      scientific_review_profile: nullable(literal(PROFILE)), scientific_review_relations: list(literal("exact"), 1), populated_observations: integer(0, 100) }), 8, 8),
    planned_groups: list(one(["geometry", "competing_order"]), 2, 2), unregistered_dictionary_fields: literal("planned_not_database_properties"),
    rps_fields: object({ kind: literal("policy_assessment_not_scientific_ground_truth"), keys: list(one(["rps_score", "rps_physical", "rps_gain", "rps_action"]), 4, 4) }) }),
  scientific_acceptance: falseFlag, ml_training_approved: falseFlag, public_release_authorized: falseFlag,
};
const payload = union(object({ ...payloadFields, version: literal(VERSION), selection, rows: list(materialRow, 25, 1) }),
  object({ ...payloadFields, version: literal(VERSION_V2), selection: selectionV2, rows: list(materialRowV2, 25, 1) }));
const publicationFields = { package_id: uuid, payload_sha256: sha, selection_sha256: sha, publication_sha256: sha, review_sha256: sha };
const publication = object(publicationFields);
export type ScientificPublication = Value<typeof publication>;
const catalogSchema = object({ version: literal("discovery-scientific-catalog/1.0.0"), status: one(["published", "degraded", "unavailable", "not_published"]),
  items: list(publication, 25), unavailable_count: integer(0, 25), scientific_acceptance: falseFlag, ml_training_approved: falseFlag });
export type ScientificCatalog = Value<typeof catalogSchema>;
const receipt = object({ version: literal("discovery-projection-governance/1.0.0"), ...publicationFields, payload,
  scientific_acceptance: falseFlag, ml_training_approved: falseFlag, current_authorization_checked: falseFlag });
export type ScientificReceipt = Value<typeof receipt>;
export type ScientificPayload = Value<typeof payload>;

// Reuse the same closed scientific shapes in the private curator reader.
// This is not a public-admission entry point.
export const preparationScientificShapes = { assessment, campaign, quantity, materialRef, assessmentRef,
  stateContext: object({ material_id: identifier, ...conditions, phase: str(4000), sample_context: str(4000) }) };
export function validatePreparationAssessment(a: ScientificAssessment, c: ScientificPayload["campaign"]) {
  checkAssessment(a, { campaign: c, policy_sha256: a.result.policy_hash });
}

function requireValue(value: unknown): asserts value { if (!value) throw new Error(SCIENTIFIC_FAILURE); }
const equal = (a: unknown, b: unknown): boolean => {
  if (a === b) return true;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v, i) => equal(v, b[i]));
  return record(a) && record(b) && Object.keys(a).length === Object.keys(b).length
    && Object.keys(a).every(k => Object.hasOwn(b, k) && equal(a[k], b[k]));
};
const sortedUnique = (items: string[]) => items.every((item, i) => i === 0 || items[i - 1] < item);
export type MainBarrierCell = Pick<ScientificCell, "property_key" | "availability"> & { quantified: boolean };
/** Basis membership records the curator's selection, not scientific truth. */
export function mainBarrierOptions(category: MainBarrierCategory, a: ScientificAssessment, cells: MainBarrierCell[]): MainBarrierBasis[] {
  const refs: MainBarrierBasis[] = category === "recorded_policy_reason"
    ? [...new Set(a.result.reason_codes)].map(code => ({ kind: "assessment_reason", code }))
    : category === "execution_constraint" ? [...new Set(a.result.execution_constraint_reasons)].map(code => ({ kind: "execution_constraint", code }))
      : cells.filter(c => category === "evidence_gap" ? ["unknown", "not_computed", "conflicted"].includes(c.availability)
        : ["reported", "conflicted"].includes(c.availability) && c.quantified).map(c => ({ kind: "scientific_cell", property_key: c.property_key }));
  return refs.sort(compareMainBarrierBasis);
}
export function validMainBarrier(value: unknown, a: ScientificAssessment, cells: MainBarrierCell[]): value is MainBarrier {
  if (!mainBarrierShape(value)) return false;
  if (value.status === "not_declared") return true;
  const options = mainBarrierOptions(value.category, a, cells);
  return value.basis_refs.every((ref, i) => i === 0 || compareMainBarrierBasis(value.basis_refs[i - 1], ref) < 0)
    && value.basis_refs.every(ref => options.some(option => equal(ref, option)));
}
function validConditions(v: Value<typeof observation>["state"] | ScientificMaterial["state_context"]) {
  requireValue(v.pressure_status === "explicit_ambient" ? v.pressure_gpa === 0 : v.pressure_status === "reported"
    ? v.pressure_gpa !== null : v.pressure_gpa === null);
  requireValue(v.temperature_role !== "unknown" || v.temperature_k === null);
}
function checkObservation(o: ScientificObservation, c: ScientificCell, r: ScientificMaterial) {
  const q = o.quantity, key = c.property_key;
  const shapes = {
    exact: q.value !== null && q.lower === null && q.upper === null,
    interval: q.value === null && q.lower !== null && q.upper !== null && q.lower <= q.upper,
    lt: q.value === null && q.lower === null && q.upper !== null, le: q.value === null && q.lower === null && q.upper !== null,
    gt: q.value === null && q.lower !== null && q.upper === null, ge: q.value === null && q.lower !== null && q.upper === null,
    unreported: q.value === null && q.lower === null && q.upper === null,
  };
  requireValue(shapes[q.relation] && o.property.property_key === key && q.unit === c.unit);
  if (key !== "formation_energy_per_atom" && key !== "phonon_min_frequency") requireValue([q.value, q.lower, q.upper].every(v => v === null || v >= 0));
  for (const name of ["material", "state", "structure"] as const) {
    const native = o[name], selected = r[name];
    requireValue(selected === null ? native === null : native !== null && native.id === selected.row_id && native.row_sha256 === selected.row_sha256);
  }
  validConditions(o.state);
  for (const k of ["pressure_status", "pressure_gpa", "temperature_role", "temperature_k"] as const) requireValue(o.state[k] === r.state_context[k]);
  requireValue(o.structure?.structure_kind !== "coordinates" || o.structure.artifact_id !== null);
  requireValue(!["Computed", "AI-Proposed"].includes(o.event.knowledge_origin) || o.run !== null);
  const [fidelity, science] = o.review.scopes;
  requireValue(fidelity.scope === "extraction_fidelity" && science.scope === "scientific_result");
  for (const s of o.review.scopes) {
    if (s.effective_status === "unreviewed") requireValue([s.profile_version, s.decision_id, s.decision_sha256, s.decision].every(v => v === null) && !s.scientific_scope_accepted);
    else requireValue(key === "phonon_min_frequency" && q.relation === "exact" && s.decision === "accept" && s.decision_id !== null && s.decision_sha256 !== null
      && (s.scope === "scientific_result" ? s.profile_version === PROFILE && s.scientific_scope_accepted
        : ["native-sampled-frequency-extraction/1.0.0", "recorded-sampled-frequency-fidelity/1.0.0"].includes(s.profile_version!) && !s.scientific_scope_accepted));
  }
  requireValue(o.scientific_scope_accepted === (science.effective_status === "accepted")
    && (!o.scientific_scope_accepted || fidelity.effective_status === "accepted"));
  const artifacts = [o.state.source_artifact, o.run?.input_manifest, o.run?.output_manifest, ...o.sources.map(s => s.artifact)];
  for (const a of artifacts) if (a) requireValue((a.hash_status === "verified") === (a.bytes_sha256 !== null));
  requireValue(sortedUnique(o.sources.map(s => s.id)) && sortedUnique(o.source_occurrences.map(s => `${s.table}:${s.id}`)));
  for (const source of o.sources) {
    requireValue((source.relation_scope === "selected_event") === (source.owner_event_id === o.event.id));
    requireValue(source.link_type === "source"
      ? source.artifact !== null && [source.input_event_id, source.input_property_id, source.input_claim_id].every(v => v === null)
      : source.artifact === null && source.input_event_id !== null && source.input_event_id !== source.owner_event_id
        && !(source.input_property_id !== null && source.input_claim_id !== null));
    if (source.link_type === "derives_from") requireValue([source.input_property_id, source.input_claim_id].filter(v => v !== null).length === 1);
  }
  for (const s of [...o.sources, ...o.source_occurrences]) if ("line" in s.locator) requireValue(s.locator.end_byte >= s.locator.start_byte);
}
function checkAssessment(a: ScientificAssessment, p: Pick<ScientificPayload, "campaign" | "policy_sha256">) {
  const s = a.result;
  requireValue(s.policy_hash === p.policy_sha256 && p.campaign.action_templates[a.action_template.id] === a.action_template.sha256);
  requireValue(s.rank_group === (a.role === "mechanism_anchor" ? "mechanism" : "discovery")
    && (s.eligibility === "reference_only") === ["reference_anchor", "benchmark_control", "negative_control"].includes(a.role));
  const scored = s.eligibility === "eligible";
  requireValue(scored ? s.score_display !== null && s.score_display % 50 === 0 && s.score_raw !== null && s.score_upper !== null && s.a_lower !== null && a.rank !== null
    : s.score_display === null && s.score_raw === null && s.score_upper === null && a.rank === null);
  requireValue(s.p_lower <= s.p_upper && s.g_lower <= s.g_upper && (s.a_lower === null || s.a_upper !== null && s.a_lower <= s.a_upper));
  for (const d of Object.values(a.dimensions)) requireValue([0, 25, 50, 75, 100].includes(d.lower) && [0, 25, 50, 75, 100].includes(d.upper) && d.lower <= d.upper && (d.status === "unknown"
    ? d.anchor === null && d.missing_reason !== null && d.evidence_polarity === "unknown" && d.lower === 0 && d.upper === 100
    : d.anchor !== null && [0, 25, 50, 75, 100].includes(d.anchor) && d.lower <= d.anchor && d.anchor <= d.upper && d.missing_reason === null));
}
function checkPayload(p: ScientificReceipt["payload"]) {
  requireValue(p.selection.release_manifest_sha256 === p.base.release_manifest_sha256 && p.selection.public_bundle_sha256 === p.base.public_bundle_sha256);
  requireValue(equal(p.capabilities.groups, SCIENTIFIC_GROUPS) && equal(p.capabilities.planned_groups, ["geometry", "competing_order"])
    && equal(p.capabilities.rps_fields.keys, ["rps_score", "rps_physical", "rps_gain", "rps_action"]));
  requireValue(equal(p.capabilities.scientific_properties.map(c => c.property_key), SCIENTIFIC_KEYS));
  requireValue(p.rows.length === p.selection.representatives.length && sortedUnique(p.rows.map(r => r.assessment.material_id))
    && new Set(p.rows.map(r => r.material.row_id)).size === p.rows.length);
  const properties = new Set<string>(), assessments = new Set<string>();
  const counts = Object.fromEntries(SCIENTIFIC_KEYS.map(k => [k, 0]));
  for (const [i, r] of p.rows.entries()) {
    const selected = p.selection.representatives[i];
    if (p.version === VERSION_V2) {
      requireValue("main_barrier" in r && "main_barrier" in selected && equal(r.main_barrier, selected.main_barrier)
        && validMainBarrier(r.main_barrier, r.assessment, r.cells.map(c => ({ ...c, quantified: c.observations.some(o => o.quantity.relation !== "unreported") }))));
    }
    requireValue(selected.material.id === r.assessment.material_id && r.state_context.material_id === r.assessment.material_id
      && equal(selected.assessment, r.representative) && equal(selected.structure, r.structure) && selected.rationale === r.selection_rationale
      && equal(selected.alternatives, r.alternatives.map(a => a.reference)));
    requireValue(r.profile_assignment.campaign_hash === p.campaign_sha256 && Object.values(p.campaign.profile_mixes).some(m => equal(m, r.profile_assignment.mix)));
    validConditions(r.state_context);
    requireValue(sortedUnique(r.alternatives.map(a => a.reference.id)));
    for (const a of [{ reference: r.representative, assessment: r.assessment }, ...r.alternatives]) {
      requireValue(a.reference.id === a.assessment.id && a.reference.revision === a.assessment.revision
        && a.assessment.material_id === selected.material.id && !assessments.has(a.reference.id));
      assessments.add(a.reference.id); checkAssessment(a.assessment, p);
    }
    requireValue(equal(r.cells.map(c => c.property_key), SCIENTIFIC_KEYS));
    for (const [j, c] of r.cells.entries()) {
      const spec = SCIENTIFIC_FIELDS[c.property_key], { unit, group, observations, availability_basis, ...choice } = c;
      requireValue(equal(choice, selected.cells[j]) && unit === spec.unit && group === spec.group);
      requireValue(sortedUnique(c.result_refs.map(ref => `${ref.table}:${ref.row_id}`)) && sortedUnique(c.evidence_refs.map(ref => `${ref.table}:${ref.row_id}`)));
      requireValue(equal(c.result_refs, observations.map(o => ({ table: "event_properties", row_id: o.property.id, row_sha256: o.property.row_sha256 }))));
      const declared = ["not_computed", "not_applicable", "conflicted"].includes(c.availability);
      requireValue(availability_basis === (declared ? "explicit_review_required_declaration" : "registered_result_inventory") && (!declared || c.evidence_refs.length > 0));
      const quantified = observations.filter(o => o.quantity.relation !== "unreported");
      requireValue(c.availability === "reported" ? quantified.length > 0 : c.availability === "conflicted"
        ? quantified.length >= 2 && new Set(quantified.map(o => o.property.component_key)).size === 1 : quantified.length === 0);
      if (c.availability === "unknown") requireValue(c.reason_code === (observations.length ? "source_does_not_report_value" : "no_matching_registered_result"));
      for (const o of observations) {
        requireValue(!properties.has(o.property.id)); properties.add(o.property.id);
        checkObservation(o, c, r); counts[c.property_key] += 1;
      }
    }
  }
  requireValue(properties.size <= 100 && assessments.size <= 200);
  for (const c of p.capabilities.scientific_properties) {
    const spec = SCIENTIFIC_FIELDS[c.property_key], supported = c.property_key === "phonon_min_frequency";
    requireValue(c.unit === spec.unit && c.group === spec.group && c.populated_observations === counts[c.property_key]
      && c.exact_scientific_review_supported === supported && c.scientific_review_profile === (supported ? PROFILE : null)
      && equal(c.scientific_review_relations, supported ? ["exact"] : []));
  }
}

/** Locate complete JSON value spans without round-tripping Python float spelling.
 * Duplicate keys, non-finite numbers, unpaired surrogates and excess nesting are
 * rejected before JSON.parse. Hashes bind bytes, not scientific truth or rights.
 */
function scan(raw: string, limit: number, paths = ["payload", "payload/selection", "payload/campaign"], maxDepth = 40, maxNodes = 200000) {
  requireValue(raw.length <= limit && new TextEncoder().encode(raw).length <= limit);
  let at = 0, nodes = 0;
  const spans = new Map<string, string>();
  const white = () => { while (/[ \n\r\t]/.test(raw[at] ?? "x")) at++; };
  function string() {
    const start = at++;
    while (at < raw.length) {
      const char = raw[at++];
      if (char === "\\") { at++; continue; }
      if (char === '"') {
        const value: unknown = JSON.parse(raw.slice(start, at));
        requireValue(typeof value === "string");
        for (let i = 0; i < value.length; i++) {
          const code = value.charCodeAt(i);
          if (code >= 0xd800 && code <= 0xdbff) { const next = value.charCodeAt(++i); requireValue(next >= 0xdc00 && next <= 0xdfff); }
          else requireValue(code < 0xdc00 || code > 0xdfff);
        }
        return value;
      }
    }
    throw new Error(SCIENTIFIC_FAILURE);
  }
  function value(path: string[], depth: number) {
    requireValue(depth <= maxDepth && ++nodes <= maxNodes); white(); const start = at;
    if (raw[at] === "{") {
      at++; white(); const keys = new Set<string>();
      if (raw[at] !== "}") while (true) {
        requireValue(raw[at] === '"'); const key = string(); requireValue(!keys.has(key)); keys.add(key);
        white(); requireValue(raw[at++] === ":"); value([...path, key], depth + 1); white();
        if (raw[at] !== ",") break; at++; white();
      }
      requireValue(raw[at++] === "}");
    } else if (raw[at] === "[") {
      at++; white(); let index = 0;
      if (raw[at] !== "]") while (true) { value([...path, String(index++)], depth + 1); white(); if (raw[at] !== ",") break; at++; white(); }
      requireValue(raw[at++] === "]");
    } else if (raw[at] === '"') string();
    else {
      const match = /^(?:true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/.exec(raw.slice(at));
      requireValue(match); at += match[0].length;
      if (!/^(true|false|null)$/.test(match[0])) {
        const number = Number(match[0]);
        requireValue(Number.isFinite(number) && (number !== 0 || !/[1-9]/.test(match[0].split(/[eE]/)[0])));
      }
    }
    const key = path.join("/");
    if (paths.includes(key)) spans.set(key, raw.slice(start, at));
  }
  try { value([], 0); white(); requireValue(at === raw.length); return { value: JSON.parse(raw) as unknown, spans }; }
  catch { throw new Error(SCIENTIFIC_FAILURE); }
}
async function hash(raw: string) {
  const bytes = new TextEncoder().encode(raw);
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), b => b.toString(16).padStart(2, "0")).join("");
}
export function parseScientificCatalog(raw: string): ScientificCatalog {
  const { value } = scan(raw, 16 * 1024);
  requireValue(catalogSchema(value));
  const status = value.items.length ? value.unavailable_count ? "degraded" : "published" : value.unavailable_count ? "unavailable" : "not_published";
  requireValue(value.status === status && value.items.length + value.unavailable_count <= 25 && sortedUnique(value.items.map(i => i.package_id)));
  return value;
}
export async function parseScientificReceipt(raw: string, selected: ScientificPublication): Promise<ScientificReceipt> {
  requireValue(publication(selected)); const expected = { ...selected };
  const { value, spans } = scan(raw, SCIENTIFIC_MAX_BYTES);
  requireValue(receipt(value));
  for (const k of Object.keys(publicationFields) as (keyof ScientificPublication)[]) requireValue(value[k] === expected[k]);
  requireValue(value.payload.selection_sha256 === expected.selection_sha256);
  checkPayload(value.payload);
  // Public-only admission remains unconditional at the public entry point.
  requireValue(value.payload.rows.some(r => r.cells.some(c => c.observations.some(o => o.scientific_scope_accepted))));
  const actual = await Promise.all(["payload", "payload/selection", "payload/campaign"].map(k => { requireValue(spans.has(k)); return hash(spans.get(k)!); }));
  requireValue(actual[0] === expected.payload_sha256 && actual[1] === expected.selection_sha256 && actual[2] === value.payload.campaign_sha256);
  return value;
}

/** Private text parsing retains every other closed/scientific invariant, but
 * legitimately permits empty or wholly unreviewed scientific observations. */
export function parsePrivateDiscoveryJSON(raw: string, limit: number, paths: string[] = []) {
  return scan(raw, limit, paths, 48, 500000);
}
export async function parsePreparedScientificPayload(raw: string, expectedPayload: string, expectedSelection: string) {
  const { value, spans } = scan(raw, 4 * 1024 * 1024, ["selection", "campaign"], 48, 500000);
  requireValue(payload(value) && sha(expectedPayload) && sha(expectedSelection));
  checkPayload(value);
  requireValue(value.selection_sha256 === expectedSelection);
  const actual = await Promise.all([hash(raw), hash(spans.get("selection")!), hash(spans.get("campaign")!)]);
  requireValue(actual[0] === expectedPayload && actual[1] === expectedSelection && actual[2] === value.campaign_sha256);
  return { payload: value, selectionJSON: spans.get("selection")!, campaignJSON: spans.get("campaign")! };
}

async function publicText(path: string, max: number, signal?: AbortSignal) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) abort();
  const timer = setTimeout(abort, 60000); // Server permits a total 55-second admission budget.
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  try {
    const response = await fetch(`${PUBLIC_API_BASE.replace(/\/$/, "")}/discovery/scientific${path}`, {
      method: "GET", credentials: "omit", cache: "no-store", redirect: "error", signal: controller.signal,
      headers: { Accept: "application/json" },
    });
    requireValue(response.ok && /^application\/json(?:\s*;|$)/i.test(response.headers.get("content-type") ?? "") && response.body);
    const length = response.headers.get("content-length");
    requireValue(length === null || /^\d+$/.test(length) && Number(length) <= max);
    reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });
    let raw = "", size = 0, parts = 0;
    while (true) {
      const chunk = await reader.read();
      requireValue(!controller.signal.aborted);
      if (chunk.done) break;
      size += chunk.value.byteLength; requireValue(size <= max && ++parts <= 4096);
      raw += decoder.decode(chunk.value, { stream: true });
    }
    return raw + decoder.decode();
  } catch { throw new Error(SCIENTIFIC_FAILURE); }
  finally { controller.abort(); void reader?.cancel().catch(() => {}); clearTimeout(timer); signal?.removeEventListener("abort", abort); }
}
export async function getScientificCatalog(signal?: AbortSignal) {
  return parseScientificCatalog(await publicText("", 16 * 1024, signal));
}
export async function getScientificProjection(selected: ScientificPublication, signal?: AbortSignal) {
  requireValue(publication(selected)); const expected = { ...selected };
  const checked = await parseScientificReceipt(await publicText(`/${expected.package_id}`, SCIENTIFIC_MAX_BYTES, signal), expected);
  requireValue(!signal?.aborted); return checked;
}

// No fixed decimal rounding: a small nonzero scientific result must stay nonzero.
export const scientificNumber = (value: number | null) => value === null ? "Unknown" : Object.is(value, -0) ? "−0" : String(value);
export function scientificQuantity(q: ScientificQuantity) {
  const n = scientificNumber;
  const value = q.relation === "exact" ? n(q.value) : q.relation === "interval" ? `[${n(q.lower)}, ${n(q.upper)}]`
    : q.relation === "lt" ? `< ${n(q.upper)}` : q.relation === "le" ? `≤ ${n(q.upper)}`
      : q.relation === "gt" ? `> ${n(q.lower)}` : q.relation === "ge" ? `≥ ${n(q.lower)}` : "Unreported";
  return q.relation === "unreported" ? value : `${value}${q.unit === "1" ? " (dimensionless)" : ` ${q.unit}`}`;
}
export const AVAILABILITY_LABELS = { reported: "Reported", unknown: "Unknown", not_computed: "Not computed (declared)",
  not_applicable: "Not applicable (declared)", conflicted: "Conflicted (declared)" } as const;
