/** Exact own-review declarations. No scientific acceptance or execution authority. */
import { API_BASE, ApiError } from "./api";
import { parsePrivateDiscoveryJSON } from "./discovery-scientific";
import { importCanonical, importDigest } from "./scientific-imports";
import { boundedPilotOperation, pilotBase64, pilotBytesHash, pilotHash as hash, pilotKey as key, pilotReason, pilotUuid as uuid, PILOT_FILE_LIMIT } from "./ml-pilot-participation";

export const REVIEW_VERSION = "ml08-review-attestation/1.0.0";
export const REVIEW_INTENT = "ml08-review-attestation-intent/1.0.0";
export const REVIEW_COVERAGE_VERSION = "ml08-review-coverage/1.0.0";
export const DECLARATION_VERSION = "ml08-own-review-declaration/1.0.0";
export const DECLARATION_HASH = "a4c700bf0217f6af942a7370a6993e997477c9e4f69c0afb98c305aab6b48fc4";
export const REVIEW_FILES = ["selection", "protocol", "reviews", "conclusion"] as const;
export const REVIEW_UPLOAD_LIMIT = 4 * Math.ceil(PILOT_FILE_LIMIT / 3) * 4 + 65536;
export const REVIEW_EVIDENCE_TYPE = "application/vnd.sclib.ml08-evidence-v1";
export const REVIEW_EVIDENCE_LIMIT = new TextEncoder().encode("SCLIB-ML08-EVIDENCE-1\n").length + 9 + 129 * 1024 * 1024;
type Obj = Record<string, unknown>;
export type ReviewRef = { participant_id: string; participant_sha256: string; registration_sha256: string };
export type ReviewAction = "attest" | "withdraw";
export type ReviewWording = { actor_user_id: string; declaration_version: typeof DECLARATION_VERSION; declaration_sha256: string; declaration_text: string };
export type ReviewControl = ReviewRef & { request_key: string; reason_code: string; supersedes_id: string | null; supersedes_sha256: string | null;
  declaration_version: typeof DECLARATION_VERSION; declaration_sha256: string; declaration_acknowledged: true };
export type ReviewBasis = { input_pins: Record<`${typeof REVIEW_FILES[number]}_file_sha256`, string>; selection_sha256: string; review_log_sha256: string;
  document_projection_sha256: string; implementation_sha256: string; selected_candidates: number; review_record_count: number; own_review_record_count: number;
  own_review_records_sha256: string; conclusion_author_is_current_account: boolean; recorded_recommendation: "go" | "narrow" | "stop"; declared_canary_sha256: string };
export type ReviewIntent = Omit<ReviewControl, "declaration_acknowledged"> & { version: typeof REVIEW_INTENT; actor_user_id: string; action: ReviewAction;
  participation_id: string; participation_sha256: string; basis_sha256: string };
export type ReviewRecord = Omit<ReviewIntent, "version"> & { version: typeof REVIEW_VERSION; id: string; intent_sha256: string; record_sha256: string; created_at: string; basis: ReviewBasis };
export type ReviewResult = { intent: ReviewIntent; intent_sha256: string; declaration: ReviewRecord | null; dry_run: boolean; replayed: boolean };
export type ReviewRecovery = { actorId: string; requestKey: string; intentSha256: string };
export type ReviewDocuments = Record<`${typeof REVIEW_FILES[number]}_base64` | `${typeof REVIEW_FILES[number]}_file_sha256`, string>
  & { selection_sha256: string; review_log_sha256: string };
export type ReviewDocumentSet = Record<typeof REVIEW_FILES[number], File>;
const referenceFields = ["participant_id", "participant_sha256", "registration_sha256"];
const controlFields = [...referenceFields, "request_key", "reason_code", "supersedes_id", "supersedes_sha256", "declaration_version", "declaration_sha256"];
const intentFields = ["version", "actor_user_id", "action", "participation_id", "participation_sha256", "basis_sha256", ...controlFields];
const basisFields = ["input_pins", "selection_sha256", "review_log_sha256", "document_projection_sha256", "implementation_sha256", "selected_candidates",
  "review_record_count", "own_review_record_count", "own_review_records_sha256", "conclusion_author_is_current_account", "recorded_recommendation", "declared_canary_sha256"];
