import { API_BASE, ApiError } from "./api";
import { SCIENTIFIC_FIELDS, SCIENTIFIC_KEYS, parsePreparedScientificPayload, parsePrivateDiscoveryJSON,
  preparationScientificShapes as shapes, validatePreparationAssessment,
  type ScientificAssessment, type ScientificKey, type ScientificMaterial, type ScientificPayload, type ScientificQuantity } from "./discovery-scientific";

export const SELECTION_VERSION = "discovery-selection-preparation/1.0.0";
export const SELECTION_FAILURE = "The private selection response could not be verified. Reload the exact context before continuing.";
export const BUNDLE_LIMIT = 16 * 1024 * 1024;
const CONTEXT_LIMIT = 8 * 1024 * 1024;
const COMMAND_LIMIT = 20 * 1024 * 1024;
const PREPARED_LIMIT = 64 * 1024 * 1024;
const authority = ["scientific_acceptance", "ml_training_approved", "current_authorization_checked", "public_release_authorized", "registration_performed"];
type Authority = { scientific_acceptance: false; ml_training_approved: false; current_authorization_checked: false; public_release_authorized: false; registration_performed: false };
export type SelectionAccess = Authority & { version: typeof SELECTION_VERSION; actor_user_id: string; actor_grant_id: string; can_prepare_selection: true };
export type SelectionSource = { distribution_package_id: string; public_bundle_json: string; expected_public_bundle_text_sha256: string };
export type NativeReference = { table: string; row_id: string; row_sha256: string };
type AssessmentReference = { id: string; revision: number; sha256: string };
export type SelectionCandidate = {
  descriptor: { id: string; sha256: string }; material: NativeReference;
  assessments: { reference: AssessmentReference; assessment: ScientificAssessment; state: NativeReference; state_context: ScientificMaterial["state_context"] }[];
  structures: { reference: NativeReference | null; structure_kind: string }[];
  results: { reference: NativeReference; property_key: ScientificKey; registry_version: "rv2/1"; component_key: string;
    quantity: ScientificQuantity; state_id: string; structure_id: string | null;
    event: { id: string; row_sha256: string; revision: number; knowledge_origin: string } }[];
  declaration_evidence: { state_id: string; structure_id: string | null; reference: NativeReference }[];
};
export type SelectionContext = Authority & { version: typeof SELECTION_VERSION; actor_user_id: string; actor_grant_id: string;
  distribution_package_id: string; distribution_record_sha256: string; inventory_sha256: string; public_bundle_sha256: string;
  public_bundle_text_sha256: string; release_manifest_sha256: string; campaign: ScientificPayload["campaign"];
  materials: SelectionCandidate[]; quantity_basis: "frozen_inventory_not_current_scientific_acceptance" };
export type ContextReceipt = { context: SelectionContext; context_sha256: string };
export type CellChoice = { property_key: ScientificKey; availability: "reported" | "unknown" | "not_computed" | "not_applicable" | "conflicted"; reason_code: string; evidence_refs: NativeReference[] };
export type MaterialChoice = { material_id: string; assessment_id: string; structure_id: string | null; rationale: string; cells: CellChoice[] };
export type SelectionRequest = { source: SelectionSource; expected_context_sha256: string; request_key: string; choices: MaterialChoice[] };
export type PreparedSelection = { actor_user_id: string; actor_grant_id: string; context_sha256: string; request_key: string; request_sha256: string;
  payload_sha256: string; selection_sha256: string; payload: ScientificPayload; preview_json: string; commit_json: string };
export type SelectionRecovery = { actorId: string; requestKey: string; requestSha256: string; payloadSha256: string; selectionSha256: string };
export type RegistrationReceipt = { id: string; package_id: string; record_sha256: string; payload_sha256: string; selection_sha256: string;
  request_sha256: string; replayed: boolean; dry_run: boolean };

