/** Closed private ML rights protocol. A verified hash is not legal or run authority. */
import { API_BASE, ApiError } from "./api";
import { parsePrivateDiscoveryJSON } from "./discovery-scientific";
import { importCanonical, importDigest } from "./scientific-imports";

export const ML_RIGHTS_VERSION = "ml-use-rights/1.0.0";
export const ML_RIGHTS_INTENT = "ml-use-rights-intent/1.0.0";
export const ML_RIGHTS_PURPOSE = "private_baseline_evaluation";
export const ML_RIGHTS_LIMIT = 1100 * 1024;
export const ML_RIGHTS_BASES = ["documented_license", "documented_permission", "documented_institutional_policy", "rights_unresolved", "withdrawn"] as const;
export const ML_RIGHTS_STATUSES = ["unreviewed", "allow_recorded", "denied", "revoked", "expired", "reviewer_unavailable"] as const;
const flags = ["scientific_acceptance", "public_release", "ml_training_approved", "reviewer_authority_authenticated", "live_source_rights_checked",
  "external_dependency_completeness_proven", "source_permission_granted", "run_authorization_granted", "data_access_granted",
  "current_source_validity_checked", "legal_evidence_independently_verified"];
const boundaryKeys = [...flags, "training_execution"];
const actors = ["actor_user_id", "reviewer_grant_id", "curator_grant_id"];
const pins = ["submission_id", "submission_sha256", "inventory_sha256"];
const intentFields = [...pins, "purpose", "resource_id", ...actors, "request_key", "decision", "basis_code", "evidence_sha256", "expires_epoch", "supersedes_id", "supersedes_sha256"];
type Obj = Record<string, unknown>;
export type MlRightsActor = { actor_user_id: string; reviewer_grant_id: string; curator_grant_id: string };
export type MlRightsQuery = { submission_id: string; submission_sha256: string; inventory_sha256: string; after?: string | null };
export type MlRightsInput = Omit<MlRightsQuery, "after"> & Omit<MlRightsActor, "actor_user_id"> & {
  resource_id: string; purpose: typeof ML_RIGHTS_PURPOSE; request_key: string; decision: "allow" | "deny" | "revoke";
  basis_code: typeof ML_RIGHTS_BASES[number]; evidence_sha256: string | null; expires_epoch: number | null;
  supersedes_id: string | null; supersedes_sha256: string | null };
export type MlRightsIntent = MlRightsInput & { actor_user_id: string; version: typeof ML_RIGHTS_INTENT };
export type MlRightsDecision = Omit<MlRightsIntent, "version"> & { version: typeof ML_RIGHTS_VERSION; id: string; intent_sha256: string; record_sha256: string; created_at: string };
export type MlRightsRepresentation = { encoding: string; scope: string; sha256: string; container_sha256: string | null; origins: string[] };
export type MlRightsResource = { resource_id: string; head: MlRightsDecision | null; recorded_permission_status: typeof ML_RIGHTS_STATUSES[number] } & (
  { kind: "row"; entry: { table: string; row_id: string; representations: MlRightsRepresentation[] } } |
  { kind: "artifact"; entry: { sha256: string; uploaded_size_bytes: number | null; origins: string[] } });
export type MlRightsPage = MlRightsActor & Omit<MlRightsQuery, "after"> & { purpose: typeof ML_RIGHTS_PURPOSE;
  input_access_expires_at: string; resource_count: number; resources: MlRightsResource[]; next_after: string | null };
