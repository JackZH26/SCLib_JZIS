/** Private pending field tasks. Exact retained proof strings never become scientific approval. */
import { expressionCanonical, expressionSha, knownSourceRevision, parseExpressionJson, type SourceRevision } from "./source-expressions";

export const FIELD_CASE_VERSION = "material-field-case/1.0.0";
export const FIELD_CASE_REQUEST_VERSION = "material-field-case-operation/1.0.0";
export const FIELD_CASE_PAGE_SIZE = 8;
export const FIELD_CASE_FIELDS = ["tc_kelvin", "pressure_gpa", "tc_criterion", "measurement_method", "sample_form", "space_group", "crystal_structure", "lattice_a", "lattice_b", "lattice_c", "measurement_temperature_k", "atomic_sites", "site_occupancies", "composition_identity", "pairing_symmetry", "gap_structure", "is_unconventional", "competing_order", "hc2_tesla", "lambda_london_nm", "xi_gl_nm", "lambda_eph", "omega_log_k", "mu_star"] as const;
export const FIELD_CASE_OUTCOMES = ["pending_expression_available", "source_unavailable", "not_found_in_checked_scope", "requires_interpretation", "association_unresolved", "current_source_held", "target_changed", "external_reference_available", "needs_new_calculation_or_experiment"] as const;
export const FIELD_CASE_REASONS = [...FIELD_CASE_OUTCOMES, "bounded_scope_only", "source_identity_unresolved", "source_identity_proposed", "publication_currentness_unverified", "publication_rights_unverified", "expression_superseded", "target_fingerprint_changed", "material_not_currently_eligible", "source_lifecycle_held", "native_source_binding_unavailable", "unit_requires_review", "value_requires_review", "different_source_window", "different_model", "sample_state_unestablished", "no_expression_available"] as const;
export type TargetKind = "retained_result" | "tc_claim" | "event_property";
export type TargetSelector = { kind: TargetKind; material_id: string; record_index: number | null; entity_id: string | null; expected_context_sha256: string };
export type FieldCaseAuthority = { scientific_acceptance: false; canonical_promotions: 0; selected_result_association: "unestablished"; sample_identity_established: false; phase_identity_established: false; public_content_release: false; ml_training_approved: false };
export type FieldCaseEligibility = { eligible: boolean; reason_codes: string[] };
export type FieldCaseCapabilities = FieldCaseAuthority & { version: string; request_version: string; actor_user_id: string; session_version: number; curator_grant_id: string | null; can_write: boolean; field_ids: string[]; outcomes: string[]; reason_codes: string[]; expression_field_map: Record<string, string | null>; max_page_size: number; max_operation_bytes: number };
export type FieldCaseClosure = { material_id: string; kind: TargetKind; record_index: number | null; entity_id: string | null; paper_id: string | null; work_id: string | null; event_id: string | null; state_id: string | null; sample_id: string | null; legacy_result_id: string | null; retained_record_sha256: string | null };
export type FieldCaseContext = FieldCaseAuthority & { version: string; actor_user_id: string; session_version: number; target: TargetSelector; context_canonical_json: string; context_sha256: string; closure: FieldCaseClosure; eligibility: FieldCaseEligibility };
export type FieldCasePredecessor = { id: string; record_sha256: string };
export type FieldCaseExpressionPin = { revision_id: string; record_sha256: string };
export type FieldCaseTargetPayload = { field_id: string; target: TargetSelector };
export type FieldCaseAssociationPayload = { target_id: string; target_sha256: string; expression_revision_id: string; expression_record_sha256: string; source_identity: { paper_id: string | null; work_id: string | null }; action: "propose" | "withdraw"; predecessor: FieldCasePredecessor | null };
export type FieldCaseAttemptPayload = { target_id: string; target_sha256: string; outcome: string; reason_codes: string[]; checked_scope: { source_ids: string[]; fulltext_checked: boolean; supplement_checked: boolean; scope_label: string }; expression_pins: FieldCaseExpressionPin[]; predecessor: FieldCasePredecessor | null };
export type FieldCaseRequest = { version: string; request_key: string } & ({ operation: "target"; payload: FieldCaseTargetPayload } | { operation: "association"; payload: FieldCaseAssociationPayload } | { operation: "attempt"; payload: FieldCaseAttemptPayload });
export type FieldCaseReceipt = FieldCaseAuthority & { version: string; receipt_id: string; receipt_sha256: string; operation: FieldCaseRequest["operation"]; target_id: string; actor_user_id: string; actor_grant_id: string; actor_session_version: number; request_key: string; request_sha256: string; preview_sha256: string; request_canonical_json: string; preview_canonical_json: string; receipt_canonical_json: string; replayed: boolean; dry_run: boolean; pending_ledger_written: boolean };
export type FieldCaseRecovery = { actorId: string; requestKey: string; requestSha: string; requestCanonical: string; previewSha: string; receiptSha: string; receiptId: string; operation: FieldCaseRequest["operation"]; targetContextSha: string; fieldId: string; chainKey: string | null };
export type FieldCaseEntry = FieldCaseAuthority & { id: string; record_sha256: string; record_canonical_json: string; operation: FieldCaseRequest["operation"]; payload: FieldCaseTargetPayload | FieldCaseAssociationPayload | FieldCaseAttemptPayload; context_canonical_json: string | null; context_sha256: string; created_at: string; eligibility: FieldCaseEligibility; is_head?: boolean; expression?: SourceRevision | null; source_identity_status?: "proposed" };
export type FieldCaseDetail = FieldCaseAuthority & { version: string; actor_user_id: string; session_version: number; target: FieldCaseEntry; associations: FieldCaseEntry[]; attempts: FieldCaseEntry[]; association_total: number; attempt_total: number; association_returned: number; attempt_returned: number; association_omitted: number; attempt_omitted: number; response_truncated: boolean };
export type FieldCaseMaterialPage = FieldCaseAuthority & { version: string; actor_user_id: string; session_version: number; material_id: string; total: number; offset: number; limit: number; next_offset: number | null; entries: FieldCaseDetail[]; eligibility: FieldCaseEligibility; expressions_returned: number; expressions_omitted: number; entries_returned: number; entries_omitted: number; response_truncated: boolean };

