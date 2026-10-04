/** Private associations to existing evidence. No sample identity or execution is inferred. */
import { designClosed, designHash, designId, designObject, designText, knownDesignBaseline, type DesignBaseline, type DesignCapabilities, type DesignDetail, type DesignEligibility, type DesignEntry } from "./discovery-designs";
import { expressionCanonical, expressionSha, parseExpressionJson } from "./source-expressions";

export const FEEDBACK_VERSION = "discovery-feedback/1.0.0";
export const FEEDBACK_REQUEST_VERSION = "discovery-feedback-operation/1.0.0";
export const FEEDBACK_MAX_BYTES = 32768;
export const FEEDBACK_AUTHORITY = { scientific_acceptance: false, canonical_promotions: 0, ml_training_approved: false, public_release: false, calculation_executed: false, experiment_executed: false, physical_association_established: false, scope: "private_owner_evidence_association" } as const;
export type FeedbackAuthority = typeof FEEDBACK_AUTHORITY;
export type FeedbackDesignPin = { design_id: string; revision_id: string; record_sha256: string; next_action_sha256: string };
export type FeedbackChildPin = { design_id: string; revision_id: string; record_sha256: string };
export type FeedbackPin = { id: string; record_sha256: string };
export type FeedbackBaseline = DesignBaseline & { kind: "retained_result"; material_id: string; record_index: number; property_id: null };
export type FeedbackDecision = "continue" | "stop" | "redirect";
export type FeedbackRequest = { version: typeof FEEDBACK_REQUEST_VERSION; request_key: string } & (
  { operation: "return_evidence"; payload: { design: FeedbackDesignPin; evidence: FeedbackBaseline; findings: string; decision: FeedbackDecision; reason: string; unknowns: string[] } }
  | { operation: "link_follow_up"; payload: { feedback: FeedbackPin; child: FeedbackChildPin } }
);
const RECORD_FIELDS = ["id", "paper_id", "knowledge_origin", "evidence_type", "tc_kelvin", "tc_type", "tc_definition", "tc_criterion", "criterion", "measurement", "measurement_method", "method_statement", "pressure_gpa", "pressure_status", "pressure_kind", "pressure_conditions", "hc2_tesla", "hc2_tesla_unit", "hc2_conditions", "hc2_direction", "field_orientation", "magnetic_field_orientation"] as const;
const VALUE_FIELDS = ["raw_value", "input_unit", "raw_unit", "normalized_value", "normalized_unit", "status"] as const;
type Scalar = string | number | null;
type SourceValue = Record<typeof VALUE_FIELDS[number], Scalar>;
export type FeedbackRecord = Record<typeof RECORD_FIELDS[number], Scalar> & { scientific_values: Partial<Record<"tc_kelvin" | "hc2_tesla", SourceValue>> | null };
export type FeedbackProjection = { kind: "retained_result"; material_id: string; formula: string | null; record_index: number; source_snapshot_sha256: string; record: FeedbackRecord; withheld_fields: string[]; physical_association: "unestablished" };
export type FeedbackCapabilities = FeedbackAuthority & { version: string; request_version: string; actor_user_id: string; session_version: number; curator_grant_id: string; can_write: true; baseline_kinds: ["retained_result"]; action_kinds: ["source_review"]; decisions: ["continue", "stop", "redirect"]; operations: ["return_evidence", "link_follow_up"]; max_page_size: 8; max_operation_bytes: 32768 };
export type FeedbackContext = FeedbackAuthority & { version: string; actor_user_id: string; session_version: number; design: FeedbackDesignPin; evidence: FeedbackBaseline; context_sha256: string; projection: FeedbackProjection | null; projection_canonical_json: string | null; projection_sha256: string; eligibility: DesignEligibility };
export type FeedbackReceipt = FeedbackAuthority & { version: string; receipt_id: string; receipt_sha256: string; operation: FeedbackRequest["operation"]; design: FeedbackDesignPin; feedback_id: string; feedback_record_sha256: string; child: FeedbackChildPin | null; actor_user_id: string; actor_grant_id: string; actor_session_version: number; request_key: string; request_sha256: string; preview_sha256: string; request_canonical_json: string; preview_canonical_json: string; receipt_canonical_json: string; replayed: boolean; dry_run: boolean; pending_ledger_written: boolean };
/** Hashes and selectors only; never findings, source values or notes. */
export type FeedbackRecovery = { actorId: string; requestKey: string; requestSha: string; previewSha: string; receiptSha: string; receiptId: string; design: FeedbackDesignPin; operation: FeedbackRequest["operation"]; feedback: FeedbackPin | null; child: FeedbackChildPin | null };
export type FeedbackFollowUp = FeedbackAuthority & { id: string; record_sha256: string; child: FeedbackChildPin; eligibility: DesignEligibility; receipt: FeedbackReceipt };
export type FeedbackEntry = FeedbackAuthority & { id: string; record_sha256: string; design: FeedbackDesignPin; evidence: FeedbackBaseline; findings: string; decision: FeedbackDecision; reason: string; unknowns: string[]; context_sha256: string; projection_sha256: string; projection: FeedbackProjection | null; projection_canonical_json: string | null; eligibility: DesignEligibility; receipt: FeedbackReceipt; follow_ups: FeedbackFollowUp[] };
export type FeedbackPage = FeedbackAuthority & { version: string; actor_user_id: string; session_version: number; design_id: string; offset: number; limit: 8; total: number; entries: FeedbackEntry[] };