const commonBasisFields = basisFields.filter(k => !["own_review_record_count", "own_review_records_sha256", "conclusion_author_is_current_account"].includes(k));
const coverageCounts = ["matching_declaration_count", "missing_declaration_count", "withdrawn_declaration_count", "stale_declaration_count"] as const;
export type ReviewCoverage = Record<typeof coverageCounts[number], number> & {
  required_declaration_count: number; account_declarations_complete: boolean; conclusion_author_declaration_current: boolean;
  own_declaration_status: "current" | "missing" | "withdrawn" | "stale" | "not_required"; snapshot_started_at: string;
};
const baseFlags = ["scientific_acceptance", "scientific_pilot_accepted", "human_identity_verified", "scientific_reviewer_independence_verified",
  "source_permissions_verified", "actual_event_existence_verified", "external_review_chronology_verified", "public_release", "ml_training_approved",
  "run_authorization_granted", "source_document_bytes_retained"];
const reviewFlags = [...baseFlags, "external_digital_signature_verified", "canary_replay_verified", "context_bytes_checked", "current_collective_signoff_verified"];
const boundaryFields = ["scope", "training_execution", ...reviewFlags];
const object = (v: unknown): v is Obj => v !== null && typeof v === "object" && !Array.isArray(v);
const closed = (v: unknown, fields: readonly string[]): v is Obj => object(v) && Object.keys(v).length === fields.length && fields.every(k => Object.hasOwn(v, k));
function requireValue(v: unknown): asserts v { if (!v) throw new Error("The exact private review response or input could not be verified."); }
const parse = (raw: string) => { const v = parsePrivateDiscoveryJSON(raw, 128 * 1024).value; requireValue(importCanonical(v) === raw); return v; };
const integer = (v: unknown, min: number, max: number): v is number => Number.isSafeInteger(v) && typeof v === "number" && v >= min && v <= max;
const noAuthority = (v: Obj) => v.scope === "authenticated_own_review_declaration_not_collective_pilot_acceptance"
  && v.training_execution === "disabled" && reviewFlags.every(k => v[k] === false);
