/** Opt-in literal contracts. The existing numeric intake and field cases remain frozen. */
import { expressionCanonical, expressionSha, parseExpressionJson } from "./source-expressions";
import { FIELD_CASE_FIELDS, FIELD_CASE_VERSION, FIELD_CASE_REQUEST_VERSION, knownFieldCaseCapabilities, fieldCaseText, fieldCaseReason } from "./material-field-cases";
import { knownSourceCapture, expressionSourceHref, type ExpressionSpan, type ExpressionRequest, type ExpressionPackage, type ExpressionProjection, type ExpressionManifest, type ExpressionReceipt, type ExpressionCapabilities, type SourceCapture, type SourceMetadata, type SourceRevision, type ExpressionRecovery } from "./source-expressions";
import type { MaterialEnrichmentReport } from "./api";

export const LITERAL_PROFILE = "material-literal-field/1.0.0";
export const LITERAL_PREPARE_VERSION = "material-literal-field-prepare/1.0.0";
export const LITERAL_PACKAGE_VERSION = "source-expression-package/2.1.0";
export const LITERAL_INTAKE_VERSION = "source-expression-intake/2.1.0";
export const LITERAL_EXTRACTOR_VERSION = "materials-literal-extractor/1.2.0";
export const LITERAL_REGISTRY_SHA = "e473392adda8311bba2009a6c288ae46a9f94ed142bafb98585c12ce0ac3a901";
export const LITERAL_ROLES: Record<string, string> = {
  hc1_source_value: "reported_property", gap_energy_source_value: "reported_property", gap_ratio_source_value: "reported_property",
  electronic_specific_heat_coefficient_source_value: "reported_property", debye_temperature_source_value: "reported_property", isotope_effect_exponent: "reported_property", dtc_dp_source_value: "reported_property",
  maximum_applied_pressure_source_value: "study_extent", meissner_fraction_percent: "reported_property", transition_width_source_value: "reported_property", minimum_temperature_k: "measurement_limit",
  t_cdw_k: "reported_order_transition", t_afm_k: "reported_order_transition", t_sdw_k: "reported_order_transition",
};
const LITERAL_LABELS: Record<string, string> = { hc1_source_value: "Lower critical field", gap_energy_source_value: "Gap energy", gap_ratio_source_value: "Gap ratio", electronic_specific_heat_coefficient_source_value: "Electronic specific heat coefficient", debye_temperature_source_value: "Debye temperature", isotope_effect_exponent: "Isotope effect exponent", dtc_dp_source_value: "Pressure dependence of Tc", maximum_applied_pressure_source_value: "Maximum applied pressure", meissner_fraction_percent: "Meissner fraction", transition_width_source_value: "Transition width", minimum_temperature_k: "Minimum measured temperature", t_cdw_k: "Charge density wave transition", t_afm_k: "Antiferromagnetic transition", t_sdw_k: "Spin density wave transition" };
const QUALIFIERS = ["cited_negative_or_qualified_context", "model_or_calculation_context", "fit_or_estimate_context", "inference_or_unmeasured_context"];
type LiteralEntry = ExpressionRequest & { profile: string; field_role: string; cue_spans: ExpressionSpan[]; uncertainty_spans: ExpressionSpan[]; qualifiers: string[] };
export type LiteralPackage = Omit<ExpressionPackage, "expressions"> & { profile: string; expressions: LiteralEntry[] };
export type LiteralValue = { status: "raw_literal"; raw_value: string; raw_amount: string; raw_unit: string | null; raw_uncertainty: string | null; quantity: null; normalization: "none"; field_cue: string; role: string; qualifiers: string[]; value_span: Span; unit_span: Span | null; cue_span: Span; uncertainty_span: Span | null };
type Span = { char_start: number; char_end: number; text_sha256: string };
export type LiteralProjection = Omit<ExpressionProjection, "value"> & { profile: string; field_role: string; value: LiteralValue; field_interpretation_reviewed: false; public_content_release: false; ml_training_approved: false };
export type LiteralSourceRevision = Omit<SourceRevision, "projection" | "source_entry"> & { projection: LiteralProjection; source_entry: LiteralEntry };
export type LiteralPrepared = { package: LiteralPackage; sourceText: string; retainedBytes: number; packageSha: string; requestSha: string; projections: LiteralProjection[] };
export type LiteralSourceRecovery = ExpressionRecovery & { receiptId: string; receiptSha: string; captureId: string };
export type LiteralPrepareRequest = { version: string; material_id: string; target: TargetSelector; candidate_id: string; extractor_version: string; chunk_id: string; source_content_sha256: string; retained_result_id: string; retained_record_sha256: string };
export type LiteralPrepare = LiteralCaseAuthority & { version: string; profile: string; status: string; actor_user_id: string; session_version: number; package: LiteralPackage; package_sha256: string; projection_sha256: string; target_operation: LiteralCaseRequest; context_canonical_json: string; pins: Omit<LiteralPrepareRequest, "version" | "material_id" | "target">; source_origin: { chunk_kind: string; evidence_revision_id: string; publication_revision_verified: false; source_rights_verified: false }; pending_ledger_written: false; verified: LiteralPrepared };
export type LiteralCandidate = { candidateId: string; field: string; rawValue: string; role: string; rawUnit: string | null; rawUncertainty: string | null; fieldCue: string; qualifiers: string[]; chunkId: string; contentSha: string; resultRefs: { resultId: string; recordSha: string }[]; sourceRevision: string; paperId: string };

export const LITERAL_CASE_VERSION = "material-field-case/1.1.0";
export const LITERAL_CASE_REQUEST_VERSION = "material-field-case-operation/1.1.0";
export const LITERAL_CASE_PAGE_SIZE = 8;
export const LITERAL_CASE_FIELDS = ["hc1_source_value", "gap_energy_source_value", "gap_ratio_source_value", "electronic_specific_heat_coefficient_source_value", "debye_temperature_source_value", "isotope_effect_exponent", "dtc_dp_source_value", "maximum_applied_pressure_source_value", "meissner_fraction_percent", "transition_width_source_value", "minimum_temperature_k", "t_cdw_k", "t_afm_k", "t_sdw_k"] as const;
export const LITERAL_CASE_OUTCOMES = ["pending_expression_available", "source_unavailable", "not_found_in_checked_scope", "requires_interpretation", "association_unresolved", "current_source_held", "target_changed", "external_reference_available", "needs_new_calculation_or_experiment"] as const;
export const LITERAL_CASE_REASONS = [...LITERAL_CASE_OUTCOMES, "bounded_scope_only", "source_identity_unresolved", "source_identity_proposed", "publication_currentness_unverified", "publication_rights_unverified", "expression_superseded", "target_fingerprint_changed", "material_not_currently_eligible", "source_lifecycle_held", "native_source_binding_unavailable", "unit_requires_review", "value_requires_review", "different_source_window", "different_model", "sample_state_unestablished", "no_expression_available"] as const;
export type TargetKind = "retained_result" | "tc_claim" | "event_property";
export type TargetSelector = { kind: TargetKind; material_id: string; record_index: number | null; entity_id: string | null; expected_context_sha256: string };
export type LiteralCaseAuthority = { scientific_acceptance: false; canonical_promotions: 0; selected_result_association: "unestablished"; sample_identity_established: false; phase_identity_established: false; public_content_release: false; ml_training_approved: false };
export type LiteralCaseEligibility = { eligible: boolean; reason_codes: string[] };
export type LiteralCaseCapabilities = LiteralCaseAuthority & { profile: string; field_request_versions: Record<string, string>; read_hold_reason_codes: string[]; version: string; request_version: string; actor_user_id: string; session_version: number; curator_grant_id: string | null; can_write: boolean; field_ids: string[]; outcomes: string[]; reason_codes: string[]; expression_field_map: Record<string, string | null>; max_page_size: number; max_operation_bytes: number };
export type LiteralCaseClosure = { material_id: string; kind: TargetKind; record_index: number | null; entity_id: string | null; paper_id: string | null; work_id: string | null; event_id: string | null; state_id: string | null; sample_id: string | null; legacy_result_id: string | null; retained_record_sha256: string | null };
export type LiteralCaseContext = LiteralCaseAuthority & { version: string; actor_user_id: string; session_version: number; target: TargetSelector; context_canonical_json: string; context_sha256: string; closure: LiteralCaseClosure; eligibility: LiteralCaseEligibility };
export type LiteralCasePredecessor = { id: string; record_sha256: string };
export type LiteralCaseExpressionPin = { revision_id: string; record_sha256: string };
export type LiteralCaseTargetPayload = { field_id: string; target: TargetSelector };
export type LiteralCaseAssociationPayload = { target_id: string; target_sha256: string; expression_revision_id: string; expression_record_sha256: string; source_identity: { paper_id: string | null; work_id: string | null }; action: "propose" | "withdraw"; predecessor: LiteralCasePredecessor | null };
export type LiteralCaseAttemptPayload = { target_id: string; target_sha256: string; outcome: string; reason_codes: string[]; checked_scope: { source_ids: string[]; fulltext_checked: boolean; supplement_checked: boolean; scope_label: string }; expression_pins: LiteralCaseExpressionPin[]; predecessor: LiteralCasePredecessor | null };
export type LiteralCaseRequest = { version: string; request_key: string } & ({ operation: "target"; payload: LiteralCaseTargetPayload } | { operation: "association"; payload: LiteralCaseAssociationPayload } | { operation: "attempt"; payload: LiteralCaseAttemptPayload });
export type LiteralCaseReceipt = LiteralCaseAuthority & { version: string; receipt_id: string; receipt_sha256: string; operation: LiteralCaseRequest["operation"]; target_id: string; actor_user_id: string; actor_grant_id: string; actor_session_version: number; request_key: string; request_sha256: string; preview_sha256: string; request_canonical_json: string; preview_canonical_json: string; receipt_canonical_json: string; replayed: boolean; dry_run: boolean; pending_ledger_written: boolean };
export type LiteralCaseRecovery = { actorId: string; requestKey: string; requestSha: string; requestCanonical: string; previewSha: string; receiptSha: string; receiptId: string; operation: LiteralCaseRequest["operation"]; targetContextSha: string; fieldId: string; chainKey: string | null };
export type LiteralCaseEntry = LiteralCaseAuthority & { id: string; record_sha256: string; record_canonical_json: string; operation: LiteralCaseRequest["operation"]; payload: LiteralCaseTargetPayload | LiteralCaseAssociationPayload | LiteralCaseAttemptPayload; context_canonical_json: string | null; context_sha256: string; created_at: string; eligibility: LiteralCaseEligibility; is_head?: boolean; expression?: LiteralSourceRevision | null; source_identity_status?: "proposed" };
export type LiteralCaseDetail = LiteralCaseAuthority & { version: string; actor_user_id: string; session_version: number; target: LiteralCaseEntry; associations: LiteralCaseEntry[]; attempts: LiteralCaseEntry[]; association_total: number; attempt_total: number; association_returned: number; attempt_returned: number; association_omitted: number; attempt_omitted: number; response_truncated: boolean };
export type LiteralCaseMaterialPage = LiteralCaseAuthority & { version: string; actor_user_id: string; session_version: number; material_id: string; total: number; offset: number; limit: number; next_offset: number | null; entries: LiteralCaseDetail[]; eligibility: LiteralCaseEligibility; expressions_returned: number; expressions_omitted: number; entries_returned: number; entries_omitted: number; response_truncated: boolean };

