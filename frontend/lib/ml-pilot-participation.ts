/** Private account participation, never scientific approval or a training grant. */
import { API_BASE, ApiError } from "./api";
import { parsePrivateDiscoveryJSON } from "./discovery-scientific";
import { mlRightsHash as hash, mlRightsKey as key, mlRightsUuid as uuid } from "./ml-use-rights";
import { importCanonical, importDigest } from "./scientific-imports";

export { mlRightsHash as pilotHash, mlRightsKey as pilotKey, mlRightsUuid as pilotUuid } from "./ml-use-rights";
export const PILOT_VERSION = "ml08-registration/1.0.0", PILOT_INTENT = "ml08-participation-intent/1.0.0";
export const PILOT_DOCUMENT_POLICY = "ml08-registration-documents/1.1.0";
export const PILOT_FILE_LIMIT = 8 * 1024 * 1024, PILOT_RESPONSE_LIMIT = 128 * 1024;
export const PILOT_UPLOAD_LIMIT = 2 * Math.ceil(PILOT_FILE_LIMIT / 3) * 4 + 65536;
export const PILOT_ROLES = ["primary", "secondary", "arbitration"] as const;
export type PilotChoice = "accept" | "decline" | "withdraw";
type Obj = Record<string, unknown>;
type BaseRecord = { id: string; version: typeof PILOT_VERSION; record_sha256: string; created_at: string };
export type PilotRef = { registration_id: string; registration_sha256: string };
export type PilotActor = { actor_user_id: string };
export type PilotInput = { participant_id: string; participant_sha256: string; registration_sha256: string;
  request_key: string; decision: PilotChoice; reason_code: string; supersedes_id: string | null; supersedes_sha256: string | null };
export type PilotDecision = PilotInput & BaseRecord & { actor_user_id: string; intent_sha256: string };
export type PilotMember = BaseRecord & PilotRef & { user_id: string; reviewer_grant_id: string; alias_sha256: string;
  roles: typeof PILOT_ROLES[number][]; roles_sha256: string };
export type PilotRegistration = { id: string; record_sha256: string; created_at: string;
  selection_file_sha256: string; protocol_file_sha256: string; selection_sha256: string };
export type PilotInspection = { registration: PilotRegistration; participants: { binding: PilotMember; head: PilotDecision | null }[];
  participant_count: number; accepted_account_count: number; current_bound_roles_available: boolean;
  current_registration_document_policy: boolean; registration_document_check_version: string; ready_for_prospective_review: boolean; owner: boolean };
export type PilotRecovery = { actorId: string; requestKey: string; intentSha256: string };
export type PilotResult = { intent: PilotInput & { actor_user_id: string; version: typeof PILOT_INTENT };
  intent_sha256: string; decision: PilotDecision | null; replayed: boolean; dry_run: boolean };
export type PilotFiles = { selection_base64: string; protocol_base64: string; selection_file_sha256: string;
  protocol_file_sha256: string; selection_sha256: string };

const flags = ["scientific_acceptance", "scientific_pilot_accepted", "human_identity_verified", "scientific_reviewer_independence_verified",
  "source_permissions_verified", "actual_event_existence_verified", "external_review_chronology_verified", "public_release",
  "ml_training_approved", "run_authorization_granted", "source_document_bytes_retained"];
const boundaryKeys = ["scope", "training_execution", ...flags];
const inputFields = ["participant_id", "participant_sha256", "registration_sha256", "request_key", "decision", "reason_code", "supersedes_id", "supersedes_sha256"];
const baseFields = ["version", "id", "created_at", "record_sha256"];
const registrationFields = ["id", "record_sha256", "created_at", "selection_file_sha256", "protocol_file_sha256", "selection_sha256"];
const ownerFields = ["version", "actor_user_id", "curator_grant_id", "request_key", "intent_sha256", "roster_sha256", "implementation_sha256", "roster", "implementation"];
const object = (v: unknown): v is Obj => v !== null && typeof v === "object" && !Array.isArray(v);
const closed = (v: unknown, names: string[]): v is Obj => object(v) && Object.keys(v).length === names.length && names.every(k => Object.hasOwn(v, k));
const integer = (v: unknown, min: number, max: number): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max;
const timestamp = (v: unknown): v is string => typeof v === "string" && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(v)
  && !v.startsWith("0000") && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0, 19) === v.slice(0, 19);
