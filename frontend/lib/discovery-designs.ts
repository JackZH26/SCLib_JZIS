/** Private proposal contract. Host/modification labels confer no material identity. */
import { expressionCanonical, expressionSha, parseExpressionJson } from "./source-expressions";

export const DESIGN_VERSION = "discovery-design/1.0.0";
export const DESIGN_REQUEST_VERSION = "discovery-design-operation/1.0.0";
export const DESIGN_MAX_BYTES = 65536;
export const DESIGN_MODIFICATIONS = ["doping", "substitution", "vacancy", "strain", "interface", "layer", "twist", "pressure"] as const;
export const DESIGN_PAIRING = ["unresolved", "epc", "correlated", "multiband", "interface"] as const;
export const DESIGN_RESOURCES = { cpu_hours: "core-hour", gpu_hours: "gpu-hour", memory: "GiB", storage: "GiB", human_hours: "person-hour" } as const;
export const DESIGN_AUTHORITY = { scientific_acceptance: false, canonical_promotions: 0, ml_training_approved: false, public_release: false, calculation_executed: false, scope: "private_owner_research_design" } as const;
export type DesignAuthority = typeof DESIGN_AUTHORITY;
export type DesignBaseline = { kind: "unanchored" | "retained_result" | "native_property"; material_id: string | null; record_index: number | null; property_id: string | null; expected_context_sha256: string };
export type DesignPin = { id: string; record_sha256: string };
export type DesignParent = { design_id: string; revision_id: string; record_sha256: string } | null;
export type ResearchDesign = {
  host_label: string; state_label: string;
  modifications: Array<{ kind: typeof DESIGN_MODIFICATIONS[number]; parameters: string }>;
  target_conditions: { pressure: { kind: "unspecified" | "ambient" | "specified"; raw_gpa: string | null }; temperature_k: string | null };
  pairing_hypothesis: typeof DESIGN_PAIRING[number]; hypothesis: string;
  next_action: { kind: "source_review" | "calculation" | "experiment"; question: string; prerequisites: string[];
    outcomes: Array<{ observation: string; decision: "continue" | "stop" | "redirect" }>;
    budget: Array<{ resource: keyof typeof DESIGN_RESOURCES; status: "unknown" | "estimated"; raw_upper: string | null; unit: string }> };
};
export type DesignRequest = { version: typeof DESIGN_REQUEST_VERSION; request_key: string } & (
  { operation: "propose"; payload: { baseline: DesignBaseline; design: ResearchDesign; parent: DesignParent } }
  | { operation: "revise"; payload: { baseline: DesignBaseline; design: ResearchDesign; parent: DesignParent; design_id: string; predecessor: DesignPin } }
  | { operation: "withdraw"; payload: { design_id: string; predecessor: DesignPin; reason: string } });