type Obj = Record<string, unknown>;
function requireValue(value: unknown): asserts value { if (!value) throw new Error(SELECTION_FAILURE); }
const obj = (v: unknown): v is Obj => v !== null && typeof v === "object" && !Array.isArray(v);
const closed = (v: unknown, fields: string[]): v is Obj => obj(v) && Object.keys(v).length === fields.length && fields.every(k => Object.hasOwn(v, k));
export const selectionUUID = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(v);
const sha = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const id = (v: unknown): v is string => typeof v === "string" && /^[A-Za-z0-9_.:-]{1,120}$/.test(v) && ![".", ".."].includes(v);
export const selectionCode = (v: unknown): v is string => typeof v === "string" && /^[a-z][a-z0-9_]{0,159}$/.test(v);
const requestKey = (v: unknown): v is string => typeof v === "string" && /^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$/.test(v);
const text = (v: unknown, max: number): v is string => typeof v === "string" && !!v.trim() && Array.from(v).length <= max && !v.includes("\0");
const list = (v: unknown, max: number, min = 0): v is unknown[] => Array.isArray(v) && v.length >= min && v.length <= max;
const positive = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v > 0;
const noAuthority = (v: Obj) => authority.every(k => v[k] === false);
const ordered = (ids: string[]) => ids.every((value, i) => i === 0 || ids[i - 1] < value);
const same = (a: unknown, b: unknown): boolean => {
  if (Object.is(a, b)) return true;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v, i) => same(v, b[i]));
  return obj(a) && obj(b) && Object.keys(a).length === Object.keys(b).length && Object.keys(a).every(k => Object.hasOwn(b, k) && same(a[k], b[k]));
};
// Selection has no floating quantities: only closed objects, strings, null and
// safe integer revisions. Match the backend's sorted, compact UTF-8 spelling.
function canonicalSelection(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalSelection).join(",")}]`;
  if (obj(value)) return `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${canonicalSelection(value[k])}`).join(",")}}`;
  requireValue(value === null || typeof value === "string" || typeof value === "number" && Number.isSafeInteger(value) && !Object.is(value, -0));
  return JSON.stringify(value);
}
const ref = (v: unknown, tables: string[]) => closed(v, ["table", "row_id", "row_sha256"]) && tables.includes(v.table as string) && selectionUUID(v.row_id) && sha(v.row_sha256);
const evidenceKey = (e: SelectionCandidate["declaration_evidence"][number]) => `${e.state_id}:${e.structure_id ?? ""}:${e.reference.table}:${e.reference.row_id}`;
export async function selectionTextHash(raw: string) {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(raw))), b => b.toString(16).padStart(2, "0")).join("");
}
function parse(raw: string, max: number, paths: string[] = []) { return parsePrivateDiscoveryJSON(raw, max, paths); }
function quantityValid(q: ScientificQuantity, key: ScientificKey) {
  if (!shapes.quantity(q) || q.unit !== SCIENTIFIC_FIELDS[key].unit) return false;
  const { value: v, lower: l, upper: u } = q;
  if (!["formation_energy_per_atom", "phonon_min_frequency"].includes(key) && [v, l, u].some(n => n !== null && n < 0)) return false;
  return ({ exact: v !== null && l === null && u === null, interval: v === null && l !== null && u !== null && l <= u,
    lt: v === null && l === null && u !== null, le: v === null && l === null && u !== null,
    gt: v === null && l !== null && u === null, ge: v === null && l !== null && u === null,
    unreported: v === null && l === null && u === null })[q.relation];
}
function conditionsValid(v: ScientificMaterial["state_context"]) {
  return (v.pressure_status === "explicit_ambient" ? v.pressure_gpa === 0 : v.pressure_status === "reported" ? v.pressure_gpa !== null : v.pressure_gpa === null)
    && (v.temperature_role !== "unknown" || v.temperature_k === null);
}