const timeKey = (v: string) => v.slice(0, 19) + "." + (v.slice(19).match(/^\.(\d{1,6})/)?.[1] ?? "").padEnd(6, "0");
const noAuthority = (v: Obj) => v.scope === "private_pilot_document_commitment_and_account_participation_only"
  && v.training_execution === "disabled" && flags.every(k => v[k] === false);
export const pilotReason = (v: unknown): v is string => typeof v === "string" && /^[a-z][a-z0-9_]{0,159}$/.test(v);
export const validPilotRef = (v: PilotRef) => uuid(v.registration_id) && hash(v.registration_sha256);
function requireValue(v: unknown): asserts v { if (!v) throw new Error("The private pilot response or exact input could not be verified."); }
const parse = (raw: string, limit = PILOT_RESPONSE_LIMIT) => {
  const v = parsePrivateDiscoveryJSON(raw, limit).value; requireValue(importCanonical(v) === raw); return v;
};
const roles = (v: unknown): v is typeof PILOT_ROLES[number][] => Array.isArray(v) && v.length > 0
  && importCanonical(v) === importCanonical(PILOT_ROLES.filter(r => v.includes(r)));
const nullableHash = (v: unknown) => v === null || hash(v);

export function parsePilotAccess(raw: string): PilotActor {
  const v = parse(raw, 4096);
  requireValue(closed(v, ["version", "actor_user_id", ...boundaryKeys]) && v.version === PILOT_VERSION && uuid(v.actor_user_id) && noAuthority(v));
  return { actor_user_id: v.actor_user_id };
}
function validIntent(v: unknown): v is PilotResult["intent"] {
  return closed(v, ["version", "actor_user_id", ...inputFields]) && v.version === PILOT_INTENT && uuid(v.actor_user_id)
    && uuid(v.participant_id) && hash(v.participant_sha256) && hash(v.registration_sha256) && key(v.request_key)
    && ["accept", "decline", "withdraw"].includes(v.decision as string) && pilotReason(v.reason_code)
    && (v.supersedes_id === null || uuid(v.supersedes_id)) && nullableHash(v.supersedes_sha256)
    && (v.supersedes_id === null) === (v.supersedes_sha256 === null) && (v.decision !== "withdraw" || v.supersedes_id !== null);
}
export function pilotIntent(input: PilotInput, actorId: string): PilotResult["intent"] {
  const v = { version: PILOT_INTENT, ...input, actor_user_id: actorId }; requireValue(validIntent(v)); return v;
}
async function verifyRecord(v: Obj, decoded: string[] = []) {
  requireValue(v.version === PILOT_VERSION && uuid(v.id) && hash(v.record_sha256) && timestamp(v.created_at));
  const body = Object.fromEntries(Object.entries(v).filter(([k]) => !["created_at", "record_sha256", ...decoded].includes(k)));
  requireValue(await importDigest(body) === v.record_sha256);
}
async function decision(value: unknown): Promise<PilotDecision> {
  requireValue(closed(value, [...baseFields, ...inputFields, "actor_user_id", "intent_sha256"]));
  const intent = { version: PILOT_INTENT, ...Object.fromEntries(["actor_user_id", ...inputFields].map(k => [k, value[k]])) };
  requireValue(validIntent(intent) && hash(value.intent_sha256) && await importDigest(intent) === value.intent_sha256 && value.id !== value.supersedes_id);
  await verifyRecord(value); return value as unknown as PilotDecision;
}
async function member(value: unknown): Promise<PilotMember> {
  requireValue(closed(value, [...baseFields, "registration_id", "registration_sha256", "user_id", "reviewer_grant_id", "alias_sha256", "roles_sha256", "roles"])
    && validPilotRef(value as PilotRef) && uuid(value.user_id) && uuid(value.reviewer_grant_id) && hash(value.alias_sha256)
    && roles(value.roles) && hash(value.roles_sha256) && await importDigest(value.roles) === value.roles_sha256);
  await verifyRecord(value, ["roles"]); return value as unknown as PilotMember;
}
async function ownerRegistration(value: Obj) {
  requireValue(value.version === PILOT_VERSION && uuid(value.actor_user_id) && uuid(value.curator_grant_id) && key(value.request_key)
    && [value.intent_sha256, value.roster_sha256, value.implementation_sha256].every(hash) && Array.isArray(value.roster));
  await verifyRecord(value, ["roster", "implementation"]);
  requireValue(await importDigest(value.roster) === value.roster_sha256 && await importDigest(value.implementation) === value.implementation_sha256);
  const impl = value.implementation;
  requireValue(closed(impl, ["version", "scope", "files"]) && [PILOT_DOCUMENT_POLICY, "ml08-registration-documents/1.0.0"].includes(impl.version as string)
    && impl.scope === "selected_installed_disk_sources_not_runtime_attestation");
  const fileNames = ["ml_pilot_accounting.py", "ml_pilot_documents.py", "ml_pilot_registration_documents.py", "ml_pilot_registration_worker.py", "ml08_pilot.schema.json",
    ...(impl.version === PILOT_DOCUMENT_POLICY ? ["ml_use_reconstruction_worker.py"] : [])];
  requireValue(closed(impl.files, fileNames) && Object.values(impl.files).every(hash));
  const intent = { version: "ml08-registration-intent/1.0.0", ...Object.fromEntries(["actor_user_id", "curator_grant_id", "request_key",
    "selection_file_sha256", "protocol_file_sha256", "selection_sha256", "roster_sha256", "implementation_sha256"].map(k => [k, value[k]])) };
  requireValue(await importDigest(intent) === value.intent_sha256);
}
export async function parsePilotInspection(raw: string, actor: PilotActor, ref: PilotRef): Promise<PilotInspection> {
  requireValue(uuid(actor.actor_user_id) && validPilotRef(ref)); const v = parse(raw);
  requireValue(closed(v, ["version", "registration_recorded", "registration", "participants", "participant_count", "accepted_account_count",
    "current_bound_roles_checked", "current_bound_roles_available", "registration_document_check_version", "current_registration_document_policy",
    "ready_for_prospective_review", "readiness_scope", ...boundaryKeys]) && v.version === PILOT_VERSION && noAuthority(v)
    && v.registration_recorded === true && v.current_bound_roles_checked === true && typeof v.current_bound_roles_available === "boolean"
    && typeof v.current_registration_document_policy === "boolean" && typeof v.ready_for_prospective_review === "boolean"
    && v.readiness_scope === "current_account_protocol_participation_not_scientific_acceptance"
    && [PILOT_DOCUMENT_POLICY, "ml08-registration-documents/1.0.0"].includes(v.registration_document_check_version as string)
    && v.current_registration_document_policy === (v.registration_document_check_version === PILOT_DOCUMENT_POLICY)
    && integer(v.participant_count, 2, 30) && integer(v.accepted_account_count, 0, v.participant_count) && Array.isArray(v.participants));
  const reg = v.registration, owner = object(reg) && reg.actor_user_id === actor.actor_user_id;
  requireValue(closed(reg, [...registrationFields, ...(owner ? ownerFields : [])]) && reg.id === ref.registration_id && reg.record_sha256 === ref.registration_sha256
    && timestamp(reg.created_at) && [reg.selection_file_sha256, reg.protocol_file_sha256, reg.selection_sha256].every(hash));
  if (owner) { await ownerRegistration(reg); requireValue((reg.implementation as Obj).version === v.registration_document_check_version); }
  requireValue(v.participants.length === (owner ? v.participant_count : 1));
  const roster: Obj[] = [], users = new Set<string>(); let previousAlias = "", accepted = 0;
  for (const row of v.participants) {
    requireValue(closed(row, ["binding", "head"])); const binding = await member(row.binding);
    requireValue(binding.registration_id === reg.id && binding.registration_sha256 === reg.record_sha256 && binding.alias_sha256 > previousAlias
      && !users.has(binding.user_id) && (owner || binding.user_id === actor.actor_user_id) && timeKey(binding.created_at) >= timeKey(reg.created_at));
    users.add(binding.user_id); previousAlias = binding.alias_sha256;
    roster.push({ alias_sha256: binding.alias_sha256, user_id: binding.user_id, reviewer_grant_id: binding.reviewer_grant_id, roles: binding.roles });
    if (row.head !== null) {
      const head = await decision(row.head);
      requireValue(head.actor_user_id === binding.user_id && head.participant_id === binding.id && head.participant_sha256 === binding.record_sha256
        && head.registration_sha256 === reg.record_sha256 && timeKey(head.created_at) >= timeKey(binding.created_at));
      if (head.decision === "accept") accepted++;
    }
  }
  if (owner) {
    requireValue(importCanonical(roster) === importCanonical(reg.roster) && accepted === v.accepted_account_count
      && roster.some(a => roster.some(b => a.user_id !== b.user_id && (a.roles as string[]).includes("primary") && (b.roles as string[]).includes("secondary"))));
  } else requireValue(v.accepted_account_count >= accepted && v.accepted_account_count <= v.participant_count - 1 + accepted);
  requireValue(v.ready_for_prospective_review === (v.current_bound_roles_available && v.current_registration_document_policy && v.accepted_account_count === v.participant_count));
  // Participant projection intentionally cannot reconstruct the hidden full
  // registration hash or other accounts' heads. Do not claim that it does.
  return { ...v, owner } as unknown as PilotInspection;
}
export async function parsePilotResult(raw: string, ref: PilotRecovery, committed: boolean, input?: PilotInput): Promise<PilotResult> {
  requireValue(uuid(ref.actorId) && key(ref.requestKey) && hash(ref.intentSha256)); const v = parse(raw);
  requireValue(closed(v, ["version", "committed", "result"]) && v.version === PILOT_VERSION && v.committed === committed);
  const r = v.result;
  requireValue(closed(r, ["version", "dry_run", "committed", "replayed", "intent", "intent_sha256", "decision", "account_participation_recorded", ...boundaryKeys])
    && r.version === PILOT_VERSION && noAuthority(r) && r.committed === false && r.dry_run === !committed && r.account_participation_recorded === committed
    && typeof r.replayed === "boolean" && validIntent(r.intent) && r.intent.actor_user_id === ref.actorId && r.intent.request_key === ref.requestKey
    && r.intent_sha256 === ref.intentSha256 && await importDigest(r.intent) === ref.intentSha256);
  if (input) requireValue(await importDigest(pilotIntent(input, ref.actorId)) === ref.intentSha256);
  if (committed) { const saved = await decision(r.decision); requireValue(saved.intent_sha256 === ref.intentSha256); }
  else requireValue(r.decision === null);
  return r as unknown as PilotResult;
}