type Row = Record<string, unknown>;
const AUTHORITY: FieldCaseAuthority = { scientific_acceptance: false, canonical_promotions: 0, selected_result_association: "unestablished", sample_identity_established: false, phase_identity_established: false, public_content_release: false, ml_training_approved: false };
const AUTH_KEYS = Object.keys(AUTHORITY).join(" ");
const ROW_KEYS = "id actor_user_id actor_grant_id actor_session_version operation request_key request_json payload request_sha256 preview_json preview_sha256 context_json context_sha256 field_id target_id chain_key predecessor_id predecessor_sha256 expression_revision_id expression_record_sha256";
const HASH = /^[a-f0-9]{64}$/, UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
function row(v: unknown): v is Row { return v !== null && typeof v === "object" && !Array.isArray(v); }
function closed(v: unknown, keys: string): v is Row { const names = keys.split(" "); return row(v) && Object.keys(v).length === names.length && names.every(k => Object.hasOwn(v, k)); }
function safe(v: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): v is number { return typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max; }
function hash(v: unknown): v is string { return typeof v === "string" && HASH.test(v); }
function uuid(v: unknown): v is string { return typeof v === "string" && UUID.test(v); }
export function fieldCaseText(v: unknown, max = 160): v is string { return typeof v === "string" && v.trim() === v && Array.from(v).length > 0 && Array.from(v).length <= max && !/[\u0000-\u001f]/.test(v) && !Array.from(v).some(c => c.length === 1 && c.charCodeAt(0) >= 0xd800 && c.charCodeAt(0) <= 0xdfff); }
function includes(values: readonly string[], v: unknown): v is string { return typeof v === "string" && values.includes(v); }
function equal(a: unknown, b: unknown): boolean { if (a === b) return true; if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v, i) => equal(v, b[i])); return row(a) && row(b) && Object.keys(a).length === Object.keys(b).length && Object.keys(a).every(k => Object.hasOwn(b, k) && equal(a[k], b[k])); }
function authority(v: Row) { return Object.entries(AUTHORITY).every(([k, val]) => v[k] === val); }
function eligibility(v: unknown): v is FieldCaseEligibility { return closed(v, "eligible reason_codes") && typeof v.eligible === "boolean" && Array.isArray(v.reason_codes) && v.reason_codes.every(x => includes(FIELD_CASE_REASONS, x)) && new Set(v.reason_codes).size === v.reason_codes.length && v.eligible === (v.reason_codes.length === 0); }
function predecessor(v: unknown) { return v === null || closed(v, "id record_sha256") && uuid(v.id) && hash(v.record_sha256); }
function selector(v: unknown): v is TargetSelector { return closed(v, "kind material_id record_index entity_id expected_context_sha256") && includes(["retained_result", "tc_claim", "event_property"], v.kind) && fieldCaseText(v.material_id, 100) && hash(v.expected_context_sha256) && (v.kind === "retained_result" ? safe(v.record_index, 0, 4999) && v.entity_id === null : v.record_index === null && uuid(v.entity_id)); }
export function knownFieldCaseRequest(v: unknown): v is FieldCaseRequest {
  if (!closed(v, "version request_key operation payload") || v.version !== FIELD_CASE_REQUEST_VERSION || !fieldCaseText(v.request_key) || !/^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$/.test(v.request_key) || !includes(["target", "association", "attempt"], v.operation)) return false;
  const p = v.payload;
  if (v.operation === "target") { if (!closed(p, "field_id target") || !includes(FIELD_CASE_FIELDS, p.field_id) || !selector(p.target)) return false; }
  else {
    if (!closed(p, v.operation === "association" ? "target_id target_sha256 expression_revision_id expression_record_sha256 source_identity action predecessor" : "target_id target_sha256 outcome reason_codes checked_scope expression_pins predecessor") || !uuid(p.target_id) || !hash(p.target_sha256) || !predecessor(p.predecessor)) return false;
    if (v.operation === "association") {
      if (!uuid(p.expression_revision_id) || !hash(p.expression_record_sha256) || !includes(["propose", "withdraw"], p.action) || p.action === "withdraw" && p.predecessor === null || !closed(p.source_identity, "paper_id work_id") || !(p.source_identity.paper_id === null || fieldCaseText(p.source_identity.paper_id, 100)) || !(p.source_identity.work_id === null || uuid(p.source_identity.work_id))) return false;
    } else {
      const scope = p.checked_scope;
      if (!includes(FIELD_CASE_OUTCOMES, p.outcome) || !Array.isArray(p.reason_codes) || p.reason_codes.length < 1 || p.reason_codes.length > 16 || new Set(p.reason_codes).size !== p.reason_codes.length || !p.reason_codes.every(x => includes(FIELD_CASE_REASONS, x)) || !closed(scope, "source_ids fulltext_checked supplement_checked scope_label") || !Array.isArray(scope.source_ids) || scope.source_ids.length > 8 || new Set(scope.source_ids).size !== scope.source_ids.length || !scope.source_ids.every(x => fieldCaseText(x)) || !fieldCaseText(scope.scope_label, 500) || typeof scope.fulltext_checked !== "boolean" || typeof scope.supplement_checked !== "boolean" || !scope.source_ids.length && (scope.fulltext_checked || scope.supplement_checked) || !Array.isArray(p.expression_pins) || p.expression_pins.length > 8 || !p.expression_pins.every(pin => closed(pin, "revision_id record_sha256") && uuid(pin.revision_id) && hash(pin.record_sha256)) || new Set(p.expression_pins.map(pin => (pin as Row).revision_id)).size !== p.expression_pins.length || p.outcome === "pending_expression_available" && !p.expression_pins.length) return false;
    }
  }
  try { return new TextEncoder().encode(expressionCanonical(v)).length <= 32768; } catch { return false; }
}
const EXPECTED_MAP: Record<string, string | null> = Object.fromEntries(FIELD_CASE_FIELDS.map(field => [field, ({ measurement_method: "method_statement", sample_form: "sample_form_statement", space_group: "structure_statement", crystal_structure: "structure_statement", pairing_symmetry: "classification_statement", gap_structure: "classification_statement", is_unconventional: "classification_statement", competing_order: "classification_statement", tc_criterion: "tc_kelvin:criterion_statement:reported_result_condition", atomic_sites: null, site_occupancies: null, composition_identity: null, xi_gl_nm: null } as Record<string, string | null>)[field] ?? (["atomic_sites", "site_occupancies", "composition_identity", "xi_gl_nm"].includes(field) ? null : field)]));
export function knownFieldCaseCapabilities(v: unknown, actor: string): FieldCaseCapabilities | null {
  return closed(v, `version request_version actor_user_id session_version curator_grant_id can_write field_ids outcomes reason_codes expression_field_map max_page_size max_operation_bytes ${AUTH_KEYS}`) && v.version === FIELD_CASE_VERSION && v.request_version === FIELD_CASE_REQUEST_VERSION && v.actor_user_id === actor && uuid(v.actor_user_id) && safe(v.session_version) && typeof v.can_write === "boolean" && (v.can_write ? uuid(v.curator_grant_id) : v.curator_grant_id === null) && equal(v.field_ids, FIELD_CASE_FIELDS) && equal(v.outcomes, FIELD_CASE_OUTCOMES) && equal(v.reason_codes, FIELD_CASE_REASONS) && equal(v.expression_field_map, EXPECTED_MAP) && v.max_page_size === 8 && v.max_operation_bytes === 32768 && authority(v) ? v as unknown as FieldCaseCapabilities : null;
}
async function proof(text: unknown, sha: unknown, maximum = 262144): Promise<Row | null> {
  if (typeof text !== "string" || new TextEncoder().encode(text).length > maximum || !hash(sha) || await expressionSha(text) !== sha) return null;
  try { const parsed = parseExpressionJson(text, false); return row(parsed) ? parsed : null; } catch { return null; }
}
function contextBody(body: unknown, target: TargetSelector) { return closed(body, "kind material_id record_index entity_id material result event state sample") && body.kind === target.kind && body.material_id === target.material_id && body.record_index === target.record_index && body.entity_id === target.entity_id && row(body.material) && body.material.id === target.material_id && row(body.result) && ["event", "state", "sample"].every(k => body[k] === null || row(body[k])) && (target.kind !== "retained_result" || body.event === null && body.state === null && body.sample === null); }
export async function knownFieldCaseContext(v: unknown, cap: FieldCaseCapabilities, materialId: string, kind: TargetKind, recordIndex: number | null, entityId: string | null): Promise<FieldCaseContext | null> {
  try {
    if (!closed(v, `version actor_user_id session_version target context_canonical_json context_sha256 closure eligibility ${AUTH_KEYS}`) || v.version !== FIELD_CASE_VERSION || v.actor_user_id !== cap.actor_user_id || v.session_version !== cap.session_version || !selector(v.target) || v.target.material_id !== materialId || v.target.kind !== kind || v.target.record_index !== recordIndex || v.target.entity_id !== entityId || v.target.expected_context_sha256 !== v.context_sha256 || !eligibility(v.eligibility) || !authority(v)) return null;
    const body = await proof(v.context_canonical_json, v.context_sha256, 131072);
    if (!contextBody(body, v.target) || !closed(v.closure, "material_id kind record_index entity_id paper_id work_id event_id state_id sample_id legacy_result_id retained_record_sha256")) return null;
    const c = v.closure;
    if (!["material_id", "kind", "record_index", "entity_id"].every(k => c[k] === (v.target as unknown as Row)[k]) || !(c.paper_id === null || fieldCaseText(c.paper_id, 100)) || !["work_id", "event_id", "state_id", "sample_id"].every(k => c[k] === null || uuid(c[k])) || !(c.legacy_result_id === null || fieldCaseText(c.legacy_result_id, 200)) || !(c.retained_record_sha256 === null || hash(c.retained_record_sha256))) return null;
    const parsed = body as Row, result = parsed.result as Row;
    if (c.paper_id !== (result.paper_id ?? null) || c.work_id !== (result.work_id ?? null) || !["event", "state", "sample"].every(k => { const child = parsed[k]; return c[k + "_id"] === (row(child) ? child.id : null); })) return null;
    return v as unknown as FieldCaseContext;
  } catch { return null; }
}
async function rowProof(text: unknown, sha: unknown): Promise<Row | null> {
  const body = await proof(text, sha, 524288);
  if (!closed(body, ROW_KEYS) || !uuid(body.id) || !uuid(body.actor_user_id) || !uuid(body.actor_grant_id) || !safe(body.actor_session_version) || !includes(FIELD_CASE_FIELDS, body.field_id)) return null;
  const request = await proof(body.request_json, body.request_sha256, 32768);
  if (!knownFieldCaseRequest(request) || request.operation !== body.operation || request.request_key !== body.request_key || !equal(request.payload, body.payload)) return null;
  const preview = await proof(body.preview_json, body.preview_sha256, 8192);
  if (!equal(preview, { version: FIELD_CASE_VERSION, actor: { actor_user_id: body.actor_user_id, actor_grant_id: body.actor_grant_id, actor_session_version: body.actor_session_version }, request_sha256: body.request_sha256, receipt_id: body.id, context_sha256: body.context_sha256 })) return null;
  if (request.operation === "target") {
    const p = request.payload;
    if (body.field_id !== p.field_id || !["target_id", "chain_key", "predecessor_id", "predecessor_sha256", "expression_revision_id", "expression_record_sha256"].every(k => body[k] === null) || p.target.expected_context_sha256 !== body.context_sha256 || !contextBody(await proof(body.context_json, body.context_sha256, 131072), p.target)) return null;
  } else {
    const p = request.payload;
    if (body.target_id !== p.target_id || body.predecessor_id !== (p.predecessor?.id ?? null) || body.predecessor_sha256 !== (p.predecessor?.record_sha256 ?? null) || !await proof(body.context_json, body.context_sha256, 131072)) return null;
    if (request.operation === "association") { if (body.expression_revision_id !== request.payload.expression_revision_id || body.expression_record_sha256 !== request.payload.expression_record_sha256 || !hash(body.chain_key)) return null; }
    else if (body.expression_revision_id !== null || body.expression_record_sha256 !== null || body.chain_key !== p.target_id) return null;
  }
  return body;
}
export function fieldCaseRecovery(request: FieldCaseRequest, cap: FieldCaseCapabilities, requestSha: string, target?: FieldCaseEntry, associationChain: string | null = null): FieldCaseRecovery {
  const originalTarget = request.operation !== "target" && target?.id === request.payload.target_id && target.record_sha256 === request.payload.target_sha256 ? target : undefined;
  return { actorId: cap.actor_user_id, requestKey: request.request_key, requestSha, requestCanonical: expressionCanonical(request), previewSha: "", receiptSha: "", receiptId: "", operation: request.operation,
    targetContextSha: request.operation === "target" ? request.payload.target.expected_context_sha256 : originalTarget?.context_sha256 ?? "",
    fieldId: request.operation === "target" ? request.payload.field_id : (originalTarget?.payload as FieldCaseTargetPayload | undefined)?.field_id ?? "",
    chainKey: request.operation === "target" ? null : request.operation === "attempt" ? request.payload.target_id : associationChain };
}
export async function knownFieldCaseReceipt(v: unknown, cap: FieldCaseCapabilities, ref: FieldCaseRecovery, stage: "preview" | "commit" | "outcome"): Promise<FieldCaseReceipt | null> {
  try {
    if (!closed(v, `version receipt_id receipt_sha256 operation target_id actor_user_id actor_grant_id actor_session_version request_key request_sha256 preview_sha256 request_canonical_json preview_canonical_json receipt_canonical_json replayed dry_run pending_ledger_written ${AUTH_KEYS}`) || v.version !== FIELD_CASE_VERSION || v.actor_user_id !== cap.actor_user_id || v.actor_user_id !== ref.actorId || v.operation !== ref.operation || v.request_key !== ref.requestKey || v.request_sha256 !== ref.requestSha || v.request_canonical_json !== ref.requestCanonical || !uuid(v.target_id) || typeof v.replayed !== "boolean" || typeof v.dry_run !== "boolean" || typeof v.pending_ledger_written !== "boolean" || v.pending_ledger_written !== !v.dry_run || !authority(v)) return null;
    const body = await rowProof(v.receipt_canonical_json, v.receipt_sha256);
    if (!body || !hash(ref.targetContextSha) || !includes(FIELD_CASE_FIELDS, ref.fieldId) || body.context_sha256 !== ref.targetContextSha || body.field_id !== ref.fieldId || body.chain_key !== ref.chainKey || v.operation === "association" && !hash(ref.chainKey) || v.receipt_id !== body.id || v.target_id !== (v.operation === "target" ? body.id : body.target_id) || !["actor_user_id", "actor_grant_id", "actor_session_version", "request_key", "request_sha256", "preview_sha256"].every(k => v[k] === body[k]) || v.request_canonical_json !== body.request_json || v.preview_canonical_json !== body.preview_json) return null;
    if (stage === "preview") { if (v.replayed ? v.dry_run : !v.dry_run || v.actor_grant_id !== cap.curator_grant_id || v.actor_session_version !== cap.session_version) return null; }
    else if (v.dry_run || !hash(ref.previewSha) || !hash(ref.receiptSha) || !uuid(ref.receiptId) || v.preview_sha256 !== ref.previewSha || v.receipt_sha256 !== ref.receiptSha || v.receipt_id !== ref.receiptId || stage === "outcome" && !v.replayed || !v.replayed && (v.actor_grant_id !== cap.curator_grant_id || v.actor_session_version !== cap.session_version)) return null;
    return v as unknown as FieldCaseReceipt;
  } catch { return null; }
}
const ENTRY_KEYS = `id record_sha256 record_canonical_json operation payload context_canonical_json context_sha256 created_at eligibility ${AUTH_KEYS}`;
export async function knownFieldCaseEntry(v: unknown, operation: FieldCaseRequest["operation"], target?: FieldCaseEntry, original?: FieldCaseEntry): Promise<FieldCaseEntry | null> {
  try {
    if (!closed(v, ENTRY_KEYS + (operation === "association" ? " is_head expression source_identity_status" : operation === "attempt" ? " is_head" : "")) || v.operation !== operation || !fieldCaseText(v.created_at, 50) || !Number.isFinite(Date.parse(v.created_at)) || !eligibility(v.eligibility) || !authority(v) || original && (v.id !== original.id || v.record_sha256 !== original.record_sha256 || v.record_canonical_json !== original.record_canonical_json)) return null;
    const body = await rowProof(v.record_canonical_json, v.record_sha256);
    if (!body || body.id !== v.id || body.operation !== operation || !equal(body.payload, v.payload) || body.context_sha256 !== v.context_sha256 || (operation === "target" ? v.context_canonical_json !== body.context_json : v.context_canonical_json !== null || !target || body.target_id !== target.id || (body.payload as Row).target_sha256 !== target.record_sha256 || body.context_sha256 !== target.context_sha256 || body.context_json !== target.context_canonical_json || body.field_id !== (target.payload as FieldCaseTargetPayload).field_id) || operation !== "target" && typeof v.is_head !== "boolean") return null;
    if (operation === "association") {
      if (v.source_identity_status !== "proposed" || v.expression !== null && !v.eligibility.eligible) return null;
      if (v.expression !== null) { const expr = await knownSourceRevision(v.expression); if (!expr || expr.id !== body.expression_revision_id || expr.record_sha256 !== body.expression_record_sha256 || !expr.is_expression_head || !v.is_head || (v.payload as FieldCaseAssociationPayload).action !== "propose" || !compatibleFieldExpression(body.field_id as string, expr)) return null; if (body.chain_key !== await expressionSha(expressionCanonical([target!.id, expr.expression_key]))) return null; }
    }
    return v as unknown as FieldCaseEntry;
  } catch { return null; }
}
export function compatibleFieldExpression(field: string, expr: SourceRevision): boolean { const mapped = EXPECTED_MAP[field]; return mapped != null && (field === "tc_criterion" ? expr.projection.field_id === "tc_kelvin" && expr.projection.conditions.some(c => c.field_id === "criterion_statement" && c.role === "reported_result_condition") : expr.projection.field_id === mapped); }
export function fieldCaseEntryActor(entry: FieldCaseEntry): string | null { try { const body = parseExpressionJson(entry.record_canonical_json, false); return row(body) && uuid(body.actor_user_id) ? body.actor_user_id : null; } catch { return null; } }
export function fieldCaseEntryChain(entry: FieldCaseEntry): string | null { try { const body = parseExpressionJson(entry.record_canonical_json, false); return row(body) && hash(body.chain_key) ? body.chain_key : null; } catch { return null; } }
/** Display only known retained scalar metadata. No unit conversion, fallback origin or source join. */
export function fieldCaseTargetSummary(contextCanonical: string): { label: string; value: string }[] {
  try {
    const body = parseExpressionJson(contextCanonical, false);
    if (!closed(body, "kind material_id record_index entity_id material result event state sample") || !row(body.result)) return [];
    const record = body.kind === "tc_claim" && row(body.result.raw_record) ? body.result.raw_record : body.result;
    const scalar = (keys: string[]) => { for (const key of keys) { const value = record[key]; if (typeof value === "number" && Number.isFinite(value)) return String(value); if (typeof value === "string" && fieldCaseText(value, 200)) return value; } return null; };
    const quantity = (name: string, canonicalKey: string, rawKey: string, unitKey: string, canonicalUnit: string) => {
      const namedValue = scalar([canonicalKey]), value = namedValue ?? scalar([rawKey]), unit = scalar(namedValue !== null ? [`${canonicalKey}_unit`, unitKey] : [unitKey]);
      const bare = value !== null && /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value);
      // Inline values and generic fields are raw metadata: never infer or convert their unit.
      const label = bare && unit !== null ? `Retained ${name} (${unit})` : bare && namedValue !== null ? `Retained ${name} (${canonicalUnit})` : `Retained ${name} ${name === "pressure" && !bare ? "label" : "raw value"}`;
      return { label, value };
    };
    return [
      { label: "Retained formula", value: scalar(["material_formula", "formula", "material"]) },
      quantity("Tc", "tc_kelvin", "tc", "tc_unit", "K"),
      quantity("pressure", "pressure_gpa", "pressure", "pressure_unit", "GPa"),
      { label: "Retained origin", value: scalar(["knowledge_origin"]) },
      { label: "Retained criterion", value: scalar(["tc_criterion", "tc_definition", "criterion"]) },
    ].filter((item): item is { label: string; value: string } => item.value !== null);
  } catch { return []; }
}
export async function knownFieldCaseDetail(v: unknown, cap: FieldCaseCapabilities, original?: FieldCaseEntry): Promise<FieldCaseDetail | null> {
  if (!closed(v, `version actor_user_id session_version target associations attempts association_total attempt_total association_returned attempt_returned association_omitted attempt_omitted response_truncated ${AUTH_KEYS}`) || v.version !== FIELD_CASE_VERSION || v.actor_user_id !== cap.actor_user_id || v.session_version !== cap.session_version || !authority(v) || typeof v.response_truncated !== "boolean" || !Array.isArray(v.associations) || !Array.isArray(v.attempts)) return null;
  const target = await knownFieldCaseEntry(v.target, "target", undefined, original); if (!target) return null;
  for (const kind of ["association", "attempt"] as const) {
    const entries = v[kind === "association" ? "associations" : "attempts"] as unknown[], total = v[kind + "_total"], returned = v[kind + "_returned"], omitted = v[kind + "_omitted"];
    if (!safe(total) || returned !== entries.length || !safe(returned, 0, 8) || !safe(omitted) || total !== returned + omitted || new Set(entries.map(x => row(x) ? x.id : null)).size !== entries.length || (await Promise.all(entries.map(x => knownFieldCaseEntry(x, kind, target)))).some(x => !x)) return null;
  }
  return v as unknown as FieldCaseDetail;
}
export async function knownFieldCaseMaterial(v: unknown, cap: FieldCaseCapabilities, materialId: string, offset: number): Promise<FieldCaseMaterialPage | null> {
  if (!closed(v, `version actor_user_id session_version material_id total offset limit next_offset entries eligibility expressions_returned expressions_omitted entries_returned entries_omitted response_truncated ${AUTH_KEYS}`) || v.version !== FIELD_CASE_VERSION || v.actor_user_id !== cap.actor_user_id || v.session_version !== cap.session_version || v.material_id !== materialId || !safe(v.total) || v.offset !== offset || v.limit !== 8 || !Array.isArray(v.entries) || v.entries_returned !== v.entries.length || !safe(v.entries_returned, 0, 8) || !safe(v.entries_omitted, 0, 8) || v.entries_returned + v.entries_omitted !== Math.min(8, Math.max(0, v.total - offset)) || v.next_offset !== (offset + v.entries.length < v.total ? offset + v.entries.length : null) || v.entries.length === 0 && v.next_offset !== null || typeof v.response_truncated !== "boolean" || v.response_truncated !== (v.entries_omitted > 0) || !eligibility(v.eligibility) || !safe(v.expressions_returned, 0, 8) || !safe(v.expressions_omitted) || !authority(v)) return null;
  const details = await Promise.all(v.entries.map(x => knownFieldCaseDetail(x, cap)));
  if (details.some(x => !x || (x.target.payload as FieldCaseTargetPayload).target.material_id !== materialId) || new Set(details.map(x => x?.target.id)).size !== details.length || details.reduce((n, x) => n + (x?.associations.filter(a => a.expression !== null).length ?? 0), 0) !== v.expressions_returned || !v.eligibility.eligible && v.expressions_returned !== 0) return null;
  return v as unknown as FieldCaseMaterialPage;
}
export function fieldCaseLabel(field: string): string { return ({ tc_kelvin: "Reported Tc", pressure_gpa: "Pressure", tc_criterion: "Tc criterion", criterion_statement: "Criterion", method_statement: "Method", window_statement: "Source window", magnetic_field_t: "Magnetic field", measurement_method: "Measurement method", sample_form: "Sample form", space_group: "Space group", crystal_structure: "Crystal structure", lattice_a: "Lattice a", lattice_b: "Lattice b", lattice_c: "Lattice c", measurement_temperature_k: "Measurement temperature", atomic_sites: "Atomic sites", site_occupancies: "Site occupancies", composition_identity: "Composition identity", pairing_symmetry: "Pairing symmetry", gap_structure: "Gap structure", is_unconventional: "Unconventional classification", competing_order: "Competing order", hc2_tesla: "Upper critical field", lambda_london_nm: "London penetration depth", xi_gl_nm: "GL coherence length", lambda_eph: "Electron–phonon coupling λ", omega_log_k: "Logarithmic phonon frequency", mu_star: "Coulomb pseudopotential μ*" } as Record<string, string>)[field] ?? field; }
export function fieldCaseReason(reason: string): string { return ({ pending_expression_available: "Pending source expression available", source_unavailable: "Source unavailable", not_found_in_checked_scope: "Not found in the checked scope", requires_interpretation: "Requires interpretation", association_unresolved: "Association unresolved", current_source_held: "Current source held", target_changed: "Target changed", external_reference_available: "Independent reference available", needs_new_calculation_or_experiment: "Needs a new calculation or experiment", bounded_scope_only: "Bounded scope only", source_identity_unresolved: "Source identity unresolved", source_identity_proposed: "Source identity proposed", publication_currentness_unverified: "Publication currentness unverified", publication_rights_unverified: "Publication rights unverified", expression_superseded: "Expression superseded", target_fingerprint_changed: "Target fingerprint changed", material_not_currently_eligible: "Material currently ineligible", source_lifecycle_held: "Source lifecycle held", native_source_binding_unavailable: "Native source binding unavailable", unit_requires_review: "Unit requires review", value_requires_review: "Value requires review", different_source_window: "Different source window", different_model: "Different model", sample_state_unestablished: "Sample and state unestablished", no_expression_available: "No expression available" } as Record<string, string>)[reason] ?? reason; }
