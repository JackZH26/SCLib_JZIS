/** Explicit table profile. Receipt checks mirror the frozen literal protocol;
 * table projections independently bind the original grid, subject column and row unit.
 * The literal module remains closed to this version. */
import { expressionCanonical, expressionSha, parseExpressionJson } from "./source-expressions";
import { FIELD_CASE_VERSION, fieldCaseText, fieldCaseReason } from "./material-field-cases";
import { knownSourceCapture, expressionSourceHref, type ExpressionSpan, type ExpressionRequest, type ExpressionPackage, type ExpressionProjection, type ExpressionManifest, type ExpressionReceipt, type ExpressionCapabilities, type SourceCapture, type SourceMetadata, type SourceRevision, type ExpressionRecovery } from "./source-expressions";

export const TABLE_PROFILE = "material-table-field/1.0.0";
export const TABLE_PACKAGE_VERSION = "source-expression-package/2.2.0";
export const TABLE_INTAKE_VERSION = "source-expression-intake/2.2.0";
export const TABLE_REGISTRY_SHA = "98842a70856a2bd71f024dcae309732bd2707f9f36f64042b01ad84b91bbdc98";
export const TABLE_ROLES: Record<string, string> = { electronic_specific_heat_coefficient_source_value: "reported_property", debye_temperature_source_value: "reported_property" };
const TABLE_LABELS: Record<string, string> = { electronic_specific_heat_coefficient_source_value: "Electronic specific heat coefficient", debye_temperature_source_value: "Debye temperature" };
const QUALIFIERS = ["cited_negative_or_qualified_context", "model_or_calculation_context", "fit_or_estimate_context", "inference_or_unmeasured_context"];
type TableEntry = ExpressionRequest & { profile: string; field_role: string; cue_spans: ExpressionSpan[]; uncertainty_spans: ExpressionSpan[]; qualifiers: string[]; table_binding: TableGrid };
export type TablePackage = Omit<ExpressionPackage, "expressions"> & { profile: string; expressions: TableEntry[] };
export type TableValue = { status: "raw_literal"; raw_value: string; raw_amount: string; raw_unit: string | null; raw_uncertainty: string | null; quantity: null; normalization: "none"; unit_basis: "table_row_label"; field_cue: string; role: string; qualifiers: string[]; value_span: Span; unit_span: Span | null; cue_span: Span; uncertainty_span: Span | null };
type Span = { char_start: number; char_end: number; text_sha256: string };
export type TableGrid = { version: "source-table-grid/1.0.0"; caption_spans: ExpressionSpan[]; header_spans: ExpressionSpan[]; rows: ExpressionSpan[][]; row_index: number; column_index: number };
export type TableBinding = { version: "source-table-grid/1.0.0"; grid_sha256: string; verification: "retained_spans_checked_layout_declared"; row_index_0_based: number; column_index_0_based: number; row_count: number; column_count: number; raw_caption: string | null; raw_row_label: string; header_span: Span; row_label_span: Span; caption_span: Span | null };

function tableGridShape(v: unknown): v is TableGrid {
  const cell = (s: unknown, bound = 1200) => closed(s, "start end sha256") && safe(s.start, 0, 131072) && safe(s.end, 1, 131072) && s.end > s.start && s.end - s.start <= bound && hash(s.sha256);
  if (!closed(v, "version caption_spans header_spans rows row_index column_index") || v.version !== "source-table-grid/1.0.0" || !Array.isArray(v.caption_spans) || v.caption_spans.length > 1 || !v.caption_spans.every(s => cell(s, 1000)) || !Array.isArray(v.header_spans) || v.header_spans.length < 2 || v.header_spans.length > 16 || !v.header_spans.every(s => cell(s)) || !Array.isArray(v.rows) || v.rows.length < 1 || v.rows.length > 32) return false;
  const columns = v.header_spans.length;
  return v.rows.every(r => Array.isArray(r) && r.length === columns && r.every(s => cell(s))) && safe(v.row_index, 0, v.rows.length - 1) && safe(v.column_index, 1, columns - 1);
}

async function tableBinding(chars: string[], entry: TableEntry, offset: number): Promise<TableBinding> {
  const g = entry.table_binding, window = entry.window.label_spans[0];
  requireTable(tableGridShape(g));
  let end = window.start;
  for (const cell of [...g.caption_spans, ...g.header_spans, ...g.rows.flat()]) {
    requireTable(cell.start >= end && cell.end <= window.end);
    await selection(chars, [cell], offset); end = cell.end;
  }
  const header = g.header_spans[g.column_index], row = g.rows[g.row_index], label = row[0];
  requireTable(equal(entry.subject.formula_spans, [header]) && entry.subject.sample_label_spans.length === 0 && equal(entry.value_spans, [row[g.column_index]]));
  const unit = entry.unit_spans[0], cue = entry.cue_spans[0];
  requireTable(entry.unit_spans.length === 1 && label.start <= unit.start && unit.end <= label.end && label.start <= cue.start && cue.end <= label.end && cue.end <= unit.start);
  requireTable(entry.locator.row === g.row_index + 1 && entry.locator.column === g.column_index + 1 && typeof entry.locator.table === "string" && entry.locator.table.length > 0);
  return { version: g.version, grid_sha256: await expressionSha(expressionCanonical(g)), verification: "retained_spans_checked_layout_declared", row_index_0_based: g.row_index, column_index_0_based: g.column_index, row_count: g.rows.length, column_count: g.header_spans.length, raw_caption: await selection(chars, g.caption_spans, offset) || null, raw_row_label: await selection(chars, [label], offset), header_span: spanProjection(header)!, row_label_span: spanProjection(label)!, caption_span: spanProjection(g.caption_spans[0]) };
}
export type TableProjection = Omit<ExpressionProjection, "value"> & { profile: string; field_role: string; value: TableValue; table_binding: TableBinding; field_interpretation_reviewed: false; public_content_release: false; ml_training_approved: false };
export type TableSourceRevision = Omit<SourceRevision, "projection" | "source_entry"> & { projection: TableProjection; source_entry: TableEntry };
export type TablePrepared = { package: TablePackage; sourceText: string; retainedBytes: number; packageSha: string; requestSha: string; projections: TableProjection[] };
export type TableSourceRecovery = ExpressionRecovery & { receiptId: string; receiptSha: string; captureId: string };