export function parseSelectionAccess(raw: string): SelectionAccess {
  const v = parse(raw, 4096).value;
  requireValue(closed(v, ["version", "actor_user_id", "actor_grant_id", "can_prepare_selection", ...authority])
    && v.version === SELECTION_VERSION && selectionUUID(v.actor_user_id) && selectionUUID(v.actor_grant_id) && v.can_prepare_selection === true && noAuthority(v));
  return v as SelectionAccess;
}
export async function selectionSourceFromFile(file: File, packageId: string): Promise<SelectionSource> {
  requireValue(selectionUUID(packageId) && file.size > 0 && file.size <= BUNDLE_LIMIT);
  const bytes = await file.arrayBuffer(); requireValue(bytes.byteLength === file.size && bytes.byteLength <= BUNDLE_LIMIT);
  const raw = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
  requireValue(obj(parse(raw, BUNDLE_LIMIT).value));
  return { distribution_package_id: packageId, public_bundle_json: raw, expected_public_bundle_text_sha256: await selectionTextHash(raw) };
}
export async function parseSelectionContext(raw: string, access: SelectionAccess, source: SelectionSource): Promise<ContextReceipt> {
  access = { ...access }; source = { ...source };
  const envelope = parse(raw, 2 * CONTEXT_LIMIT + 1024).value;
  requireValue(closed(envelope, ["version", "context_json", "context_sha256", ...authority]) && envelope.version === SELECTION_VERSION
    && typeof envelope.context_json === "string" && sha(envelope.context_sha256) && noAuthority(envelope));
  const c = parse(envelope.context_json, CONTEXT_LIMIT).value;
  requireValue(closed(c, ["version", "actor_user_id", "actor_grant_id", "distribution_package_id", "distribution_record_sha256", "inventory_sha256", "public_bundle_sha256",
    "public_bundle_text_sha256", "release_manifest_sha256", "campaign", "materials", "quantity_basis", ...authority]) && c.version === SELECTION_VERSION
    && c.actor_user_id === access.actor_user_id && c.actor_grant_id === access.actor_grant_id && noAuthority(c)
    && selectionUUID(c.distribution_package_id) && c.distribution_package_id === source.distribution_package_id
    && [c.distribution_record_sha256, c.inventory_sha256, c.public_bundle_sha256, c.release_manifest_sha256, c.public_bundle_text_sha256].every(sha)
    && c.public_bundle_text_sha256 === source.expected_public_bundle_text_sha256 && shapes.campaign(c.campaign)
    && list(c.materials, 25, 1) && c.quantity_basis === "frozen_inventory_not_current_scientific_acceptance");
  const context = c as unknown as SelectionContext;
  const assessments = new Set<string>(), properties = new Set<string>(), policies = new Set<string>(); let evidenceCount = 0;
  requireValue(ordered(context.materials.map(m => m.descriptor.id)) && new Set(context.materials.map(m => m.material.row_id)).size === context.materials.length);
  for (const m of context.materials) {
    requireValue(closed(m, ["descriptor", "material", "assessments", "structures", "results", "declaration_evidence"])
      && closed(m.descriptor, ["id", "sha256"]) && id(m.descriptor.id) && sha(m.descriptor.sha256) && shapes.materialRef(m.material)
      && list(m.assessments, 200, 1) && list(m.structures, 20001, 1) && list(m.results, 5000) && list(m.declaration_evidence, 5000));
    requireValue(ordered(m.assessments.map(a => a.reference.id)));
    for (const a of m.assessments) {
      requireValue(closed(a, ["reference", "assessment", "state", "state_context"]) && shapes.assessmentRef(a.reference) && shapes.assessment(a.assessment)
        && ref(a.state, ["material_states"]) && shapes.stateContext(a.state_context) && conditionsValid(a.state_context)
        && a.reference.id === a.assessment.id && a.reference.revision === a.assessment.revision && a.assessment.material_id === m.descriptor.id
        && a.state_context.material_id === m.descriptor.id && !assessments.has(a.reference.id));
      assessments.add(a.reference.id); policies.add(a.assessment.result.policy_hash); validatePreparationAssessment(a.assessment, context.campaign);
    }
    requireValue(same(m.structures[0], { reference: null, structure_kind: "not_selected" }) && ordered(m.structures.slice(1).map(s => s.reference!.row_id)));
    for (const s of m.structures.slice(1)) requireValue(closed(s, ["reference", "structure_kind"]) && ref(s.reference, ["structure_records"])
      && ["coordinates", "prototype", "literature_description", "unresolved"].includes(s.structure_kind));
    const states = new Set(m.assessments.map(a => a.state.row_id)), structures = new Set(m.structures.map(s => s.reference?.row_id ?? null));
    requireValue(ordered(m.results.map(r => r.reference.row_id)) && ordered(m.declaration_evidence.map(evidenceKey)));
    for (const r of m.results) {
      requireValue(closed(r, ["reference", "property_key", "registry_version", "component_key", "quantity", "state_id", "structure_id", "event"])
        && ref(r.reference, ["event_properties"]) && SCIENTIFIC_KEYS.includes(r.property_key) && r.registry_version === "rv2/1"
        && text(r.component_key, 120) && r.component_key === r.component_key.trim() && !/[\u0000-\u001f]/.test(r.component_key)
        && quantityValid(r.quantity, r.property_key) && states.has(r.state_id) && structures.has(r.structure_id)
        && closed(r.event, ["id", "row_sha256", "revision", "knowledge_origin"]) && selectionUUID(r.event.id) && sha(r.event.row_sha256)
        && positive(r.event.revision) && ["Observed", "Computed", "Inferred", "AI-Proposed", "unknown"].includes(r.event.knowledge_origin)
        && !properties.has(r.reference.row_id));
      properties.add(r.reference.row_id);
    }
    for (const e of m.declaration_evidence) requireValue(closed(e, ["state_id", "structure_id", "reference"])
      && states.has(e.state_id) && structures.has(e.structure_id) && ref(e.reference, ["event_evidence", "evidence_artifacts", "research_runs"]));
    evidenceCount += m.declaration_evidence.length;
  }
  requireValue(assessments.size <= 200 && properties.size <= 5000 && evidenceCount <= 5000 && policies.size === 1);
  requireValue(await selectionTextHash(envelope.context_json) === envelope.context_sha256
    && await selectionTextHash(source.public_bundle_json) === source.expected_public_bundle_text_sha256);
  return { context, context_sha256: envelope.context_sha256 };
}