const AUTH_KEYS = Object.keys(FEEDBACK_AUTHORITY).join(" ");
const FLAG_KEYS = Object.keys(FEEDBACK_AUTHORITY).filter(k => k !== "scope").join(" ");
const RECEIPT_KEYS = `version receipt_id receipt_sha256 operation design feedback_id feedback_record_sha256 child actor_user_id actor_grant_id actor_session_version request_key request_sha256 preview_sha256 request_canonical_json preview_canonical_json receipt_canonical_json replayed dry_run pending_ledger_written ${AUTH_KEYS}`;
function detached<T>(value: T): T | null { try { return structuredClone(value); } catch { return null; } }
function same(a: unknown, b: unknown) { try { return expressionCanonical(a) === expressionCanonical(b); } catch { return false; } }
function integer(value: unknown, maximum = Number.MAX_SAFE_INTEGER): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 && value <= maximum; }
function authority(value: Record<string, unknown>) { return Object.entries(FEEDBACK_AUTHORITY).every(([k, v]) => value[k] === v); }
function flags(value: Record<string, unknown>) { return Object.entries(FEEDBACK_AUTHORITY).filter(([k]) => k !== "scope").every(([k, v]) => value[k] === v); }
function scoped(value: Record<string, unknown>, cap: FeedbackCapabilities) { return value.version === FEEDBACK_VERSION && value.actor_user_id === cap.actor_user_id && value.session_version === cap.session_version && authority(value); }
function decision(value: unknown): value is FeedbackDecision { return value === "continue" || value === "stop" || value === "redirect"; }
export function knownFeedbackDesignPin(value: unknown): value is FeedbackDesignPin { return designClosed(value, "design_id revision_id record_sha256 next_action_sha256") && designId(value.design_id) && designId(value.revision_id) && designHash(value.record_sha256) && designHash(value.next_action_sha256); }
export function knownFeedbackChildPin(value: unknown): value is FeedbackChildPin { return designClosed(value, "design_id revision_id record_sha256") && designId(value.design_id) && designId(value.revision_id) && designHash(value.record_sha256); }
function pin(value: unknown): value is FeedbackPin { return designClosed(value, "id record_sha256") && designId(value.id) && designHash(value.record_sha256); }
function baseline(value: unknown): value is FeedbackBaseline { return knownDesignBaseline(value) && value.kind === "retained_result"; }
function eligibility(value: unknown): value is DesignEligibility { return designClosed(value, "eligible reason_codes") && typeof value.eligible === "boolean" && Array.isArray(value.reason_codes) && value.reason_codes.length <= 32 && value.reason_codes.every(r => typeof r === "string" && /^[a-z][a-z0-9_]{0,159}$/.test(r)) && new Set(value.reason_codes).size === value.reason_codes.length && (value.eligible ? value.reason_codes.length === 0 : value.reason_codes.length > 0); }
function unknowns(value: unknown): value is string[] { return Array.isArray(value) && value.length <= 16 && value.every(s => designText(s, 1000)) && new Set(value).size === value.length; }
export function knownFeedbackRequest(value: unknown): value is FeedbackRequest {
  if (!designClosed(value, "version request_key operation payload") || value.version !== FEEDBACK_REQUEST_VERSION || typeof value.request_key !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$/.test(value.request_key)) return false;
  const p = value.payload;
  const valid = value.operation === "return_evidence"
    ? designClosed(p, "design evidence findings decision reason unknowns") && knownFeedbackDesignPin(p.design) && baseline(p.evidence) && designText(p.findings, 4000) && decision(p.decision) && designText(p.reason, 2000) && unknowns(p.unknowns)
    : value.operation === "link_follow_up" && designClosed(p, "feedback child") && pin(p.feedback) && knownFeedbackChildPin(p.child);
  try { return valid && new TextEncoder().encode(expressionCanonical(value)).length <= FEEDBACK_MAX_BYTES; } catch { return false; }
}
export async function feedbackDesignPin(entry: DesignEntry): Promise<FeedbackDesignPin | null> {
  const copy = detached(entry); if (!copy || !designId(copy.design_id) || !designId(copy.id) || !designHash(copy.record_sha256)) return null;
  return { design_id: copy.design_id, revision_id: copy.id, record_sha256: copy.record_sha256, next_action_sha256: await expressionSha(expressionCanonical(copy.design.next_action)) };
}
/** The fragment uses the original retained array index, before display sorting or visibility filtering. */
export function feedbackRecordHref(materialId: string, recordIndex: number): string | null {
  return designText(materialId, 100) && integer(recordIndex, 4999) ? `/materials/${encodeURIComponent(materialId)}#retained-record-${recordIndex}` : null;
}
/** Read only after knownDesignDetail verifies the complete owner-scoped history. */
export function feedbackChildFromDetail(detail: DesignDetail, parent: FeedbackDesignPin): FeedbackChildPin | null {
  const copy = detached(detail), pin = detached(parent), head = copy?.entries[0];
  if (!copy || !pin || !knownFeedbackDesignPin(pin) || !head || head.design_id !== copy.design_id || !head.is_head || head.revision !== 1 || head.operation !== "propose" || head.status !== "proposed" || !head.eligibility.eligible || !same(head.parent, { design_id: pin.design_id, revision_id: pin.revision_id, record_sha256: pin.record_sha256 })) return null;
  const child = { design_id: head.design_id, revision_id: head.id, record_sha256: head.record_sha256 };
  return knownFeedbackChildPin(child) ? child : null;
}
export function knownFeedbackCapabilities(value: unknown, design: DesignCapabilities): FeedbackCapabilities | null {
  const v = detached(value), d = detached(design);
  if (!v || !d || !designClosed(v, `version request_version actor_user_id session_version curator_grant_id can_write baseline_kinds action_kinds decisions operations max_page_size max_operation_bytes ${AUTH_KEYS}`)
    || v.version !== FEEDBACK_VERSION || v.request_version !== FEEDBACK_REQUEST_VERSION || v.actor_user_id !== d.actor_user_id || v.session_version !== d.session_version || v.curator_grant_id !== d.curator_grant_id || v.can_write !== true || !authority(v)
    || !same(v.baseline_kinds, ["retained_result"]) || !same(v.action_kinds, ["source_review"]) || !same(v.decisions, ["continue", "stop", "redirect"]) || !same(v.operations, ["return_evidence", "link_follow_up"]) || v.max_page_size !== 8 || v.max_operation_bytes !== FEEDBACK_MAX_BYTES) return null;
  return v as FeedbackCapabilities;
}
function scalar(value: unknown, maximum = 2000): value is Scalar { return value === null || typeof value === "number" && Number.isFinite(value) || typeof value === "string" && Array.from(value).length <= maximum && !/[\u0000-\u001f\u007f\ud800-\udfff]/u.test(value); }
function projection(value: unknown, evidence: FeedbackBaseline): value is FeedbackProjection {
  if (!designClosed(value, "kind material_id formula record_index source_snapshot_sha256 record withheld_fields physical_association") || value.kind !== "retained_result" || value.material_id !== evidence.material_id || value.record_index !== evidence.record_index || !scalar(value.formula, 500) || !(value.formula === null || typeof value.formula === "string") || value.source_snapshot_sha256 !== evidence.expected_context_sha256 || !designHash(value.source_snapshot_sha256) || value.physical_association !== "unestablished"
    || !designClosed(value.record, `${RECORD_FIELDS.join(" ")} scientific_values`)) return false;
  const record = value.record;
  if (!RECORD_FIELDS.every(k => scalar(record[k], k.endsWith("_unit") ? 40 : 2000))) return false;
  const values = record.scientific_values;
  if (values !== null && (!designObject(values) || Object.keys(values).length < 1 || Object.keys(values).length > 2 || Object.keys(values).some(k => k !== "tc_kelvin" && k !== "hc2_tesla") || !Object.values(values).every(v => designClosed(v, VALUE_FIELDS.join(" ")) && VALUE_FIELDS.every(k => scalar(v[k], k.endsWith("unit") ? 40 : 500))))) return false;
  const allowed = new Set<string>([...RECORD_FIELDS, "scientific_values", ...["tc_kelvin", "hc2_tesla"].flatMap(field => [`scientific_values.${field}`, ...VALUE_FIELDS.map(k => `scientific_values.${field}.${k}`)])]);
  return Array.isArray(value.withheld_fields) && value.withheld_fields.length <= allowed.size && value.withheld_fields.every(k => typeof k === "string" && allowed.has(k)) && new Set(value.withheld_fields).size === value.withheld_fields.length;
}
async function proof(text: unknown, hash: unknown, maximum = 262144): Promise<Record<string, unknown> | null> {
  try { if (typeof text !== "string" || new TextEncoder().encode(text).length > maximum || !designHash(hash) || await expressionSha(text) !== hash) return null; const parsed = parseExpressionJson(text); return designObject(parsed) && expressionCanonical(parsed) === text ? parsed : null; } catch { return null; }
}
/** Compare already-bounded source DTOs, while retaining original SQL decimal proof bytes. */
function projectionEqual(left: unknown, right: unknown): boolean {
  let nodes = 0;
  function equal(a: unknown, b: unknown, depth: number): boolean {
    if (++nodes > 1000 || depth > 12) return false;
    if (a === b) return a === null || typeof a === "string" || typeof a === "boolean" || typeof a === "number" && Number.isFinite(a);
    if (Array.isArray(a) || Array.isArray(b)) return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((item, i) => equal(item, b[i], depth + 1));
    if (!designObject(a) || !designObject(b)) return false;
    const keys = Object.keys(a); return keys.length === Object.keys(b).length && keys.every(k => Object.hasOwn(b, k) && equal(a[k], b[k], depth + 1));
  }
  return equal(left, right, 0);
}
async function verifiedProjection(value: FeedbackProjection | null, text: string | null, hash: string, evidence: FeedbackBaseline, eligible: boolean) {
  if (value === null) return !eligible && text === null && designHash(hash);
  if (!eligible) return false;
  if (!projection(value, evidence) || typeof text !== "string" || new TextEncoder().encode(text).length > 16384 || !designHash(hash) || await expressionSha(text) !== hash) return false;
  // Backend decimal tokens keep their exact canonical bytes; do not rewrite 1.0 to 1.
  try { return projectionEqual(parseExpressionJson(text, false), value); } catch { return false; }
}
export async function knownFeedbackContext(value: unknown, capabilities: FeedbackCapabilities, expected: { design: FeedbackDesignPin; materialId: string; recordIndex: number }): Promise<FeedbackContext | null> {
  const v = detached(value), cap = detached(capabilities), exp = detached(expected);
  if (!v || !cap || !exp || !designClosed(v, `version actor_user_id session_version design evidence context_sha256 projection projection_canonical_json projection_sha256 eligibility ${AUTH_KEYS}`) || !scoped(v, cap) || !same(v.design, exp.design) || !knownFeedbackDesignPin(v.design) || !baseline(v.evidence) || v.evidence.material_id !== exp.materialId || v.evidence.record_index !== exp.recordIndex || v.context_sha256 !== v.evidence.expected_context_sha256 || !designHash(v.context_sha256) || !designHash(v.projection_sha256) || !eligibility(v.eligibility)) return null;
  if (!await verifiedProjection(v.projection as FeedbackProjection | null, v.projection_canonical_json as string | null, v.projection_sha256, v.evidence, v.eligibility.eligible)) return null;
  return v as FeedbackContext;
}