export type MlRightsResult = { intent: MlRightsIntent; intent_sha256: string; decision: MlRightsDecision | null; replayed: boolean; dry_run: boolean };
export type MlRightsRecovery = { actorId: string; requestKey: string; intentSha256: string };
export const mlRightsHash = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
export const mlRightsUuid = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(v);
export const mlRightsKey = (v: unknown): v is string => typeof v === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$/.test(v);
const object = (v: unknown): v is Obj => v !== null && typeof v === "object" && !Array.isArray(v);
const closed = (v: unknown, fields: string[]): v is Obj => object(v) && Object.keys(v).length === fields.length && fields.every(k => Object.hasOwn(v, k));
const integer = (v: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max;
const text = (v: unknown, max: number): v is string => typeof v === "string" && !!v.length && Array.from(v).length <= max && !/[\u0000-\u001f\u007f-\u009f]/.test(v);
const timestamp = (v: unknown): v is string => typeof v === "string" && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(v) && Number.isFinite(Date.parse(v));
const nullableHash = (v: unknown) => v === null || mlRightsHash(v);
const noAuthority = (v: Obj) => flags.every(k => v[k] === false) && v.training_execution === "disabled";
const parse = (raw: string, limit = ML_RIGHTS_LIMIT) => {
  const value = parsePrivateDiscoveryJSON(raw, limit).value;
  // This version's HTTP response uses the integer-only canonical codec. Check
  // exact bytes too: JSON.parse must not round a fractional/unsafe numeric token
  // into an apparently valid integer, expiry or resource size.
  requireValue(importCanonical(value) === raw); return value;
};
function requireValue(v: unknown): asserts v { if (!v) throw new Error("The private ML rights response could not be verified."); }
const same = (v: Obj, expected: object, fields: string[]) => fields.every(k => v[k] === (expected as Obj)[k]);
export const validMlRightsQuery = (v: MlRightsQuery) => mlRightsUuid(v.submission_id) && mlRightsHash(v.submission_sha256) && mlRightsHash(v.inventory_sha256)
  && (v.after === undefined || nullableHash(v.after));

export function parseMlRightsAccess(raw: string): MlRightsActor {
  const v = parse(raw, 4096);
  requireValue(closed(v, ["version", ...actors, "can_review_rights", ...boundaryKeys]) && v.version === ML_RIGHTS_VERSION && noAuthority(v)
    && actors.every(k => mlRightsUuid(v[k])) && v.can_review_rights === true);
  return Object.fromEntries(actors.map(k => [k, v[k]])) as MlRightsActor;
}
function validIntent(v: unknown): v is MlRightsIntent {
  return closed(v, ["version", ...intentFields]) && v.version === ML_RIGHTS_INTENT && v.purpose === ML_RIGHTS_PURPOSE
    && [...actors, "submission_id"].every(k => mlRightsUuid(v[k])) && [v.submission_sha256, v.inventory_sha256, v.resource_id].every(mlRightsHash)
    && mlRightsKey(v.request_key) && ["allow", "deny", "revoke"].includes(v.decision as string)
    && ML_RIGHTS_BASES.includes(v.basis_code as typeof ML_RIGHTS_BASES[number]) && nullableHash(v.evidence_sha256)
    && (v.supersedes_id === null || mlRightsUuid(v.supersedes_id)) && nullableHash(v.supersedes_sha256)
    && (v.supersedes_id === null) === (v.supersedes_sha256 === null) && (v.decision !== "revoke" || v.supersedes_id !== null)
    && (v.decision === "allow" ? ML_RIGHTS_BASES.slice(0, 3).includes(v.basis_code as never) && mlRightsHash(v.evidence_sha256) && integer(v.expires_epoch, 1)
      : ML_RIGHTS_BASES.slice(3).includes(v.basis_code as never) && v.expires_epoch === null);
}
export function mlRightsIntent(input: MlRightsInput, actorId: string): MlRightsIntent {
  const v = { version: ML_RIGHTS_INTENT, ...input, actor_user_id: actorId }; requireValue(validIntent(v)); return v;
}
async function decision(v: unknown): Promise<MlRightsDecision> {
  requireValue(closed(v, ["version", ...intentFields, "id", "intent_sha256", "record_sha256", "created_at"])
    && v.version === ML_RIGHTS_VERSION && mlRightsUuid(v.id) && mlRightsHash(v.intent_sha256) && mlRightsHash(v.record_sha256) && timestamp(v.created_at));
  const i = { version: ML_RIGHTS_INTENT, ...Object.fromEntries(intentFields.map(k => [k, v[k]])) };
  requireValue(validIntent(i) && await importDigest(i) === v.intent_sha256);
  const { created_at: _created, record_sha256: hash, ...body } = v;
  requireValue(await importDigest(body) === hash);
  return v as unknown as MlRightsDecision;
}
function origins(v: unknown, max: number): boolean {
  return Array.isArray(v) && v.length > 0 && v.length <= max && v.every(x => text(x, 240)) && new Set(v).size === v.length;
}
const encodings = ["scientific-subject-membership/1.0.0", "scientific-adjudication-canonical/1.0.0", "source-lifecycle-jsonb-text/1.0.0", "research-release-canonical/1.0.0", "ml-feature-binding-record/1.0.0"];
function entry(v: unknown, kind: unknown): boolean {
  if (kind === "artifact") return closed(v, ["sha256", "uploaded_size_bytes", "origins"]) && mlRightsHash(v.sha256)
    && (v.uploaded_size_bytes === null || integer(v.uploaded_size_bytes)) && origins(v.origins, 16000);
  if (kind !== "row" || !closed(v, ["table", "row_id", "representations"]) || typeof v.table !== "string" || !/^[a-z][a-z0-9_]{0,99}$/.test(v.table)
    || !text(v.row_id, 200) || !Array.isArray(v.representations) || v.representations.length < 1 || v.representations.length > 16000) return false;
  return v.representations.every(r => closed(r, ["encoding", "scope", "sha256", "container_sha256", "origins"])
    && encodings.includes(r.encoding as string) && ["current_observation", "historical_input", "historical_subject"].includes(r.scope as string)
    && mlRightsHash(r.sha256) && nullableHash(r.container_sha256) && (r.encoding === encodings[0] ? mlRightsHash(r.container_sha256) : r.container_sha256 === null)
    && origins(r.origins, 32)) && new Set(v.representations.map(r => JSON.stringify([r.encoding, r.scope, r.sha256, r.container_sha256]))).size === v.representations.length;
}
export async function parseMlRightsPage(raw: string, actor: MlRightsActor, query: MlRightsQuery, previous?: MlRightsPage): Promise<MlRightsPage> {
  requireValue(validMlRightsQuery(query)); const v = parse(raw);
  requireValue(closed(v, ["version", ...actors, ...pins, "purpose", "input_access_expires_at", "resource_count", "resources", "next_after", "inventory_scope", ...boundaryKeys])
    && v.version === ML_RIGHTS_VERSION && noAuthority(v) && same(v, actor, actors) && same(v, query, pins)
    && v.purpose === ML_RIGHTS_PURPOSE && timestamp(v.input_access_expires_at) && integer(v.resource_count, 1, 8000)
    && v.inventory_scope === "exact_registered_and_recaptured_inventory_not_external_completeness"
    && Array.isArray(v.resources) && v.resources.length <= 25 && v.resources.length <= v.resource_count && nullableHash(v.next_after));
  if (previous) requireValue(same(v, previous, [...pins, "resource_count", "input_access_expires_at"]));
  let last = query.after ?? "";
  for (const row of v.resources) {
    requireValue(closed(row, ["resource_id", "kind", "entry", "head", "recorded_permission_status"]) && mlRightsHash(row.resource_id) && row.resource_id > last
      && entry(row.entry, row.kind) && ML_RIGHTS_STATUSES.includes(row.recorded_permission_status as typeof ML_RIGHTS_STATUSES[number])
      && await importDigest({ kind: row.kind, entry: row.entry }) === row.resource_id);
    last = row.resource_id;
    if (row.head === null) requireValue(row.recorded_permission_status === "unreviewed");
    else {
      const head = await decision(row.head);
      requireValue(same(head as unknown as Obj, query, pins) && head.purpose === ML_RIGHTS_PURPOSE && head.resource_id === row.resource_id
        && (head.decision === "deny" ? row.recorded_permission_status === "denied" : head.decision === "revoke" ? row.recorded_permission_status === "revoked"
          : ["allow_recorded", "expired", "reviewer_unavailable"].includes(row.recorded_permission_status as string)));
    }
  }
  requireValue((query.after || v.resources.length > 0) && (v.next_after === null || v.resources.length === 25 && v.next_after === last));
  return v as unknown as MlRightsPage;
}
export async function parseMlRightsResult(raw: string, ref: MlRightsRecovery, committed: boolean, input?: MlRightsInput): Promise<MlRightsResult> {
  requireValue(mlRightsUuid(ref.actorId) && mlRightsKey(ref.requestKey) && mlRightsHash(ref.intentSha256));
  const v = parse(raw, 16384);
  requireValue(closed(v, ["version", "committed", "result"]) && v.version === ML_RIGHTS_VERSION && v.committed === committed);
  const r = v.result;
  requireValue(closed(r, ["version", "dry_run", "committed", "replayed", "intent", "intent_sha256", "decision", "scope", ...boundaryKeys])
    && r.version === ML_RIGHTS_VERSION && noAuthority(r) && r.committed === false && r.dry_run === !committed && typeof r.replayed === "boolean"
    && r.scope === "historical_rights_decision_not_current_permission_or_run_authority" && validIntent(r.intent)
    && r.intent.actor_user_id === ref.actorId && r.intent.request_key === ref.requestKey && r.intent_sha256 === ref.intentSha256
    && await importDigest(r.intent) === ref.intentSha256);
  if (input) requireValue(await importDigest(mlRightsIntent(input, ref.actorId)) === ref.intentSha256);
  if (committed) { const d = await decision(r.decision); requireValue(d.intent_sha256 === ref.intentSha256); }
  else requireValue(r.decision === null);
  return r as unknown as MlRightsResult;
}

/** Bounded text transport rejects duplicate keys downstream; no redirects, storage or retries. */
async function wire(path: "/access" | "/inspect" | "/decisions" | "/outcome", body?: object, signal?: AbortSignal) {
  if (signal?.aborted) throw new ApiError(0, null, "Private ML rights request interrupted");
  const payload = body === undefined ? undefined : JSON.stringify(body);
  requireValue(payload === undefined || new TextEncoder().encode(payload).length <= 8192);
  const controller = new AbortController(), abort = () => controller.abort();
  let reject!: (reason: Error) => void;
  const aborted = new Promise<never>((_, no) => { reject = no; });
  const stop = () => reject(new ApiError(0, null, "Private ML rights request interrupted"));
  controller.signal.addEventListener("abort", stop, { once: true }); signal?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, 30000);
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined, stream: ReadableStream<Uint8Array> | null = null;
  try {
    const response = await Promise.race([fetch(`${API_BASE}/ml/use/rights${path}`, { method: payload === undefined ? "GET" : "POST", body: payload,
      credentials: "include", cache: "no-store", redirect: "error", signal: controller.signal,
      headers: { Accept: "application/json", ...(payload === undefined ? {} : { "Content-Type": "application/json" }) } }), aborted]);
    stream = response.body;
    if (!response.ok) throw new ApiError(response.status, null, "Private ML rights request unavailable");
    const limit = path === "/inspect" ? ML_RIGHTS_LIMIT : path === "/access" ? 4096 : 16384;
    const length = response.headers.get("content-length");
    requireValue(/^application\/json(?:\s*;|$)/i.test(response.headers.get("content-type") ?? "") && stream
      && (length === null || /^\d+$/.test(length) && Number(length) <= limit));
    reader = stream.getReader(); const decoder = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });
    let raw = "", size = 0, parts = 0;
    while (true) {
      const item = await Promise.race([reader.read(), aborted]); requireValue(!controller.signal.aborted);
      if (item.done) break; size += item.value.length; requireValue(size <= limit && ++parts <= 4096); raw += decoder.decode(item.value, { stream: true });
    }
    return raw + decoder.decode();
  } catch (e) { if (e instanceof ApiError) throw e; throw new ApiError(0, null, "Private ML rights response unavailable"); }
  finally { clearTimeout(timer); signal?.removeEventListener("abort", abort); controller.signal.removeEventListener("abort", stop); controller.abort();
    if (reader) void reader.cancel().catch(() => {}); else void stream?.cancel().catch(() => {}); }
}
export const getMlRightsAccess = (signal?: AbortSignal) => wire("/access", undefined, signal);
export function inspectMlRights(query: MlRightsQuery, signal?: AbortSignal) { requireValue(validMlRightsQuery(query)); return wire("/inspect", query, signal); }
export const previewMlRights = (input: MlRightsInput, signal?: AbortSignal) => wire("/decisions", { ...input, dry_run: true }, signal);
export function commitMlRights(input: MlRightsInput, pin: string, signal?: AbortSignal) {
  requireValue(mlRightsHash(pin)); return wire("/decisions", { ...input, dry_run: false, expected_intent_sha256: pin }, signal);
}
export function recoverMlRights(ref: MlRightsRecovery, signal?: AbortSignal) {
  requireValue(mlRightsKey(ref.requestKey) && mlRightsHash(ref.intentSha256));
  return wire("/outcome", { request_key: ref.requestKey, expected_intent_sha256: ref.intentSha256 }, signal);
}