export const TABLE_CASE_VERSION = "material-field-case/1.2.0";
export const TABLE_CASE_REQUEST_VERSION = "material-field-case-operation/1.2.0";
export const TABLE_CASE_PAGE_SIZE = 8;
export const TABLE_CASE_FIELDS = ["electronic_specific_heat_coefficient_source_value", "debye_temperature_source_value"] as const;
export const TABLE_CASE_OUTCOMES = ["pending_expression_available", "source_unavailable", "not_found_in_checked_scope", "requires_interpretation", "association_unresolved", "current_source_held", "target_changed", "external_reference_available", "needs_new_calculation_or_experiment"] as const;
export const TABLE_CASE_REASONS = [...TABLE_CASE_OUTCOMES, "bounded_scope_only", "source_identity_unresolved", "source_identity_proposed", "publication_currentness_unverified", "publication_rights_unverified", "expression_superseded", "target_fingerprint_changed", "material_not_currently_eligible", "source_lifecycle_held", "native_source_binding_unavailable", "unit_requires_review", "value_requires_review", "different_source_window", "different_model", "sample_state_unestablished", "no_expression_available"] as const;
export type TargetKind = "retained_result" | "tc_claim" | "event_property";
export type TargetSelector = { kind: TargetKind; material_id: string; record_index: number | null; entity_id: string | null; expected_context_sha256: string };
export type TableCaseAuthority = { scientific_acceptance: false; canonical_promotions: 0; selected_result_association: "unestablished"; sample_identity_established: false; phase_identity_established: false; public_content_release: false; ml_training_approved: false };
export type TableCaseEligibility = { eligible: boolean; reason_codes: string[] };
export type TableCaseCapabilities = TableCaseAuthority & { profile: string; field_request_versions: Record<string, string>; read_hold_reason_codes: string[]; version: string; request_version: string; actor_user_id: string; session_version: number; curator_grant_id: string | null; can_write: boolean; field_ids: string[]; outcomes: string[]; reason_codes: string[]; expression_field_map: Record<string, string | null>; max_page_size: number; max_operation_bytes: number };
export type TableCaseClosure = { material_id: string; kind: TargetKind; record_index: number | null; entity_id: string | null; paper_id: string | null; work_id: string | null; event_id: string | null; state_id: string | null; sample_id: string | null; legacy_result_id: string | null; retained_record_sha256: string | null };
export type TableCaseContext = TableCaseAuthority & { version: string; actor_user_id: string; session_version: number; target: TargetSelector; context_canonical_json: string; context_sha256: string; closure: TableCaseClosure; eligibility: TableCaseEligibility };
export type TableCasePredecessor = { id: string; record_sha256: string };
export type TableCaseExpressionPin = { revision_id: string; record_sha256: string };
export type TableCaseTargetPayload = { field_id: string; target: TargetSelector };
export type TableCaseAssociationPayload = { target_id: string; target_sha256: string; expression_revision_id: string; expression_record_sha256: string; source_identity: { paper_id: string | null; work_id: string | null }; action: "propose" | "withdraw"; predecessor: TableCasePredecessor | null };
export type TableCaseAttemptPayload = { target_id: string; target_sha256: string; outcome: string; reason_codes: string[]; checked_scope: { source_ids: string[]; fulltext_checked: boolean; supplement_checked: boolean; scope_label: string }; expression_pins: TableCaseExpressionPin[]; predecessor: TableCasePredecessor | null };
export type TableCaseRequest = { version: string; request_key: string } & ({ operation: "target"; payload: TableCaseTargetPayload } | { operation: "association"; payload: TableCaseAssociationPayload } | { operation: "attempt"; payload: TableCaseAttemptPayload });
export type TableCaseReceipt = TableCaseAuthority & { version: string; receipt_id: string; receipt_sha256: string; operation: TableCaseRequest["operation"]; target_id: string; actor_user_id: string; actor_grant_id: string; actor_session_version: number; request_key: string; request_sha256: string; preview_sha256: string; request_canonical_json: string; preview_canonical_json: string; receipt_canonical_json: string; replayed: boolean; dry_run: boolean; pending_ledger_written: boolean };
export type TableCaseRecovery = { actorId: string; requestKey: string; requestSha: string; requestCanonical: string; previewSha: string; receiptSha: string; receiptId: string; operation: TableCaseRequest["operation"]; targetContextSha: string; fieldId: string; chainKey: string | null };
export type TableCaseEntry = TableCaseAuthority & { id: string; record_sha256: string; record_canonical_json: string; operation: TableCaseRequest["operation"]; payload: TableCaseTargetPayload | TableCaseAssociationPayload | TableCaseAttemptPayload; context_canonical_json: string | null; context_sha256: string; created_at: string; eligibility: TableCaseEligibility; is_head?: boolean; expression?: TableSourceRevision | null; source_identity_status?: "proposed" };
export type TableCaseDetail = TableCaseAuthority & { version: string; actor_user_id: string; session_version: number; target: TableCaseEntry; associations: TableCaseEntry[]; attempts: TableCaseEntry[]; association_total: number; attempt_total: number; association_returned: number; attempt_returned: number; association_omitted: number; attempt_omitted: number; response_truncated: boolean };
export type TableCaseMaterialPage = TableCaseAuthority & { version: string; actor_user_id: string; session_version: number; material_id: string; total: number; offset: number; limit: number; next_offset: number | null; entries: TableCaseDetail[]; eligibility: TableCaseEligibility; expressions_returned: number; expressions_omitted: number; entries_returned: number; entries_omitted: number; response_truncated: boolean };