export type DesignObject = Record<string, unknown>;
export function designObject(value: unknown): value is DesignObject { return value !== null && typeof value === "object" && !Array.isArray(value); }
export function designClosed(value: unknown, keys: string): value is DesignObject { const names = keys.split(" "); return designObject(value) && Object.keys(value).length === names.length && names.every(k => Object.hasOwn(value, k)); }
export function designHash(value: unknown): value is string { return typeof value === "string" && /^[a-f0-9]{64}$/.test(value); }
export function designId(value: unknown): value is string { return typeof value === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value); }
export function designText(value: unknown, maximum: number): value is string { return typeof value === "string" && !!value && value.trim() === value && Array.from(value).length <= maximum && !/[\u0000-\u001f\u007f\ud800-\udfff]/u.test(value); }
function integer(value: unknown, maximum = Number.MAX_SAFE_INTEGER): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 && value <= maximum; }
function oneOf(value: unknown, choices: readonly string[]) { return typeof value === "string" && choices.includes(value); }
function decimal(value: unknown) { return designText(value, 80) && /^(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value) && Number.isFinite(Number(value)) && (Number(value) !== 0 || !/[1-9]/.test(value.split(/[eE]/)[0])); }
export function knownDesignBaseline(value: unknown): value is DesignBaseline {
  if (!designClosed(value, "kind material_id record_index property_id expected_context_sha256") || !designHash(value.expected_context_sha256)) return false;
  if (value.kind === "unanchored") return value.material_id === null && value.record_index === null && value.property_id === null;
  return designText(value.material_id, 100) && (value.kind === "retained_result" ? integer(value.record_index, 4999) && value.property_id === null : value.kind === "native_property" && value.record_index === null && designId(value.property_id));
}
function pin(value: unknown): value is DesignPin { return designClosed(value, "id record_sha256") && designId(value.id) && designHash(value.record_sha256); }
export function knownDesignParent(value: unknown): value is DesignParent { return value === null || designClosed(value, "design_id revision_id record_sha256") && designId(value.design_id) && designId(value.revision_id) && designHash(value.record_sha256); }
export function knownResearchDesign(value: unknown): value is ResearchDesign {
  if (!designClosed(value, "host_label state_label modifications target_conditions pairing_hypothesis hypothesis next_action")
      || !designText(value.host_label, 500) || !designText(value.state_label, 500) || !designText(value.hypothesis, 4000) || !oneOf(value.pairing_hypothesis, DESIGN_PAIRING)
      || !Array.isArray(value.modifications) || value.modifications.length < 1 || value.modifications.length > 8
      || !value.modifications.every(m => designClosed(m, "kind parameters") && oneOf(m.kind, DESIGN_MODIFICATIONS) && designText(m.parameters, 2000))
      || !designClosed(value.target_conditions, "pressure temperature_k") || !designClosed(value.target_conditions.pressure, "kind raw_gpa")) return false;
  const p = value.target_conditions.pressure;
  if (!oneOf(p.kind, ["unspecified", "ambient", "specified"]) || (p.kind === "specified" ? !decimal(p.raw_gpa) : p.raw_gpa !== null)
      || !(value.target_conditions.temperature_k === null || decimal(value.target_conditions.temperature_k))) return false;
  const a = value.next_action;
  if (!designClosed(a, "kind question prerequisites outcomes budget") || !oneOf(a.kind, ["source_review", "calculation", "experiment"]) || !designText(a.question, 2000)
      || !Array.isArray(a.prerequisites) || a.prerequisites.length < 1 || a.prerequisites.length > 16 || !a.prerequisites.every(s => designText(s, 1000))
      || !Array.isArray(a.outcomes) || a.outcomes.length < 2 || a.outcomes.length > 8 || !a.outcomes.every(o => designClosed(o, "observation decision") && designText(o.observation, 1000) && oneOf(o.decision, ["continue", "stop", "redirect"]))
      || new Set(a.outcomes.map(o => o.observation.toLocaleLowerCase("en-US"))).size !== a.outcomes.length || new Set(a.outcomes.map(o => o.decision)).size < 2
      || !Array.isArray(a.budget) || a.budget.length !== 5 || new Set(a.budget.map(b => b.resource)).size !== 5) return false;
  return a.budget.every(b => designClosed(b, "resource status raw_upper unit") && typeof b.resource === "string" && Object.hasOwn(DESIGN_RESOURCES, b.resource)
    && b.unit === DESIGN_RESOURCES[b.resource as keyof typeof DESIGN_RESOURCES] && (b.status === "unknown" ? b.raw_upper === null : b.status === "estimated" && decimal(b.raw_upper)));
}
export function knownDesignRequest(value: unknown): value is DesignRequest {
  if (!designClosed(value, "version request_key operation payload") || value.version !== DESIGN_REQUEST_VERSION || typeof value.request_key !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$/.test(value.request_key)) return false;
  const p = value.payload;
  if (value.operation === "withdraw") return designClosed(p, "design_id predecessor reason") && designId(p.design_id) && pin(p.predecessor) && designText(p.reason, 2000);
  return (value.operation === "propose" || value.operation === "revise") && designClosed(p, value.operation === "propose" ? "baseline design parent" : "baseline design parent design_id predecessor")
    && knownDesignBaseline(p.baseline) && knownResearchDesign(p.design) && knownDesignParent(p.parent) && (value.operation !== "revise" || designId(p.design_id) && pin(p.predecessor));
}
export async function designProof(text: unknown, sha: unknown, maximum = 131072): Promise<DesignObject | null> {
  try {
    if (typeof text !== "string" || new TextEncoder().encode(text).length > maximum || !designHash(sha) || await expressionSha(text) !== sha) return null;
    const body = parseExpressionJson(text);
    return designObject(body) && expressionCanonical(body) === text ? body : null;
  } catch { return null; }
}
export function designAuthority(value: DesignObject) { return Object.entries(DESIGN_AUTHORITY).every(([key, expected]) => value[key] === expected); }
const AUTH_KEYS = Object.keys(DESIGN_AUTHORITY).join(" ");
export type DesignCapabilities = DesignAuthority & { version: string; request_version: string; actor_user_id: string; session_version: number; curator_grant_id: string; can_write: true; baseline_kinds: string[]; modification_kinds: string[]; pairing_hypotheses: string[]; action_kinds: string[]; decisions: string[]; budget_resources: string[]; max_page_size: 8; max_operation_bytes: 65536 };
export type DesignProjection = { kind: DesignBaseline["kind"]; material_id: string | null; formula: string | null; record_index: number | null; property_id: string | null; event_id: string | null; state_id: string | null; producer_run_id: string | null; source_snapshot_sha256: string; values: Array<{ field_id: string; value: number; unit: string; relation: string }>; knowledge_origin: string | null; pressure_status: string | null; pressure_gpa: number | null; temperature_k: number | null };
export type DesignEligibility = { eligible: boolean; reason_codes: string[] };
export type DesignContext = DesignAuthority & { version: string; actor_user_id: string; session_version: number; baseline: DesignBaseline; context_sha256: string; projection_sha256: string; projection_canonical_json: string | null; projection: DesignProjection | null; eligibility: DesignEligibility };
export type DesignReceipt = DesignAuthority & { version: string; receipt_id: string; receipt_sha256: string; design_id: string; revision: number; operation: DesignRequest["operation"]; status: "proposed" | "withdrawn"; actor_user_id: string; actor_grant_id: string; actor_session_version: number; request_key: string; request_sha256: string; preview_sha256: string; request_canonical_json: string; preview_canonical_json: string; receipt_canonical_json: string; replayed: boolean; dry_run: boolean; pending_ledger_written: boolean };
export type DesignRecovery = { actorId: string; requestKey: string; requestSha: string; previewSha: string; receiptSha: string; receiptId: string };
export type DesignEntry = DesignAuthority & { id: string; record_sha256: string; design_id: string; revision: number; operation: DesignRequest["operation"]; status: "proposed" | "withdrawn"; is_head: boolean; baseline: DesignBaseline; design: ResearchDesign; parent: DesignParent; predecessor: DesignPin | null; context_sha256: string; projection_sha256: string; projection_canonical_json: string | null; projection: DesignProjection | null; eligibility: DesignEligibility; receipt: DesignReceipt };
export type DesignPage = DesignAuthority & { version: string; actor_user_id: string; session_version: number; offset: number; limit: number; total: number; entries: DesignEntry[] };
export type DesignDetail = DesignAuthority & { version: string; actor_user_id: string; session_version: number; design_id: string; revision_total: number; history_limit: 8; entries: DesignEntry[] };
const RECEIPT_KEYS = `version receipt_id receipt_sha256 design_id revision operation status actor_user_id actor_grant_id actor_session_version request_key request_sha256 preview_sha256 request_canonical_json preview_canonical_json receipt_canonical_json replayed dry_run pending_ledger_written ${AUTH_KEYS}`;
const RECORD_KEYS = "id design_id revision actor_user_id actor_grant_id actor_session_version operation request_key request_json payload request_sha256 preview_json preview_sha256 baseline design parent predecessor_id predecessor_sha256 context_sha256 projection_sha256 scientific_acceptance canonical_promotions ml_training_approved public_release calculation_executed";
function same(a: unknown, b: unknown): boolean { try { return expressionCanonical(a) === expressionCanonical(b); } catch { return false; } }
function list(value: unknown, expected: readonly string[]) { return Array.isArray(value) && same(value, expected); }
function scoped(value: DesignObject, cap: DesignCapabilities) { return value.version === DESIGN_VERSION && value.actor_user_id === cap.actor_user_id && value.session_version === cap.session_version && designAuthority(value); }
function eligible(value: unknown): value is DesignEligibility { return designClosed(value, "eligible reason_codes") && typeof value.eligible === "boolean" && Array.isArray(value.reason_codes) && value.reason_codes.length <= 16 && value.reason_codes.every(x => typeof x === "string" && /^[a-z][a-z0-9_]{0,119}$/.test(x)) && value.eligible === (value.reason_codes.length === 0); }
const NATIVE_UNITS: Record<string, string> = { formation_energy_per_atom: "eV/atom", energy_above_hull: "eV/atom", band_gap: "eV", dos_at_fermi: "states/eV/formula_unit", electron_phonon_lambda: "1", omega_log: "K", phonon_min_frequency: "THz", superfluid_stiffness: "K" };
function knownProjection(value: unknown, baseline: DesignBaseline, sha: string): value is DesignProjection {
  if (!designClosed(value, "kind material_id formula record_index property_id event_id state_id producer_run_id source_snapshot_sha256 values knowledge_origin pressure_status pressure_gpa temperature_k")
      || !["kind", "material_id", "record_index", "property_id"].every(k => value[k] === baseline[k as keyof DesignBaseline]) || value.source_snapshot_sha256 !== sha
      || !(value.formula === null || designText(value.formula, 500)) || !["event_id", "state_id", "producer_run_id"].every(k => value[k] === null || designId(value[k]))
      || !(value.knowledge_origin === null || oneOf(value.knowledge_origin, ["Observed", "Computed"])) || !(value.pressure_status === null || oneOf(value.pressure_status, ["reported", "explicit_ambient", "not_reported", "ambiguous"]))
      || !["pressure_gpa", "temperature_k"].every(k => value[k] === null || typeof value[k] === "number" && Number.isFinite(value[k]) && (value[k] as number) >= 0)
      || !Array.isArray(value.values) || value.values.length > 1) return false;
  if (baseline.kind === "unanchored") return value.formula === null && value.values.length === 0 && ["event_id", "state_id", "producer_run_id", "knowledge_origin", "pressure_status", "pressure_gpa", "temperature_k"].every(k => value[k] === null);
  if (baseline.kind === "retained_result" && !["event_id", "state_id", "producer_run_id", "pressure_status", "temperature_k"].every(k => value[k] === null)) return false;
  return value.values.every(v => designClosed(v, "field_id value unit relation") && typeof v.value === "number" && Number.isFinite(v.value)
    && (baseline.kind === "retained_result" ? v.field_id === "tc_kelvin" && v.unit === "K" && v.relation === "source_reported_unspecified_criterion" && v.value >= 0 : typeof v.field_id === "string" && Object.hasOwn(NATIVE_UNITS, v.field_id) && v.unit === NATIVE_UNITS[v.field_id] && v.relation === "exact"));
}
export function knownDesignCapabilities(value: unknown, actorId: string): DesignCapabilities | null {
  return designClosed(value, `version request_version actor_user_id session_version curator_grant_id can_write baseline_kinds modification_kinds pairing_hypotheses action_kinds decisions budget_resources max_page_size max_operation_bytes ${AUTH_KEYS}`)
    && value.version === DESIGN_VERSION && value.request_version === DESIGN_REQUEST_VERSION && value.actor_user_id === actorId && designId(actorId) && integer(value.session_version) && designId(value.curator_grant_id) && value.can_write === true
    && list(value.baseline_kinds, ["unanchored", "retained_result", "native_property"]) && list(value.modification_kinds, DESIGN_MODIFICATIONS) && list(value.pairing_hypotheses, DESIGN_PAIRING)
    && list(value.action_kinds, ["source_review", "calculation", "experiment"]) && list(value.decisions, ["continue", "stop", "redirect"]) && list(value.budget_resources, Object.keys(DESIGN_RESOURCES))
    && value.max_page_size === 8 && value.max_operation_bytes === DESIGN_MAX_BYTES && designAuthority(value) ? value as unknown as DesignCapabilities : null;
}
function equalProjection(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v, i) => equalProjection(v, b[i]));
  return designObject(a) && designObject(b) && Object.keys(a).length === Object.keys(b).length && Object.keys(a).every(k => Object.hasOwn(b, k) && equalProjection(a[k], b[k]));
}
function detached(value: unknown): unknown {
  try { return structuredClone(value); } catch { return null; }
}
async function verifiedProjection(value: DesignObject, baseline: DesignBaseline, contextSha: string): Promise<boolean> {
  if (!designHash(value.projection_sha256)) return false;
  if ((value.eligibility as DesignEligibility).eligible === false) return value.projection === null && value.projection_canonical_json === null;
  if (typeof value.projection_canonical_json !== "string" || new TextEncoder().encode(value.projection_canonical_json).length > 8192 || !knownProjection(value.projection, baseline, contextSha)) return false;
  try {
    const bytes = value.projection_canonical_json;
    const decoded = parseExpressionJson(bytes, false);
    // SQL decimal tokens can differ from JS serialization. Verify exact bytes,
    // then compare the decoded finite projection without rewriting its proof.
    return await expressionSha(bytes) === value.projection_sha256 && equalProjection(decoded, value.projection);
  } catch { return false; }
}
export async function knownDesignContext(value: unknown, cap: DesignCapabilities, expected: Pick<DesignBaseline, "kind" | "material_id" | "record_index" | "property_id">): Promise<DesignContext | null> {
  value = detached(value); cap = { ...cap }; expected = { ...expected };
  if (!designClosed(value, `version actor_user_id session_version baseline context_sha256 projection_sha256 projection_canonical_json projection eligibility ${AUTH_KEYS}`) || !scoped(value, cap) || !knownDesignBaseline(value.baseline)
      || !Object.entries(expected).every(([k, v]) => (value.baseline as DesignBaseline)[k as keyof DesignBaseline] === v) || value.context_sha256 !== value.baseline.expected_context_sha256 || !eligible(value.eligibility)) return null;
  return await verifiedProjection(value, value.baseline, value.context_sha256 as string) ? value as unknown as DesignContext : null;
}
export async function knownDesignReceipt(value: unknown, cap: DesignCapabilities, recovery?: DesignRecovery, stage: "preview" | "commit" | "outcome" | "history" = "history"): Promise<DesignReceipt | null> {
  value = detached(value); cap = { ...cap }; recovery = recovery ? { ...recovery } : undefined;
  if (!designClosed(value, RECEIPT_KEYS) || value.version !== DESIGN_VERSION || value.actor_user_id !== cap.actor_user_id || !designAuthority(value)
      || !designId(value.receipt_id) || !designId(value.design_id) || !integer(value.revision, 1000) || value.revision === 0 || !designId(value.actor_grant_id) || !integer(value.actor_session_version)
      || typeof value.replayed !== "boolean" || typeof value.dry_run !== "boolean" || value.pending_ledger_written !== !value.dry_run
      || value.status !== (value.operation === "withdraw" ? "withdrawn" : "proposed")) return null;
  const record = await designProof(value.receipt_canonical_json, value.receipt_sha256, 196608);
  const request = await designProof(value.request_canonical_json, value.request_sha256, DESIGN_MAX_BYTES);
  const preview = await designProof(value.preview_canonical_json, value.preview_sha256, 4096);
  if (!designClosed(record, RECORD_KEYS) || !knownDesignRequest(request) || !preview
      || request.operation !== value.operation || request.request_key !== value.request_key || !same(request.payload, record.payload)
      || !["actor_user_id", "actor_grant_id", "actor_session_version", "request_key", "request_sha256", "preview_sha256", "design_id", "revision", "operation"].every(k => record[k] === value[k])
      || record.id !== value.receipt_id || record.request_json !== value.request_canonical_json || record.preview_json !== value.preview_canonical_json
      || !knownDesignBaseline(record.baseline) || !knownResearchDesign(record.design) || !knownDesignParent(record.parent) || !designHash(record.context_sha256) || !designHash(record.projection_sha256)
      || !["scientific_acceptance", "canonical_promotions", "ml_training_approved", "public_release", "calculation_executed"].every(k => record[k] === DESIGN_AUTHORITY[k as keyof DesignAuthority])
      || !same(preview, { version: DESIGN_VERSION, actor: { actor_user_id: value.actor_user_id, actor_grant_id: value.actor_grant_id, actor_session_version: value.actor_session_version }, request_sha256: value.request_sha256, receipt_id: value.receipt_id, design_id: value.design_id, revision: value.revision, context_sha256: record.context_sha256 })) return null;
  if (record.context_sha256 !== record.baseline.expected_context_sha256 || (request.operation !== "withdraw" && (!same(record.baseline, request.payload.baseline) || !same(record.design, request.payload.design) || !same(record.parent, request.payload.parent)))) return null;
  if (request.operation === "propose" ? value.revision !== 1 || record.predecessor_id !== null || record.predecessor_sha256 !== null : request.payload.design_id !== value.design_id || record.predecessor_id !== request.payload.predecessor.id || record.predecessor_sha256 !== request.payload.predecessor.record_sha256) return null;
  if (recovery && (recovery.actorId !== value.actor_user_id || recovery.requestKey !== value.request_key || recovery.requestSha !== value.request_sha256
      || stage !== "preview" && (recovery.previewSha !== value.preview_sha256 || recovery.receiptSha !== value.receipt_sha256 || recovery.receiptId !== value.receipt_id))) return null;
  if (stage === "preview" ? value.replayed ? value.dry_run : !value.dry_run || value.actor_grant_id !== cap.curator_grant_id || value.actor_session_version !== cap.session_version
    : value.dry_run || stage === "outcome" && !value.replayed || stage === "commit" && !value.replayed && (value.actor_grant_id !== cap.curator_grant_id || value.actor_session_version !== cap.session_version)) return null;
  return value as unknown as DesignReceipt;
}
async function knownEntry(value: unknown, cap: DesignCapabilities): Promise<DesignEntry | null> {
  value = detached(value); cap = { ...cap };
  if (!designClosed(value, `id record_sha256 design_id revision operation status is_head baseline design parent predecessor context_sha256 projection_sha256 projection_canonical_json projection eligibility receipt ${AUTH_KEYS}`)
      || !designAuthority(value) || !knownDesignBaseline(value.baseline) || !knownResearchDesign(value.design) || !knownDesignParent(value.parent)
      || !(value.predecessor === null || pin(value.predecessor)) || typeof value.is_head !== "boolean" || !eligible(value.eligibility) || !designHash(value.context_sha256) || !designHash(value.projection_sha256)
      || !await verifiedProjection(value, value.baseline, value.context_sha256)) return null;
  const receipt = await knownDesignReceipt(value.receipt, cap), body = receipt ? await designProof(receipt.receipt_canonical_json, receipt.receipt_sha256, 196608) : null;
  if (!receipt || !body || value.id !== receipt.receipt_id || value.record_sha256 !== receipt.receipt_sha256 || !["design_id", "revision", "operation", "status"].every(k => value[k] === receipt[k as keyof DesignReceipt])
      || !["baseline", "design", "parent", "context_sha256", "projection_sha256"].every(k => same(value[k], body[k]))
      || !same(value.predecessor, body.predecessor_id === null ? null : { id: body.predecessor_id, record_sha256: body.predecessor_sha256 })) return null;
  return value as unknown as DesignEntry;
}
export async function knownDesignPage(value: unknown, cap: DesignCapabilities, offset: number): Promise<DesignPage | null> {
  value = detached(value); cap = { ...cap };
  if (!designClosed(value, `version actor_user_id session_version offset limit total entries ${AUTH_KEYS}`) || !scoped(value, cap) || value.offset !== offset || value.limit !== 8 || !integer(value.total)
      || !Array.isArray(value.entries) || value.entries.length !== Math.min(8, Math.max(0, value.total - offset))) return null;
  const entries = await Promise.all(value.entries.map(e => knownEntry(e, cap)));
  return entries.every(e => e?.is_head) && new Set(entries.map(e => e!.design_id)).size === entries.length ? { ...value, entries } as unknown as DesignPage : null;
}
export async function knownDesignDetail(value: unknown, cap: DesignCapabilities, designId: string): Promise<DesignDetail | null> {
  value = detached(value); cap = { ...cap };
  if (!designClosed(value, `version actor_user_id session_version design_id revision_total history_limit entries ${AUTH_KEYS}`) || !scoped(value, cap) || value.design_id !== designId || !integer(value.revision_total, 1000) || value.revision_total === 0 || value.history_limit !== 8
      || !Array.isArray(value.entries) || value.entries.length !== Math.min(8, value.revision_total)) return null;
  const entries = await Promise.all(value.entries.map(e => knownEntry(e, cap)));
  if (entries.some(e => e === null)) return null;
  if (!entries.every((e, i) => e && e.design_id === designId && e.revision === (value.revision_total as number) - i && e.is_head === (i === 0)
      && (i === entries.length - 1 || same(e.predecessor, { id: entries[i + 1]!.id, record_sha256: entries[i + 1]!.record_sha256 })))) return null;
  return { ...value, entries } as unknown as DesignDetail;
}
export function emptyResearchDesign(): ResearchDesign {
  return { host_label: "", state_label: "", modifications: [{ kind: "doping", parameters: "" }], target_conditions: { pressure: { kind: "unspecified", raw_gpa: null }, temperature_k: null }, pairing_hypothesis: "unresolved", hypothesis: "",
    next_action: { kind: "source_review", question: "", prerequisites: [""], outcomes: [{ observation: "", decision: "continue" }, { observation: "", decision: "stop" }], budget: Object.entries(DESIGN_RESOURCES).map(([resource, unit]) => ({ resource: resource as keyof typeof DESIGN_RESOURCES, status: "unknown", raw_upper: null, unit })) } };
}