export function knownFeedbackRecovery(value: unknown): value is FeedbackRecovery {
  return designClosed(value, "actorId requestKey requestSha previewSha receiptSha receiptId design operation feedback child") && designId(value.actorId) && typeof value.requestKey === "string" && /^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$/.test(value.requestKey) && designHash(value.requestSha) && designHash(value.previewSha) && designHash(value.receiptSha) && designId(value.receiptId) && knownFeedbackDesignPin(value.design)
    && (value.operation === "return_evidence" ? value.feedback === null && value.child === null : value.operation === "link_follow_up" && pin(value.feedback) && knownFeedbackChildPin(value.child));
}
type ReceiptExpectation = Pick<FeedbackRecovery, "actorId" | "requestKey" | "requestSha" | "design" | "operation" | "feedback" | "child"> & Partial<Pick<FeedbackRecovery, "previewSha" | "receiptSha" | "receiptId">>;
export async function knownFeedbackReceipt(value: unknown, capabilities: FeedbackCapabilities, expected: ReceiptExpectation, mode: "preview" | "commit" | "outcome" | "history"): Promise<FeedbackReceipt | null> {
  const v = detached(value), cap = detached(capabilities), exp = detached(expected);
  if (!v || !cap || !exp || !designClosed(v, RECEIPT_KEYS) || v.version !== FEEDBACK_VERSION || !authority(v) || !designId(v.receipt_id) || !designHash(v.receipt_sha256) || !designId(v.feedback_id) || !designHash(v.feedback_record_sha256) || !knownFeedbackDesignPin(v.design) || !same(v.design, exp.design)
    || v.actor_user_id !== cap.actor_user_id || v.actor_user_id !== exp.actorId || !designId(v.actor_grant_id) || !integer(v.actor_session_version) || v.request_key !== exp.requestKey || v.request_sha256 !== exp.requestSha || !designHash(v.request_sha256) || !designHash(v.preview_sha256) || v.operation !== exp.operation || typeof v.replayed !== "boolean" || typeof v.dry_run !== "boolean" || typeof v.pending_ledger_written !== "boolean") return null;
  if (mode === "preview") {
    if (v.dry_run !== !v.replayed || v.pending_ledger_written !== v.replayed) return null;
    if (!v.replayed && (v.actor_grant_id !== cap.curator_grant_id || v.actor_session_version !== cap.session_version)) return null;
  } else if (v.dry_run || !v.pending_ledger_written) return null;
  if (mode === "outcome" && !v.replayed) return null;
  if (mode === "commit" && !v.replayed && (v.actor_grant_id !== cap.curator_grant_id || v.actor_session_version !== cap.session_version)) return null;
  if (mode !== "preview" && ["previewSha", "receiptSha", "receiptId"].some(k => exp[k as keyof ReceiptExpectation] !== undefined && exp[k as keyof ReceiptExpectation] !== v[({ previewSha: "preview_sha256", receiptSha: "receipt_sha256", receiptId: "receipt_id" } as const)[k as "previewSha" | "receiptSha" | "receiptId"]])) return null;
  const [request, preview, record] = await Promise.all([proof(v.request_canonical_json, v.request_sha256, FEEDBACK_MAX_BYTES), proof(v.preview_canonical_json, v.preview_sha256), proof(v.receipt_canonical_json, v.receipt_sha256)]);
  if (!request || !preview || !record || !knownFeedbackRequest(request) || request.operation !== v.operation || request.request_key !== v.request_key || record.request_json !== v.request_canonical_json || !same(record.payload, request.payload)) return null;
  const common = "id actor_user_id actor_grant_id actor_session_version operation request_key request_json payload request_sha256 preview_json preview_sha256";
  const actor = { actor_user_id: v.actor_user_id, actor_grant_id: v.actor_grant_id, actor_session_version: v.actor_session_version };
  if (record.id !== v.receipt_id || record.actor_user_id !== v.actor_user_id || record.actor_grant_id !== v.actor_grant_id || record.actor_session_version !== v.actor_session_version || record.operation !== v.operation || record.request_key !== v.request_key || record.request_sha256 !== v.request_sha256 || record.preview_sha256 !== v.preview_sha256 || record.preview_json !== v.preview_canonical_json || !flags(record)
    || preview.version !== FEEDBACK_VERSION || !same(preview.actor, actor) || preview.request_sha256 !== v.request_sha256 || preview.receipt_id !== v.receipt_id || preview.feedback_id !== v.feedback_id) return null;
  if (request.operation === "return_evidence") {
    const p = request.payload;
    if (!designClosed(record, `${common} design_ref design_revision_id evidence findings decision reason unknowns context_sha256 projection_sha256 ${FLAG_KEYS}`) || !designClosed(preview, "version actor request_sha256 receipt_id feedback_id design context_sha256 projection_sha256")
      || v.child !== null || v.feedback_id !== v.receipt_id || v.feedback_record_sha256 !== v.receipt_sha256 || exp.feedback !== null || exp.child !== null
      || !same(p.design, v.design) || !same(record.design_ref, p.design) || record.design_revision_id !== p.design.revision_id || !same(preview.design, p.design) || !same(record.evidence, p.evidence) || record.findings !== p.findings || record.decision !== p.decision || record.reason !== p.reason || !same(record.unknowns, p.unknowns)
      || record.context_sha256 !== p.evidence.expected_context_sha256 || preview.context_sha256 !== record.context_sha256 || !designHash(record.context_sha256) || !designHash(record.projection_sha256) || preview.projection_sha256 !== record.projection_sha256) return null;
  } else {
    const p = request.payload;
    if (!designClosed(record, `${common} feedback_id feedback_record_sha256 child child_revision_id ${FLAG_KEYS}`) || !designClosed(preview, "version actor request_sha256 receipt_id feedback_id feedback_record_sha256 child")
      || !knownFeedbackChildPin(v.child) || !same(v.child, p.child) || !same(v.child, exp.child) || !same(p.feedback, exp.feedback) || v.feedback_id !== p.feedback.id || v.feedback_record_sha256 !== p.feedback.record_sha256
      || record.feedback_id !== v.feedback_id || record.feedback_record_sha256 !== v.feedback_record_sha256 || preview.feedback_record_sha256 !== v.feedback_record_sha256 || !same(record.child, v.child) || record.child_revision_id !== v.child.revision_id || !same(preview.child, v.child)) return null;
  }
  return v as FeedbackReceipt;
}
export async function knownFeedbackPage(value: unknown, capabilities: FeedbackCapabilities, designId: string, offset: number): Promise<FeedbackPage | null> {
  const v = detached(value), cap = detached(capabilities);
  if (!v || !cap || !designClosed(v, `version actor_user_id session_version design_id offset limit total entries ${AUTH_KEYS}`) || !scoped(v, cap) || v.design_id !== designId || !designIdValid(designId) || v.offset !== offset || !integer(offset, 1000) || v.limit !== 8 || !integer(v.total) || !Array.isArray(v.entries) || v.entries.length !== Math.min(8, Math.max(0, v.total - offset))) return null;
  const seen = new Set<string>();
  for (const e of v.entries) {
    if (!designClosed(e, `id record_sha256 design evidence findings decision reason unknowns context_sha256 projection_sha256 projection projection_canonical_json eligibility receipt follow_ups ${AUTH_KEYS}`) || !authority(e) || !designIdValid(e.id) || seen.has(e.id) || !designHash(e.record_sha256) || !knownFeedbackDesignPin(e.design) || e.design.design_id !== designId || !baseline(e.evidence) || !designText(e.findings, 4000) || !decision(e.decision) || !designText(e.reason, 2000) || !unknowns(e.unknowns) || e.context_sha256 !== e.evidence.expected_context_sha256 || !designHash(e.context_sha256) || !designHash(e.projection_sha256) || !eligibility(e.eligibility) || !designObject(e.receipt) || !Array.isArray(e.follow_ups) || e.follow_ups.length > 8) return null;
    const receipt = await knownFeedbackReceipt(e.receipt, cap, { actorId: cap.actor_user_id, requestKey: e.receipt.request_key as string, requestSha: e.receipt.request_sha256 as string, design: e.design, operation: "return_evidence", feedback: null, child: null, receiptId: e.id, receiptSha: e.record_sha256 }, "history");
    if (!receipt || receipt.feedback_id !== e.id || receipt.feedback_record_sha256 !== e.record_sha256) return null;
    const request = parseExpressionJson(receipt.request_canonical_json) as FeedbackRequest;
    if (request.operation !== "return_evidence" || !same(request.payload.evidence, e.evidence) || request.payload.findings !== e.findings || request.payload.decision !== e.decision || request.payload.reason !== e.reason || !same(request.payload.unknowns, e.unknowns)) return null;
    const record = parseExpressionJson(receipt.receipt_canonical_json) as Record<string, unknown>;
    if (record.context_sha256 !== e.context_sha256 || record.projection_sha256 !== e.projection_sha256 || !await verifiedProjection(e.projection as FeedbackProjection | null, e.projection_canonical_json as string | null, e.projection_sha256, e.evidence, e.eligibility.eligible)) return null;
    const links = new Set<string>(), children = new Set<string>();
    for (const link of e.follow_ups) {
      if (!designClosed(link, `id record_sha256 child eligibility receipt ${AUTH_KEYS}`) || !authority(link) || !designIdValid(link.id) || links.has(link.id) || !designHash(link.record_sha256) || !knownFeedbackChildPin(link.child) || children.has(link.child.design_id) || !eligibility(link.eligibility) || !designObject(link.receipt)) return null;
      const verified = await knownFeedbackReceipt(link.receipt, cap, { actorId: cap.actor_user_id, requestKey: link.receipt.request_key as string, requestSha: link.receipt.request_sha256 as string, design: e.design, operation: "link_follow_up", feedback: { id: e.id, record_sha256: e.record_sha256 }, child: link.child, receiptId: link.id, receiptSha: link.record_sha256 }, "history");
      if (!verified) return null; links.add(link.id); children.add(link.child.design_id);
    }
    seen.add(e.id);
  }
  return v as FeedbackPage;
}
// Avoid shadowing the imported UUID predicate with the requested page selector.
const designIdValid = designId;
