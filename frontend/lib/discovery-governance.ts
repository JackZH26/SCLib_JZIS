import { parsePreparedScientificPayload, parsePrivateDiscoveryJSON, type ScientificPayload } from "./discovery-scientific";
import { privateDiscoveryText, selectionCode, selectionTextHash, selectionUUID } from "./discovery-selection";

export const HISTORY_VERSION = "discovery-operator-history/1.0.0";
const VERSION = "discovery-projection-governance/1.0.0", SCOPE = "discovery_scientific_projection";
export const GOVERNANCE_FAILURE = "The exact governance response could not be verified. Refresh the recorded history before continuing.";
const authority = ["scientific_acceptance", "ml_training_approved", "current_authorization_checked", "public_release_authorized"];
type Authority = { scientific_acceptance: false; ml_training_approved: false; current_authorization_checked: false; public_release_authorized: false };
export type OperatorRole = "curator" | "publisher" | "reviewer";
export type OperatorAccess = Authority & { version: typeof HISTORY_VERSION; scope: typeof SCOPE; actor_user_id: string;
  grants: { role: OperatorRole; id: string }[]; admission_scope: "current_read_snapshot_role_only" };
type Ledger = { id: string; record_sha256: string; created_at: string; actor_user_id: string; actor_grant_id: string };
export type GovernancePackage = Ledger & { distribution_package_id: string; distribution_record_sha256: string; inventory_sha256: string; payload_sha256: string; selection_sha256: string };
type BoundLedger = Ledger & { package_id: string; payload_sha256: string; selection_sha256: string; reason_code: string };
export type GovernanceReview = BoundLedger & { decision: "approve" | "reject"; representative_selection_approved: boolean; disclosure_approved: boolean; rights_sha256: string };
export type GovernanceAction = BoundLedger & { review_id: string; kind: "publish" | "withdraw" };
export type GovernanceHeader = Authority & { version: typeof HISTORY_VERSION; scope: typeof SCOPE; actor_user_id: string; package: GovernancePackage;
  history_sha256: string; review_count: number; rejection_count: number; has_rejection: boolean; actions: GovernanceAction[]; has_withdrawal: boolean;
  current_publication_eligibility: "not_checked"; history_semantics: "append_only_any_rejection_holds" };
export type ReviewPage = GovernanceHeader & { reviews: GovernanceReview[]; after: string | null; next_after: string | null; page_size: 25; returned_count: number;
  history_order: "created_at_then_id_ascending" };
export type RightsTarget = { dependency_id: string; row_sha256: string };
export type ProjectionRight = RightsTarget & { license_code: "CC0-1.0" | "CC-BY-4.0" | "CC-BY-SA-4.0" | "permission-on-file"; basis_code: string };
export type CurrentInspection = { package_id: string; payload_sha256: string; selection_sha256: string; payload: ScientificPayload; rights_targets: RightsTarget[] };
export type GovernanceRecovery = { actorId: string; operation: "review" | "publish" | "withdraw"; requestKey: string; requestSha256: string;
  packageId: string; payloadSha256: string; selectionSha256: string; reviewId: string | null };
export type GovernanceDraft = { recovery: GovernanceRecovery; grantId: string; historySha256: string; previewJSON: string; commitJSON: string;
  decision: "approve" | "reject" | "publish" | "withdraw" };
export type GovernanceReceipt = { id: string; package_id: string; record_sha256: string; payload_sha256: string; selection_sha256: string; request_sha256: string;
  operation: GovernanceRecovery["operation"]; replayed: boolean };
type Obj = Record<string, unknown>;
function requireValue(v: unknown): asserts v { if (!v) throw new Error(GOVERNANCE_FAILURE); }
const obj = (v: unknown): v is Obj => v !== null && typeof v === "object" && !Array.isArray(v);
const closed = (v: unknown, keys: string[]): v is Obj => obj(v) && Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));
const sha = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const integer = (v: unknown, max: number): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0 && v <= max;
const ordered = (values: string[]) => values.every((v, i) => !i || values[i - 1] < v);
const time = (v: unknown): v is string => typeof v === "string" && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$/.test(v)
  && Number.isFinite(Date.parse(v)) && new Date(v).toISOString() === `${v.slice(0, 23)}Z`;