export const validReviewRef = (v: ReviewRef) => closed(v, referenceFields) && uuid(v.participant_id) && hash(v.participant_sha256) && hash(v.registration_sha256);
const matchesRef = (v: Obj, ref: ReviewRef) => referenceFields.every(k => v[k] === ref[k as keyof ReviewRef]);
function validControl(v: unknown): v is ReviewControl {
  if (!closed(v, [...controlFields, "declaration_acknowledged"])) return false;
  return uuid(v.participant_id) && hash(v.participant_sha256) && hash(v.registration_sha256) && key(v.request_key) && pilotReason(v.reason_code)
    && v.declaration_version === DECLARATION_VERSION && v.declaration_sha256 === DECLARATION_HASH && v.declaration_acknowledged === true
    && (v.supersedes_id === null || uuid(v.supersedes_id)) && (v.supersedes_sha256 === null || hash(v.supersedes_sha256))
    && (v.supersedes_id === null) === (v.supersedes_sha256 === null);
}
function validIntent(v: unknown): v is ReviewIntent {
  return closed(v, intentFields) && v.version === REVIEW_INTENT && uuid(v.actor_user_id) && uuid(v.participation_id) && hash(v.participation_sha256)
    && hash(v.basis_sha256) && ["attest", "withdraw"].includes(v.action as string) && (v.action !== "withdraw" || v.supersedes_id !== null)
    && validControl({ ...Object.fromEntries(controlFields.map(k => [k, v[k]])), declaration_acknowledged: true });
}
function basis(v: unknown): ReviewBasis {
  requireValue(closed(v, basisFields) && closed(v.input_pins, REVIEW_FILES.map(k => k + "_file_sha256")) && Object.values(v.input_pins).every(hash)
    && [v.selection_sha256, v.review_log_sha256, v.document_projection_sha256, v.implementation_sha256, v.own_review_records_sha256, v.declared_canary_sha256].every(hash)
    && v.selected_candidates === 60 && integer(v.review_record_count, 61, 2000) && integer(v.own_review_record_count, 0, v.review_record_count)
    && typeof v.conclusion_author_is_current_account === "boolean" && ["go", "narrow", "stop"].includes(v.recorded_recommendation as string)
    && (v.own_review_record_count > 0 || v.conclusion_author_is_current_account));
  return v as unknown as ReviewBasis;
}
export async function parseReviewWording(raw: string): Promise<ReviewWording> {
  const v = parse(raw);
  requireValue(closed(v, ["version", "actor_user_id", "declaration_version", "declaration_sha256", "declaration_text", ...boundaryFields])
    && noAuthority(v) && v.version === REVIEW_VERSION && uuid(v.actor_user_id) && v.declaration_version === DECLARATION_VERSION
    && v.declaration_sha256 === DECLARATION_HASH && typeof v.declaration_text === "string"
    && await pilotBytesHash(new TextEncoder().encode(v.declaration_text)) === DECLARATION_HASH);
  return v as unknown as ReviewWording;
}
async function record(value: unknown): Promise<ReviewRecord> {
  requireValue(closed(value, [...intentFields.filter(k => k !== "version"), "version", "id", "intent_sha256", "record_sha256", "created_at", "basis"])
    && value.version === REVIEW_VERSION && uuid(value.id) && value.id !== value.supersedes_id && hash(value.intent_sha256) && hash(value.record_sha256));
  const intent = { ...Object.fromEntries(intentFields.map(k => [k, value[k]])), version: REVIEW_INTENT };
  requireValue(validIntent(intent) && await importDigest(intent) === value.intent_sha256 && await importDigest(basis(value.basis)) === value.basis_sha256);
  const when = value.created_at;
  requireValue(typeof when === "string" && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(when) && !when.startsWith("0000")
    && Number.isFinite(Date.parse(when)) && new Date(when).toISOString().slice(0, 19) === when.slice(0, 19));
  requireValue(await importDigest(Object.fromEntries(Object.entries(value).filter(([k]) => !["basis", "created_at", "record_sha256"].includes(k)))) === value.record_sha256);
  return value as unknown as ReviewRecord;
}
export async function parseReviewInspection(raw: string, actorId: string, ref: ReviewRef): Promise<ReviewRecord | null> {
  requireValue(uuid(actorId) && validReviewRef(ref)); const v = parse(raw);
  requireValue(closed(v, ["version", "actor_user_id", ...referenceFields, "head", "historical_record_only", ...boundaryFields]) && noAuthority(v)
    && v.version === REVIEW_VERSION && v.actor_user_id === actorId && matchesRef(v, ref) && v.historical_record_only === true);
  if (v.head === null) return null;
  const head = await record(v.head); requireValue(head.actor_user_id === actorId && matchesRef(head as unknown as Obj, ref)); return head;
}
export function parseReviewPreflight(raw: string, actorId: string, ref: ReviewRef, docs: ReviewDocuments): ReviewBasis {
  requireValue(uuid(actorId) && validReviewRef(ref)); const v = parse(raw);
  const checked = ["current_accounts_and_roles_checked", "declared_review_times_fit_recorded_participation", "documentary_binding_checked"];
  const denied = [...baseFlags, "attestation_recorded", "conclusion_endorsed", "context_bytes_checked", "canary_replay_verified"];
  requireValue(closed(v, ["version", "scope", "training_execution", "actor_user_id", "registration_id", ...referenceFields, ...basisFields, ...checked, ...denied])
    && v.version === "ml08-review-admission/1.0.0" && v.scope === "private_preregistration_and_review_document_binding_only" && v.training_execution === "disabled"
    && denied.every(k => v[k] === false) && checked.every(k => v[k] === true) && v.actor_user_id === actorId && uuid(v.registration_id) && matchesRef(v, ref));
  const b = basis(Object.fromEntries(basisFields.map(k => [k, v[k]])));
  requireValue(REVIEW_FILES.every(k => b.input_pins[`${k}_file_sha256`] === docs[`${k}_file_sha256`])
    && b.selection_sha256 === docs.selection_sha256 && b.review_log_sha256 === docs.review_log_sha256);
  return b;
}
export function parseReviewCoverage(raw: string, actorId: string, ref: ReviewRef, expected: ReviewBasis): ReviewCoverage {
  requireValue(uuid(actorId) && validReviewRef(ref)); const v = parse(raw);
  const checked = ["historical_snapshot_only", "current_accounts_and_roles_checked", "declared_review_times_fit_recorded_participation", "documentary_binding_checked", "latest_declaration_heads_checked"];
  requireValue(closed(v, ["version", "actor_user_id", ...referenceFields, ...commonBasisFields, ...boundaryFields, ...checked,
    "snapshot_started_at", "attestation_recorded", "required_declaration_count", ...coverageCounts, "account_declarations_complete", "conclusion_author_declaration_current", "own_declaration_status"])
    && v.version === REVIEW_COVERAGE_VERSION && v.scope === "private_same_snapshot_account_declaration_coverage_only"
    && noAuthority({ ...v, scope: "authenticated_own_review_declaration_not_collective_pilot_acceptance" }) && checked.every(k => v[k] === true)
    && v.attestation_recorded === false && v.actor_user_id === actorId && matchesRef(v, ref)
    && commonBasisFields.every(k => importCanonical(v[k]) === importCanonical(expected[k as keyof ReviewBasis]))
    && integer(v.required_declaration_count, 2, 30) && coverageCounts.every(k => integer(v[k], 0, v.required_declaration_count as number))
    && coverageCounts.reduce((sum, k) => sum + (v[k] as number), 0) === v.required_declaration_count
    && typeof v.account_declarations_complete === "boolean" && v.account_declarations_complete === (v.matching_declaration_count === v.required_declaration_count)
    && typeof v.conclusion_author_declaration_current === "boolean" && (!v.account_declarations_complete || v.conclusion_author_declaration_current)
    && ["current", "missing", "withdrawn", "stale", "not_required"].includes(v.own_declaration_status as string));
  const status = v.own_declaration_status;
  requireValue((status === "not_required") === (expected.own_review_record_count === 0 && !expected.conclusion_author_is_current_account)
    && (status === "not_required" || (v[status === "current" ? "matching_declaration_count" : `${status}_declaration_count`] as number) > 0)
    && (!expected.conclusion_author_is_current_account || v.conclusion_author_declaration_current === (status === "current")));
  const when = v.snapshot_started_at;
  requireValue(typeof when === "string" && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(when) && !when.startsWith("0000")
    && Number.isFinite(Date.parse(when)) && new Date(when).toISOString().slice(0, 19) === when.slice(0, 19));
  return v as unknown as ReviewCoverage;
}
export async function parseReviewResult(raw: string, recovery: { actorId: string; requestKey: string; intentSha256?: string }, committed: boolean,
  expected?: { controls: ReviewControl; action: ReviewAction; basis: ReviewBasis; predecessor: ReviewRecord | null }): Promise<ReviewResult> {
  requireValue(uuid(recovery.actorId) && key(recovery.requestKey) && (recovery.intentSha256 === undefined || hash(recovery.intentSha256)));
  requireValue(!committed || hash(recovery.intentSha256)); const v = parse(raw);
  requireValue(closed(v, ["version", "committed", "result"]) && v.version === REVIEW_VERSION && v.committed === committed);
  const r = v.result;
  requireValue(closed(r, ["version", "dry_run", "committed", "replayed", "intent", "intent_sha256", "declaration_recorded", "declaration", ...boundaryFields])
    && noAuthority(r) && r.version === REVIEW_VERSION && r.committed === false && r.dry_run === !committed && r.declaration_recorded === committed
    && typeof r.replayed === "boolean" && validIntent(r.intent) && r.intent.actor_user_id === recovery.actorId && r.intent.request_key === recovery.requestKey
    && hash(r.intent_sha256) && await importDigest(r.intent) === r.intent_sha256 && (recovery.intentSha256 === undefined || r.intent_sha256 === recovery.intentSha256));
  if (expected) {
    const intent = r.intent;
    requireValue(validControl(expected.controls) && intent.action === expected.action && controlFields.every(k => intent[k as keyof ReviewIntent] === expected.controls[k as keyof ReviewControl])
      && r.intent.basis_sha256 === await importDigest(basis(expected.basis)) && r.intent.supersedes_id === (expected.predecessor?.id ?? null)
      && r.intent.supersedes_sha256 === (expected.predecessor?.record_sha256 ?? null));
    if (expected.action === "withdraw") requireValue(expected.predecessor?.action === "attest" && r.intent.basis_sha256 === expected.predecessor.basis_sha256
      && r.intent.participation_id === expected.predecessor.participation_id && r.intent.participation_sha256 === expected.predecessor.participation_sha256);
  }
  if (committed) { const d = await record(r.declaration); requireValue(d.intent_sha256 === r.intent_sha256); }
  else requireValue(r.declaration === null);
  return r as unknown as ReviewResult;
}

