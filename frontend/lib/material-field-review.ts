/** Private field fidelity review. Original values and scientific authority stay separate. */
import { expressionCanonical, expressionSha, parseExpressionJson } from "./source-expressions";

export const FIELD_REVIEW_VERSION = "material-field-review/1.0.0";
export const FIELD_REVIEW_PROFILE = "retained-tc-field-fidelity/1.0.0";
export const FIELD_REVIEW_FIELDS = ["tc_criterion", "measurement_method", "pressure_gpa"] as const;
export const FIELD_REVIEW_CHECKS = ["source_identity_and_fragment", "field_value_and_unit_boundary", "retained_result_window_and_sample_scope", "semantic_missingness_and_conflicts"] as const;
export type ReviewField = typeof FIELD_REVIEW_FIELDS[number];
export type ReviewCheck = typeof FIELD_REVIEW_CHECKS[number];
type Row = Record<string, unknown>;
type Pin = { id: string; record_sha256: string };
type ExpressionPin = Pin & { projection_sha256: string };
type Authority = { scientific_acceptance: false; canonical_promotions: 0; ml_training_approved: false; public_release_authorized: false; sample_identity_established: false; phase_identity_established: false };
const AUTH_KEYS = "scientific_acceptance canonical_promotions ml_training_approved public_release_authorized sample_identity_established phase_identity_established";
export type ReviewSelector = { targetId: string; fieldId: ReviewField; expressionId: string; componentIndex: number; componentKind: "condition" | "value"; associationId?: string; tcExpressionId?: string };
export type ReviewItem = { target_id: string; target_sha256: string; field_id: ReviewField; association: Pin | null; expression: ExpressionPin; tc_expression: ExpressionPin | null; source_identity: { paper_id: string; work_id: string | null }; component: { kind: "condition" | "value"; index: number | null; field_id: string; role: string | null }; expected_subject_sha256: string; expected_candidate_sha256: string; expected_missingness_sha256: string; expected_tuple_sha256: string; decision: "accept" | "reject" | "request_clarification"; checks: Record<ReviewCheck, "satisfied" | "unresolved" | "not_applicable">; source_inspection_attested: boolean; rationale: string; predecessor: Pin | null; resolves_decision_id: string | null };
export type ReviewRequest = { version: string; profile_version: string; request_key: string; items: ReviewItem[] };
export type ReviewCapabilities = Authority & { version: string; profile_version: string; actor_user_id: string; session_version: number; reviewer_grant_id: string | null; can_write: boolean; field_ids: ReviewField[]; checks: ReviewCheck[]; max_items: 8; max_operation_bytes: 32768; max_page_size: 8; supported_target_kinds: ["retained_result"]; field_fidelity_acceptance_available: true; support_scope: string };
export type ReviewContext = Authority & { version: string; profile_version: string; actor_user_id: string; session_version: number; subject: Row & { target_id: string; field_id: ReviewField; eligible: boolean; reason_codes: string[]; candidate: Row; missingness: Row; tuple: Row }; subject_canonical_json: string; subject_sha256: string; item_template: ReviewItem };
export type ReviewRecovery = { actorId: string; requestKey: string; requestSha: string; itemCount: number; previewSha: string | null; receiptId: string | null; receiptSha: string | null };
export type ReviewReceipt = Authority & { version: string; receipt_id: string; receipt_sha256: string; actor_user_id: string; actor_grant_id: string; actor_session_version: number; request_key: string; request_sha256: string; preview_sha256: string; request_canonical_json: string; preview_canonical_json: string; receipt_canonical_json: string; dry_run: boolean; replayed: boolean; review_ledger_written: boolean; decision_ids: string[] };
export type ReviewDecision = Authority & { id: string; record_sha256: string; record_canonical_json: string; target_id: string; field_id: ReviewField; decision: ReviewItem["decision"]; is_head: boolean; field_fidelity_accepted: boolean; effective_value: Row | null; effective_value_canonical_json: string | null; reason_codes: string[]; source_identity_status: string; created_at: string };
export type ReviewEffective = Authority & { version: string; actor_user_id: string; session_version: number; target_id: string; field_id: ReviewField; field_fidelity_accepted: boolean; effective_value: Row | null; effective_value_canonical_json: string | null; decision: ReviewDecision | null };
export const fieldReviewLabel = (field: string) => ({ tc_criterion: "Tc criterion", measurement_method: "Measurement method", pressure_gpa: "Tc result pressure" }[field] ?? field.replaceAll("_", " "));
/** Target field names differ from the frozen source-expression vocabulary. */
export function reviewFieldSourceSelection(field: string, projection: { field_id: string; conditions: { field_id: string; role: string }[] }): { field: ReviewField; kind: "condition" | "value"; index: string } | null {
  if (!FIELD_REVIEW_FIELDS.some(f => f === field)) return null;
  const selected = field as ReviewField;
  const sourceField = { tc_criterion: "criterion_statement", measurement_method: "method_statement", pressure_gpa: "pressure_gpa" }[selected];
  if (selected === "measurement_method" && projection.field_id === "method_statement") return { field: selected, kind: "value", index: "0" };
  const conditions = projection.conditions.map((c, index) => ({ ...c, index })).filter(c => c.field_id === sourceField && c.role === "reported_result_condition");
  return projection.field_id === "tc_kelvin" && conditions.length === 1 ? { field: selected, kind: "condition", index: String(conditions[0].index) } : null;
}
export const fieldReviewCheckLabel = (key: ReviewCheck) => ({ source_identity_and_fragment: "Publication identity and original source fragment", field_value_and_unit_boundary: "Field meaning, printed value and unit boundary", retained_result_window_and_sample_scope: "Same Tc result window and sample scope", semantic_missingness_and_conflicts: "Missing field and conflicts with existing aliases" }[key]);
export function fieldReviewUuid(value: unknown): value is string { return typeof value === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value); }
function row(value: unknown): value is Row { return typeof value === "object" && value !== null && !Array.isArray(value); }
function closed(value: unknown, keys: string): value is Row { return row(value) && Object.keys(value).length === keys.split(" ").length && keys.split(" ").every(k => Object.hasOwn(value, k)); }
function hash(value: unknown): value is string { return typeof value === "string" && /^[a-f0-9]{64}$/.test(value); }
function integer(value: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= min && value <= max; }
function text(value: unknown, max: number, min = 1): value is string { return typeof value === "string" && Array.from(value).length >= min && Array.from(value).length <= max && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]/.test(value) && !Array.from(value).some(c => c.length === 1 && c.charCodeAt(0) >= 0xd800 && c.charCodeAt(0) <= 0xdfff); }
function equal(a: unknown, b: unknown): boolean { if (a === b) return true; if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => equal(x, b[i])); return row(a) && row(b) && Object.keys(a).length === Object.keys(b).length && Object.keys(a).every(k => Object.hasOwn(b, k) && equal(a[k], b[k])); }
function authority(value: Row): boolean { return value.scientific_acceptance === false && value.canonical_promotions === 0 && value.ml_training_approved === false && value.public_release_authorized === false && value.sample_identity_established === false && value.phase_identity_established === false; }
function pin(value: unknown, projection = false, nullable = false): boolean { return nullable && value === null || closed(value, "id record_sha256" + (projection ? " projection_sha256" : "")) && fieldReviewUuid(value.id) && hash(value.record_sha256) && (!projection || hash(value.projection_sha256)); }
function field(value: unknown): value is ReviewField { return typeof value === "string" && (FIELD_REVIEW_FIELDS as readonly string[]).includes(value); }
function requestItem(value: unknown): value is ReviewItem {
  if (!closed(value, "target_id target_sha256 field_id association expression tc_expression source_identity component expected_subject_sha256 expected_candidate_sha256 expected_missingness_sha256 expected_tuple_sha256 decision checks source_inspection_attested rationale predecessor resolves_decision_id") || !fieldReviewUuid(value.target_id) || !hash(value.target_sha256) || !field(value.field_id) || !pin(value.association, false, true) || !pin(value.expression, true) || !pin(value.tc_expression, true, true) || !pin(value.predecessor, false, true)) return false;
  if (!closed(value.source_identity, "paper_id work_id") || !text(value.source_identity.paper_id, 100) || value.source_identity.paper_id !== value.source_identity.paper_id.trim() || value.source_identity.work_id !== null && !fieldReviewUuid(value.source_identity.work_id)) return false;
  const component = value.component, expected = { tc_criterion: "criterion_statement", measurement_method: "method_statement", pressure_gpa: "pressure_gpa" }[value.field_id];
  if (row(component) && component.kind === "condition" && value.tc_expression !== null) return false;
  if (row(component) && component.kind === "value" && value.tc_expression === null) return false;
  if (!closed(component, "kind index field_id role") || component.field_id !== expected || !(component.kind === "condition" && integer(component.index, 0, 7) && component.role === "reported_result_condition" || component.kind === "value" && value.field_id === "measurement_method" && component.index === null && component.role === null)) return false;
  if (!["expected_subject_sha256", "expected_candidate_sha256", "expected_missingness_sha256", "expected_tuple_sha256"].every(k => hash(value[k])) || !["accept", "reject", "request_clarification"].includes(value.decision as string) || typeof value.source_inspection_attested !== "boolean" || !text(value.rationale, 1000, 20) || value.rationale.trim().length < 20 || !closed(value.checks, FIELD_REVIEW_CHECKS.join(" ")) || !Object.values(value.checks).every(x => ["satisfied", "unresolved", "not_applicable"].includes(x as string))) return false;
  if (value.resolves_decision_id !== null && (!row(value.predecessor) || value.resolves_decision_id !== value.predecessor.id)) return false;
  return value.decision !== "accept" || value.source_inspection_attested && Object.values(value.checks).every(x => x === "satisfied");
}
export function knownReviewRequest(value: unknown): value is ReviewRequest { if (!closed(value, "version profile_version request_key items") || value.version !== FIELD_REVIEW_VERSION || value.profile_version !== FIELD_REVIEW_PROFILE || !text(value.request_key, 160) || !/^[A-Za-z0-9][A-Za-z0-9._:/+@-]*$/.test(value.request_key) || !Array.isArray(value.items) || value.items.length < 1 || value.items.length > 8 || !value.items.every(requestItem) || new Set(value.items.map(x => `${x.target_id}:${x.field_id}`)).size !== value.items.length) return false; try { return new TextEncoder().encode(expressionCanonical(value)).length <= 32768; } catch { return false; } }
async function proof(value: unknown, sha: unknown, maximum = 131072): Promise<Row | null> { if (!text(value, maximum) || !hash(sha) || new TextEncoder().encode(value).length > maximum || await expressionSha(value) !== sha) return null; const body = parseExpressionJson(value, false); return row(body) ? body : null; }
/** Extract exact canonical member bytes after strict, duplicate-safe parsing. Preserve float lexemes. */
function member(source: string, wanted: string): string | null {
  let at = 1;
  const stringEnd = (start: number) => { let i = start + 1; for (; i < source.length; i++) { if (source[i] === "\\") i++; else if (source[i] === '"') return i + 1; } return -1; };
  while (at < source.length && source[at] !== "}") {
    if (source[at] !== '"') return null; const end = stringEnd(at); if (end < 0) return null; const key = JSON.parse(source.slice(at, end)); at = end; if (source[at++] !== ":") return null;
    const start = at; let depth = 0;
    for (; at < source.length; at++) { const c = source[at]; if (c === '"') { const next = stringEnd(at); if (next < 0) return null; at = next - 1; } else if (c === "[" || c === "{") depth++; else if (c === "]" || c === "}") { if (depth === 0) break; depth--; } else if (c === "," && depth === 0) break; }
    if (key === wanted) return source.slice(start, at); if (source[at] === ",") at++; else break;
  }
  return null;
}
export function knownReviewCapabilities(value: unknown, actor: string): ReviewCapabilities | null {
  if (!closed(value, `version profile_version actor_user_id session_version reviewer_grant_id can_write field_ids checks max_items max_operation_bytes max_page_size supported_target_kinds field_fidelity_acceptance_available support_scope ${AUTH_KEYS}`) || value.version !== FIELD_REVIEW_VERSION || value.profile_version !== FIELD_REVIEW_PROFILE || value.actor_user_id !== actor || !fieldReviewUuid(actor) || !integer(value.session_version) || typeof value.can_write !== "boolean" || (value.can_write ? !fieldReviewUuid(value.reviewer_grant_id) : value.reviewer_grant_id !== null) || !equal(value.field_ids, FIELD_REVIEW_FIELDS) || !equal(value.checks, FIELD_REVIEW_CHECKS) || value.max_items !== 8 || value.max_operation_bytes !== 32768 || value.max_page_size !== 8 || !equal(value.supported_target_kinds, ["retained_result"]) || value.field_fidelity_acceptance_available !== true || value.support_scope !== "finite_flat_retained_records_with_current_source_expression_and_reviewed_tc_window" || !authority(value)) return null;
  return value as ReviewCapabilities;
}
export async function knownReviewContext(value: unknown, cap: ReviewCapabilities, selector: ReviewSelector): Promise<ReviewContext | null> {
  try {
    if (!closed(value, `version profile_version actor_user_id session_version subject subject_canonical_json subject_sha256 item_template ${AUTH_KEYS}`) || value.version !== FIELD_REVIEW_VERSION || value.profile_version !== FIELD_REVIEW_PROFILE || value.actor_user_id !== cap.actor_user_id || value.session_version !== cap.session_version || !authority(value)) return null;
    const body = await proof(value.subject_canonical_json, value.subject_sha256), item = value.item_template;
    if (!body || !equal(body, value.subject) || !requestItem(item) || item.target_id !== selector.targetId || item.field_id !== selector.fieldId || item.expression.id !== selector.expressionId || item.association?.id !== (selector.associationId || undefined) || item.tc_expression?.id !== (selector.tcExpressionId || undefined) || item.component.kind !== selector.componentKind || item.component.index !== (selector.componentKind === "condition" ? selector.componentIndex : null) || item.expected_subject_sha256 !== value.subject_sha256 || item.decision !== "request_clarification" || item.source_inspection_attested !== false || Object.values(item.checks).some(x => x !== "unresolved") || body.target_id !== item.target_id || body.field_id !== item.field_id || typeof body.eligible !== "boolean" || !Array.isArray(body.reason_codes) || !body.reason_codes.every(x => text(x, 160)) || body.eligible !== (body.reason_codes.length === 0)) return null;
    if (!fieldReviewUuid(body.target_user_id) || (item.association ? !fieldReviewUuid(body.association_user_id) : body.association_user_id !== null) || !["importer_user_id", "capture_user_id"].every(k => fieldReviewUuid(body[k])) || (item.tc_expression ? !fieldReviewUuid(body.tc_importer_user_id) : body.tc_importer_user_id !== null)) return null;
    for (const key of ["candidate", "missingness", "tuple"] as const) { const bytes = member(value.subject_canonical_json as string, key); if (!row(body[key]) || !bytes || await expressionSha(bytes) !== body[`${key}_sha256`] || item[`expected_${key}_sha256`] !== body[`${key}_sha256`]) return null; }
    return value as ReviewContext;
  } catch { return null; }
}
export async function reviewRecovery(request: ReviewRequest, cap: ReviewCapabilities): Promise<ReviewRecovery> { return { actorId: cap.actor_user_id, requestKey: request.request_key, requestSha: await expressionSha(expressionCanonical(request)), itemCount: request.items.length, previewSha: null, receiptId: null, receiptSha: null }; }
export async function knownReviewReceipt(value: unknown, cap: ReviewCapabilities, ref: ReviewRecovery, mode: "preview" | "commit" | "outcome"): Promise<ReviewReceipt | null> {
  try {
    if (!closed(value, `version receipt_id receipt_sha256 actor_user_id actor_grant_id actor_session_version request_key request_sha256 preview_sha256 request_canonical_json preview_canonical_json receipt_canonical_json dry_run replayed review_ledger_written decision_ids ${AUTH_KEYS}`) || value.version !== FIELD_REVIEW_VERSION || value.actor_user_id !== cap.actor_user_id || value.actor_user_id !== ref.actorId || value.request_key !== ref.requestKey || value.request_sha256 !== ref.requestSha || !fieldReviewUuid(value.receipt_id) || !fieldReviewUuid(value.actor_grant_id) || !integer(value.actor_session_version) || typeof value.dry_run !== "boolean" || typeof value.replayed !== "boolean" || value.review_ledger_written !== !value.dry_run || !authority(value) || !Array.isArray(value.decision_ids) || value.decision_ids.length !== ref.itemCount || !value.decision_ids.every(fieldReviewUuid) || new Set(value.decision_ids).size !== ref.itemCount) return null;
    const body = await proof(value.receipt_canonical_json, value.receipt_sha256), request = await proof(value.request_canonical_json, ref.requestSha, 32768), preview = await proof(value.preview_canonical_json, value.preview_sha256, 8192);
    if (!closed(body, "id actor_user_id actor_grant_id actor_session_version request_key request_json request_sha256 preview_json preview_sha256") || !request || !closed(preview, "version receipt_id actor_user_id actor_grant_id actor_session_version request_sha256") || !knownReviewRequest(request) || request.items.length !== ref.itemCount || body.id !== value.receipt_id || body.request_json !== value.request_canonical_json || body.preview_json !== value.preview_canonical_json || !["actor_user_id", "actor_grant_id", "actor_session_version", "request_key", "request_sha256", "preview_sha256"].every(k => body[k] === value[k]) || preview.version !== FIELD_REVIEW_VERSION || preview.receipt_id !== value.receipt_id || preview.actor_user_id !== value.actor_user_id || preview.actor_grant_id !== value.actor_grant_id || preview.actor_session_version !== value.actor_session_version || preview.request_sha256 !== ref.requestSha || ref.previewSha !== null && value.preview_sha256 !== ref.previewSha || ref.receiptId !== null && value.receipt_id !== ref.receiptId || ref.receiptSha !== null && value.receipt_sha256 !== ref.receiptSha) return null;
    if (mode === "preview" ? value.replayed ? value.dry_run !== false : value.dry_run !== true || value.actor_grant_id !== cap.reviewer_grant_id || value.actor_session_version !== cap.session_version : value.dry_run !== false || mode === "outcome" && value.replayed !== true) return null;
    return value as ReviewReceipt;
  } catch { return null; }
}
async function decision(value: unknown, target: string, selectedField: ReviewField): Promise<ReviewDecision | null> {
  if (!closed(value, `id record_sha256 record_canonical_json target_id field_id decision is_head field_fidelity_accepted effective_value effective_value_canonical_json reason_codes source_identity_status created_at ${AUTH_KEYS}`) || !fieldReviewUuid(value.id) || value.target_id !== target || value.field_id !== selectedField || typeof value.is_head !== "boolean" || typeof value.field_fidelity_accepted !== "boolean" || !Array.isArray(value.reason_codes) || !value.reason_codes.every(x => text(x, 160)) || !text(value.created_at, 60) || !Number.isFinite(Date.parse(value.created_at)) || !authority(value)) return null;
  const body = await proof(value.record_canonical_json, value.record_sha256);
  if (!body || body.id !== value.id || body.target_id !== target || body.field_id !== selectedField || body.decision !== value.decision || !requestItem(body.payload) || body.payload.target_id !== target || body.payload.field_id !== selectedField || body.payload.decision !== value.decision) return null;
  if (value.field_fidelity_accepted) {
    const candidate = await proof(value.effective_value_canonical_json, body.payload.expected_candidate_sha256, 32768);
    if (value.decision !== "accept" || !value.is_head || value.reason_codes.length !== 0 || value.source_identity_status !== "reviewed_field_fidelity_only" || !candidate || !equal(candidate, value.effective_value) || candidate.field_id !== selectedField) return null;
  } else if (value.effective_value !== null || value.effective_value_canonical_json !== null || value.source_identity_status !== "unestablished") return null;
  return value as ReviewDecision;
}
export async function knownReviewEffective(value: unknown, cap: ReviewCapabilities, target: string, selectedField: ReviewField): Promise<ReviewEffective | null> {
  try {
    if (!closed(value, `version actor_user_id session_version target_id field_id field_fidelity_accepted effective_value effective_value_canonical_json decision ${AUTH_KEYS}`) || value.version !== FIELD_REVIEW_VERSION || value.actor_user_id !== cap.actor_user_id || value.session_version !== cap.session_version || value.target_id !== target || value.field_id !== selectedField || typeof value.field_fidelity_accepted !== "boolean" || !authority(value)) return null;
    const entry = value.decision === null ? null : await decision(value.decision, target, selectedField);
    if (value.decision !== null && (!entry || !entry.is_head) || value.field_fidelity_accepted !== Boolean(entry?.field_fidelity_accepted) || !equal(value.effective_value, entry?.effective_value ?? null) || value.effective_value_canonical_json !== (entry?.effective_value_canonical_json ?? null)) return null;
    return value as ReviewEffective;
  } catch { return null; }
}
export function reviewSourceValue(candidate: unknown): string {
  if (!row(candidate) || !row(candidate.value) || !text(candidate.value.raw_value, 1200)) return "Printed value unavailable";
  const value = candidate.value.raw_value, unit = candidate.value.raw_unit;
  const separateUnit = Array.isArray(candidate.unit_spans) && candidate.unit_spans.length > 0 && text(unit, 40) && !value.trimEnd().endsWith(unit.trim());
  return `${value}${separateUnit ? ` ${unit}` : ""}`;
}
const RECOVERY_PREFIX = "sclib:material-field-review:pending:1:";
function savedRecovery(value: unknown, actor: string): value is ReviewRecovery {
  return closed(value, "actorId requestKey requestSha itemCount previewSha receiptId receiptSha") && value.actorId === actor && fieldReviewUuid(actor) && text(value.requestKey, 160) && /^[A-Za-z0-9][A-Za-z0-9._:/+@-]*$/.test(value.requestKey) && hash(value.requestSha) && integer(value.itemCount, 1, 8) && hash(value.previewSha) && fieldReviewUuid(value.receiptId) && hash(value.receiptSha);
}
/** Only original actor/key/hash/receipt pins survive navigation; source and review values never do. */
export function loadReviewRecovery(actor: string): ReviewRecovery | null {
  const bytes = window.sessionStorage.getItem(RECOVERY_PREFIX + actor);
  if (bytes === null) return null;
  const value = bytes.length <= 2048 ? JSON.parse(bytes) : null;
  if (!savedRecovery(value, actor)) throw new Error("Unverified browser recovery pins");
  return value;
}
export function retainReviewRecovery(value: ReviewRecovery): void {
  if (!savedRecovery(value, value.actorId)) throw new Error("Unverified original save identity");
  window.sessionStorage.setItem(RECOVERY_PREFIX + value.actorId, JSON.stringify(value));
  if (!equal(loadReviewRecovery(value.actorId), value)) throw new Error("Original save identity was not retained");
}
export function clearReviewRecovery(actor: string): void { window.sessionStorage.removeItem(RECOVERY_PREFIX + actor); }
export function reviewContextMatchesEffective(context: ReviewContext, value: ReviewEffective): boolean {
  return context.item_template.predecessor === null ? value.decision === null : value.decision !== null && context.item_template.predecessor.id === value.decision.id && context.item_template.predecessor.record_sha256 === value.decision.record_sha256;
}