export function selectedInventory(m: SelectionCandidate, assessmentId: string, structureId: string | null) {
  const a = m.assessments.find(a => a.reference.id === assessmentId);
  requireValue(a && m.structures.some(s => (s.reference?.row_id ?? null) === structureId));
  const matches = (r: { state_id: string; structure_id: string | null }) => r.state_id === a.state.row_id && r.structure_id === structureId;
  return { assessment: a, results: m.results.filter(matches), evidence: m.declaration_evidence.filter(matches) };
}
export function inventoryCell(key: ScientificKey, results: SelectionCandidate["results"]): CellChoice {
  const matching = results.filter(r => r.property_key === key), quantified = matching.some(r => r.quantity.relation !== "unreported");
  return { property_key: key, availability: quantified ? "reported" : "unknown", reason_code: quantified ? "retained_registered_result"
    : matching.length ? "source_does_not_report_value" : "no_matching_registered_result", evidence_refs: [] };
}
function expectedSelection(context: SelectionContext, choices: MaterialChoice[]) {
  requireValue(choices.length === context.materials.length && same(choices.map(c => c.material_id), context.materials.map(m => m.descriptor.id)));
  return { version: "discovery-scientific-selection/1.0.0", release_manifest_sha256: context.release_manifest_sha256,
    public_bundle_sha256: context.public_bundle_sha256, representatives: context.materials.map((m, i) => {
      const c = choices[i]; requireValue(closed(c, ["material_id", "assessment_id", "structure_id", "rationale", "cells"]) && text(c.rationale, 2000)
        && (c.structure_id === null || selectionUUID(c.structure_id)) && list(c.cells, 8, 8) && same(c.cells.map(c => c.property_key), SCIENTIFIC_KEYS));
      const { assessment: a, results, evidence } = selectedInventory(m, c.assessment_id, c.structure_id);
      const cells = c.cells.map(cell => {
        requireValue(closed(cell, ["property_key", "availability", "reason_code", "evidence_refs"]) && selectionCode(cell.reason_code)
          && ["reported", "unknown", "not_computed", "not_applicable", "conflicted"].includes(cell.availability) && list(cell.evidence_refs, 20)
          && cell.evidence_refs.every(r => evidence.some(e => same(e.reference, r))));
        return { ...cell, result_refs: results.filter(r => r.property_key === cell.property_key).map(r => r.reference) };
      });
      return { material: m.descriptor, assessment: a.reference, structure: m.structures.find(s => (s.reference?.row_id ?? null) === c.structure_id)!.reference,
        rationale: c.rationale, alternatives: m.assessments.filter(x => x.reference.id !== a.reference.id).map(x => x.reference), cells };
    }) };
}
const commandFields = ["distribution_package_id", "expected_distribution_record_sha256", "expected_inventory_sha256", "public_bundle", "selection",
  "expected_selection_sha256", "request_key", "expected_payload_sha256", "dry_run"];