type Row = Record<string, unknown>;
const AUTHORITY: LiteralCaseAuthority = { scientific_acceptance: false, canonical_promotions: 0, selected_result_association: "unestablished", sample_identity_established: false, phase_identity_established: false, public_content_release: false, ml_training_approved: false };
const AUTH_KEYS = Object.keys(AUTHORITY).join(" ");
const ROW_KEYS = "id actor_user_id actor_grant_id actor_session_version operation request_key request_json payload request_sha256 preview_json preview_sha256 context_json context_sha256 field_id target_id chain_key predecessor_id predecessor_sha256 expression_revision_id expression_record_sha256";
const HASH = /^[a-f0-9]{64}$/, UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
function row(v: unknown): v is Row { return v !== null && typeof v === "object" && !Array.isArray(v); }
function closed(v: unknown, keys: string): v is Row { const names = keys.split(" "); return row(v) && Object.keys(v).length === names.length && names.every(k => Object.hasOwn(v, k)); }
function safe(v: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): v is number { return typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max; }
function hash(v: unknown): v is string { return typeof v === "string" && HASH.test(v); }
function uuid(v: unknown): v is string { return typeof v === "string" && UUID.test(v); }
export function literalCaseText(v: unknown, max = 160): v is string { return typeof v === "string" && v.trim() === v && Array.from(v).length > 0 && Array.from(v).length <= max && !/[\u0000-\u001f]/.test(v) && !Array.from(v).some(c => c.length === 1 && c.charCodeAt(0) >= 0xd800 && c.charCodeAt(0) <= 0xdfff); }
function includes(values: readonly string[], v: unknown): v is string { return typeof v === "string" && values.includes(v); }
function equal(a: unknown, b: unknown): boolean { if (a === b) return true; if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v, i) => equal(v, b[i])); return row(a) && row(b) && Object.keys(a).length === Object.keys(b).length && Object.keys(a).every(k => Object.hasOwn(b, k) && equal(a[k], b[k])); }
function authority(v: Row) { return Object.entries(AUTHORITY).every(([k, val]) => v[k] === val); }
export const LITERAL_READ_HOLD_REASONS = ["literal_capture_superseded", "literal_capture_authority_held", "literal_import_authority_held", "literal_association_authority_held"] as const;
function eligibility(v: unknown, readHolds = true): v is LiteralCaseEligibility { return closed(v, "eligible reason_codes") && typeof v.eligible === "boolean" && Array.isArray(v.reason_codes) && v.reason_codes.every(x => includes(readHolds ? [...LITERAL_CASE_REASONS, ...LITERAL_READ_HOLD_REASONS] : LITERAL_CASE_REASONS, x)) && new Set(v.reason_codes).size === v.reason_codes.length && v.eligible === (v.reason_codes.length === 0); }
function predecessor(v: unknown) { return v === null || closed(v, "id record_sha256") && uuid(v.id) && hash(v.record_sha256); }
function selector(v: unknown): v is TargetSelector { return closed(v, "kind material_id record_index entity_id expected_context_sha256") && includes(["retained_result", "tc_claim", "event_property"], v.kind) && literalCaseText(v.material_id, 100) && hash(v.expected_context_sha256) && (v.kind === "retained_result" ? safe(v.record_index, 0, 4999) && v.entity_id === null : v.record_index === null && uuid(v.entity_id)); }
export function knownLiteralCaseRequest(v: unknown): v is LiteralCaseRequest {
  if (!closed(v, "version request_key operation payload") || v.version !== LITERAL_CASE_REQUEST_VERSION || !literalCaseText(v.request_key) || !/^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$/.test(v.request_key) || !includes(["target", "association", "attempt"], v.operation)) return false;
  const p = v.payload;
  if (v.operation === "target") { if (!closed(p, "field_id target") || !includes(LITERAL_CASE_FIELDS, p.field_id) || !selector(p.target)) return false; }
  else {
    if (!closed(p, v.operation === "association" ? "target_id target_sha256 expression_revision_id expression_record_sha256 source_identity action predecessor" : "target_id target_sha256 outcome reason_codes checked_scope expression_pins predecessor") || !uuid(p.target_id) || !hash(p.target_sha256) || !predecessor(p.predecessor)) return false;
    if (v.operation === "association") {
      if (!uuid(p.expression_revision_id) || !hash(p.expression_record_sha256) || !includes(["propose", "withdraw"], p.action) || p.action === "withdraw" && p.predecessor === null || !closed(p.source_identity, "paper_id work_id") || !(p.source_identity.paper_id === null || literalCaseText(p.source_identity.paper_id, 100)) || !(p.source_identity.work_id === null || uuid(p.source_identity.work_id))) return false;
    } else {
      const scope = p.checked_scope;
      if (!includes(LITERAL_CASE_OUTCOMES, p.outcome) || !Array.isArray(p.reason_codes) || p.reason_codes.length < 1 || p.reason_codes.length > 16 || new Set(p.reason_codes).size !== p.reason_codes.length || !p.reason_codes.every(x => includes(LITERAL_CASE_REASONS, x)) || !closed(scope, "source_ids fulltext_checked supplement_checked scope_label") || !Array.isArray(scope.source_ids) || scope.source_ids.length > 8 || new Set(scope.source_ids).size !== scope.source_ids.length || !scope.source_ids.every(x => literalCaseText(x)) || !literalCaseText(scope.scope_label, 500) || typeof scope.fulltext_checked !== "boolean" || typeof scope.supplement_checked !== "boolean" || !scope.source_ids.length && (scope.fulltext_checked || scope.supplement_checked) || !Array.isArray(p.expression_pins) || p.expression_pins.length > 8 || !p.expression_pins.every(pin => closed(pin, "revision_id record_sha256") && uuid(pin.revision_id) && hash(pin.record_sha256)) || new Set(p.expression_pins.map(pin => (pin as Row).revision_id)).size !== p.expression_pins.length || p.outcome === "pending_expression_available" && !p.expression_pins.length) return false;
    }
  }
  try { return new TextEncoder().encode(expressionCanonical(v)).length <= 32768; } catch { return false; }
}
const EXPECTED_MAP = Object.fromEntries(LITERAL_CASE_FIELDS.map(field => [field, field]));
export function knownLiteralCaseCapabilities(v: unknown, actor: string): LiteralCaseCapabilities | null {
  if (!closed(v, `version request_version actor_user_id session_version curator_grant_id can_write field_ids outcomes reason_codes expression_field_map max_page_size max_operation_bytes profile field_request_versions read_hold_reason_codes ${AUTH_KEYS}`) || v.version !== LITERAL_CASE_VERSION || v.request_version !== LITERAL_CASE_REQUEST_VERSION || v.profile !== LITERAL_PROFILE || v.actor_user_id !== actor || !uuid(v.actor_user_id) || !safe(v.session_version) || typeof v.can_write !== "boolean" || (v.can_write ? !uuid(v.curator_grant_id) : v.curator_grant_id !== null) || !equal(v.field_ids, [...FIELD_CASE_FIELDS, ...LITERAL_CASE_FIELDS]) || !equal(v.outcomes, LITERAL_CASE_OUTCOMES) || !equal(v.reason_codes, LITERAL_CASE_REASONS) || !equal(v.read_hold_reason_codes, LITERAL_READ_HOLD_REASONS) || v.max_page_size !== 8 || v.max_operation_bytes !== 32768 || !authority(v) || !row(v.expression_field_map) || !row(v.field_request_versions)) return null;
  const { profile: _profile, field_request_versions: _versions, read_hold_reason_codes: _readHolds, ...base } = v;
  if (!knownFieldCaseCapabilities({ ...base, version: FIELD_CASE_VERSION, request_version: FIELD_CASE_REQUEST_VERSION, field_ids: FIELD_CASE_FIELDS, expression_field_map: Object.fromEntries(FIELD_CASE_FIELDS.map(f => [f, (v.expression_field_map as Row)[f]])) }, actor) || Object.keys(v.expression_field_map).length !== 38 || Object.keys(v.field_request_versions).length !== 38 || !FIELD_CASE_FIELDS.every(f => (v.field_request_versions as Row)[f] === FIELD_CASE_REQUEST_VERSION) || !LITERAL_CASE_FIELDS.every(f => (v.field_request_versions as Row)[f] === LITERAL_CASE_REQUEST_VERSION && (v.expression_field_map as Row)[f] === f)) return null;
  return v as unknown as LiteralCaseCapabilities;
}
async function proof(text: unknown, sha: unknown, maximum = 262144): Promise<Row | null> {
  if (typeof text !== "string" || new TextEncoder().encode(text).length > maximum || !hash(sha) || await expressionSha(text) !== sha) return null;
  try { const parsed = parseExpressionJson(text, false); return row(parsed) ? parsed : null; } catch { return null; }
}
function contextBody(body: unknown, target: TargetSelector) { return closed(body, "kind material_id record_index entity_id material result event state sample") && body.kind === target.kind && body.material_id === target.material_id && body.record_index === target.record_index && body.entity_id === target.entity_id && row(body.material) && body.material.id === target.material_id && row(body.result) && ["event", "state", "sample"].every(k => body[k] === null || row(body[k])) && (target.kind !== "retained_result" || body.event === null && body.state === null && body.sample === null); }
export async function knownLiteralCaseContext(v: unknown, cap: LiteralCaseCapabilities, materialId: string, kind: TargetKind, recordIndex: number | null, entityId: string | null): Promise<LiteralCaseContext | null> {
  try {
    if (!closed(v, `version actor_user_id session_version target context_canonical_json context_sha256 closure eligibility ${AUTH_KEYS}`) || v.version !== FIELD_CASE_VERSION || v.actor_user_id !== cap.actor_user_id || v.session_version !== cap.session_version || !selector(v.target) || v.target.material_id !== materialId || v.target.kind !== kind || v.target.record_index !== recordIndex || v.target.entity_id !== entityId || v.target.expected_context_sha256 !== v.context_sha256 || !eligibility(v.eligibility, false) || !authority(v)) return null;
    const body = await proof(v.context_canonical_json, v.context_sha256, 131072);
    if (!contextBody(body, v.target) || !closed(v.closure, "material_id kind record_index entity_id paper_id work_id event_id state_id sample_id legacy_result_id retained_record_sha256")) return null;
    const c = v.closure;
    if (!["material_id", "kind", "record_index", "entity_id"].every(k => c[k] === (v.target as unknown as Row)[k]) || !(c.paper_id === null || literalCaseText(c.paper_id, 100)) || !["work_id", "event_id", "state_id", "sample_id"].every(k => c[k] === null || uuid(c[k])) || !(c.legacy_result_id === null || literalCaseText(c.legacy_result_id, 200)) || !(c.retained_record_sha256 === null || hash(c.retained_record_sha256))) return null;
    const parsed = body as Row, result = parsed.result as Row;
    if (c.paper_id !== (result.paper_id ?? null) || c.work_id !== (result.work_id ?? null) || !["event", "state", "sample"].every(k => { const child = parsed[k]; return c[k + "_id"] === (row(child) ? child.id : null); })) return null;
    return v as unknown as LiteralCaseContext;
  } catch { return null; }
}
async function rowProof(text: unknown, sha: unknown): Promise<Row | null> {
  const body = await proof(text, sha, 524288);
  if (!closed(body, ROW_KEYS) || !uuid(body.id) || !uuid(body.actor_user_id) || !uuid(body.actor_grant_id) || !safe(body.actor_session_version) || !includes(LITERAL_CASE_FIELDS, body.field_id)) return null;
  const request = await proof(body.request_json, body.request_sha256, 32768);
  if (!knownLiteralCaseRequest(request) || request.operation !== body.operation || request.request_key !== body.request_key || !equal(request.payload, body.payload)) return null;
  const preview = await proof(body.preview_json, body.preview_sha256, 8192);
  if (!equal(preview, { version: LITERAL_CASE_VERSION, actor: { actor_user_id: body.actor_user_id, actor_grant_id: body.actor_grant_id, actor_session_version: body.actor_session_version }, request_sha256: body.request_sha256, receipt_id: body.id, context_sha256: body.context_sha256 })) return null;
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
export function literalCaseRecovery(request: LiteralCaseRequest, cap: LiteralCaseCapabilities, requestSha: string, target?: LiteralCaseEntry, associationChain: string | null = null): LiteralCaseRecovery {
  const originalTarget = request.operation !== "target" && target?.id === request.payload.target_id && target.record_sha256 === request.payload.target_sha256 ? target : undefined;
  return { actorId: cap.actor_user_id, requestKey: request.request_key, requestSha, requestCanonical: expressionCanonical(request), previewSha: "", receiptSha: "", receiptId: "", operation: request.operation,
    targetContextSha: request.operation === "target" ? request.payload.target.expected_context_sha256 : originalTarget?.context_sha256 ?? "",
    fieldId: request.operation === "target" ? request.payload.field_id : (originalTarget?.payload as LiteralCaseTargetPayload | undefined)?.field_id ?? "",
    chainKey: request.operation === "target" ? null : request.operation === "attempt" ? request.payload.target_id : associationChain };
}
export async function knownLiteralCaseReceipt(v: unknown, cap: LiteralCaseCapabilities, ref: LiteralCaseRecovery, stage: "preview" | "commit" | "outcome"): Promise<LiteralCaseReceipt | null> {
  try {
    if (!closed(v, `version receipt_id receipt_sha256 operation target_id actor_user_id actor_grant_id actor_session_version request_key request_sha256 preview_sha256 request_canonical_json preview_canonical_json receipt_canonical_json replayed dry_run pending_ledger_written ${AUTH_KEYS}`) || v.version !== LITERAL_CASE_VERSION || v.actor_user_id !== cap.actor_user_id || v.actor_user_id !== ref.actorId || v.operation !== ref.operation || v.request_key !== ref.requestKey || v.request_sha256 !== ref.requestSha || v.request_canonical_json !== ref.requestCanonical || !uuid(v.target_id) || typeof v.replayed !== "boolean" || typeof v.dry_run !== "boolean" || typeof v.pending_ledger_written !== "boolean" || v.pending_ledger_written !== !v.dry_run || !authority(v)) return null;
    const body = await rowProof(v.receipt_canonical_json, v.receipt_sha256);
    if (!body || !hash(ref.targetContextSha) || !includes(LITERAL_CASE_FIELDS, ref.fieldId) || body.context_sha256 !== ref.targetContextSha || body.field_id !== ref.fieldId || body.chain_key !== ref.chainKey || v.operation === "association" && !hash(ref.chainKey) || v.receipt_id !== body.id || v.target_id !== (v.operation === "target" ? body.id : body.target_id) || !["actor_user_id", "actor_grant_id", "actor_session_version", "request_key", "request_sha256", "preview_sha256"].every(k => v[k] === body[k]) || v.request_canonical_json !== body.request_json || v.preview_canonical_json !== body.preview_json) return null;
    if (stage === "preview") { if (v.replayed ? v.dry_run : !v.dry_run || v.actor_grant_id !== cap.curator_grant_id || v.actor_session_version !== cap.session_version) return null; }
    else if (v.dry_run || !hash(ref.previewSha) || !hash(ref.receiptSha) || !uuid(ref.receiptId) || v.preview_sha256 !== ref.previewSha || v.receipt_sha256 !== ref.receiptSha || v.receipt_id !== ref.receiptId || stage === "outcome" && !v.replayed || !v.replayed && (v.actor_grant_id !== cap.curator_grant_id || v.actor_session_version !== cap.session_version)) return null;
    return v as unknown as LiteralCaseReceipt;
  } catch { return null; }
}
const ENTRY_KEYS = `id record_sha256 record_canonical_json operation payload context_canonical_json context_sha256 created_at eligibility ${AUTH_KEYS}`;
export async function knownLiteralCaseEntry(v: unknown, operation: LiteralCaseRequest["operation"], target?: LiteralCaseEntry, original?: LiteralCaseEntry): Promise<LiteralCaseEntry | null> {
  try {
    if (!closed(v, ENTRY_KEYS + (operation === "association" ? " is_head expression source_identity_status" : operation === "attempt" ? " is_head" : "")) || v.operation !== operation || !literalCaseText(v.created_at, 50) || !Number.isFinite(Date.parse(v.created_at)) || !eligibility(v.eligibility) || !authority(v) || original && (v.id !== original.id || v.record_sha256 !== original.record_sha256 || v.record_canonical_json !== original.record_canonical_json)) return null;
    const body = await rowProof(v.record_canonical_json, v.record_sha256);
    if (!body || body.id !== v.id || body.operation !== operation || !equal(body.payload, v.payload) || body.context_sha256 !== v.context_sha256 || (operation === "target" ? v.context_canonical_json !== body.context_json : v.context_canonical_json !== null || !target || body.target_id !== target.id || (body.payload as Row).target_sha256 !== target.record_sha256 || body.context_sha256 !== target.context_sha256 || body.context_json !== target.context_canonical_json || body.field_id !== (target.payload as LiteralCaseTargetPayload).field_id) || operation !== "target" && typeof v.is_head !== "boolean") return null;
    if (operation === "association") {
      if (v.source_identity_status !== "proposed" || v.expression !== null && !v.eligibility.eligible) return null;
      if (v.expression !== null) { const expr = await knownLiteralSourceRevision(v.expression); if (!expr || expr.id !== body.expression_revision_id || expr.record_sha256 !== body.expression_record_sha256 || !expr.is_expression_head || !v.is_head || (v.payload as LiteralCaseAssociationPayload).action !== "propose" || !compatibleFieldExpression(body.field_id as string, expr)) return null; if (body.chain_key !== await expressionSha(expressionCanonical([target!.id, expr.expression_key]))) return null; }
    }
    return v as unknown as LiteralCaseEntry;
  } catch { return null; }
}
export function compatibleFieldExpression(field: string, expr: LiteralSourceRevision): boolean { const mapped = EXPECTED_MAP[field]; return mapped != null && (field === "tc_criterion" ? expr.projection.field_id === "tc_kelvin" && expr.projection.conditions.some(c => c.field_id === "criterion_statement" && c.role === "reported_result_condition") : expr.projection.field_id === mapped); }
export function literalCaseEntryActor(entry: LiteralCaseEntry): string | null { try { const body = parseExpressionJson(entry.record_canonical_json, false); return row(body) && uuid(body.actor_user_id) ? body.actor_user_id : null; } catch { return null; } }
export function literalCaseEntryChain(entry: LiteralCaseEntry): string | null { try { const body = parseExpressionJson(entry.record_canonical_json, false); return row(body) && hash(body.chain_key) ? body.chain_key : null; } catch { return null; } }
/** Display only known retained scalar metadata. No unit conversion, fallback origin or source join. */
export function literalCaseTargetSummary(contextCanonical: string): { label: string; value: string }[] {
  try {
    const body = parseExpressionJson(contextCanonical, false);
    if (!closed(body, "kind material_id record_index entity_id material result event state sample") || !row(body.result)) return [];
    const record = body.kind === "tc_claim" && row(body.result.raw_record) ? body.result.raw_record : body.result;
    const scalar = (keys: string[]) => { for (const key of keys) { const value = record[key]; if (typeof value === "number" && Number.isFinite(value)) return String(value); if (typeof value === "string" && literalCaseText(value, 200)) return value; } return null; };
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
export async function knownLiteralCaseDetail(v: unknown, cap: LiteralCaseCapabilities, original?: LiteralCaseEntry): Promise<LiteralCaseDetail | null> {
  if (!closed(v, `version actor_user_id session_version target associations attempts association_total attempt_total association_returned attempt_returned association_omitted attempt_omitted response_truncated ${AUTH_KEYS}`) || v.version !== LITERAL_CASE_VERSION || v.actor_user_id !== cap.actor_user_id || v.session_version !== cap.session_version || !authority(v) || typeof v.response_truncated !== "boolean" || !Array.isArray(v.associations) || !Array.isArray(v.attempts)) return null;
  const target = await knownLiteralCaseEntry(v.target, "target", undefined, original); if (!target) return null;
  for (const kind of ["association", "attempt"] as const) {
    const entries = v[kind === "association" ? "associations" : "attempts"] as unknown[], total = v[kind + "_total"], returned = v[kind + "_returned"], omitted = v[kind + "_omitted"];
    if (!safe(total) || returned !== entries.length || !safe(returned, 0, 8) || !safe(omitted) || total !== returned + omitted || new Set(entries.map(x => row(x) ? x.id : null)).size !== entries.length || (await Promise.all(entries.map(x => knownLiteralCaseEntry(x, kind, target)))).some(x => !x)) return null;
  }
  return v as unknown as LiteralCaseDetail;
}
export async function knownLiteralCaseMaterial(v: unknown, cap: LiteralCaseCapabilities, materialId: string, offset: number): Promise<LiteralCaseMaterialPage | null> {
  if (!closed(v, `version actor_user_id session_version material_id total offset limit next_offset entries eligibility expressions_returned expressions_omitted entries_returned entries_omitted response_truncated ${AUTH_KEYS}`) || v.version !== LITERAL_CASE_VERSION || v.actor_user_id !== cap.actor_user_id || v.session_version !== cap.session_version || v.material_id !== materialId || !safe(v.total) || v.offset !== offset || v.limit !== 8 || !Array.isArray(v.entries) || v.entries_returned !== v.entries.length || !safe(v.entries_returned, 0, 8) || !safe(v.entries_omitted, 0, 8) || v.entries_returned + v.entries_omitted !== Math.min(8, Math.max(0, v.total - offset)) || v.next_offset !== (offset + v.entries.length < v.total ? offset + v.entries.length : null) || v.entries.length === 0 && v.next_offset !== null || typeof v.response_truncated !== "boolean" || v.response_truncated !== (v.entries_omitted > 0) || !eligibility(v.eligibility) || !safe(v.expressions_returned, 0, 8) || !safe(v.expressions_omitted) || !authority(v)) return null;
  const details = await Promise.all(v.entries.map(x => knownLiteralCaseDetail(x, cap)));
  if (details.some(x => !x || (x.target.payload as LiteralCaseTargetPayload).target.material_id !== materialId) || new Set(details.map(x => x?.target.id)).size !== details.length || details.reduce((n, x) => n + (x?.associations.filter(a => a.expression !== null).length ?? 0), 0) !== v.expressions_returned || !v.eligibility.eligible && v.expressions_returned !== 0) return null;
  return v as unknown as LiteralCaseMaterialPage;
}
export function literalCaseLabel(field: string): string { return LITERAL_LABELS[field] ?? field; }
export function literalCaseReason(reason: string): string { return ({ literal_capture_superseded: "Source capture superseded", literal_capture_authority_held: "Source capture authority held", literal_import_authority_held: "Source import authority held", literal_association_authority_held: "Source proposal authority held" } as Record<string, string>)[reason] ?? fieldCaseReason(reason); }

function requireLiteral(ok: unknown, message = "The original source proof could not be verified."): asserts ok { if (!ok) throw new Error(message); }
const LITERAL_ENTRY_KEYS = "field_id subject window source_role knowledge_origin origin_basis model_spans value_spans unit_spans conditions locator predecessor profile field_role cue_spans uncertainty_spans qualifiers";
function literalEntry(v: unknown): v is LiteralEntry {
  const spans = (value: unknown, min: number, max: number, bound: number) => Array.isArray(value) && value.length >= min && value.length <= max && value.every(s => closed(s, "start end sha256") && safe(s.start, 0, 131072) && safe(s.end, 1, 131072) && s.end > s.start && s.end - s.start <= bound && hash(s.sha256)) && value.reduce((n, s) => n + (s.end - s.start), 0) <= bound;
  if (!closed(v, LITERAL_ENTRY_KEYS) || v.profile !== LITERAL_PROFILE || !includes(LITERAL_CASE_FIELDS, v.field_id) || v.field_role !== LITERAL_ROLES[v.field_id] || !includes(["source_reported", "source_fitted", "source_model_estimate", "source_proposed"], v.source_role) || !includes(["Observed", "Computed", "unknown"], v.knowledge_origin) || !Array.isArray(v.conditions) || v.conditions.length !== 0 || !Array.isArray(v.qualifiers) || !v.qualifiers.every(q => includes(QUALIFIERS, q)) || new Set(v.qualifiers).size !== v.qualifiers.length) return false;
  if (!closed(v.subject, "formula_spans sample_label_spans") || !spans(v.subject.formula_spans, 1, 1, 200) || !spans(v.subject.sample_label_spans, 0, 8, 200) || !closed(v.window, "id label_spans") || !fieldCaseText(v.window.id) || !spans(v.window.label_spans, 1, 1, 4096) || !closed(v.origin_basis, "statement spans") || v.origin_basis.statement !== null && !fieldCaseText(v.origin_basis.statement, 500) || !spans(v.origin_basis.spans, 0, 8, 1000) || !spans(v.model_spans, 0, 8, 500) || !spans(v.value_spans, 1, 1, 1200) || !spans(v.unit_spans, 0, 1, 120) || !spans(v.cue_spans, 1, 1, 200) || !spans(v.uncertainty_spans, 0, 1, 200)) return false;
  const loc = v.locator; if (!closed(loc, "page slide table row column section member") || !["page", "slide", "row", "column"].every(k => loc[k] === null || safe(loc[k], 1, 100000)) || !["table", "section", "member"].every(k => loc[k] === null || fieldCaseText(loc[k], 200))) return false;
  return v.predecessor === null || closed(v.predecessor, "revision_id record_sha256 revision_number") && uuid(v.predecessor.revision_id) && hash(v.predecessor.record_sha256) && safe(v.predecessor.revision_number, 1, 10000);
}
async function selection(chars: string[], spans: ExpressionSpan[], offset = 0): Promise<string> {
  const parts = []; let last = -1;
  for (const s of spans) { requireLiteral(s.start >= offset && s.end <= offset + chars.length && s.start >= last); const part = chars.slice(s.start-offset, s.end-offset).join(""); requireLiteral(await expressionSha(part) === s.sha256, "A selected Unicode span does not match its original text hash."); parts.push(part); last = s.end; }
  return parts.join("");
}
const spanProjection = (s?: ExpressionSpan): Span | null => s ? { char_start: s.start, char_end: s.end, text_sha256: s.sha256 } : null;
async function literalProjection(source: SourceMetadata, chars: string[], entry: LiteralEntry, offset = 0): Promise<LiteralProjection> {
  requireLiteral(literalEntry(entry)); const window = entry.window.label_spans[0], amount = entry.value_spans[0], unit = entry.unit_spans[0], cue = entry.cue_spans[0], uncertainty = entry.uncertainty_spans[0];
  const inside = (s?: ExpressionSpan) => !s || window.start <= s.start && s.start < s.end && s.end <= window.end;
  requireLiteral([entry.subject.formula_spans[0], amount, unit, cue, uncertainty].every(inside), "A literal selection leaves its original source window.");
  requireLiteral(cue.end <= amount.start && amount.start - cue.end <= 128 && (!unit || amount.end <= unit.start && unit.start - amount.end <= 128) && (!uncertainty || amount.start <= uncertainty.start && uncertainty.end <= amount.end));
  const rawAmount = await selection(chars, entry.value_spans, offset), rawUnit = await selection(chars, entry.unit_spans, offset), rawCue = await selection(chars, entry.cue_spans, offset), rawUncertainty = await selection(chars, entry.uncertainty_spans, offset);
  const subject = { formula: await selection(chars, entry.subject.formula_spans, offset), sample_label: await selection(chars, entry.subject.sample_label_spans, offset) || null, formula_scope: "retained_formula_span" };
  const sourceWindow = { id: entry.window.id, raw_label: await selection(chars, entry.window.label_spans, offset) }, model = await selection(chars, entry.model_spans, offset) || null;
  const identity = { source_id: source.source_id, field_id: entry.field_id, profile: LITERAL_PROFILE, field_role: LITERAL_ROLES[entry.field_id], subject, window: sourceWindow, source_role: entry.source_role, model };
  return { ...identity, expression_key: await expressionSha(expressionCanonical(identity)), knowledge_origin: entry.knowledge_origin, origin_basis: { statement: entry.origin_basis.statement, retained_text: await selection(chars, entry.origin_basis.spans, offset) || null, verification: "declared_inspection_basis" }, value: { status: "raw_literal", raw_value: chars.slice(amount.start-offset, (unit?.end ?? amount.end)-offset).join("").trim(), raw_amount: rawAmount, raw_unit: unit ? rawUnit.trim() : null, raw_uncertainty: uncertainty ? rawUncertainty : null, quantity: null, normalization: "none", field_cue: rawCue, role: LITERAL_ROLES[entry.field_id], qualifiers: entry.qualifiers, value_span: spanProjection(amount)!, unit_span: spanProjection(unit), cue_span: spanProjection(cue)!, uncertainty_span: spanProjection(uncertainty) }, conditions: [], locator: entry.locator, status: "pending", selected_result_association: "unestablished", sample_identity_established: false, phase_identity_established: false, field_interpretation_reviewed: false, scientific_acceptance: false, canonical_promotions: 0, public_content_release: false, ml_training_approved: false, missingness_scope: "not_supplied_in_retained_expression_is_not_source_absence" };
}
function literalMetadata(v: unknown): v is SourceMetadata {
  return closed(v, "source_id url kind content_kind revision revision_status original_parent_sha256 parent_hash_status rights_status currentness captured_at") && fieldCaseText(v.source_id) && /^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,159}$/.test(v.source_id) && Boolean(expressionSourceHref(v.url)) && includes(["primary_paper", "conference_presentation", "supplement", "crystal_reference"], v.kind) && includes(["plain_text", "xml_text"], v.content_kind) && includes(["declared", "unresolved"], v.revision_status) && includes(["declared", "unresolved"], v.parent_hash_status) && (v.revision === null) === (v.revision_status === "unresolved") && (v.original_parent_sha256 === null) === (v.parent_hash_status === "unresolved") && (v.revision === null || fieldCaseText(v.revision)) && (v.original_parent_sha256 === null || hash(v.original_parent_sha256)) && includes(["unresolved", "declared_private_inspection", "restricted"], v.rights_status) && includes(["unresolved", "declared_current", "historical"], v.currentness) && fieldCaseText(v.captured_at, 40) && /(?:Z|[+-]\d{2}:?\d{2})$/.test(v.captured_at) && Number.isFinite(Date.parse(v.captured_at));
}
function retainedLiteralShape(v: unknown): v is Omit<LiteralPackage, "source_text_base64"> { return closed(v, "version profile source source_content_sha256 expressions") && v.version === LITERAL_PACKAGE_VERSION && v.profile === LITERAL_PROFILE && literalMetadata(v.source) && hash(v.source_content_sha256) && Array.isArray(v.expressions) && v.expressions.length >= 1 && v.expressions.length <= 20 && v.expressions.every(literalEntry); }
export async function compileLiteralPackage(value: unknown): Promise<LiteralPrepared> {
  requireLiteral(closed(value, "version profile source source_text_base64 source_content_sha256 expressions") && typeof value.source_text_base64 === "string" && value.source_text_base64.length <= 4*Math.ceil(131072/3));
  const { source_text_base64, ...retained } = value; requireLiteral(retainedLiteralShape(retained));
  let binary: string; try { binary = atob(source_text_base64); } catch { throw new Error("The original fragment is not canonical UTF-8 base64."); }
  requireLiteral(binary.length >= 1 && binary.length <= 131072 && btoa(binary) === source_text_base64);
  const bytes = Uint8Array.from(binary, c => c.charCodeAt(0)), sourceText = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes); requireLiteral(!sourceText.includes("\0") && await expressionSha(bytes) === value.source_content_sha256);
  const pkg = value as unknown as LiteralPackage, projections = await Promise.all(pkg.expressions.map(e => literalProjection(pkg.source, Array.from(sourceText), e)));
  requireLiteral(new Set(projections.map(p => p.expression_key)).size === projections.length && projections.every(p => new TextEncoder().encode(expressionCanonical(p)).length <= 32768));
  const canonical = expressionCanonical(retained); requireLiteral(new TextEncoder().encode(canonical).length <= 131072); const packageSha = await expressionSha(canonical);
  return { package: pkg, sourceText, retainedBytes: bytes.length, packageSha, requestSha: await expressionSha(expressionCanonical({ version: LITERAL_INTAKE_VERSION, package_sha256: packageSha })), projections };
}
export function knownLiteralSourceCapabilities(v: unknown, actor: string): ExpressionCapabilities | null {
  return closed(v, "version package_version actor_user_id session_version can_import curator_grant_id registry_sha256 field_profiles max_source_bytes max_package_bytes max_projection_bytes max_expression_page_size max_expressions scope scientific_acceptance canonical_promotions public_content_release") && v.version === LITERAL_INTAKE_VERSION && v.package_version === LITERAL_PACKAGE_VERSION && v.actor_user_id === actor && uuid(actor) && safe(v.session_version) && typeof v.can_import === "boolean" && (v.can_import ? uuid(v.curator_grant_id) : v.curator_grant_id === null) && v.registry_sha256 === LITERAL_REGISTRY_SHA && equal(v.field_profiles, LITERAL_ROLES) && v.max_source_bytes === 131072 && v.max_package_bytes === 131072 && v.max_projection_bytes === 32768 && v.max_expression_page_size === 8 && v.max_expressions === 20 && v.scope === "private_pending_source_expressions" && v.scientific_acceptance === false && v.canonical_promotions === 0 && v.public_content_release === false ? v as unknown as ExpressionCapabilities : null;
}

async function literalCanonicalProof(text: unknown, sha: unknown, maximum = 524288): Promise<unknown> { requireLiteral(typeof text === "string" && new TextEncoder().encode(text).length <= maximum && hash(sha) && await expressionSha(text) === sha); return parseExpressionJson(text, false); }
function retainedLiteralPackage(pkg: LiteralPackage) { const { source_text_base64: _source, ...retained } = pkg; return retained; }
function manifestShape(value: unknown): value is ExpressionManifest[] {
  return Array.isArray(value) && value.length >= 1 && value.length <= 20 && value.every((entry, index) => closed(entry, "entry_index expression_key entry_sha256 projection_sha256 predecessor_id predecessor_sha256 revision_number") && entry.entry_index === index && hash(entry.expression_key) && hash(entry.entry_sha256) && hash(entry.projection_sha256) && safe(entry.revision_number, 1, 10001) && (entry.revision_number === 1 ? entry.predecessor_id === null && entry.predecessor_sha256 === null : uuid(entry.predecessor_id) && hash(entry.predecessor_sha256))) && new Set(value.map(entry => entry.expression_key)).size === value.length;
}
const RECEIPT_KEYS = "version receipt_id receipt_sha256 actor_user_id actor_grant_id actor_session_version request_key request_sha256 preview_sha256 capture_id package_sha256 package_canonical_json request_canonical_json preview_canonical_json receipt_canonical_json expression_count expression_manifest count_scope replayed dry_run pending_ledger_written status scientific_acceptance canonical_promotions selected_result_association public_content_release";
async function literalReceiptProof(value: unknown): Promise<ExpressionReceipt | null> {
  try {
    requireLiteral(closed(value, RECEIPT_KEYS) && value.version === LITERAL_INTAKE_VERSION && uuid(value.receipt_id) && hash(value.receipt_sha256) && uuid(value.actor_user_id) && uuid(value.actor_grant_id) && safe(value.actor_session_version) && fieldCaseText(value.request_key) && /^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$/.test(value.request_key as string) && hash(value.request_sha256) && hash(value.preview_sha256) && uuid(value.capture_id) && hash(value.package_sha256) && manifestShape(value.expression_manifest) && value.expression_count === value.expression_manifest.length && value.count_scope === "source_expression_revisions_not_independent_experiments" && typeof value.replayed === "boolean" && typeof value.dry_run === "boolean" && value.pending_ledger_written === !value.dry_run && (!value.replayed || !value.dry_run) && value.status === "pending" && value.scientific_acceptance === false && value.canonical_promotions === 0 && value.selected_result_association === "unestablished" && value.public_content_release === false);
    const receipt = value as unknown as ExpressionReceipt;
    const pkg = await literalCanonicalProof(receipt.package_canonical_json, receipt.package_sha256, 131072); requireLiteral(retainedLiteralShape(pkg) && pkg.expressions.length === receipt.expression_count);
    const request = await literalCanonicalProof(receipt.request_canonical_json, receipt.request_sha256, 4096); requireLiteral(equal(request, { version: LITERAL_INTAKE_VERSION, package_sha256: receipt.package_sha256 }));
    const actor = { actor_user_id: receipt.actor_user_id, actor_grant_id: receipt.actor_grant_id, actor_session_version: receipt.actor_session_version };
    const preview = await literalCanonicalProof(receipt.preview_canonical_json, receipt.preview_sha256, 32768);
    requireLiteral(equal(preview, { version: LITERAL_INTAKE_VERSION, request_key: receipt.request_key, request_sha256: receipt.request_sha256, actor, manifest: receipt.expression_manifest }));
    const body = await literalCanonicalProof(receipt.receipt_canonical_json, receipt.receipt_sha256);
    requireLiteral(equal(body, { id: receipt.receipt_id, ...actor, request_key: receipt.request_key, request_sha256: receipt.request_sha256, preview_sha256: receipt.preview_sha256, capture_id: receipt.capture_id, package_json: receipt.package_canonical_json, package_sha256: receipt.package_sha256, expression_count: receipt.expression_count, expression_manifest: receipt.expression_manifest }));
    for (const [index, entry] of pkg.expressions.entries()) {
      const pin = receipt.expression_manifest[index]; requireLiteral(pin.entry_sha256 === await expressionSha(expressionCanonical(entry)));
      requireLiteral(entry.predecessor === null ? pin.revision_number === 1 && pin.predecessor_id === null && pin.predecessor_sha256 === null : pin.revision_number === entry.predecessor.revision_number + 1 && pin.predecessor_id === entry.predecessor.revision_id && pin.predecessor_sha256 === entry.predecessor.record_sha256);
    }
    return receipt;
  } catch { return null; }
}
export async function knownLiteralExpressionReceipt(value: unknown, cap: ExpressionCapabilities, ref: LiteralSourceRecovery, stage: "preview" | "commit" | "outcome", prepared: LiteralPrepared | null = null): Promise<ExpressionReceipt | null> {
  const receipt = await literalReceiptProof(value); if (!receipt || receipt.actor_user_id !== cap.actor_user_id || receipt.actor_user_id !== ref.actorId || receipt.request_key !== ref.requestKey || receipt.request_sha256 !== ref.requestSha || receipt.package_sha256 !== ref.packageSha || receipt.package_canonical_json !== ref.packageCanonical) return null;
  if (stage !== "preview" && (!hash(ref.previewSha) || receipt.preview_sha256 !== ref.previewSha || expressionCanonical(receipt.expression_manifest) !== ref.manifestCanonical || receipt.dry_run)) return null;
  if (stage !== "preview" && (!uuid(ref.receiptId) || !hash(ref.receiptSha) || !uuid(ref.captureId) || receipt.receipt_id !== ref.receiptId || receipt.receipt_sha256 !== ref.receiptSha || receipt.capture_id !== ref.captureId)) return null;
  if (stage === "preview" && !receipt.replayed && !receipt.dry_run || stage === "outcome" && !receipt.replayed) return null;
  if (!receipt.replayed && (receipt.actor_session_version !== cap.session_version || receipt.actor_grant_id !== cap.curator_grant_id)) return null;
  if (prepared) { if (prepared.projections.length !== receipt.expression_count) return null; for (const [index, pin] of receipt.expression_manifest.entries()) if (pin.expression_key !== prepared.projections[index].expression_key || pin.entry_sha256 !== await expressionSha(expressionCanonical(prepared.package.expressions[index])) || pin.projection_sha256 !== await expressionSha(expressionCanonical(prepared.projections[index]))) return null; }
  return receipt;
}
export function literalExpressionRecovery(prepared: LiteralPrepared, cap: ExpressionCapabilities, requestKey: string): LiteralSourceRecovery {
  return { actorId: cap.actor_user_id, requestKey, requestSha: prepared.requestSha, packageSha: prepared.packageSha, previewSha: "", manifestCanonical: "", packageCanonical: expressionCanonical(retainedLiteralPackage(prepared.package)), receiptId: "", receiptSha: "", captureId: "" };
}

export type LiteralExpressionPage = { version: string; total: number; offset: number; limit: number; count_scope: string; expressions: LiteralSourceRevision[]; scientific_acceptance: false; canonical_promotions: 0 };
export type LiteralExpressionFilters = { field?: string; sourceId?: string };
function literalProjectionShape(v: unknown): v is LiteralProjection { return row(v) && v.profile === LITERAL_PROFILE && includes(LITERAL_CASE_FIELDS, v.field_id) && v.field_role === LITERAL_ROLES[v.field_id] && row(v.window) && typeof v.window.raw_label === "string" && Array.from(v.window.raw_label).length <= 4096; }
async function literalProjectionBinding(p: LiteralProjection, entry: LiteralEntry, source: SourceMetadata) {
  try {
    // Read DTOs retain selected source text, not full fragment bytes. Check every selected
    // span and overlapping character independently; full-byte SHA is verified at prepare.
    const selections = [...entry.window.label_spans, ...entry.subject.sample_label_spans, ...entry.model_spans, ...entry.origin_basis.spans];
    const size = Math.max(...selections.map(s => s.end)); requireLiteral(size <= 131072); const chars = Array<string>(size).fill("");
    async function place(raw: string | null, spans: ExpressionSpan[]) {
      requireLiteral(spans.length === 0 ? raw === null : typeof raw === "string"); if (!spans.length) return;
      const values = Array.from(raw!); requireLiteral(values.length === spans.reduce((n, s) => n + s.end - s.start, 0)); let at = 0;
      for (const span of spans) { const part = values.slice(at, at + span.end - span.start); requireLiteral(await expressionSha(part.join("")) === span.sha256); for (const [i, c] of part.entries()) { const position = span.start+i; requireLiteral(chars[position] === "" || chars[position] === c); chars[position] = c; } at += part.length; }
    }
    await place(p.window.raw_label, entry.window.label_spans); await place(p.subject.sample_label, entry.subject.sample_label_spans); await place(p.model, entry.model_spans); await place(p.origin_basis.retained_text, entry.origin_basis.spans);
    return equal(p, await literalProjection(source, chars, entry));
  } catch { return false; }
}
const REVISION_KEYS = "id record_sha256 expression_key revision_canonical_json entry_index source_entry_sha256 import_receipt_id import_receipt_sha256 import_receipt revision_number predecessor_id predecessor_sha256 projection_sha256 projection_canonical_json projection source_entry is_expression_head capture";
export async function knownLiteralSourceRevision(value: unknown, detailId?: string, expectedRecordSha?: string): Promise<LiteralSourceRevision | null> {
  try {
    requireLiteral(closed(value, detailId ? `version ${REVISION_KEYS}` : REVISION_KEYS) && (!detailId || value.version === LITERAL_INTAKE_VERSION && value.id === detailId) && uuid(value.id) && hash(value.record_sha256) && (!expectedRecordSha || value.record_sha256 === expectedRecordSha) && hash(value.expression_key) && safe(value.entry_index, 0, 19) && hash(value.source_entry_sha256) && uuid(value.import_receipt_id) && hash(value.import_receipt_sha256) && safe(value.revision_number, 1, 10001) && (value.revision_number === 1 ? value.predecessor_id === null && value.predecessor_sha256 === null : uuid(value.predecessor_id) && hash(value.predecessor_sha256)) && hash(value.projection_sha256) && literalProjectionShape(value.projection) && literalEntry(value.source_entry) && typeof value.is_expression_head === "boolean");
    const revision = value as unknown as LiteralSourceRevision, capture = await knownSourceCapture(revision.capture); requireLiteral(capture);
    requireLiteral(equal(await literalCanonicalProof(revision.projection_canonical_json, revision.projection_sha256, 32768), revision.projection));
    const body = await literalCanonicalProof(revision.revision_canonical_json, revision.record_sha256, 65536);
    requireLiteral(closed(body, "id actor_user_id actor_grant_id actor_session_version import_receipt_id import_receipt_sha256 capture_id entry_index entry_sha256 expression_key field_id revision_number predecessor_id predecessor_sha256 projection_json projection_sha256") && uuid(body.actor_user_id) && uuid(body.actor_grant_id) && safe(body.actor_session_version));
    requireLiteral(equal(body, { id: revision.id, actor_user_id: body.actor_user_id, actor_grant_id: body.actor_grant_id, actor_session_version: body.actor_session_version, import_receipt_id: revision.import_receipt_id, import_receipt_sha256: revision.import_receipt_sha256, capture_id: capture.id, entry_index: revision.entry_index, entry_sha256: revision.source_entry_sha256, expression_key: revision.expression_key, field_id: revision.projection.field_id, revision_number: revision.revision_number, predecessor_id: revision.predecessor_id, predecessor_sha256: revision.predecessor_sha256, projection_json: revision.projection_canonical_json, projection_sha256: revision.projection_sha256 }));
    requireLiteral(revision.expression_key === revision.projection.expression_key && revision.source_entry_sha256 === await expressionSha(expressionCanonical(revision.source_entry)) && await literalProjectionBinding(revision.projection, revision.source_entry, capture.source));
    requireLiteral(revision.source_entry.predecessor === null ? revision.revision_number === 1 : revision.source_entry.predecessor.revision_id === revision.predecessor_id && revision.source_entry.predecessor.record_sha256 === revision.predecessor_sha256 && revision.source_entry.predecessor.revision_number + 1 === revision.revision_number);
    if (detailId) {
      const receipt = await literalReceiptProof(revision.import_receipt); requireLiteral(receipt && !receipt.dry_run && receipt.receipt_id === revision.import_receipt_id && receipt.receipt_sha256 === revision.import_receipt_sha256 && receipt.capture_id === capture.id && receipt.actor_user_id === body.actor_user_id && receipt.actor_grant_id === body.actor_grant_id && receipt.actor_session_version === body.actor_session_version);
      const pkg = parseExpressionJson(receipt.package_canonical_json) as Omit<LiteralPackage, "source_text_base64">;
      const pin = receipt.expression_manifest[revision.entry_index]; requireLiteral(pin && pin.expression_key === revision.expression_key && pin.entry_sha256 === revision.source_entry_sha256 && pin.projection_sha256 === revision.projection_sha256 && pin.predecessor_id === revision.predecessor_id && pin.predecessor_sha256 === revision.predecessor_sha256 && pin.revision_number === revision.revision_number && equal(pkg.expressions[revision.entry_index], revision.source_entry) && equal(pkg.source, capture.source) && pkg.source_content_sha256 === capture.source_content_sha256);
    } else requireLiteral(revision.import_receipt === null);
    return revision;
  } catch { return null; }
}
export async function knownLiteralExpressionPage(value: unknown, offset: number, limit: number, filters: LiteralExpressionFilters = {}): Promise<LiteralExpressionPage | null> {
  if (!safe(offset, 0, 10000) || !safe(limit, 1, 8) || !closed(value, "version total offset limit count_scope expressions scientific_acceptance canonical_promotions") || value.version !== LITERAL_INTAKE_VERSION || !safe(value.total) || value.offset !== offset || value.limit !== limit || value.count_scope !== "current_pending_expression_heads_not_experiments_or_verified_properties" || value.scientific_acceptance !== false || value.canonical_promotions !== 0 || !Array.isArray(value.expressions) || value.expressions.length > limit || value.expressions.length !== Math.min(limit, Math.max(0, value.total - offset))) return null;
  const items = await Promise.all(value.expressions.map(item => knownLiteralSourceRevision(item)));
  if (items.some(item => !item || !item.is_expression_head || filters.field && item.projection.field_id !== filters.field || filters.sourceId && item.capture.source.source_id !== filters.sourceId) || new Set(items.map(item => item?.expression_key)).size !== items.length) return null;
  return value as unknown as LiteralExpressionPage;
}

const PREPARE_KEYS = ["version", "material_id", "target", "candidate_id", "extractor_version", "chunk_id", "source_content_sha256", "retained_result_id", "retained_record_sha256"];
export function knownLiteralPrepareCapabilities(v: unknown, actor: string): LiteralCaseCapabilities | null {
  if (!closed(v, `version profile prepare_request_keys field_cases scope ${AUTH_KEYS}`) || v.version !== LITERAL_PREPARE_VERSION || v.profile !== LITERAL_PROFILE || v.scope !== "private_pending_prepare" || !equal(v.prepare_request_keys, [...PREPARE_KEYS].sort()) || !authority(v)) return null;
  return knownLiteralCaseCapabilities(v.field_cases, actor);
}
function literalRawText(v: unknown, max: number): v is string { return typeof v === "string" && Array.from(v).length > 0 && Array.from(v).length <= max && !v.includes("\0") && !Array.from(v).some(c => c.length === 1 && c.charCodeAt(0) >= 0xd800 && c.charCodeAt(0) <= 0xdfff); }
/** Public metadata is used only to choose selectors. The prepare endpoint rereads original bytes. */
export function literalCandidates(report: MaterialEnrichmentReport, materialId: string, context: LiteralCaseContext): LiteralCandidate[] | null {
  if (report.version !== "materials-enrichment/1.0.0" || report.extractor_version !== LITERAL_EXTRACTOR_VERSION || report.scientific_acceptance !== false || report.database_changed !== false || !Array.isArray(report.candidates) || report.candidates.length > 512 || context.target.material_id !== materialId || !context.eligibility.eligible || !context.closure.legacy_result_id || !context.closure.retained_record_sha256) return null;
  const result: LiteralCandidate[] = [];
  for (const v of report.candidates) {
    if (!row(v) || !includes(LITERAL_CASE_FIELDS, v.field)) continue;
    if (v.version !== "materials-enrichment/1.0.0" || v.extractor_version !== LITERAL_EXTRACTOR_VERSION || v.material_id !== materialId || v.disposition !== "pending" || v.quantity !== null || !["scientific_acceptance", "ml_training_approved", "public_release", "database_changed", "source_content_checked", "material_state_reviewed"].every(k => v[k] === false) || typeof v.candidate_id !== "string" || !/^enrichment:[a-f0-9]{64}$/.test(v.candidate_id) || !row(v.subject) || v.subject.identity_basis !== "exact_formula_local" || !row(v.source) || !fieldCaseText(v.source.capture_id, 200) || !hash(v.source.content_sha256) || !fieldCaseText(v.source.source_revision) || !fieldCaseText(v.source.paper_id, 100) || v.source.paper_id !== context.closure.paper_id || !row(v.source_value) || v.source_value.normalization !== "none" || v.source_value.role !== LITERAL_ROLES[v.field] || !literalRawText(v.source_value.raw_value, 2000) || !literalRawText(v.source_value.field_cue, 200) || v.source_value.raw_unit !== null && !literalRawText(v.source_value.raw_unit, 120) || v.source_value.raw_uncertainty !== null && !literalRawText(v.source_value.raw_uncertainty, 200) || !Array.isArray(v.source_value.qualifiers) || !v.source_value.qualifiers.every(q => includes(QUALIFIERS, q)) || !Array.isArray(v.retained_result_refs) || v.retained_result_refs.length > 5000) return null;
    const refs = v.retained_result_refs.map(ref => row(ref) && fieldCaseText(ref.result_id, 160) && hash(ref.record_sha256) ? { resultId: ref.result_id, recordSha: ref.record_sha256 } : null);
    if (refs.some(ref => ref === null)) return null;
    if (!refs.some(ref => ref!.resultId === context.closure.legacy_result_id && ref!.recordSha === context.closure.retained_record_sha256)) continue;
    result.push({ candidateId: v.candidate_id, field: v.field, rawValue: v.source_value.raw_value, role: v.source_value.role as string, rawUnit: v.source_value.raw_unit as string | null, rawUncertainty: v.source_value.raw_uncertainty as string | null, fieldCue: v.source_value.field_cue, qualifiers: v.source_value.qualifiers as string[], chunkId: v.source.capture_id, contentSha: v.source.content_sha256, resultRefs: refs as { resultId: string; recordSha: string }[], sourceRevision: v.source.source_revision, paperId: v.source.paper_id });
  }
  return new Set(result.map(c => c.candidateId)).size === result.length ? result : null;
}
export function literalPrepareRequest(context: LiteralCaseContext, candidate: LiteralCandidate): LiteralPrepareRequest {
  return { version: LITERAL_PREPARE_VERSION, material_id: context.target.material_id, target: context.target, candidate_id: candidate.candidateId, extractor_version: LITERAL_EXTRACTOR_VERSION, chunk_id: candidate.chunkId, source_content_sha256: candidate.contentSha, retained_result_id: context.closure.legacy_result_id!, retained_record_sha256: context.closure.retained_record_sha256! };
}
export async function knownLiteralPrepare(v: unknown, cap: LiteralCaseCapabilities, context: LiteralCaseContext, candidate: LiteralCandidate, request: LiteralPrepareRequest): Promise<LiteralPrepare | null> {
  try {
    requireLiteral(closed(v, `version profile status actor_user_id session_version package package_sha256 projection_sha256 target_operation context_canonical_json pins source_origin pending_ledger_written ${AUTH_KEYS}`) && v.version === LITERAL_PREPARE_VERSION && v.profile === LITERAL_PROFILE && v.status === "prepared_pending" && v.actor_user_id === cap.actor_user_id && v.session_version === cap.session_version && v.context_canonical_json === context.context_canonical_json && v.pending_ledger_written === false && authority(v) && closed(v.source_origin, "chunk_kind evidence_revision_id publication_revision_verified source_rights_verified") && includes(["original_passage", "abstract"], v.source_origin.chunk_kind) && uuid(v.source_origin.evidence_revision_id) && v.source_origin.publication_revision_verified === false && v.source_origin.source_rights_verified === false);
    const { version: _version, material_id: _material, target: _target, ...pins } = request;
    requireLiteral(equal(v.pins, pins) && knownLiteralCaseRequest(v.target_operation) && v.target_operation.operation === "target" && v.target_operation.payload.field_id === candidate.field && equal(v.target_operation.payload.target, context.target));
    const verified = await compileLiteralPackage(v.package); requireLiteral(verified.packageSha === v.package_sha256 && verified.package.expressions.length === 1 && verified.package.source_content_sha256 === request.source_content_sha256 && verified.package.source.revision === candidate.sourceRevision && verified.package.source.source_id === "retained-chunk:" + await expressionSha(expressionCanonical(request.chunk_id)) && verified.package.source.kind === "primary_paper");
    const p = verified.projections[0]; requireLiteral(await expressionSha(expressionCanonical(p)) === v.projection_sha256 && p.field_id === candidate.field && p.value.raw_value === candidate.rawValue && p.value.raw_unit === candidate.rawUnit && p.value.raw_uncertainty === candidate.rawUncertainty && p.value.field_cue === candidate.fieldCue && p.value.role === candidate.role && equal(p.value.qualifiers, candidate.qualifiers) && p.locator.member === request.chunk_id);
    return { ...v, verified } as unknown as LiteralPrepare;
  } catch { return null; }
}
export function literalRoleLabel(role: string): string { return ({ reported_property: "Reported property", study_extent: "Study extent", measurement_limit: "Measurement limit", reported_order_transition: "Reported order transition" } as Record<string, string>)[role] ?? "Unverified role"; }

export const LITERAL_RECOVERY_VERSION = "material-literal-save-identity/1.0.0";
type StoredBase = { version: string; actorId: string; requestKey: string; requestSha: string; previewSha: string; receiptId: string; receiptSha: string };
export type LiteralStoredIdentity = StoredBase & ({ kind: "source"; packageSha: string; captureId: string; manifestSha: string } | { kind: "case"; operation: LiteralCaseRequest["operation"]; targetContextSha: string; fieldId: string; chainKey: string | null });
export type LiteralStorageRead = { status: "empty" } | { status: "blocked" } | { status: "pending"; identity: LiteralStoredIdentity };
export type LiteralSaveConfirmation = { kind: "source" | "case"; receiptId: string; receiptSha: string; requestKey: string };
export function literalRecoveryStorageKey(actor: string): string { requireLiteral(uuid(actor)); return `sclib:literal-save:${actor}`; }
export function knownLiteralStoredIdentity(value: unknown, actor: string): LiteralStoredIdentity | null {
  if (!row(value) || !closed(value, value.kind === "source" ? "version actorId requestKey requestSha previewSha receiptId receiptSha kind packageSha captureId manifestSha" : "version actorId requestKey requestSha previewSha receiptId receiptSha kind operation targetContextSha fieldId chainKey") || value.version !== LITERAL_RECOVERY_VERSION || value.actorId !== actor || !uuid(actor) || !fieldCaseText(value.requestKey) || !/^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$/.test(value.requestKey) || !hash(value.requestSha) || !hash(value.previewSha) || !uuid(value.receiptId) || !hash(value.receiptSha)) return null;
  if (value.kind === "source") return hash(value.packageSha) && uuid(value.captureId) && hash(value.manifestSha) ? value as unknown as LiteralStoredIdentity : null;
  return value.kind === "case" && includes(["target", "association", "attempt"], value.operation) && hash(value.targetContextSha) && includes(LITERAL_CASE_FIELDS, value.fieldId) && (value.operation === "target" ? value.chainKey === null : value.operation === "association" ? hash(value.chainKey) : uuid(value.chainKey)) ? value as unknown as LiteralStoredIdentity : null;
}
/** Minimal pins only. Unavailable or malformed storage is never an empty ledger. */
export function readLiteralRecovery(actor: string): LiteralStorageRead {
  try { const raw = sessionStorage.getItem(literalRecoveryStorageKey(actor)); if (raw === null) return { status: "empty" }; if (new TextEncoder().encode(raw).length > 4096) return { status: "blocked" }; const identity = knownLiteralStoredIdentity(parseExpressionJson(raw), actor); return identity ? { status: "pending", identity } : { status: "blocked" }; } catch { return { status: "blocked" }; }
}
/** Must succeed, including exact read-back, before a POST. Never overwrite an unresolved actor. */
export function storeLiteralRecovery(identity: LiteralStoredIdentity): boolean {
  try { if (!knownLiteralStoredIdentity(identity, identity.actorId) || readLiteralRecovery(identity.actorId).status !== "empty") return false; const raw = expressionCanonical(identity); if (new TextEncoder().encode(raw).length > 4096) return false; const key = literalRecoveryStorageKey(identity.actorId); sessionStorage.setItem(key, raw); return sessionStorage.getItem(key) === raw && readLiteralRecovery(identity.actorId).status === "pending"; } catch { return false; }
}
/** Called only after a verified commit/outcome. A different or inaccessible identity stays held. */
export function clearLiteralRecovery(identity: LiteralStoredIdentity): boolean {
  try { const current = readLiteralRecovery(identity.actorId); if (current.status !== "pending" || !equal(current.identity, identity)) return false; const key = literalRecoveryStorageKey(identity.actorId); sessionStorage.removeItem(key); return sessionStorage.getItem(key) === null; } catch { return false; }
}
export async function literalStoredSourceIdentity(ref: LiteralSourceRecovery): Promise<LiteralStoredIdentity> {
  const result: LiteralStoredIdentity = { version: LITERAL_RECOVERY_VERSION, kind: "source", actorId: ref.actorId, requestKey: ref.requestKey, requestSha: ref.requestSha, previewSha: ref.previewSha, receiptId: ref.receiptId, receiptSha: ref.receiptSha, packageSha: ref.packageSha, captureId: ref.captureId, manifestSha: await expressionSha(ref.manifestCanonical) }; requireLiteral(knownLiteralStoredIdentity(result, ref.actorId)); return result;
}
export function literalStoredCaseIdentity(ref: LiteralCaseRecovery): LiteralStoredIdentity {
  const result: LiteralStoredIdentity = { version: LITERAL_RECOVERY_VERSION, kind: "case", actorId: ref.actorId, requestKey: ref.requestKey, requestSha: ref.requestSha, previewSha: ref.previewSha, receiptId: ref.receiptId, receiptSha: ref.receiptSha, operation: ref.operation, targetContextSha: ref.targetContextSha, fieldId: ref.fieldId, chainKey: ref.chainKey }; requireLiteral(knownLiteralStoredIdentity(result, ref.actorId)); return result;
}
/** Independently validate the original saved GET proof without retaining request/payload/source text. */
export async function knownLiteralStoredOutcome(value: unknown, actor: string, identity: LiteralStoredIdentity): Promise<LiteralSaveConfirmation | null> {
  try {
    requireLiteral(knownLiteralStoredIdentity(identity, actor));
    if (identity.kind === "source") {
      const receipt = await literalReceiptProof(value); requireLiteral(receipt && receipt.actor_user_id === actor && receipt.request_key === identity.requestKey && receipt.request_sha256 === identity.requestSha && receipt.preview_sha256 === identity.previewSha && receipt.receipt_id === identity.receiptId && receipt.receipt_sha256 === identity.receiptSha && receipt.capture_id === identity.captureId && receipt.package_sha256 === identity.packageSha && await expressionSha(expressionCanonical(receipt.expression_manifest)) === identity.manifestSha && receipt.replayed === true && receipt.dry_run === false && receipt.pending_ledger_written === true);
    } else {
      requireLiteral(closed(value, `version receipt_id receipt_sha256 operation target_id actor_user_id actor_grant_id actor_session_version request_key request_sha256 preview_sha256 request_canonical_json preview_canonical_json receipt_canonical_json replayed dry_run pending_ledger_written ${AUTH_KEYS}`) && value.version === LITERAL_CASE_VERSION && value.actor_user_id === actor && value.operation === identity.operation && value.request_key === identity.requestKey && value.request_sha256 === identity.requestSha && value.preview_sha256 === identity.previewSha && value.receipt_id === identity.receiptId && value.receipt_sha256 === identity.receiptSha && value.replayed === true && value.dry_run === false && value.pending_ledger_written === true && authority(value));
      const body = await rowProof(value.receipt_canonical_json, identity.receiptSha); requireLiteral(body && body.id === identity.receiptId && body.operation === identity.operation && body.actor_user_id === actor && body.context_sha256 === identity.targetContextSha && body.field_id === identity.fieldId && body.chain_key === identity.chainKey && value.target_id === (identity.operation === "target" ? body.id : body.target_id) && value.request_canonical_json === body.request_json && value.preview_canonical_json === body.preview_json && ["actor_user_id", "actor_grant_id", "actor_session_version", "request_key", "request_sha256", "preview_sha256"].every(key => value[key] === body[key]));
    }
    return { kind: identity.kind, receiptId: identity.receiptId, receiptSha: identity.receiptSha, requestKey: identity.requestKey };
  } catch { return null; }
}