const baseFields = ["id", "record_sha256", "created_at", "actor_user_id", "actor_grant_id"];
const packageFields = [...baseFields, "distribution_package_id", "distribution_record_sha256", "inventory_sha256", "payload_sha256", "selection_sha256"];
const boundFields = [...baseFields, "package_id", "payload_sha256", "selection_sha256", "reason_code"];
const headerFields = ["version", "scope", "actor_user_id", "package", "history_sha256", "review_count", "rejection_count", "has_rejection", "actions", "has_withdrawal",
  "current_publication_eligibility", "history_semantics", ...authority];
const pageFields = ["reviews", "after", "next_after", "page_size", "returned_count", "history_order"];
const ledger = (v: Obj) => selectionUUID(v.id) && sha(v.record_sha256) && time(v.created_at) && selectionUUID(v.actor_user_id) && selectionUUID(v.actor_grant_id);
function bound(v: Obj, p: GovernancePackage) {
  return ledger(v) && v.package_id === p.id && v.payload_sha256 === p.payload_sha256 && v.selection_sha256 === p.selection_sha256
    && v.actor_user_id !== p.actor_user_id && selectionCode(v.reason_code);
}
function parse(raw: string, max: number) { return parsePrivateDiscoveryJSON(raw, max).value; }
/** Only non-floating command/metadata trees use this encoder. Scientific
 * payloads and their Python numeric spelling are never reserialized here. */