type Endpoint = "/review-attestations/evidence" | "/review-attestations/declaration" | "/review-attestations/inspect" | "/review-attestations/outcome" | "/review-attestations/withdraw" | "/review-attestations/coverage" | "/review-attestations" | "/review-preflight";
async function wire(path: Endpoint, value?: object, caller?: AbortSignal, ref?: ReviewRef) {
  const evidence = path === "/review-attestations/evidence";
  requireValue(!evidence || value instanceof Blob && ref && validReviewRef(ref) && value.size > 0 && value.size <= REVIEW_EVIDENCE_LIMIT
    && value.type === REVIEW_EVIDENCE_TYPE);
  const payload = evidence ? value as Blob : value === undefined ? undefined : JSON.stringify(value);
  requireValue(payload === undefined || payload instanceof Blob || new TextEncoder().encode(payload).length <= (["/review-attestations", "/review-preflight", "/review-attestations/coverage"].includes(path) ? REVIEW_UPLOAD_LIMIT : 8192));
  return boundedPilotOperation(async (signal, interrupted) => {
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined, stream: ReadableStream<Uint8Array> | null = null;
    try {
      const response = await Promise.race([fetch(`${API_BASE}/ml/pilots${path}`, { method: payload === undefined ? "GET" : "POST", body: payload,
        credentials: "include", cache: "no-store", redirect: "error", signal, headers: { Accept: "application/json", ...(payload === undefined ? {} : { "Content-Type": evidence ? REVIEW_EVIDENCE_TYPE : "application/json" }),
          ...(ref ? { "X-SCLib-Participant-Id": ref.participant_id, "X-SCLib-Participant-Sha256": ref.participant_sha256 } : {}) } }), interrupted]);
      stream = response.body;
      if (!response.ok) throw new ApiError(response.status, null, "Private review request unavailable");
      const limit = 128 * 1024, length = response.headers.get("content-length");
      requireValue(/^application\/json(?:\s*;|$)/i.test(response.headers.get("content-type") ?? "") && stream
        && (length === null || /^\d+$/.test(length) && Number(length) <= limit));
      reader = stream.getReader(); const decoder = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }); let raw = "", size = 0, parts = 0;
      while (true) {
        const item = await Promise.race([reader.read(), interrupted]); requireValue(!signal.aborted);
        if (item.done) break; size += item.value.length; requireValue(size <= limit && ++parts <= 4096); raw += decoder.decode(item.value, { stream: true });
      }
      return raw + decoder.decode();
    } catch (error) { if (error instanceof ApiError) throw error; throw new ApiError(0, null, "Private review response unavailable"); }
    finally { if (reader) void reader.cancel().catch(() => {}); else void stream?.cancel().catch(() => {}); }
  }, caller);
}
export const sendReviewEvidence = (ref: ReviewRef, payload: Blob, signal?: AbortSignal) => wire("/review-attestations/evidence", payload, signal, ref);
export const getReviewWording = (signal?: AbortSignal) => wire("/review-attestations/declaration", undefined, signal);
export const inspectReview = (ref: ReviewRef, signal?: AbortSignal) => { requireValue(validReviewRef(ref)); return wire("/review-attestations/inspect", ref, signal); };
export const recoverReview = (ref: ReviewRecovery, signal?: AbortSignal) => {
  requireValue(uuid(ref.actorId) && key(ref.requestKey) && hash(ref.intentSha256));
  return wire("/review-attestations/outcome", { request_key: ref.requestKey, expected_intent_sha256: ref.intentSha256 }, signal);
};
export async function prepareReviewDocuments(files: ReviewDocumentSet, signal?: AbortSignal): Promise<ReviewDocuments> {
  requireValue(closed(files, REVIEW_FILES) && REVIEW_FILES.every(k => files[k] && integer(files[k].size, 1, PILOT_FILE_LIMIT)));
  return boundedPilotOperation(async (active, interrupted) => {
    const out: Record<string, string> = {}, decoded: Record<string, Obj> = {};
    for (const k of REVIEW_FILES) {
      const bytes = new Uint8Array(await Promise.race([files[k].arrayBuffer(), interrupted]));
      requireValue(!active.aborted && bytes.length === files[k].size && bytes.length <= PILOT_FILE_LIMIT);
      out[`${k}_file_sha256`] = await pilotBytesHash(bytes); requireValue(!active.aborted);
      out[`${k}_base64`] = pilotBase64(bytes);
      if (k === "selection" || k === "conclusion") {
        const v = parsePrivateDiscoveryJSON(new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes), PILOT_FILE_LIMIT).value;
        requireValue(object(v)); decoded[k] = v;
      }
    }
    requireValue(decoded.selection.schema_version === "ml08-selection/1.0.0" && decoded.conclusion.schema_version === "ml08-conclusion/1.0.0"
      && hash(decoded.selection.selection_sha256) && decoded.selection.selection_sha256 === decoded.conclusion.selection_sha256 && hash(decoded.conclusion.review_log_sha256));
    return { ...out, selection_sha256: decoded.selection.selection_sha256, review_log_sha256: decoded.conclusion.review_log_sha256 } as ReviewDocuments;
  }, signal, 30000);
}
function checkDocuments(docs: ReviewDocuments) {
  requireValue(closed(docs, [...REVIEW_FILES.flatMap(k => [k + "_base64", k + "_file_sha256"]), "selection_sha256", "review_log_sha256"])
    && hash(docs.selection_sha256) && hash(docs.review_log_sha256) && REVIEW_FILES.every(k => hash(docs[`${k}_file_sha256`])
      && typeof docs[`${k}_base64`] === "string" && docs[`${k}_base64`].length > 0 && docs[`${k}_base64`].length <= Math.ceil(PILOT_FILE_LIMIT / 3) * 4));
}
export function checkReviewDocuments(ref: ReviewRef, docs: ReviewDocuments, signal?: AbortSignal) {
  requireValue(validReviewRef(ref)); checkDocuments(docs);
  return wire("/review-preflight", { version: "ml08-review-upload/1.0.0", ...docs, parameters: ref }, signal, ref);
}
export function checkReviewCoverage(ref: ReviewRef, docs: ReviewDocuments, signal?: AbortSignal) {
  requireValue(validReviewRef(ref)); checkDocuments(docs);
  return wire("/review-attestations/coverage", { version: "ml08-review-upload/1.0.0", ...docs, parameters: ref }, signal, ref);
}
async function send(action: ReviewAction, controls: ReviewControl, docs: ReviewDocuments | null, pin: string | null, signal?: AbortSignal) {
  requireValue(validControl(controls) && ["attest", "withdraw"].includes(action) && (pin === null || hash(pin)));
  const parameters = { ...controls, dry_run: pin === null, expected_intent_sha256: pin };
  if (action === "withdraw") { requireValue(docs === null && controls.supersedes_id !== null); return wire("/review-attestations/withdraw", parameters, signal); }
  requireValue(docs !== null); checkDocuments(docs);
  const ref = Object.fromEntries(referenceFields.map(k => [k, controls[k as keyof ReviewControl]])) as ReviewRef;
  return wire("/review-attestations", { version: "ml08-review-attestation-upload/1.0.0", ...docs, parameters }, signal, ref);
}
export const previewReview = (action: ReviewAction, controls: ReviewControl, docs: ReviewDocuments | null, signal?: AbortSignal) => send(action, controls, docs, null, signal);
export const commitReview = (action: ReviewAction, controls: ReviewControl, docs: ReviewDocuments | null, pin: string, signal?: AbortSignal) => {
  requireValue(hash(pin)); return send(action, controls, docs, pin, signal);
};