/** Bound even a stalled fetch/read/hash without logging or persisting its data. */
async function bounded<T>(action: (signal: AbortSignal, interrupted: Promise<never>) => Promise<T>, caller?: AbortSignal, timeout = 65000): Promise<T> {
  if (caller?.aborted) throw new ApiError(0, null, "Private pilot operation interrupted");
  const controller = new AbortController(), abort = () => controller.abort();
  let reject!: (error: Error) => void;
  const interrupted = new Promise<never>((_, no) => { reject = no; });
  const stop = () => reject(new ApiError(0, null, "Private pilot operation interrupted"));
  controller.signal.addEventListener("abort", stop, { once: true }); caller?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, timeout);
  try { return await Promise.race([action(controller.signal, interrupted), interrupted]); }
  finally { clearTimeout(timer); caller?.removeEventListener("abort", abort); controller.signal.removeEventListener("abort", stop); controller.abort(); }
}
type Endpoint = "/participant-access" | "/inspect" | "/participation/accept" | "/participation/decisions" | "/participation/outcome";
async function wire(path: Endpoint, body?: object, caller?: AbortSignal, invitation?: PilotInput) {
  const payload = body === undefined ? undefined : JSON.stringify(body);
  requireValue(payload === undefined || new TextEncoder().encode(payload).length <= (path === "/participation/accept" ? PILOT_UPLOAD_LIMIT : 8192));
  return bounded(async (signal, interrupted) => {
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined, stream: ReadableStream<Uint8Array> | null = null;
    try {
      const response = await Promise.race([fetch(`${API_BASE}/ml/pilots${path}`, { method: payload === undefined ? "GET" : "POST", body: payload,
        credentials: "include", cache: "no-store", redirect: "error", signal,
        headers: { Accept: "application/json", ...(payload === undefined ? {} : { "Content-Type": "application/json" }),
          ...(invitation ? { "X-SCLib-Participant-Id": invitation.participant_id, "X-SCLib-Participant-Sha256": invitation.participant_sha256 } : {}) } }), interrupted]);
      stream = response.body;
      if (!response.ok) throw new ApiError(response.status, null, "Private pilot request unavailable");
      const limit = path === "/participant-access" ? 4096 : PILOT_RESPONSE_LIMIT, length = response.headers.get("content-length");
      requireValue(/^application\/json(?:\s*;|$)/i.test(response.headers.get("content-type") ?? "") && stream
        && (length === null || /^\d+$/.test(length) && Number(length) <= limit));
      reader = stream.getReader(); const decoder = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }); let raw = "", size = 0, parts = 0;
      while (true) {
        const item = await Promise.race([reader.read(), interrupted]); requireValue(!signal.aborted);
        if (item.done) break; size += item.value.length; requireValue(size <= limit && ++parts <= 4096); raw += decoder.decode(item.value, { stream: true });
      }
      return raw + decoder.decode();
    } catch (error) { if (error instanceof ApiError) throw error; throw new ApiError(0, null, "Private pilot response unavailable"); }
    finally { if (reader) void reader.cancel().catch(() => {}); else void stream?.cancel().catch(() => {}); }
  }, caller);
}
export const getPilotAccess = (signal?: AbortSignal) => wire("/participant-access", undefined, signal);
export function inspectPilot(ref: PilotRef, signal?: AbortSignal) { requireValue(validPilotRef(ref)); return wire("/inspect", ref, signal); }
export const pilotBytesHash = async (bytes: Uint8Array) => Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new Uint8Array(bytes)))).map(b => b.toString(16).padStart(2, "0")).join("");
function base64(bytes: Uint8Array) {
  const chunks = []; for (let i = 0; i < bytes.length; i += 16384) chunks.push(String.fromCharCode(...bytes.subarray(i, i + 16384))); return btoa(chunks.join(""));
}
export async function preparePilotFiles(reg: PilotRegistration, selection: File, protocol: File, signal?: AbortSignal): Promise<PilotFiles> {
  requireValue([reg.selection_file_sha256, reg.protocol_file_sha256, reg.selection_sha256].every(hash));
  for (const file of [selection, protocol]) requireValue(file && integer(file.size, 1, PILOT_FILE_LIMIT));
  return bounded(async (active, interrupted) => {
    const read = async (file: File, pin: string) => {
      const bytes = new Uint8Array(await Promise.race([file.arrayBuffer(), interrupted]));
      requireValue(!active.aborted && bytes.length === file.size && bytes.length <= PILOT_FILE_LIMIT && await pilotBytesHash(bytes) === pin);
      requireValue(!active.aborted); return base64(bytes);
    };
    const [selection_base64, protocol_base64] = await Promise.all([read(selection, reg.selection_file_sha256), read(protocol, reg.protocol_file_sha256)]);
    requireValue(!active.aborted);
    return { selection_base64, protocol_base64, selection_file_sha256: reg.selection_file_sha256, protocol_file_sha256: reg.protocol_file_sha256, selection_sha256: reg.selection_sha256 };
  }, signal, 30000);
}
async function send(input: PilotInput, actorId: string, files: PilotFiles | null, pin: string | null, signal?: AbortSignal) {
  pilotIntent(input, actorId); requireValue(pin === null || hash(pin));
  const controls = { ...input, dry_run: pin === null, expected_intent_sha256: pin };
  if (input.decision !== "accept") { requireValue(files === null); return wire("/participation/decisions", controls, signal); }
  requireValue(closed(files, ["selection_base64", "protocol_base64", "selection_file_sha256", "protocol_file_sha256", "selection_sha256"])
    && [files.selection_file_sha256, files.protocol_file_sha256, files.selection_sha256].every(hash));
  for (const name of ["selection_base64", "protocol_base64"] as const) requireValue(typeof files[name] === "string" && files[name].length > 0 && files[name].length <= Math.ceil(PILOT_FILE_LIMIT / 3) * 4);
  const { decision: _decision, ...parameters } = controls;
  return wire("/participation/accept", { version: "ml08-registration-upload/1.0.0", operation: "accept", ...files, parameters }, signal, input);
}
export const previewPilotDecision = (input: PilotInput, actorId: string, files: PilotFiles | null, signal?: AbortSignal) => send(input, actorId, files, null, signal);
export const commitPilotDecision = (input: PilotInput, actorId: string, files: PilotFiles | null, pin: string, signal?: AbortSignal) => { requireValue(hash(pin)); return send(input, actorId, files, pin, signal); };
export function recoverPilotDecision(ref: PilotRecovery, signal?: AbortSignal) {
  requireValue(uuid(ref.actorId) && key(ref.requestKey) && hash(ref.intentSha256));
  return wire("/participation/outcome", { request_key: ref.requestKey, expected_intent_sha256: ref.intentSha256 }, signal);
}