export function governanceCanonical(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(governanceCanonical).join(",")}]`;
  if (obj(v)) return `{${Object.keys(v).sort().map(k => `${JSON.stringify(k)}:${governanceCanonical(v[k])}`).join(",")}}`;
  requireValue(v === null || typeof v === "boolean" || typeof v === "string" || typeof v === "number" && Number.isSafeInteger(v) && !Object.is(v, -0));
  return JSON.stringify(v);
}
export const roleGrant = (a: OperatorAccess, role: OperatorRole) => a.grants.find(g => g.role === role)?.id ?? null;
export function parseOperatorAccess(raw: string): OperatorAccess {
  const v = parse(raw, 8192);
  requireValue(closed(v, ["version", "scope", "actor_user_id", "grants", "admission_scope", ...authority]) && v.version === HISTORY_VERSION && v.scope === SCOPE
    && selectionUUID(v.actor_user_id) && v.admission_scope === "current_read_snapshot_role_only" && authority.every(k => v[k] === false)
    && Array.isArray(v.grants) && v.grants.length > 0 && v.grants.length <= 3);
  requireValue(v.grants.every(g => closed(g, ["role", "id"]) && ["curator", "publisher", "reviewer"].includes(g.role as string) && selectionUUID(g.id)));
  requireValue(ordered(v.grants.map(g => g.role)) && new Set(v.grants.map(g => g.id)).size === v.grants.length);
  return v as OperatorAccess;
}
function checkHeader(v: unknown, a: OperatorAccess, packageId: string, extra: string[] = []): asserts v is GovernanceHeader {
  requireValue(closed(v, [...headerFields, ...extra]) && v.version === HISTORY_VERSION && v.scope === SCOPE && v.actor_user_id === a.actor_user_id
    && v.current_publication_eligibility === "not_checked" && v.history_semantics === "append_only_any_rejection_holds" && authority.every(k => v[k] === false)
    && sha(v.history_sha256) && integer(v.review_count, 1000) && integer(v.rejection_count, v.review_count) && v.has_rejection === (v.rejection_count > 0));
  requireValue(closed(v.package, packageFields) && ledger(v.package) && v.package.id === packageId && selectionUUID(v.package.distribution_package_id)
    && [v.package.distribution_record_sha256, v.package.inventory_sha256, v.package.payload_sha256, v.package.selection_sha256].every(sha));
  const p = v.package as GovernancePackage;
  requireValue(Array.isArray(v.actions) && v.actions.length <= 2);
  requireValue(v.actions.every(row => closed(row, [...boundFields, "review_id", "kind"]) && bound(row, p) && selectionUUID(row.review_id) && ["publish", "withdraw"].includes(row.kind as string)));
  requireValue(ordered(v.actions.map(row => row.kind)) && v.has_withdrawal === v.actions.some(row => row.kind === "withdraw"));
}
export function parseGovernanceHeader(raw: string, access: OperatorAccess, packageId: string): GovernanceHeader {
  const v = parse(raw, 16384); checkHeader(v, access, packageId); return v;
}
export function parseReviewPage(raw: string, access: OperatorAccess, header: GovernanceHeader, after: string | null): ReviewPage {
  const v = parse(raw, 131072); checkHeader(v, access, header.package.id, pageFields);
  requireValue(headerFields.every(k => governanceCanonical((v as unknown as Obj)[k]) === governanceCanonical((header as unknown as Obj)[k])));
  const p = v as ReviewPage;
  requireValue(p.after === after && (p.next_after === null || selectionUUID(p.next_after)) && p.page_size === 25 && integer(p.returned_count, 25)
    && p.history_order === "created_at_then_id_ascending" && Array.isArray(p.reviews) && p.reviews.length === p.returned_count
    && p.returned_count <= p.review_count);
  for (const row of p.reviews) requireValue(closed(row, [...boundFields, "decision", "representative_selection_approved", "disclosure_approved", "rights_sha256"])
    && bound(row, header.package) && ["approve", "reject"].includes(row.decision) && typeof row.representative_selection_approved === "boolean"
    && typeof row.disclosure_approved === "boolean" && sha(row.rights_sha256)
    && (row.decision !== "approve" || row.representative_selection_approved && row.disclosure_approved));
  requireValue(ordered(p.reviews.map(r => `${r.created_at}:${r.id}`)) && !p.reviews.some(r => r.id === after)
    && (p.next_after === null || p.returned_count === 25 && p.next_after === p.reviews.at(-1)?.id));
  return p;
}
export async function verifyCompleteHistory(header: GovernanceHeader, reviews: GovernanceReview[]) {
  requireValue(reviews.length === header.review_count && ordered(reviews.map(r => `${r.created_at}:${r.id}`))
    && new Set(reviews.map(r => r.id)).size === reviews.length && reviews.filter(r => r.decision === "reject").length === header.rejection_count);
  for (const action of header.actions) {
    const r = reviews.find(r => r.id === action.review_id);
    requireValue(r?.decision === "approve" && r.actor_user_id !== action.actor_user_id);
  }
  requireValue(await selectionTextHash(governanceCanonical({ version: HISTORY_VERSION, package: header.package, reviews, actions: header.actions })) === header.history_sha256);
}
export async function parseCurrentInspection(raw: string, header: GovernanceHeader): Promise<CurrentInspection> {
  header = structuredClone(header);
  const parsed = parsePrivateDiscoveryJSON(raw, 8 * 1024 * 1024, ["payload"]), v = parsed.value;
  requireValue(closed(v, ["version", "package_id", "payload_sha256", "selection_sha256", "payload", "rights_targets", "scope", ...authority.slice(0, 3)])
    && v.version === VERSION && v.scope === SCOPE && v.package_id === header.package.id && v.payload_sha256 === header.package.payload_sha256
    && v.selection_sha256 === header.package.selection_sha256 && authority.slice(0, 3).every(k => v[k] === false)
    && Array.isArray(v.rights_targets) && v.rights_targets.length > 0 && v.rights_targets.length <= 20000);
  requireValue(v.rights_targets.every(t => closed(t, ["dependency_id", "row_sha256"]) && sha(t.dependency_id) && sha(t.row_sha256))
    && ordered(v.rights_targets.map(t => t.dependency_id)));
  const checked = await parsePreparedScientificPayload(parsed.spans.get("payload")!, header.package.payload_sha256, header.package.selection_sha256);
  requireValue(checked.payload.base.distribution_package_id === header.package.distribution_package_id
    && checked.payload.base.distribution_record_sha256 === header.package.distribution_record_sha256 && checked.payload.base.inventory_sha256 === header.package.inventory_sha256);
  return { package_id: header.package.id, payload_sha256: header.package.payload_sha256, selection_sha256: header.package.selection_sha256,
    payload: checked.payload, rights_targets: v.rights_targets as RightsTarget[] };
}
export async function readProjectionRights(file: File, targets: RightsTarget[]): Promise<ProjectionRight[]> {
  requireValue(file.size > 0 && file.size <= 8 * 1024 * 1024);
  targets = structuredClone(targets); const bytes = await file.arrayBuffer(); requireValue(bytes.byteLength === file.size);
  const raw = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes), rows = parse(raw, 8 * 1024 * 1024);
  requireValue(Array.isArray(rows) && rows.length === targets.length && rows.length <= 20000);
  rows.forEach((r, i) => requireValue(closed(r, ["dependency_id", "row_sha256", "license_code", "basis_code"])
    && r.dependency_id === targets[i].dependency_id && r.row_sha256 === targets[i].row_sha256
    && ["CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "permission-on-file"].includes(r.license_code as string) && selectionCode(r.basis_code)));
  return rows as ProjectionRight[];
}
export async function prepareGovernanceDraft(options: { access: OperatorAccess; header: GovernanceHeader; decision: GovernanceDraft["decision"]; reasonCode: string;
  rights: ProjectionRight[]; representativeApproved: boolean; disclosureApproved: boolean; review: GovernanceReview | null; current: CurrentInspection | null;
  historyComplete: boolean; requestKey: string }): Promise<GovernanceDraft> {
  const o = structuredClone(options), operation = o.decision === "approve" || o.decision === "reject" ? "review" : o.decision;
  const role = operation === "review" ? "reviewer" : "publisher", grant = roleGrant(o.access, role), p = o.header.package;
  requireValue(grant && o.access.actor_user_id === o.header.actor_user_id && o.access.actor_user_id !== p.actor_user_id && selectionCode(o.reasonCode)
    && /^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$/.test(o.requestKey));
  if (o.decision === "approve" || o.decision === "publish") requireValue(o.current && o.historyComplete
    && o.current.package_id === p.id && o.current.payload_sha256 === p.payload_sha256 && o.current.selection_sha256 === p.selection_sha256);
  let command: Obj, hashBody: Obj;
  const pins = { expected_payload_sha256: p.payload_sha256, expected_selection_sha256: p.selection_sha256 };
  if (operation === "review") {
    requireValue(o.decision === "reject" || o.representativeApproved && o.disclosureApproved && o.current
      && o.rights.length === o.current.rights_targets.length && o.rights.every((r, i) => closed(r, ["dependency_id", "row_sha256", "license_code", "basis_code"])
        && r.dependency_id === o.current!.rights_targets[i].dependency_id
        && r.row_sha256 === o.current!.rights_targets[i].row_sha256 && selectionCode(r.basis_code)
        && ["CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "permission-on-file"].includes(r.license_code)));
    command = { ...pins, decision: o.decision, rights: o.decision === "reject" ? [] : o.rights,
      representative_selection_approved: o.decision === "approve" && o.representativeApproved,
      disclosure_approved: o.decision === "approve" && o.disclosureApproved, reason_code: o.reasonCode };
    hashBody = { package_id: p.id, payload_sha256: p.payload_sha256, selection_sha256: p.selection_sha256, decision: command.decision, rights: command.rights,
      representative_selection_approved: command.representative_selection_approved, disclosure_approved: command.disclosure_approved, reason_code: o.reasonCode, scope: SCOPE };
  } else {
    requireValue(o.review && o.review.decision === "approve" && o.review.package_id === p.id && o.review.payload_sha256 === p.payload_sha256
      && o.review.selection_sha256 === p.selection_sha256 && new Set([o.access.actor_user_id, o.review.actor_user_id, p.actor_user_id]).size === 3);
    if (operation === "publish") requireValue(!o.header.has_rejection && !o.header.has_withdrawal && o.header.actions.length === 0
      && o.current!.payload.rows.some(r => r.cells.some(c => c.observations.some(v => v.scientific_scope_accepted))));
    else requireValue(!o.header.has_withdrawal);
    command = { ...pins, review_id: o.review.id, kind: operation, reason_code: o.reasonCode };
    hashBody = { package_id: p.id, payload_sha256: p.payload_sha256, selection_sha256: p.selection_sha256, review_id: o.review.id, kind: operation, reason_code: o.reasonCode };
  }
  const requestSha = await selectionTextHash(governanceCanonical({ version: VERSION, operation, ...hashBody }));
  return { grantId: grant, historySha256: o.header.history_sha256, decision: o.decision,
    recovery: { actorId: o.access.actor_user_id, operation, requestKey: o.requestKey, requestSha256: requestSha, packageId: p.id,
      payloadSha256: p.payload_sha256, selectionSha256: p.selection_sha256, reviewId: operation === "review" ? null : o.review!.id },
    previewJSON: governanceCanonical({ ...command, request_key: o.requestKey, dry_run: true }),
    commitJSON: governanceCanonical({ ...command, request_key: o.requestKey, dry_run: false }) };
}
export function parseGovernanceReceipt(raw: string, ref: GovernanceRecovery, committed: boolean, recovered = false): GovernanceReceipt {
  requireValue(selectionUUID(ref.actorId) && selectionUUID(ref.packageId) && [ref.requestSha256, ref.payloadSha256, ref.selectionSha256].every(sha)
    && ["review", "publish", "withdraw"].includes(ref.operation) && (ref.operation === "review" ? ref.reviewId === null : selectionUUID(ref.reviewId)));
  const v = parse(raw, 8192);
  requireValue(closed(v, ["version", "dry_run", "committed", "result"]) && v.version === "research-distribution-operation/1.0.0" && v.dry_run === !committed && v.committed === committed);
  const r = v.result;
  requireValue(closed(r, ["version", "operation", "id", "package_id", "record_sha256", "payload_sha256", "selection_sha256", "request_sha256", "dry_run", "committed", "replayed", ...authority.slice(0, 3)])
    && r.version === VERSION && r.operation === ref.operation && selectionUUID(r.id) && r.package_id === ref.packageId && sha(r.record_sha256)
    && r.payload_sha256 === ref.payloadSha256 && r.selection_sha256 === ref.selectionSha256 && r.request_sha256 === ref.requestSha256
    && r.dry_run === !committed && r.committed === false && typeof r.replayed === "boolean" && (!recovered || r.replayed) && authority.slice(0, 3).every(k => r[k] === false));
  return r as unknown as GovernanceReceipt;
}
export const getOperatorAccess = (signal?: AbortSignal) => privateDiscoveryText("/operator/access", 8192, signal);
export function getGovernanceHeader(id: string, signal?: AbortSignal) {
  requireValue(selectionUUID(id)); return privateDiscoveryText(`/${id}/governance`, 16384, signal);
}
export function getReviewPage(header: GovernanceHeader, after: string | null, signal?: AbortSignal) {
  requireValue(selectionUUID(header.package.id) && sha(header.history_sha256) && (after === null || selectionUUID(after)));
  const params = new URLSearchParams({ expected_history_sha256: header.history_sha256, ...(after === null ? {} : { after }) });
  return privateDiscoveryText(`/${header.package.id}/reviews?${params}`, 131072, signal);
}
export function getCurrentInspection(id: string, signal?: AbortSignal) {
  requireValue(selectionUUID(id)); return privateDiscoveryText(`/${id}`, 8 * 1024 * 1024, signal);
}
export function postGovernance(draft: GovernanceDraft, commit: boolean, signal?: AbortSignal) {
  requireValue(selectionUUID(draft.recovery.packageId)); const body = commit ? draft.commitJSON : draft.previewJSON;
  requireValue(new TextEncoder().encode(body).length <= 20 * 1024 * 1024);
  return privateDiscoveryText(`/${draft.recovery.packageId}/${draft.recovery.operation === "review" ? "reviews" : "actions"}`, 8192, signal, body);
}
export function getGovernanceOutcome(ref: GovernanceRecovery, signal?: AbortSignal) {
  requireValue(selectionUUID(ref.actorId) && selectionUUID(ref.packageId) && ["review", "publish", "withdraw"].includes(ref.operation) && sha(ref.requestSha256)
    && /^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$/.test(ref.requestKey));
  const params = new URLSearchParams({ operation: ref.operation, request_key: ref.requestKey, expected_request_sha256: ref.requestSha256 });
  return privateDiscoveryText(`/outcome?${params}`, 8192, signal);
}