export async function parsePreparedSelection(raw: string, access: SelectionAccess, originalContext: ContextReceipt, original: SelectionRequest): Promise<PreparedSelection> {
  access = { ...access }; const context = structuredClone(originalContext), request = structuredClone(original);
  requireValue(requestKey(request.request_key) && request.expected_context_sha256 === context.context_sha256);
  const v = parse(raw, PREPARED_LIMIT).value;
  requireValue(closed(v, ["version", "actor_user_id", "actor_grant_id", "context_sha256", "request_key", "request_sha256", "payload_json", "payload_sha256",
    "selection_sha256", "preview_json", "preview_sha256", "commit_json", "commit_sha256", ...authority]) && v.version === SELECTION_VERSION && noAuthority(v)
    && v.actor_user_id === access.actor_user_id && v.actor_grant_id === access.actor_grant_id && v.actor_user_id === context.context.actor_user_id
    && v.actor_grant_id === context.context.actor_grant_id && v.context_sha256 === context.context_sha256 && v.request_key === request.request_key
    && [v.request_sha256, v.payload_sha256, v.selection_sha256, v.preview_sha256, v.commit_sha256].every(sha)
    && typeof v.payload_json === "string" && typeof v.preview_json === "string" && typeof v.commit_json === "string");
  const checked = await parsePreparedScientificPayload(v.payload_json, v.payload_sha256 as string, v.selection_sha256 as string);
  const p = checked.payload, c = context.context;
  requireValue(p.base.distribution_package_id === c.distribution_package_id && p.base.distribution_record_sha256 === c.distribution_record_sha256
    && p.base.inventory_sha256 === c.inventory_sha256 && p.base.public_bundle_sha256 === c.public_bundle_sha256 && p.base.release_manifest_sha256 === c.release_manifest_sha256
    && same(p.campaign, c.campaign) && same(p.selection, expectedSelection(c, request.choices)));
  for (const [i, row] of p.rows.entries()) {
    const m = c.materials[i], chosen = selectedInventory(m, request.choices[i].assessment_id, request.choices[i].structure_id);
    requireValue(same(row.material, m.material) && same(row.state, chosen.assessment.state) && same(row.state_context, chosen.assessment.state_context)
      && same(row.assessment, chosen.assessment.assessment) && row.alternatives.every(a => same(a.assessment, m.assessments.find(x => x.reference.id === a.reference.id)?.assessment)));
    for (const cell of row.cells) for (const o of cell.observations) {
      const r = chosen.results.find(r => r.reference.row_id === o.property.id);
      requireValue(r && same(o.quantity, r.quantity) && o.property.component_key === r.component_key && o.event.id === r.event.id
        && o.event.row_sha256 === r.event.row_sha256 && o.event.revision === r.event.revision && o.event.knowledge_origin === r.event.knowledge_origin
        && (o.structure === null || o.structure.structure_kind === m.structures.find(s => s.reference?.row_id === o.structure?.id)?.structure_kind));
    }
  }
  const preview = parse(v.preview_json, COMMAND_LIMIT, commandFields), commit = parse(v.commit_json, COMMAND_LIMIT, commandFields);
  requireValue(closed(preview.value, commandFields) && closed(commit.value, commandFields) && preview.value.dry_run === true && commit.value.dry_run === false);
  for (const key of commandFields.filter(k => k !== "dry_run")) requireValue(preview.spans.get(key) === commit.spans.get(key));
  const cmd = commit.value;
  requireValue(cmd.distribution_package_id === c.distribution_package_id && cmd.expected_distribution_record_sha256 === c.distribution_record_sha256
    && cmd.expected_inventory_sha256 === c.inventory_sha256 && cmd.expected_selection_sha256 === v.selection_sha256 && cmd.expected_payload_sha256 === v.payload_sha256
    && cmd.request_key === request.request_key && commit.spans.get("public_bundle") === request.source.public_bundle_json && commit.spans.get("selection") === checked.selectionJSON
    && request.source.distribution_package_id === c.distribution_package_id && request.source.expected_public_bundle_text_sha256 === c.public_bundle_text_sha256);
  const hashKeys = commandFields.filter(k => !["dry_run", "request_key", "expected_payload_sha256"].includes(k)).concat(["operation", "version"]).sort();
  requireValue(commit.spans.get("selection") === canonicalSelection(cmd.selection));
  for (const k of commandFields.filter(k => !["public_bundle", "selection", "dry_run"].includes(k))) {
    requireValue(commit.spans.get(k) === JSON.stringify(cmd[k]));
  }
  const hashJSON = `{${hashKeys.map(k => `${JSON.stringify(k)}:${k === "operation" ? '"register"' : k === "version" ? '"discovery-projection-governance/1.0.0"' : commit.spans.get(k)}`).join(",")}}`;
  const hashes = await Promise.all([selectionTextHash(v.preview_json), selectionTextHash(v.commit_json), selectionTextHash(hashJSON), selectionTextHash(request.source.public_bundle_json)]);
  requireValue(hashes[0] === v.preview_sha256 && hashes[1] === v.commit_sha256 && hashes[2] === v.request_sha256 && hashes[3] === c.public_bundle_text_sha256);
  return { actor_user_id: access.actor_user_id, actor_grant_id: access.actor_grant_id, context_sha256: context.context_sha256, request_key: request.request_key,
    request_sha256: v.request_sha256 as string, payload_sha256: v.payload_sha256 as string, selection_sha256: v.selection_sha256 as string,
    payload: p, preview_json: v.preview_json, commit_json: v.commit_json };
}
export function recoveryFor(v: PreparedSelection): SelectionRecovery {
  return { actorId: v.actor_user_id, requestKey: v.request_key, requestSha256: v.request_sha256, payloadSha256: v.payload_sha256, selectionSha256: v.selection_sha256 };
}
export function parseRegistrationReceipt(raw: string, binding: SelectionRecovery, committed: boolean, recovered = false): RegistrationReceipt {
  requireValue(selectionUUID(binding.actorId) && requestKey(binding.requestKey) && [binding.requestSha256, binding.payloadSha256, binding.selectionSha256].every(sha));
  const v = parse(raw, 8192).value;
  requireValue(closed(v, ["version", "dry_run", "committed", "result"]) && v.version === "research-distribution-operation/1.0.0" && v.committed === committed && v.dry_run === !committed);
  const r = v.result;
  requireValue(closed(r, ["version", "operation", "id", "package_id", "record_sha256", "payload_sha256", "selection_sha256", "request_sha256", "dry_run", "committed", "replayed",
    "scientific_acceptance", "ml_training_approved", "current_authorization_checked"]) && r.version === "discovery-projection-governance/1.0.0" && r.operation === "register"
    && r.committed === false && r.dry_run === !committed && typeof r.replayed === "boolean" && (!recovered || r.replayed)
    && selectionUUID(r.id) && r.package_id === r.id && sha(r.record_sha256) && r.request_sha256 === binding.requestSha256 && r.payload_sha256 === binding.payloadSha256
    && r.selection_sha256 === binding.selectionSha256 && r.scientific_acceptance === false && r.ml_training_approved === false && r.current_authorization_checked === false);
  return r as unknown as RegistrationReceipt;
}