type Row = Record<string, unknown>;
const AUTHORITY: TableCaseAuthority = { scientific_acceptance: false, canonical_promotions: 0, selected_result_association: "unestablished", sample_identity_established: false, phase_identity_established: false, public_content_release: false, ml_training_approved: false };
const AUTH_KEYS = Object.keys(AUTHORITY).join(" ");
const ROW_KEYS = "id actor_user_id actor_grant_id actor_session_version operation request_key request_json payload request_sha256 preview_json preview_sha256 context_json context_sha256 field_id target_id chain_key predecessor_id predecessor_sha256 expression_revision_id expression_record_sha256";
const HASH = /^[a-f0-9]{64}$/, UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
function row(v: unknown): v is Row { return v !== null && typeof v === "object" && !Array.isArray(v); }
function closed(v: unknown, keys: string): v is Row { const names = keys.split(" "); return row(v) && Object.keys(v).length === names.length && names.every(k => Object.hasOwn(v, k)); }
function safe(v: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): v is number { return typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max; }
function hash(v: unknown): v is string { return typeof v === "string" && HASH.test(v); }
function uuid(v: unknown): v is string { return typeof v === "string" && UUID.test(v); }
export function tableCaseText(v: unknown, max = 160): v is string { return typeof v === "string" && v.trim() === v && Array.from(v).length > 0 && Array.from(v).length <= max && !/[\u0000-\u001f]/.test(v) && !Array.from(v).some(c => c.length === 1 && c.charCodeAt(0) >= 0xd800 && c.charCodeAt(0) <= 0xdfff); }
function includes(values: readonly string[], v: unknown): v is string { return typeof v === "string" && values.includes(v); }
function equal(a: unknown, b: unknown): boolean { if (a === b) return true; if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v, i) => equal(v, b[i])); return row(a) && row(b) && Object.keys(a).length === Object.keys(b).length && Object.keys(a).every(k => Object.hasOwn(b, k) && equal(a[k], b[k])); }
function authority(v: Row) { return Object.entries(AUTHORITY).every(([k, val]) => v[k] === val); }
export const TABLE_READ_HOLD_REASONS = ["literal_capture_superseded", "literal_capture_authority_held", "literal_import_authority_held", "literal_association_authority_held"] as const;
function eligibility(v: unknown, readHolds = true): v is TableCaseEligibility { return closed(v, "eligible reason_codes") && typeof v.eligible === "boolean" && Array.isArray(v.reason_codes) && v.reason_codes.every(x => includes(readHolds ? [...TABLE_CASE_REASONS, ...TABLE_READ_HOLD_REASONS] : TABLE_CASE_REASONS, x)) && new Set(v.reason_codes).size === v.reason_codes.length && v.eligible === (v.reason_codes.length === 0); }
function predecessor(v: unknown) { return v === null || closed(v, "id record_sha256") && uuid(v.id) && hash(v.record_sha256); }
function selector(v: unknown): v is TargetSelector { return closed(v, "kind material_id record_index entity_id expected_context_sha256") && includes(["retained_result", "tc_claim", "event_property"], v.kind) && tableCaseText(v.material_id, 100) && hash(v.expected_context_sha256) && (v.kind === "retained_result" ? safe(v.record_index, 0, 4999) && v.entity_id === null : v.record_index === null && uuid(v.entity_id)); }
export function knownTableCaseRequest(v: unknown): v is TableCaseRequest {
  if (!closed(v, "version request_key operation payload") || v.version !== TABLE_CASE_REQUEST_VERSION || !tableCaseText(v.request_key) || !/^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$/.test(v.request_key) || !includes(["target", "association", "attempt"], v.operation)) return false;
  const p = v.payload;
  if (v.operation === "target") { if (!closed(p, "field_id target") || !includes(TABLE_CASE_FIELDS, p.field_id) || !selector(p.target)) return false; }
  else {
    if (!closed(p, v.operation === "association" ? "target_id target_sha256 expression_revision_id expression_record_sha256 source_identity action predecessor" : "target_id target_sha256 outcome reason_codes checked_scope expression_pins predecessor") || !uuid(p.target_id) || !hash(p.target_sha256) || !predecessor(p.predecessor)) return false;
    if (v.operation === "association") {
      if (!uuid(p.expression_revision_id) || !hash(p.expression_record_sha256) || !includes(["propose", "withdraw"], p.action) || p.action === "withdraw" && p.predecessor === null || !closed(p.source_identity, "paper_id work_id") || !(p.source_identity.paper_id === null || tableCaseText(p.source_identity.paper_id, 100)) || !(p.source_identity.work_id === null || uuid(p.source_identity.work_id))) return false;
    } else {
      const scope = p.checked_scope;
      if (!includes(TABLE_CASE_OUTCOMES, p.outcome) || !Array.isArray(p.reason_codes) || p.reason_codes.length < 1 || p.reason_codes.length > 16 || new Set(p.reason_codes).size !== p.reason_codes.length || !p.reason_codes.every(x => includes(TABLE_CASE_REASONS, x)) || !closed(scope, "source_ids fulltext_checked supplement_checked scope_label") || !Array.isArray(scope.source_ids) || scope.source_ids.length > 8 || new Set(scope.source_ids).size !== scope.source_ids.length || !scope.source_ids.every(x => tableCaseText(x)) || !tableCaseText(scope.scope_label, 500) || typeof scope.fulltext_checked !== "boolean" || typeof scope.supplement_checked !== "boolean" || !scope.source_ids.length && (scope.fulltext_checked || scope.supplement_checked) || !Array.isArray(p.expression_pins) || p.expression_pins.length > 8 || !p.expression_pins.every(pin => closed(pin, "revision_id record_sha256") && uuid(pin.revision_id) && hash(pin.record_sha256)) || new Set(p.expression_pins.map(pin => (pin as Row).revision_id)).size !== p.expression_pins.length || p.outcome === "pending_expression_available" && !p.expression_pins.length) return false;
    }
  }
  try { return new TextEncoder().encode(expressionCanonical(v)).length <= 32768; } catch { return false; }
}
const EXPECTED_MAP = Object.fromEntries(TABLE_CASE_FIELDS.map(field => [field, field]));
export function knownTableCaseCapabilities(v: unknown, actor: string): TableCaseCapabilities | null {
  if (!closed(v, `version request_version actor_user_id session_version curator_grant_id can_write field_ids outcomes reason_codes expression_field_map max_page_size max_operation_bytes profile field_request_versions read_hold_reason_codes ${AUTH_KEYS}`) || v.version !== TABLE_CASE_VERSION || v.request_version !== TABLE_CASE_REQUEST_VERSION || v.profile !== TABLE_PROFILE || v.actor_user_id !== actor || !uuid(v.actor_user_id) || !safe(v.session_version) || typeof v.can_write !== "boolean" || (v.can_write ? !uuid(v.curator_grant_id) : v.curator_grant_id !== null) || !equal(v.field_ids, TABLE_CASE_FIELDS) || !equal(v.outcomes, TABLE_CASE_OUTCOMES) || !equal(v.reason_codes, TABLE_CASE_REASONS) || !equal(v.read_hold_reason_codes, TABLE_READ_HOLD_REASONS) || v.max_page_size !== 8 || v.max_operation_bytes !== 32768 || !authority(v) || !row(v.expression_field_map) || !row(v.field_request_versions)) return null;
  if (!equal(v.expression_field_map, EXPECTED_MAP) || !equal(v.field_request_versions, Object.fromEntries(TABLE_CASE_FIELDS.map(f => [f, TABLE_CASE_REQUEST_VERSION])))) return null;
  return v as unknown as TableCaseCapabilities;
}
async function proof(text: unknown, sha: unknown, maximum = 262144): Promise<Row | null> {
  if (typeof text !== "string" || new TextEncoder().encode(text).length > maximum || !hash(sha) || await expressionSha(text) !== sha) return null;
  try { const parsed = parseExpressionJson(text, false); return row(parsed) ? parsed : null; } catch { return null; }
}
function contextBody(body: unknown, target: TargetSelector) { return closed(body, "kind material_id record_index entity_id material result event state sample") && body.kind === target.kind && body.material_id === target.material_id && body.record_index === target.record_index && body.entity_id === target.entity_id && row(body.material) && body.material.id === target.material_id && row(body.result) && ["event", "state", "sample"].every(k => body[k] === null || row(body[k])) && (target.kind !== "retained_result" || body.event === null && body.state === null && body.sample === null); }
export async function knownTableCaseContext(v: unknown, cap: TableCaseCapabilities, materialId: string, kind: TargetKind, recordIndex: number | null, entityId: string | null): Promise<TableCaseContext | null> {
  try {
    if (!closed(v, `version actor_user_id session_version target context_canonical_json context_sha256 closure eligibility ${AUTH_KEYS}`) || v.version !== FIELD_CASE_VERSION || v.actor_user_id !== cap.actor_user_id || v.session_version !== cap.session_version || !selector(v.target) || v.target.material_id !== materialId || v.target.kind !== kind || v.target.record_index !== recordIndex || v.target.entity_id !== entityId || v.target.expected_context_sha256 !== v.context_sha256 || !eligibility(v.eligibility, false) || !authority(v)) return null;
    const body = await proof(v.context_canonical_json, v.context_sha256, 131072);
    if (!contextBody(body, v.target) || !closed(v.closure, "material_id kind record_index entity_id paper_id work_id event_id state_id sample_id legacy_result_id retained_record_sha256")) return null;
    const c = v.closure;
    if (!["material_id", "kind", "record_index", "entity_id"].every(k => c[k] === (v.target as unknown as Row)[k]) || !(c.paper_id === null || tableCaseText(c.paper_id, 100)) || !["work_id", "event_id", "state_id", "sample_id"].every(k => c[k] === null || uuid(c[k])) || !(c.legacy_result_id === null || tableCaseText(c.legacy_result_id, 200)) || !(c.retained_record_sha256 === null || hash(c.retained_record_sha256))) return null;
    const parsed = body as Row, result = parsed.result as Row;
    if (c.paper_id !== (result.paper_id ?? null) || c.work_id !== (result.work_id ?? null) || !["event", "state", "sample"].every(k => { const child = parsed[k]; return c[k + "_id"] === (row(child) ? child.id : null); })) return null;
    return v as unknown as TableCaseContext;
  } catch { return null; }
}
async function rowProof(text: unknown, sha: unknown): Promise<Row | null> {
  const body = await proof(text, sha, 524288);
  if (!closed(body, ROW_KEYS) || !uuid(body.id) || !uuid(body.actor_user_id) || !uuid(body.actor_grant_id) || !safe(body.actor_session_version) || !includes(TABLE_CASE_FIELDS, body.field_id)) return null;
  const request = await proof(body.request_json, body.request_sha256, 32768);
  if (!knownTableCaseRequest(request) || request.operation !== body.operation || request.request_key !== body.request_key || !equal(request.payload, body.payload)) return null;
  const preview = await proof(body.preview_json, body.preview_sha256, 8192);
  if (!equal(preview, { version: TABLE_CASE_VERSION, actor: { actor_user_id: body.actor_user_id, actor_grant_id: body.actor_grant_id, actor_session_version: body.actor_session_version }, request_sha256: body.request_sha256, receipt_id: body.id, context_sha256: body.context_sha256 })) return null;
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
export function tableCaseRecovery(request: TableCaseRequest, cap: TableCaseCapabilities, requestSha: string, target?: TableCaseEntry, associationChain: string | null = null): TableCaseRecovery {
  const originalTarget = request.operation !== "target" && target?.id === request.payload.target_id && target.record_sha256 === request.payload.target_sha256 ? target : undefined;
  return { actorId: cap.actor_user_id, requestKey: request.request_key, requestSha, requestCanonical: expressionCanonical(request), previewSha: "", receiptSha: "", receiptId: "", operation: request.operation,
    targetContextSha: request.operation === "target" ? request.payload.target.expected_context_sha256 : originalTarget?.context_sha256 ?? "",
    fieldId: request.operation === "target" ? request.payload.field_id : (originalTarget?.payload as TableCaseTargetPayload | undefined)?.field_id ?? "",
    chainKey: request.operation === "target" ? null : request.operation === "attempt" ? request.payload.target_id : associationChain };
}
export async function knownTableCaseReceipt(v: unknown, cap: TableCaseCapabilities, ref: TableCaseRecovery, stage: "preview" | "commit" | "outcome"): Promise<TableCaseReceipt | null> {
  try {
    if (!closed(v, `version receipt_id receipt_sha256 operation target_id actor_user_id actor_grant_id actor_session_version request_key request_sha256 preview_sha256 request_canonical_json preview_canonical_json receipt_canonical_json replayed dry_run pending_ledger_written ${AUTH_KEYS}`) || v.version !== TABLE_CASE_VERSION || v.actor_user_id !== cap.actor_user_id || v.actor_user_id !== ref.actorId || v.operation !== ref.operation || v.request_key !== ref.requestKey || v.request_sha256 !== ref.requestSha || v.request_canonical_json !== ref.requestCanonical || !uuid(v.target_id) || typeof v.replayed !== "boolean" || typeof v.dry_run !== "boolean" || typeof v.pending_ledger_written !== "boolean" || v.pending_ledger_written !== !v.dry_run || !authority(v)) return null;
    const body = await rowProof(v.receipt_canonical_json, v.receipt_sha256);
    if (!body || !hash(ref.targetContextSha) || !includes(TABLE_CASE_FIELDS, ref.fieldId) || body.context_sha256 !== ref.targetContextSha || body.field_id !== ref.fieldId || body.chain_key !== ref.chainKey || v.operation === "association" && !hash(ref.chainKey) || v.receipt_id !== body.id || v.target_id !== (v.operation === "target" ? body.id : body.target_id) || !["actor_user_id", "actor_grant_id", "actor_session_version", "request_key", "request_sha256", "preview_sha256"].every(k => v[k] === body[k]) || v.request_canonical_json !== body.request_json || v.preview_canonical_json !== body.preview_json) return null;
    if (stage === "preview") { if (v.replayed ? v.dry_run : !v.dry_run || v.actor_grant_id !== cap.curator_grant_id || v.actor_session_version !== cap.session_version) return null; }
    else if (v.dry_run || !hash(ref.previewSha) || !hash(ref.receiptSha) || !uuid(ref.receiptId) || v.preview_sha256 !== ref.previewSha || v.receipt_sha256 !== ref.receiptSha || v.receipt_id !== ref.receiptId || stage === "outcome" && !v.replayed || !v.replayed && (v.actor_grant_id !== cap.curator_grant_id || v.actor_session_version !== cap.session_version)) return null;
    return v as unknown as TableCaseReceipt;
  } catch { return null; }
}
const ENTRY_KEYS = `id record_sha256 record_canonical_json operation payload context_canonical_json context_sha256 created_at eligibility ${AUTH_KEYS}`;
export async function knownTableCaseEntry(v: unknown, operation: TableCaseRequest["operation"], target?: TableCaseEntry, original?: TableCaseEntry): Promise<TableCaseEntry | null> {
  try {
    if (!closed(v, ENTRY_KEYS + (operation === "association" ? " is_head expression source_identity_status" : operation === "attempt" ? " is_head" : "")) || v.operation !== operation || !tableCaseText(v.created_at, 50) || !Number.isFinite(Date.parse(v.created_at)) || !eligibility(v.eligibility) || !authority(v) || original && (v.id !== original.id || v.record_sha256 !== original.record_sha256 || v.record_canonical_json !== original.record_canonical_json)) return null;
    const body = await rowProof(v.record_canonical_json, v.record_sha256);
    if (!body || body.id !== v.id || body.operation !== operation || !equal(body.payload, v.payload) || body.context_sha256 !== v.context_sha256 || (operation === "target" ? v.context_canonical_json !== body.context_json : v.context_canonical_json !== null || !target || body.target_id !== target.id || (body.payload as Row).target_sha256 !== target.record_sha256 || body.context_sha256 !== target.context_sha256 || body.context_json !== target.context_canonical_json || body.field_id !== (target.payload as TableCaseTargetPayload).field_id) || operation !== "target" && typeof v.is_head !== "boolean") return null;
    if (operation === "association") {
      if (v.source_identity_status !== "proposed" || v.expression !== null && !v.eligibility.eligible) return null;
      if (v.expression !== null) { const expr = await knownTableSourceRevision(v.expression); if (!expr || expr.id !== body.expression_revision_id || expr.record_sha256 !== body.expression_record_sha256 || !expr.is_expression_head || !v.is_head || (v.payload as TableCaseAssociationPayload).action !== "propose" || !compatibleFieldExpression(body.field_id as string, expr)) return null; if (body.chain_key !== await expressionSha(expressionCanonical([target!.id, expr.expression_key]))) return null; }
    }
    return v as unknown as TableCaseEntry;
  } catch { return null; }
}
export function compatibleFieldExpression(field: string, expr: TableSourceRevision): boolean { const mapped = EXPECTED_MAP[field]; return mapped != null && (field === "tc_criterion" ? expr.projection.field_id === "tc_kelvin" && expr.projection.conditions.some(c => c.field_id === "criterion_statement" && c.role === "reported_result_condition") : expr.projection.field_id === mapped); }
export function tableCaseEntryActor(entry: TableCaseEntry): string | null { try { const body = parseExpressionJson(entry.record_canonical_json, false); return row(body) && uuid(body.actor_user_id) ? body.actor_user_id : null; } catch { return null; } }
export function tableCaseEntryChain(entry: TableCaseEntry): string | null { try { const body = parseExpressionJson(entry.record_canonical_json, false); return row(body) && hash(body.chain_key) ? body.chain_key : null; } catch { return null; } }
/** Display only known retained scalar metadata. No unit conversion, fallback origin or source join. */
export function tableCaseTargetSummary(contextCanonical: string): { label: string; value: string }[] {
  try {
    const body = parseExpressionJson(contextCanonical, false);
    if (!closed(body, "kind material_id record_index entity_id material result event state sample") || !row(body.result)) return [];
    const record = body.kind === "tc_claim" && row(body.result.raw_record) ? body.result.raw_record : body.result;
    const scalar = (keys: string[]) => { for (const key of keys) { const value = record[key]; if (typeof value === "number" && Number.isFinite(value)) return String(value); if (typeof value === "string" && tableCaseText(value, 200)) return value; } return null; };
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
export async function knownTableCaseDetail(v: unknown, cap: TableCaseCapabilities, original?: TableCaseEntry): Promise<TableCaseDetail | null> {
  if (!closed(v, `version actor_user_id session_version target associations attempts association_total attempt_total association_returned attempt_returned association_omitted attempt_omitted response_truncated ${AUTH_KEYS}`) || v.version !== TABLE_CASE_VERSION || v.actor_user_id !== cap.actor_user_id || v.session_version !== cap.session_version || !authority(v) || typeof v.response_truncated !== "boolean" || !Array.isArray(v.associations) || !Array.isArray(v.attempts)) return null;
  const target = await knownTableCaseEntry(v.target, "target", undefined, original); if (!target) return null;
  for (const kind of ["association", "attempt"] as const) {
    const entries = v[kind === "association" ? "associations" : "attempts"] as unknown[], total = v[kind + "_total"], returned = v[kind + "_returned"], omitted = v[kind + "_omitted"];
    if (!safe(total) || returned !== entries.length || !safe(returned, 0, 8) || !safe(omitted) || total !== returned + omitted || new Set(entries.map(x => row(x) ? x.id : null)).size !== entries.length || (await Promise.all(entries.map(x => knownTableCaseEntry(x, kind, target)))).some(x => !x)) return null;
  }
  return v as unknown as TableCaseDetail;
}
export async function knownTableCaseMaterial(v: unknown, cap: TableCaseCapabilities, materialId: string, offset: number): Promise<TableCaseMaterialPage | null> {
  if (!closed(v, `version actor_user_id session_version material_id total offset limit next_offset entries eligibility expressions_returned expressions_omitted entries_returned entries_omitted response_truncated ${AUTH_KEYS}`) || v.version !== TABLE_CASE_VERSION || v.actor_user_id !== cap.actor_user_id || v.session_version !== cap.session_version || v.material_id !== materialId || !safe(v.total) || v.offset !== offset || v.limit !== 8 || !Array.isArray(v.entries) || v.entries_returned !== v.entries.length || !safe(v.entries_returned, 0, 8) || !safe(v.entries_omitted, 0, 8) || v.entries_returned + v.entries_omitted !== Math.min(8, Math.max(0, v.total - offset)) || v.next_offset !== (offset + v.entries.length < v.total ? offset + v.entries.length : null) || v.entries.length === 0 && v.next_offset !== null || typeof v.response_truncated !== "boolean" || v.response_truncated !== (v.entries_omitted > 0) || !eligibility(v.eligibility) || !safe(v.expressions_returned, 0, 8) || !safe(v.expressions_omitted) || !authority(v)) return null;
  const details = await Promise.all(v.entries.map(x => knownTableCaseDetail(x, cap)));
  if (details.some(x => !x || (x.target.payload as TableCaseTargetPayload).target.material_id !== materialId) || new Set(details.map(x => x?.target.id)).size !== details.length || details.reduce((n, x) => n + (x?.associations.filter(a => a.expression !== null).length ?? 0), 0) !== v.expressions_returned || !v.eligibility.eligible && v.expressions_returned !== 0) return null;
  return v as unknown as TableCaseMaterialPage;
}
export function tableCaseLabel(field: string): string { return TABLE_LABELS[field] ?? field; }
export function tableCaseReason(reason: string): string { return ({ literal_capture_superseded: "Source capture superseded", literal_capture_authority_held: "Source capture authority held", literal_import_authority_held: "Source import authority held", literal_association_authority_held: "Source proposal authority held" } as Record<string, string>)[reason] ?? fieldCaseReason(reason); }

function requireTable(ok: unknown, message = "The original source proof could not be verified."): asserts ok { if (!ok) throw new Error(message); }
const TABLE_ENTRY_KEYS = "field_id subject window source_role knowledge_origin origin_basis model_spans value_spans unit_spans conditions locator predecessor profile field_role cue_spans uncertainty_spans qualifiers table_binding";
function tableEntry(v: unknown): v is TableEntry {
  const spans = (value: unknown, min: number, max: number, bound: number) => Array.isArray(value) && value.length >= min && value.length <= max && value.every(s => closed(s, "start end sha256") && safe(s.start, 0, 131072) && safe(s.end, 1, 131072) && s.end > s.start && s.end - s.start <= bound && hash(s.sha256)) && value.reduce((n, s) => n + (s.end - s.start), 0) <= bound;
  if (!closed(v, TABLE_ENTRY_KEYS) || !tableGridShape(v.table_binding) || v.profile !== TABLE_PROFILE || !includes(TABLE_CASE_FIELDS, v.field_id) || v.field_role !== TABLE_ROLES[v.field_id] || !includes(["source_reported", "source_fitted", "source_model_estimate", "source_proposed"], v.source_role) || !includes(["Observed", "Computed", "unknown"], v.knowledge_origin) || !Array.isArray(v.conditions) || v.conditions.length !== 0 || !Array.isArray(v.qualifiers) || !v.qualifiers.every(q => includes(QUALIFIERS, q)) || new Set(v.qualifiers).size !== v.qualifiers.length) return false;
  if (!closed(v.subject, "formula_spans sample_label_spans") || !spans(v.subject.formula_spans, 1, 1, 200) || !spans(v.subject.sample_label_spans, 0, 8, 200) || !closed(v.window, "id label_spans") || !fieldCaseText(v.window.id) || !spans(v.window.label_spans, 1, 1, 4096) || !closed(v.origin_basis, "statement spans") || v.origin_basis.statement !== null && !fieldCaseText(v.origin_basis.statement, 500) || !spans(v.origin_basis.spans, 0, 8, 1000) || !spans(v.model_spans, 0, 8, 500) || !spans(v.value_spans, 1, 1, 1200) || !spans(v.unit_spans, 0, 1, 120) || !spans(v.cue_spans, 1, 1, 200) || !spans(v.uncertainty_spans, 0, 1, 200)) return false;
  const loc = v.locator; if (!closed(loc, "page slide table row column section member") || !["page", "slide", "row", "column"].every(k => loc[k] === null || safe(loc[k], 1, 100000)) || !["table", "section", "member"].every(k => loc[k] === null || fieldCaseText(loc[k], 200))) return false;
  return v.predecessor === null || closed(v.predecessor, "revision_id record_sha256 revision_number") && uuid(v.predecessor.revision_id) && hash(v.predecessor.record_sha256) && safe(v.predecessor.revision_number, 1, 10000);
}
async function selection(chars: string[], spans: ExpressionSpan[], offset = 0): Promise<string> {
  const parts = []; let last = -1;
  for (const s of spans) { requireTable(s.start >= offset && s.end <= offset + chars.length && s.start >= last); const part = chars.slice(s.start-offset, s.end-offset).join(""); requireTable(await expressionSha(part) === s.sha256, "A selected Unicode span does not match its original text hash."); parts.push(part); last = s.end; }
  return parts.join("");
}
const spanProjection = (s?: ExpressionSpan): Span | null => s ? { char_start: s.start, char_end: s.end, text_sha256: s.sha256 } : null;
async function tableProjection(source: SourceMetadata, chars: string[], entry: TableEntry, offset = 0): Promise<TableProjection> {
  requireTable(tableEntry(entry)); const window = entry.window.label_spans[0], amount = entry.value_spans[0], unit = entry.unit_spans[0], cue = entry.cue_spans[0], uncertainty = entry.uncertainty_spans[0];
  const inside = (s?: ExpressionSpan) => !s || window.start <= s.start && s.start < s.end && s.end <= window.end;
  requireTable([entry.subject.formula_spans[0], amount, unit, cue, uncertainty].every(inside), "A table selection leaves its original source window.");
  requireTable(!uncertainty || amount.start <= uncertainty.start && uncertainty.end <= amount.end);
  const binding = await tableBinding(chars, entry, offset);
  const rawAmount = await selection(chars, entry.value_spans, offset), rawUnit = await selection(chars, entry.unit_spans, offset), rawCue = await selection(chars, entry.cue_spans, offset), rawUncertainty = await selection(chars, entry.uncertainty_spans, offset);
  const subject = { formula: await selection(chars, entry.subject.formula_spans, offset), sample_label: await selection(chars, entry.subject.sample_label_spans, offset) || null, formula_scope: "retained_formula_span" };
  const sourceWindow = { id: entry.window.id, raw_label: await selection(chars, entry.window.label_spans, offset) }, model = await selection(chars, entry.model_spans, offset) || null;
  const identity = { source_id: source.source_id, field_id: entry.field_id, profile: TABLE_PROFILE, field_role: TABLE_ROLES[entry.field_id], subject, window: sourceWindow, source_role: entry.source_role, model, table_binding: binding };
  return { ...identity, expression_key: await expressionSha(expressionCanonical(identity)), knowledge_origin: entry.knowledge_origin, origin_basis: { statement: entry.origin_basis.statement, retained_text: await selection(chars, entry.origin_basis.spans, offset) || null, verification: "declared_inspection_basis" }, value: { status: "raw_literal", raw_value: rawAmount, raw_amount: rawAmount, raw_unit: unit ? rawUnit.trim() : null, raw_uncertainty: uncertainty ? rawUncertainty : null, quantity: null, normalization: "none", unit_basis: "table_row_label", field_cue: rawCue, role: TABLE_ROLES[entry.field_id], qualifiers: entry.qualifiers, value_span: spanProjection(amount)!, unit_span: spanProjection(unit), cue_span: spanProjection(cue)!, uncertainty_span: spanProjection(uncertainty) }, conditions: [], locator: entry.locator, status: "pending", selected_result_association: "unestablished", sample_identity_established: false, phase_identity_established: false, field_interpretation_reviewed: false, scientific_acceptance: false, canonical_promotions: 0, public_content_release: false, ml_training_approved: false, missingness_scope: "not_supplied_in_retained_expression_is_not_source_absence" };
}
function tableMetadata(v: unknown): v is SourceMetadata {
  return closed(v, "source_id url kind content_kind revision revision_status original_parent_sha256 parent_hash_status rights_status currentness captured_at") && fieldCaseText(v.source_id) && /^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,159}$/.test(v.source_id) && Boolean(expressionSourceHref(v.url)) && includes(["primary_paper", "conference_presentation", "supplement", "crystal_reference"], v.kind) && includes(["plain_text", "xml_text"], v.content_kind) && includes(["declared", "unresolved"], v.revision_status) && includes(["declared", "unresolved"], v.parent_hash_status) && (v.revision === null) === (v.revision_status === "unresolved") && (v.original_parent_sha256 === null) === (v.parent_hash_status === "unresolved") && (v.revision === null || fieldCaseText(v.revision)) && (v.original_parent_sha256 === null || hash(v.original_parent_sha256)) && includes(["unresolved", "declared_private_inspection", "restricted"], v.rights_status) && includes(["unresolved", "declared_current", "historical"], v.currentness) && fieldCaseText(v.captured_at, 40) && /(?:Z|[+-]\d{2}:?\d{2})$/.test(v.captured_at) && Number.isFinite(Date.parse(v.captured_at));
}
function retainedTableShape(v: unknown): v is Omit<TablePackage, "source_text_base64"> { return closed(v, "version profile source source_content_sha256 expressions") && v.version === TABLE_PACKAGE_VERSION && v.profile === TABLE_PROFILE && tableMetadata(v.source) && hash(v.source_content_sha256) && Array.isArray(v.expressions) && v.expressions.length >= 1 && v.expressions.length <= 20 && v.expressions.every(tableEntry); }
export async function compileTablePackage(value: unknown): Promise<TablePrepared> {
  requireTable(closed(value, "version profile source source_text_base64 source_content_sha256 expressions") && typeof value.source_text_base64 === "string" && value.source_text_base64.length <= 4*Math.ceil(131072/3));
  const { source_text_base64, ...retained } = value; requireTable(retainedTableShape(retained));
  let binary: string; try { binary = atob(source_text_base64); } catch { throw new Error("The original fragment is not canonical UTF-8 base64."); }
  requireTable(binary.length >= 1 && binary.length <= 131072 && btoa(binary) === source_text_base64);
  const bytes = Uint8Array.from(binary, c => c.charCodeAt(0)), sourceText = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes); requireTable(!sourceText.includes("\0") && await expressionSha(bytes) === value.source_content_sha256);
  const pkg = value as unknown as TablePackage, projections = await Promise.all(pkg.expressions.map(e => tableProjection(pkg.source, Array.from(sourceText), e)));
  requireTable(new Set(projections.map(p => p.expression_key)).size === projections.length && projections.every(p => new TextEncoder().encode(expressionCanonical(p)).length <= 32768));
  const canonical = expressionCanonical(retained); requireTable(new TextEncoder().encode(canonical).length <= 131072); const packageSha = await expressionSha(canonical);
  return { package: pkg, sourceText, retainedBytes: bytes.length, packageSha, requestSha: await expressionSha(expressionCanonical({ version: TABLE_INTAKE_VERSION, package_sha256: packageSha })), projections };
}
export function knownTableSourceCapabilities(v: unknown, actor: string): ExpressionCapabilities | null {
  return closed(v, "version package_version actor_user_id session_version can_import curator_grant_id registry_sha256 field_profiles max_source_bytes max_package_bytes max_projection_bytes max_expression_page_size max_expressions scope scientific_acceptance canonical_promotions public_content_release") && v.version === TABLE_INTAKE_VERSION && v.package_version === TABLE_PACKAGE_VERSION && v.actor_user_id === actor && uuid(actor) && safe(v.session_version) && typeof v.can_import === "boolean" && (v.can_import ? uuid(v.curator_grant_id) : v.curator_grant_id === null) && v.registry_sha256 === TABLE_REGISTRY_SHA && equal(v.field_profiles, TABLE_ROLES) && v.max_source_bytes === 131072 && v.max_package_bytes === 131072 && v.max_projection_bytes === 32768 && v.max_expression_page_size === 8 && v.max_expressions === 20 && v.scope === "private_pending_source_expressions" && v.scientific_acceptance === false && v.canonical_promotions === 0 && v.public_content_release === false ? v as unknown as ExpressionCapabilities : null;
}

async function tableCanonicalProof(text: unknown, sha: unknown, maximum = 524288): Promise<unknown> { requireTable(typeof text === "string" && new TextEncoder().encode(text).length <= maximum && hash(sha) && await expressionSha(text) === sha); return parseExpressionJson(text, false); }
function retainedTablePackage(pkg: TablePackage) { const { source_text_base64: _source, ...retained } = pkg; return retained; }
function manifestShape(value: unknown): value is ExpressionManifest[] {
  return Array.isArray(value) && value.length >= 1 && value.length <= 20 && value.every((entry, index) => closed(entry, "entry_index expression_key entry_sha256 projection_sha256 predecessor_id predecessor_sha256 revision_number") && entry.entry_index === index && hash(entry.expression_key) && hash(entry.entry_sha256) && hash(entry.projection_sha256) && safe(entry.revision_number, 1, 10001) && (entry.revision_number === 1 ? entry.predecessor_id === null && entry.predecessor_sha256 === null : uuid(entry.predecessor_id) && hash(entry.predecessor_sha256))) && new Set(value.map(entry => entry.expression_key)).size === value.length;
}
const RECEIPT_KEYS = "version receipt_id receipt_sha256 actor_user_id actor_grant_id actor_session_version request_key request_sha256 preview_sha256 capture_id package_sha256 package_canonical_json request_canonical_json preview_canonical_json receipt_canonical_json expression_count expression_manifest count_scope replayed dry_run pending_ledger_written status scientific_acceptance canonical_promotions selected_result_association public_content_release";
async function tableReceiptProof(value: unknown): Promise<ExpressionReceipt | null> {
  try {
    requireTable(closed(value, RECEIPT_KEYS) && value.version === TABLE_INTAKE_VERSION && uuid(value.receipt_id) && hash(value.receipt_sha256) && uuid(value.actor_user_id) && uuid(value.actor_grant_id) && safe(value.actor_session_version) && fieldCaseText(value.request_key) && /^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$/.test(value.request_key as string) && hash(value.request_sha256) && hash(value.preview_sha256) && uuid(value.capture_id) && hash(value.package_sha256) && manifestShape(value.expression_manifest) && value.expression_count === value.expression_manifest.length && value.count_scope === "source_expression_revisions_not_independent_experiments" && typeof value.replayed === "boolean" && typeof value.dry_run === "boolean" && value.pending_ledger_written === !value.dry_run && (!value.replayed || !value.dry_run) && value.status === "pending" && value.scientific_acceptance === false && value.canonical_promotions === 0 && value.selected_result_association === "unestablished" && value.public_content_release === false);
    const receipt = value as unknown as ExpressionReceipt;
    const pkg = await tableCanonicalProof(receipt.package_canonical_json, receipt.package_sha256, 131072); requireTable(retainedTableShape(pkg) && pkg.expressions.length === receipt.expression_count);
    const request = await tableCanonicalProof(receipt.request_canonical_json, receipt.request_sha256, 4096); requireTable(equal(request, { version: TABLE_INTAKE_VERSION, package_sha256: receipt.package_sha256 }));
    const actor = { actor_user_id: receipt.actor_user_id, actor_grant_id: receipt.actor_grant_id, actor_session_version: receipt.actor_session_version };
    const preview = await tableCanonicalProof(receipt.preview_canonical_json, receipt.preview_sha256, 32768);
    requireTable(equal(preview, { version: TABLE_INTAKE_VERSION, request_key: receipt.request_key, request_sha256: receipt.request_sha256, actor, manifest: receipt.expression_manifest }));
    const body = await tableCanonicalProof(receipt.receipt_canonical_json, receipt.receipt_sha256);
    requireTable(equal(body, { id: receipt.receipt_id, ...actor, request_key: receipt.request_key, request_sha256: receipt.request_sha256, preview_sha256: receipt.preview_sha256, capture_id: receipt.capture_id, package_json: receipt.package_canonical_json, package_sha256: receipt.package_sha256, expression_count: receipt.expression_count, expression_manifest: receipt.expression_manifest }));
    for (const [index, entry] of pkg.expressions.entries()) {
      const pin = receipt.expression_manifest[index]; requireTable(pin.entry_sha256 === await expressionSha(expressionCanonical(entry)));
      requireTable(entry.predecessor === null ? pin.revision_number === 1 && pin.predecessor_id === null && pin.predecessor_sha256 === null : pin.revision_number === entry.predecessor.revision_number + 1 && pin.predecessor_id === entry.predecessor.revision_id && pin.predecessor_sha256 === entry.predecessor.record_sha256);
    }
    return receipt;
  } catch { return null; }
}
export async function knownTableExpressionReceipt(value: unknown, cap: ExpressionCapabilities, ref: TableSourceRecovery, stage: "preview" | "commit" | "outcome", prepared: TablePrepared | null = null): Promise<ExpressionReceipt | null> {
  const receipt = await tableReceiptProof(value); if (!receipt || receipt.actor_user_id !== cap.actor_user_id || receipt.actor_user_id !== ref.actorId || receipt.request_key !== ref.requestKey || receipt.request_sha256 !== ref.requestSha || receipt.package_sha256 !== ref.packageSha || receipt.package_canonical_json !== ref.packageCanonical) return null;
  if (stage !== "preview" && (!hash(ref.previewSha) || receipt.preview_sha256 !== ref.previewSha || expressionCanonical(receipt.expression_manifest) !== ref.manifestCanonical || receipt.dry_run)) return null;
  if (stage !== "preview" && (!uuid(ref.receiptId) || !hash(ref.receiptSha) || !uuid(ref.captureId) || receipt.receipt_id !== ref.receiptId || receipt.receipt_sha256 !== ref.receiptSha || receipt.capture_id !== ref.captureId)) return null;
  if (stage === "preview" && !receipt.replayed && !receipt.dry_run || stage === "outcome" && !receipt.replayed) return null;
  if (!receipt.replayed && (receipt.actor_session_version !== cap.session_version || receipt.actor_grant_id !== cap.curator_grant_id)) return null;
  if (prepared) { if (prepared.projections.length !== receipt.expression_count) return null; for (const [index, pin] of receipt.expression_manifest.entries()) if (pin.expression_key !== prepared.projections[index].expression_key || pin.entry_sha256 !== await expressionSha(expressionCanonical(prepared.package.expressions[index])) || pin.projection_sha256 !== await expressionSha(expressionCanonical(prepared.projections[index]))) return null; }
  return receipt;
}
export function tableExpressionRecovery(prepared: TablePrepared, cap: ExpressionCapabilities, requestKey: string): TableSourceRecovery {
  return { actorId: cap.actor_user_id, requestKey, requestSha: prepared.requestSha, packageSha: prepared.packageSha, previewSha: "", manifestCanonical: "", packageCanonical: expressionCanonical(retainedTablePackage(prepared.package)), receiptId: "", receiptSha: "", captureId: "" };
}

export type TableExpressionPage = { version: string; total: number; offset: number; limit: number; count_scope: string; expressions: TableSourceRevision[]; scientific_acceptance: false; canonical_promotions: 0 };
export type TableExpressionFilters = { field?: string; sourceId?: string };
function tableProjectionShape(v: unknown): v is TableProjection { return row(v) && v.profile === TABLE_PROFILE && includes(TABLE_CASE_FIELDS, v.field_id) && v.field_role === TABLE_ROLES[v.field_id] && row(v.window) && typeof v.window.raw_label === "string" && Array.from(v.window.raw_label).length <= 4096; }
async function tableProjectionBinding(p: TableProjection, entry: TableEntry, source: SourceMetadata) {
  try {
    // Read DTOs retain selected source text, not full fragment bytes. Check every selected
    // span and overlapping character independently; full-byte SHA is verified at prepare.
    const selections = [...entry.window.label_spans, ...entry.subject.sample_label_spans, ...entry.model_spans, ...entry.origin_basis.spans];
    const size = Math.max(...selections.map(s => s.end)); requireTable(size <= 131072); const chars = Array<string>(size).fill("");
    async function place(raw: string | null, spans: ExpressionSpan[]) {
      requireTable(spans.length === 0 ? raw === null : typeof raw === "string"); if (!spans.length) return;
      const values = Array.from(raw!); requireTable(values.length === spans.reduce((n, s) => n + s.end - s.start, 0)); let at = 0;
      for (const span of spans) { const part = values.slice(at, at + span.end - span.start); requireTable(await expressionSha(part.join("")) === span.sha256); for (const [i, c] of part.entries()) { const position = span.start+i; requireTable(chars[position] === "" || chars[position] === c); chars[position] = c; } at += part.length; }
    }
    await place(p.window.raw_label, entry.window.label_spans); await place(p.subject.sample_label, entry.subject.sample_label_spans); await place(p.model, entry.model_spans); await place(p.origin_basis.retained_text, entry.origin_basis.spans);
    return equal(p, await tableProjection(source, chars, entry));
  } catch { return false; }
}
const REVISION_KEYS = "id record_sha256 expression_key revision_canonical_json entry_index source_entry_sha256 import_receipt_id import_receipt_sha256 import_receipt revision_number predecessor_id predecessor_sha256 projection_sha256 projection_canonical_json projection source_entry is_expression_head capture";
export async function knownTableSourceRevision(value: unknown, detailId?: string, expectedRecordSha?: string): Promise<TableSourceRevision | null> {
  try {
    requireTable(closed(value, detailId ? `version ${REVISION_KEYS}` : REVISION_KEYS) && (!detailId || value.version === TABLE_INTAKE_VERSION && value.id === detailId) && uuid(value.id) && hash(value.record_sha256) && (!expectedRecordSha || value.record_sha256 === expectedRecordSha) && hash(value.expression_key) && safe(value.entry_index, 0, 19) && hash(value.source_entry_sha256) && uuid(value.import_receipt_id) && hash(value.import_receipt_sha256) && safe(value.revision_number, 1, 10001) && (value.revision_number === 1 ? value.predecessor_id === null && value.predecessor_sha256 === null : uuid(value.predecessor_id) && hash(value.predecessor_sha256)) && hash(value.projection_sha256) && tableProjectionShape(value.projection) && tableEntry(value.source_entry) && typeof value.is_expression_head === "boolean");
    const revision = value as unknown as TableSourceRevision, capture = await knownSourceCapture(revision.capture); requireTable(capture);
    requireTable(equal(await tableCanonicalProof(revision.projection_canonical_json, revision.projection_sha256, 32768), revision.projection));
    const body = await tableCanonicalProof(revision.revision_canonical_json, revision.record_sha256, 65536);
    requireTable(closed(body, "id actor_user_id actor_grant_id actor_session_version import_receipt_id import_receipt_sha256 capture_id entry_index entry_sha256 expression_key field_id revision_number predecessor_id predecessor_sha256 projection_json projection_sha256") && uuid(body.actor_user_id) && uuid(body.actor_grant_id) && safe(body.actor_session_version));
    requireTable(equal(body, { id: revision.id, actor_user_id: body.actor_user_id, actor_grant_id: body.actor_grant_id, actor_session_version: body.actor_session_version, import_receipt_id: revision.import_receipt_id, import_receipt_sha256: revision.import_receipt_sha256, capture_id: capture.id, entry_index: revision.entry_index, entry_sha256: revision.source_entry_sha256, expression_key: revision.expression_key, field_id: revision.projection.field_id, revision_number: revision.revision_number, predecessor_id: revision.predecessor_id, predecessor_sha256: revision.predecessor_sha256, projection_json: revision.projection_canonical_json, projection_sha256: revision.projection_sha256 }));
    requireTable(revision.expression_key === revision.projection.expression_key && revision.source_entry_sha256 === await expressionSha(expressionCanonical(revision.source_entry)) && await tableProjectionBinding(revision.projection, revision.source_entry, capture.source));
    requireTable(revision.source_entry.predecessor === null ? revision.revision_number === 1 : revision.source_entry.predecessor.revision_id === revision.predecessor_id && revision.source_entry.predecessor.record_sha256 === revision.predecessor_sha256 && revision.source_entry.predecessor.revision_number + 1 === revision.revision_number);
    if (detailId) {
      const receipt = await tableReceiptProof(revision.import_receipt); requireTable(receipt && !receipt.dry_run && receipt.receipt_id === revision.import_receipt_id && receipt.receipt_sha256 === revision.import_receipt_sha256 && receipt.capture_id === capture.id && receipt.actor_user_id === body.actor_user_id && receipt.actor_grant_id === body.actor_grant_id && receipt.actor_session_version === body.actor_session_version);
      const pkg = parseExpressionJson(receipt.package_canonical_json) as Omit<TablePackage, "source_text_base64">;
      const pin = receipt.expression_manifest[revision.entry_index]; requireTable(pin && pin.expression_key === revision.expression_key && pin.entry_sha256 === revision.source_entry_sha256 && pin.projection_sha256 === revision.projection_sha256 && pin.predecessor_id === revision.predecessor_id && pin.predecessor_sha256 === revision.predecessor_sha256 && pin.revision_number === revision.revision_number && equal(pkg.expressions[revision.entry_index], revision.source_entry) && equal(pkg.source, capture.source) && pkg.source_content_sha256 === capture.source_content_sha256);
    } else requireTable(revision.import_receipt === null);
    return revision;
  } catch { return null; }
}
export async function knownTableExpressionPage(value: unknown, offset: number, limit: number, filters: TableExpressionFilters = {}): Promise<TableExpressionPage | null> {
  if (!safe(offset, 0, 10000) || !safe(limit, 1, 8) || !closed(value, "version total offset limit count_scope expressions scientific_acceptance canonical_promotions") || value.version !== TABLE_INTAKE_VERSION || !safe(value.total) || value.offset !== offset || value.limit !== limit || value.count_scope !== "current_pending_expression_heads_not_experiments_or_verified_properties" || value.scientific_acceptance !== false || value.canonical_promotions !== 0 || !Array.isArray(value.expressions) || value.expressions.length > limit || value.expressions.length !== Math.min(limit, Math.max(0, value.total - offset))) return null;
  const items = await Promise.all(value.expressions.map(item => knownTableSourceRevision(item)));
  if (items.some(item => !item || !item.is_expression_head || filters.field && item.projection.field_id !== filters.field || filters.sourceId && item.capture.source.source_id !== filters.sourceId) || new Set(items.map(item => item?.expression_key)).size !== items.length) return null;
  return value as unknown as TableExpressionPage;
}

export function tableRoleLabel(role: string): string { return ({ reported_property: "Reported property", study_extent: "Study extent", measurement_limit: "Measurement limit", reported_order_transition: "Reported order transition" } as Record<string, string>)[role] ?? "Unverified role"; }

export const TABLE_RECOVERY_VERSION = "material-table-save-identity/1.0.0";
type StoredBase = { version: string; actorId: string; requestKey: string; requestSha: string; previewSha: string; receiptId: string; receiptSha: string };
export type TableStoredIdentity = StoredBase & ({ kind: "source"; packageSha: string; captureId: string; manifestSha: string } | { kind: "case"; operation: TableCaseRequest["operation"]; targetContextSha: string; fieldId: string; chainKey: string | null });
export type TableStorageRead = { status: "empty" } | { status: "blocked" } | { status: "pending"; identity: TableStoredIdentity };
export type TableSaveConfirmation = { kind: "source" | "case"; receiptId: string; receiptSha: string; requestKey: string };
export function tableRecoveryStorageKey(actor: string): string { requireTable(uuid(actor)); return `sclib:table-save:${actor}`; }
export function knownTableStoredIdentity(value: unknown, actor: string): TableStoredIdentity | null {
  if (!row(value) || !closed(value, value.kind === "source" ? "version actorId requestKey requestSha previewSha receiptId receiptSha kind packageSha captureId manifestSha" : "version actorId requestKey requestSha previewSha receiptId receiptSha kind operation targetContextSha fieldId chainKey") || value.version !== TABLE_RECOVERY_VERSION || value.actorId !== actor || !uuid(actor) || !fieldCaseText(value.requestKey) || !/^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$/.test(value.requestKey) || !hash(value.requestSha) || !hash(value.previewSha) || !uuid(value.receiptId) || !hash(value.receiptSha)) return null;
  if (value.kind === "source") return hash(value.packageSha) && uuid(value.captureId) && hash(value.manifestSha) ? value as unknown as TableStoredIdentity : null;
  return value.kind === "case" && includes(["target", "association", "attempt"], value.operation) && hash(value.targetContextSha) && includes(TABLE_CASE_FIELDS, value.fieldId) && (value.operation === "target" ? value.chainKey === null : value.operation === "association" ? hash(value.chainKey) : uuid(value.chainKey)) ? value as unknown as TableStoredIdentity : null;
}
/** Minimal pins only. Unavailable or malformed storage is never an empty ledger. */
export function readTableRecovery(actor: string): TableStorageRead {
  try { const raw = sessionStorage.getItem(tableRecoveryStorageKey(actor)); if (raw === null) return { status: "empty" }; if (new TextEncoder().encode(raw).length > 4096) return { status: "blocked" }; const identity = knownTableStoredIdentity(parseExpressionJson(raw), actor); return identity ? { status: "pending", identity } : { status: "blocked" }; } catch { return { status: "blocked" }; }
}
/** Must succeed, including exact read-back, before a POST. Never overwrite an unresolved actor. */
export function storeTableRecovery(identity: TableStoredIdentity): boolean {
  try { if (!knownTableStoredIdentity(identity, identity.actorId) || readTableRecovery(identity.actorId).status !== "empty") return false; const raw = expressionCanonical(identity); if (new TextEncoder().encode(raw).length > 4096) return false; const key = tableRecoveryStorageKey(identity.actorId); sessionStorage.setItem(key, raw); return sessionStorage.getItem(key) === raw && readTableRecovery(identity.actorId).status === "pending"; } catch { return false; }
}
/** Called only after a verified commit/outcome. A different or inaccessible identity stays held. */
export function clearTableRecovery(identity: TableStoredIdentity): boolean {
  try { const current = readTableRecovery(identity.actorId); if (current.status !== "pending" || !equal(current.identity, identity)) return false; const key = tableRecoveryStorageKey(identity.actorId); sessionStorage.removeItem(key); return sessionStorage.getItem(key) === null; } catch { return false; }
}
export async function tableStoredSourceIdentity(ref: TableSourceRecovery): Promise<TableStoredIdentity> {
  const result: TableStoredIdentity = { version: TABLE_RECOVERY_VERSION, kind: "source", actorId: ref.actorId, requestKey: ref.requestKey, requestSha: ref.requestSha, previewSha: ref.previewSha, receiptId: ref.receiptId, receiptSha: ref.receiptSha, packageSha: ref.packageSha, captureId: ref.captureId, manifestSha: await expressionSha(ref.manifestCanonical) }; requireTable(knownTableStoredIdentity(result, ref.actorId)); return result;
}
export function tableStoredCaseIdentity(ref: TableCaseRecovery): TableStoredIdentity {
  const result: TableStoredIdentity = { version: TABLE_RECOVERY_VERSION, kind: "case", actorId: ref.actorId, requestKey: ref.requestKey, requestSha: ref.requestSha, previewSha: ref.previewSha, receiptId: ref.receiptId, receiptSha: ref.receiptSha, operation: ref.operation, targetContextSha: ref.targetContextSha, fieldId: ref.fieldId, chainKey: ref.chainKey }; requireTable(knownTableStoredIdentity(result, ref.actorId)); return result;
}
/** Independently validate the original saved GET proof without retaining request/payload/source text. */
export async function knownTableStoredOutcome(value: unknown, actor: string, identity: TableStoredIdentity): Promise<TableSaveConfirmation | null> {
  try {
    requireTable(knownTableStoredIdentity(identity, actor));
    if (identity.kind === "source") {
      const receipt = await tableReceiptProof(value); requireTable(receipt && receipt.actor_user_id === actor && receipt.request_key === identity.requestKey && receipt.request_sha256 === identity.requestSha && receipt.preview_sha256 === identity.previewSha && receipt.receipt_id === identity.receiptId && receipt.receipt_sha256 === identity.receiptSha && receipt.capture_id === identity.captureId && receipt.package_sha256 === identity.packageSha && await expressionSha(expressionCanonical(receipt.expression_manifest)) === identity.manifestSha && receipt.replayed === true && receipt.dry_run === false && receipt.pending_ledger_written === true);
    } else {
      requireTable(closed(value, `version receipt_id receipt_sha256 operation target_id actor_user_id actor_grant_id actor_session_version request_key request_sha256 preview_sha256 request_canonical_json preview_canonical_json receipt_canonical_json replayed dry_run pending_ledger_written ${AUTH_KEYS}`) && value.version === TABLE_CASE_VERSION && value.actor_user_id === actor && value.operation === identity.operation && value.request_key === identity.requestKey && value.request_sha256 === identity.requestSha && value.preview_sha256 === identity.previewSha && value.receipt_id === identity.receiptId && value.receipt_sha256 === identity.receiptSha && value.replayed === true && value.dry_run === false && value.pending_ledger_written === true && authority(value));
      const body = await rowProof(value.receipt_canonical_json, identity.receiptSha); requireTable(body && body.id === identity.receiptId && body.operation === identity.operation && body.actor_user_id === actor && body.context_sha256 === identity.targetContextSha && body.field_id === identity.fieldId && body.chain_key === identity.chainKey && value.target_id === (identity.operation === "target" ? body.id : body.target_id) && value.request_canonical_json === body.request_json && value.preview_canonical_json === body.preview_json && ["actor_user_id", "actor_grant_id", "actor_session_version", "request_key", "request_sha256", "preview_sha256"].every(key => value[key] === body[key]));
    }
    return { kind: identity.kind, receiptId: identity.receiptId, receiptSha: identity.receiptSha, requestKey: identity.requestKey };
  } catch { return null; }
}