/** Same API base and existing HttpOnly browser session; no new auth, redirects,
 * arbitrary URLs, stored drafts or automatic retries. Preserve response text. */
async function privateText(path: string, max: number, signal?: AbortSignal, body?: string) {
  if (signal?.aborted) throw new ApiError(0, null, "Selection request interrupted");
  const controller = new AbortController(), abort = () => controller.abort();
  let rejectAbort!: (reason: unknown) => void;
  const aborted = new Promise<never>((_, reject) => { rejectAbort = reject; });
  const stopped = () => rejectAbort(new ApiError(0, null, "Selection request interrupted"));
  controller.signal.addEventListener("abort", stopped, { once: true });
  signal?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, 35000);
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  let responseBody: ReadableStream<Uint8Array> | null = null;
  try {
    const response = await Promise.race([fetch(`${API_BASE}/ml/discovery-projections${path}`, {
      method: body === undefined ? "GET" : "POST", body, credentials: "include", cache: "no-store", redirect: "error", signal: controller.signal,
      headers: { Accept: "application/json", ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    }), aborted]);
    responseBody = response.body;
    if (!response.ok) throw new ApiError(response.status, null, "Private selection request unavailable");
    requireValue(/^application\/json(?:\s*;|$)/i.test(response.headers.get("content-type") ?? "") && response.body);
    const length = response.headers.get("content-length"); requireValue(length === null || /^\d+$/.test(length) && Number(length) <= max);
    reader = response.body.getReader(); const decoder = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });
    let raw = "", size = 0, chunks = 0;
    while (true) {
      const chunk = await Promise.race([reader.read(), aborted]); requireValue(!controller.signal.aborted);
      if (chunk.done) break;
      size += chunk.value.byteLength; requireValue(size <= max && ++chunks <= 4096); raw += decoder.decode(chunk.value, { stream: true });
    }
    return raw + decoder.decode();
  } catch (error) { if (error instanceof ApiError) throw error; throw new ApiError(0, null, "Private selection response unavailable"); }
  finally {
    clearTimeout(timer); signal?.removeEventListener("abort", abort); controller.signal.removeEventListener("abort", stopped); controller.abort();
    if (reader) void reader.cancel().catch(() => {});
    else void responseBody?.cancel().catch(() => {});
  }
}
export const getSelectionAccess = (signal?: AbortSignal) => privateText("/selection/access", 4096, signal);
export function getSelectionContext(source: SelectionSource, signal?: AbortSignal) {
  const body = JSON.stringify({ source }); requireValue(new TextEncoder().encode(body).length <= 40 * 1024 * 1024);
  return privateText("/selection/context", 2 * CONTEXT_LIMIT + 1024, signal, body);
}
export function prepareSelection(request: SelectionRequest, signal?: AbortSignal) {
  const body = JSON.stringify(request); requireValue(new TextEncoder().encode(body).length <= 40 * 1024 * 1024);
  return privateText("/selection/prepare", PREPARED_LIMIT, signal, body);
}
export function registerSelection(raw: string, signal?: AbortSignal) {
  requireValue(new TextEncoder().encode(raw).length <= COMMAND_LIMIT);
  return privateText("/register", 8192, signal, raw);
}
export function getSelectionOutcome(ref: SelectionRecovery, signal?: AbortSignal) {
  requireValue(selectionUUID(ref.actorId) && requestKey(ref.requestKey) && sha(ref.requestSha256));
  const query = new URLSearchParams({ operation: "register", request_key: ref.requestKey, expected_request_sha256: ref.requestSha256 });
  return privateText(`/outcome?${query}`, 8192, signal);
}
