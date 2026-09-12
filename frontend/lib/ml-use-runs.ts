/** Closed run-governance protocol. Verified receipts are not execution authority. */
import { API_BASE, ApiError } from "./api";
import { parsePrivateDiscoveryJSON } from "./discovery-scientific";
import { mlRightsHash as hash, mlRightsKey as key, mlRightsUuid as uuid } from "./ml-use-rights";
import { importCanonical, importDigest } from "./scientific-imports";

export { mlRightsHash as runHash, mlRightsKey as runKey, mlRightsUuid as runUuid } from "./ml-use-rights";
export const RUN_VERSION = "ml-use-run-governance/1.0.0";
export const RUN_PROFILE = "private-cpu-baseline/1.0.0";
export const RUN_PURPOSE = "private_baseline_evaluation";
export const RUN_LIMIT = 128 * 1024;
export type RunKind = "plan" | "decision";
export type RunActor = { kind: RunKind; actor_user_id: string; curator_grant_id: string; role_grant_id: string };
export type SubmissionRef = { submission_id: string; submission_sha256: string; inventory_sha256: string };
export type PlanRef = { plan_id: string; plan_sha256: string };
export type RunBudget = { cpu_seconds: number; wall_seconds: number; memory_mib: number };
type InputPins = { prepared_sha256: string; task_sha256: string; config_sha256: string; package_sha256: string;
  implementation_sha256: string; runtime_sha256: string };
type HostDocuments = { implementation_json: string; runtime_json: string };
export type RunPlanInput = SubmissionRef & InputPins & RunBudget & { requester_grant_id: string; curator_grant_id: string; request_key: string };
export type RunDecisionInput = PlanRef & { approver_grant_id: string; curator_grant_id: string; request_key: string;
  decision: "approve" | "deny" | "revoke"; reason_code: string; evidence_sha256: string | null; expires_epoch: number | null;
  supersedes_id: string | null; supersedes_sha256: string | null };
export type RunInput = RunPlanInput | RunDecisionInput;
type RecordFields = { id: string; actor_user_id: string; version: string; intent_sha256: string; record_sha256: string; created_at: string };
export type RunPlan = RunPlanInput & RecordFields & HostDocuments & { runner_profile: typeof RUN_PROFILE; purpose: typeof RUN_PURPOSE };
export type RunDecision = RunDecisionInput & RecordFields;
export type RunContext = SubmissionRef & InputPins & HostDocuments & { actor_user_id: string; requester_grant_id: string;
  curator_grant_id: string; input_access_expires_at: string; runner_profile: typeof RUN_PROFILE; purpose: typeof RUN_PURPOSE };
export type RunInspection = { plan: RunPlan; head: RunDecision | null; recorded_approval_status: ApprovalStatus; input_access_expires_at: string };
export type RunRecovery = { kind: RunKind; actorId: string; requestKey: string; intentSha256: string };
export type RunResult = { kind: RunKind; intent: Obj; intent_sha256: string; record: RunPlan | RunDecision | null; replayed: boolean; dry_run: boolean };
export const APPROVAL_STATUSES = ["unreviewed", "conditional_approval_recorded", "denied", "revoked", "expired", "approver_unavailable"] as const;
export type ApprovalStatus = typeof APPROVAL_STATUSES[number];
export const COVERAGE_STATUSES = ["allow_recorded", "unreviewed", "denied", "revoked", "expired", "reviewer_unavailable"] as const;
type CoverageStatus = typeof COVERAGE_STATUSES[number];
export type RunCoverage = SubmissionRef & { resource_count: number; status_counts: Record<CoverageStatus, number>; coverage_sha256: string;
  recorded_permissions_complete: boolean; source_permission_granted: boolean; current_source_validity_passed: boolean; observed_epoch: string;
  first_blocked_resources: { resource_id: string; status: Exclude<CoverageStatus, "allow_recorded">; decision_id: string | null; record_sha256: string | null }[] };
export type RunReadiness = PlanRef & { approval: RunDecision | null; approval_status: ApprovalStatus; source_coverage: RunCoverage;
  fingerprints_match: { implementation: boolean; runtime: boolean }; observed_epoch: string; blockers: string[]; conditional_run_approval_current: boolean };
type Obj = Record<string, unknown>;
const baseFlags = ["scientific_acceptance", "public_release", "ml_training_approved", "reviewer_authority_authenticated", "live_source_rights_checked",
  "external_dependency_completeness_proven", "source_permission_granted", "run_authorization_granted", "data_access_granted",
  "current_source_validity_checked", "legal_evidence_independently_verified"];
const runFlags = ["conditional_run_approval_current", "execution_environment_attested", "budget_reserved", "scientific_pilot_accepted", "execution_consumer_available"];
const boundaryKeys = [...baseFlags, "training_execution", ...runFlags];
const submissionFields = ["submission_id", "submission_sha256", "inventory_sha256"];
const inputPins = ["prepared_sha256", "task_sha256", "config_sha256", "package_sha256", "implementation_sha256", "runtime_sha256"];
const budgetFields = ["cpu_seconds", "wall_seconds", "memory_mib"];
const planFields = ["actor_user_id", "requester_grant_id", "curator_grant_id", ...submissionFields, ...inputPins, ...budgetFields, "request_key"];
const decisionFields = ["actor_user_id", "approver_grant_id", "curator_grant_id", "plan_id", "plan_sha256", "request_key", "decision",
  "reason_code", "evidence_sha256", "expires_epoch", "supersedes_id", "supersedes_sha256"];
const budgetLimits = { cpu_seconds_min: 1, cpu_seconds_max: 1800, wall_seconds_min: 1, wall_seconds_max: 1800, memory_mib_min: 128, memory_mib_max: 4096 };
const fields = (kind: RunKind) => kind === "plan" ? planFields : decisionFields;
const intentVersion = (kind: RunKind) => kind === "plan" ? "ml-use-run-plan-intent/1.0.0" : "ml-use-run-decision-intent/1.0.0";
const roleField = (kind: RunKind) => kind === "plan" ? "requester_grant_id" : "approver_grant_id";
const object = (v: unknown): v is Obj => v !== null && typeof v === "object" && !Array.isArray(v);
const closed = (v: unknown, names: string[]): v is Obj => object(v) && Object.keys(v).length === names.length && names.every(k => Object.hasOwn(v, k));
const integer = (v: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max;
const text = (v: unknown, max: number): v is string => typeof v === "string" && v.length > 0 && v.length <= max && !/[\u0000-\u001f\u007f-\u009f]/.test(v);
const timestamp = (v: unknown): v is string => typeof v === "string" && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(v)
  && !v.startsWith("0000") && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0, 19) === v.slice(0, 19);
const epoch = (v: unknown): v is string => typeof v === "string" && /^[1-9]\d{0,12}(?:\.\d{1,6})?$/.test(v);
function requireValue(v: unknown): asserts v { if (!v) throw new Error("The private ML run response could not be verified."); }
const same = (v: Obj, expected: object, keys: string[]) => keys.every(k => v[k] === (expected as Obj)[k]);
const noAuthority = (v: Obj, observed: string[] = [], run = true) => [...baseFlags, ...(run ? runFlags : [])].every(k => observed.includes(k) ? typeof v[k] === "boolean" : v[k] === false)
  && v.training_execution === "disabled";
const parse = (raw: string, limit = RUN_LIMIT) => { const value = parsePrivateDiscoveryJSON(raw, limit).value; requireValue(importCanonical(value) === raw); return value; };
export const validSubmissionRef = (v: SubmissionRef) => uuid(v.submission_id) && hash(v.submission_sha256) && hash(v.inventory_sha256);
export const validPlanRef = (v: PlanRef) => uuid(v.plan_id) && hash(v.plan_sha256);
export const validRunBudget = (v: RunBudget) => integer(v.cpu_seconds, 1, 1800) && integer(v.wall_seconds, v.cpu_seconds, 1800) && integer(v.memory_mib, 128, 4096);

export function parseRunAccess(raw: string, kind: RunKind): RunActor {
  const v = parse(raw, 4096), role = roleField(kind), capability = kind === "plan" ? "can_request_plan" : "can_review_plan";
  requireValue(closed(v, ["version", "actor_user_id", "curator_grant_id", role, capability, ...boundaryKeys])
    && v.version === RUN_VERSION && noAuthority(v) && v[capability] === true && [v.actor_user_id, v.curator_grant_id, v[role]].every(uuid));
  return { kind, actor_user_id: v.actor_user_id as string, curator_grant_id: v.curator_grant_id as string, role_grant_id: v[role] as string };
}
async function hostDocuments(v: Obj) {
  for (const name of ["implementation", "runtime"]) {
    const raw = v[name + "_json"];
    requireValue(typeof raw === "string" && new TextEncoder().encode(raw).length <= 16384 && hash(v[name + "_sha256"]));
    const pin = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(raw)))).map(x => x.toString(16).padStart(2, "0")).join("");
    requireValue(pin === v[name + "_sha256"]);
    // Numerical policy contains Python float tokens. Hash its original string
    // bytes, never parse/re-serialize it through the integer-only intent codec.
    const doc = parsePrivateDiscoveryJSON(raw, 16384).value;
    if (name === "implementation") {
      requireValue(closed(doc, ["version", "selected_modules", "scope"]) && doc.version === "ml-run-source-observation/1.0.0"
        && doc.scope === "on_disk_selected_sources_not_loaded_code_or_complete_release_attestation" && object(doc.selected_modules)
        && Object.keys(doc.selected_modules).length > 0 && Object.keys(doc.selected_modules).length <= 64
        && Object.entries(doc.selected_modules).every(([k, value]) => /^(models|services|routers)\.[a-zA-Z0-9_.]+$/.test(k) && hash(value)));
    } else {
      requireValue(closed(doc, ["version", "observed", "scope"]) && doc.version === "ml-run-host-observation/1.0.0"
        && doc.scope === "host_properties_and_lockfile_not_installed_dependency_or_execution_image_attestation"
        && closed(doc.observed, ["api_lock_sha256", "python", "implementation", "machine", "byteorder", "numerical_policy"]));
      const observed = doc.observed;
      requireValue(hash(observed.api_lock_sha256) && text(observed.python, 4096) && text(observed.implementation, 80)
        && text(observed.machine, 80) && ["little", "big"].includes(observed.byteorder as string));
      const p = observed.numerical_policy;
      requireValue(closed(p, ["version", "ridge_objective", "intercept", "solver", "pivot_relative_tolerance", "pivot_absolute_tolerance",
        "replay_relative_tolerance", "replay_absolute_tolerance"]) && p.version === "float64-normal-equations/1.0.0"
        && p.ridge_objective === "sum_squared_error_plus_alpha_l2_slopes" && p.intercept === "unpenalized"
        && p.solver === "centered_normal_equations_partial_pivot" && p.pivot_relative_tolerance === 1e-12
        && p.pivot_absolute_tolerance === 1e-14 && p.replay_relative_tolerance === 1e-10 && p.replay_absolute_tolerance === 1e-10);
    }
  }
}
function validIntent(v: unknown, kind: RunKind): v is Obj {
  if (!closed(v, ["version", ...fields(kind)]) || v.version !== intentVersion(kind) || !uuid(v.actor_user_id)
    || !uuid(v.curator_grant_id) || !uuid(v[roleField(kind)]) || !key(v.request_key)) return false;
  if (kind === "plan") return validSubmissionRef(v as SubmissionRef) && inputPins.every(k => hash(v[k])) && validRunBudget(v as RunBudget);
  return validPlanRef(v as PlanRef) && ["approve", "deny", "revoke"].includes(v.decision as string)
    && typeof v.reason_code === "string" && /^[a-z][a-z0-9_]{0,159}$/.test(v.reason_code) && (v.evidence_sha256 === null || hash(v.evidence_sha256))
    && (v.supersedes_id === null || uuid(v.supersedes_id)) && (v.supersedes_sha256 === null || hash(v.supersedes_sha256))
    && (v.supersedes_id === null) === (v.supersedes_sha256 === null) && (v.decision !== "revoke" || v.supersedes_id !== null)
    && (v.decision === "approve" ? hash(v.evidence_sha256) && integer(v.expires_epoch, 1) : v.expires_epoch === null);
}
export function runIntent(kind: RunKind, input: RunInput, actorId: string): Obj {
  const v = { version: intentVersion(kind), ...input, actor_user_id: actorId }; requireValue(validIntent(v, kind)); return v;
}
async function record(v: unknown, kind: RunKind): Promise<RunPlan | RunDecision> {
  requireValue(closed(v, ["version", ...fields(kind), "id", "intent_sha256", "record_sha256", "created_at",
    ...(kind === "plan" ? ["implementation_json", "runtime_json", "runner_profile", "purpose"] : [])])
    && v.version === RUN_VERSION && uuid(v.id) && hash(v.intent_sha256) && hash(v.record_sha256) && timestamp(v.created_at));
  const i = { version: intentVersion(kind), ...Object.fromEntries(fields(kind).map(k => [k, v[k]])) };
  requireValue(validIntent(i, kind) && await importDigest(i) === v.intent_sha256);
  const { created_at: _date, record_sha256: pin, ...body } = v;
  requireValue(await importDigest(body) === pin);
  if (kind === "plan") { requireValue(v.runner_profile === RUN_PROFILE && v.purpose === RUN_PURPOSE); await hostDocuments(v); }
  else requireValue(v.supersedes_id !== v.id && (v.decision !== "approve" || (v.expires_epoch as number) > Date.parse(v.created_at as string) / 1000));
  return v as unknown as RunPlan | RunDecision;
}
export async function parseRunContext(raw: string, actor: RunActor, ref: SubmissionRef): Promise<RunContext> {
  const v = parse(raw);
  requireValue(actor.kind === "plan" && validSubmissionRef(ref) && closed(v, ["version", "actor_user_id", "requester_grant_id", "curator_grant_id",
    ...submissionFields, ...inputPins, "implementation_json", "runtime_json", "runner_profile", "purpose", "input_access_expires_at", "budget_limits", "budget_scope", ...boundaryKeys])
    && v.version === RUN_VERSION && noAuthority(v) && same(v, ref, submissionFields) && v.actor_user_id === actor.actor_user_id
    && v.curator_grant_id === actor.curator_grant_id && v.requester_grant_id === actor.role_grant_id && inputPins.every(k => hash(v[k]))
    && v.runner_profile === RUN_PROFILE && v.purpose === RUN_PURPOSE && timestamp(v.input_access_expires_at)
    && importCanonical(v.budget_limits) === importCanonical(budgetLimits)
    && v.budget_scope === "requested_single_process_cpu_budget_not_reserved_or_enforced_by_this_endpoint");
  await hostDocuments(v); return v as unknown as RunContext;
}
function statusMatches(status: unknown, head: RunDecision | null) {
  return APPROVAL_STATUSES.includes(status as ApprovalStatus) && (head === null ? status === "unreviewed"
    : head.decision === "deny" ? status === "denied" : head.decision === "revoke" ? status === "revoked"
      : ["conditional_approval_recorded", "expired", "approver_unavailable"].includes(status as string));
}
export async function parseRunInspection(raw: string, actor: RunActor, ref: PlanRef): Promise<RunInspection> {
  const v = parse(raw);
  requireValue(actor.kind === "decision" && validPlanRef(ref) && closed(v, ["version", "actor_user_id", "approver_grant_id", "curator_grant_id",
    "plan", "head", "recorded_approval_status", "input_access_expires_at", "scope", ...boundaryKeys]) && v.version === RUN_VERSION && noAuthority(v)
    && v.actor_user_id === actor.actor_user_id && v.curator_grant_id === actor.curator_grant_id && v.approver_grant_id === actor.role_grant_id
    && v.scope === "conditional_plan_review_metadata_not_live_readiness" && timestamp(v.input_access_expires_at));
  const plan = await record(v.plan, "plan") as RunPlan;
  requireValue(plan.id === ref.plan_id && plan.record_sha256 === ref.plan_sha256 && plan.actor_user_id !== actor.actor_user_id);
  const head = v.head === null ? null : await record(v.head, "decision") as RunDecision;
  requireValue(statusMatches(v.recorded_approval_status, head) && (head === null || head.plan_id === plan.id && head.plan_sha256 === plan.record_sha256 && head.actor_user_id !== plan.actor_user_id));
  if (head?.decision === "approve") requireValue(head.expires_epoch! <= Date.parse(v.input_access_expires_at) / 1000);
  return { plan, head, recorded_approval_status: v.recorded_approval_status as ApprovalStatus, input_access_expires_at: v.input_access_expires_at };
}
export async function parseRunResult(raw: string, ref: RunRecovery, committed: boolean, input?: RunInput): Promise<RunResult> {
  requireValue(uuid(ref.actorId) && key(ref.requestKey) && hash(ref.intentSha256));
  const v = parse(raw);
  requireValue(closed(v, ["version", "committed", "result"]) && v.version === RUN_VERSION && v.committed === committed);
  const r = v.result;
  requireValue(closed(r, ["version", "dry_run", "committed", "replayed", "intent", "intent_sha256", ref.kind, "scope", ...boundaryKeys])
    && r.version === RUN_VERSION && noAuthority(r) && r.committed === false && r.dry_run === !committed && typeof r.replayed === "boolean"
    && r.scope === "historical_exact_run_contract_not_live_permission_or_execution_authority" && validIntent(r.intent, ref.kind)
    && r.intent.actor_user_id === ref.actorId && r.intent.request_key === ref.requestKey && r.intent_sha256 === ref.intentSha256
    && await importDigest(r.intent) === ref.intentSha256);
  if (input) requireValue(await importDigest(runIntent(ref.kind, input, ref.actorId)) === ref.intentSha256);
  const item = committed ? await record(r[ref.kind], ref.kind) : null;
  requireValue(committed ? item!.intent_sha256 === ref.intentSha256 : r[ref.kind] === null);
  return { kind: ref.kind, intent: r.intent, intent_sha256: r.intent_sha256 as string, record: item, replayed: r.replayed, dry_run: r.dry_run as boolean };
}
function coverage(v: unknown): RunCoverage {
  requireValue(closed(v, ["version", ...submissionFields, "purpose", "resource_count", "status_counts", "coverage_sha256", "recorded_permissions_complete",
    "first_blocked_resources", "observed_epoch", "scope", ...baseFlags, "training_execution", "current_source_validity_passed"])
    && v.version === "ml-use-rights/1.0.0" && validSubmissionRef(v as SubmissionRef) && v.purpose === RUN_PURPOSE
    && noAuthority(v, ["source_permission_granted", "live_source_rights_checked", "current_source_validity_checked"], false)
    && v.live_source_rights_checked === true && v.current_source_validity_checked === true && typeof v.current_source_validity_passed === "boolean"
    && integer(v.resource_count, 1, 8000) && closed(v.status_counts, [...COVERAGE_STATUSES]) && Object.values(v.status_counts).every(n => integer(n, 0, 8000))
    && Object.values(v.status_counts).reduce<number>((sum, n) => sum + (n as number), 0) === v.resource_count
    && hash(v.coverage_sha256) && epoch(v.observed_epoch) && v.scope === "exact_current_inventory_private_baseline_only_no_authorization_lease"
    && v.recorded_permissions_complete === (v.status_counts.allow_recorded === v.resource_count)
    && v.source_permission_granted === (v.recorded_permissions_complete && v.current_source_validity_passed)
    && Array.isArray(v.first_blocked_resources) && v.first_blocked_resources.length === Math.min(25, v.resource_count - (v.status_counts.allow_recorded as number)));
  let last = ""; const visibleCounts: Record<string, number> = {};
  for (const row of v.first_blocked_resources) {
    requireValue(closed(row, ["resource_id", "status", "decision_id", "record_sha256"]) && hash(row.resource_id) && row.resource_id > last
      && COVERAGE_STATUSES.slice(1).includes(row.status as never) && (v.status_counts[row.status as string] as number) > 0
      && (row.status === "unreviewed" ? row.decision_id === null && row.record_sha256 === null : uuid(row.decision_id) && hash(row.record_sha256)));
    last = row.resource_id;
    const status = row.status as string; visibleCounts[status] = (visibleCounts[status] ?? 0) + 1;
    requireValue(visibleCounts[status] <= (v.status_counts[status] as number));
  }
  return v as unknown as RunCoverage;
}
export async function parseRunReadiness(raw: string, actor: RunActor, ref: PlanRef, plan?: RunPlan): Promise<RunReadiness> {
  const v = parse(raw);
  requireValue(actor.kind === "plan" && validPlanRef(ref) && closed(v, ["version", "plan_id", "plan_sha256", "approval", "approval_status", "source_coverage",
    "fingerprints_match", "observed_epoch", "blockers", "decision", "ready_for_execution", "scope", ...boundaryKeys]) && v.version === RUN_VERSION
    && noAuthority(v, ["conditional_run_approval_current", "source_permission_granted", "live_source_rights_checked", "current_source_validity_checked"])
    && same(v, ref, ["plan_id", "plan_sha256"]) && v.live_source_rights_checked === true && v.current_source_validity_checked === true
    && v.ready_for_execution === false && v.decision === "not_authorized" && v.scope === "current_snapshot_only_not_a_permission_lease"
    && closed(v.fingerprints_match, ["implementation", "runtime"]) && Object.values(v.fingerprints_match).every(x => typeof x === "boolean") && epoch(v.observed_epoch));
  const approved = v.approval === null ? null : await record(v.approval, "decision") as RunDecision;
  requireValue(statusMatches(v.approval_status, approved) && (approved === null || approved.plan_id === ref.plan_id && approved.plan_sha256 === ref.plan_sha256 && approved.actor_user_id !== actor.actor_user_id)
    && v.conditional_run_approval_current === (v.approval_status === "conditional_approval_recorded"));
  if (approved) requireValue(Date.parse(approved.created_at) / 1000 <= Number(v.observed_epoch));
  if (v.approval_status === "conditional_approval_recorded") requireValue(approved!.expires_epoch! > Number(v.observed_epoch));
  if (v.approval_status === "expired") requireValue(approved!.expires_epoch! <= Number(v.observed_epoch));
  const source = coverage(v.source_coverage);
  requireValue(source.source_permission_granted === v.source_permission_granted && Number(source.observed_epoch) <= Number(v.observed_epoch));
  if (plan) requireValue(plan.id === ref.plan_id && plan.record_sha256 === ref.plan_sha256 && plan.actor_user_id === actor.actor_user_id && same(source as unknown as Obj, plan, submissionFields));
  const blockers = ["independent_scientific_pilot_not_attested", "guarded_execution_consumer_unavailable", "execution_environment_not_attested"];
  if (!source.source_permission_granted) blockers.push("current_source_permissions_or_validity_incomplete");
  if (v.approval_status !== "conditional_approval_recorded") blockers.push("exact_plan_approval_" + v.approval_status);
  for (const name of ["implementation", "runtime"]) if (!v.fingerprints_match[name]) blockers.push(name + "_fingerprint_changed");
  requireValue(importCanonical(v.blockers) === importCanonical(blockers));
  return v as unknown as RunReadiness;
}

const endpoints = ["/requester-access", "/approver-access", "/context", "/plans", "/inspect", "/decisions", "/plans/outcome", "/decisions/outcome", "/check"] as const;
type Endpoint = typeof endpoints[number];
async function wire(path: Endpoint, body?: object, signal?: AbortSignal) {
  requireValue(endpoints.includes(path));
  if (signal?.aborted) throw new ApiError(0, null, "Private ML run request interrupted");
  const payload = body === undefined ? undefined : JSON.stringify(body);
  requireValue(payload === undefined || new TextEncoder().encode(payload).length <= 8192);
  const controller = new AbortController(), abort = () => controller.abort();
  let reject!: (error: Error) => void;
  const interrupted = new Promise<never>((_, no) => { reject = no; });
  const stop = () => reject(new ApiError(0, null, "Private ML run request interrupted"));
  controller.signal.addEventListener("abort", stop, { once: true }); signal?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, path === "/check" ? 95000 : 30000);
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined, stream: ReadableStream<Uint8Array> | null = null;
  try {
    const response = await Promise.race([fetch(`${API_BASE}/ml/use/runs${path}`, { method: payload === undefined ? "GET" : "POST", body: payload,
      credentials: "include", cache: "no-store", redirect: "error", signal: controller.signal,
      headers: { Accept: "application/json", ...(payload === undefined ? {} : { "Content-Type": "application/json" }) } }), interrupted]);
    stream = response.body;
    if (!response.ok) throw new ApiError(response.status, null, "Private ML run request unavailable");
    const length = response.headers.get("content-length"), limit = path.endsWith("-access") ? 4096 : RUN_LIMIT;
    requireValue(/^application\/json(?:\s*;|$)/i.test(response.headers.get("content-type") ?? "") && stream
      && (length === null || /^\d+$/.test(length) && Number(length) <= limit));
    reader = stream.getReader(); const decoder = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }); let raw = "", size = 0, parts = 0;
    while (true) { const item = await Promise.race([reader.read(), interrupted]); requireValue(!controller.signal.aborted);
      if (item.done) break; size += item.value.length; requireValue(size <= limit && ++parts <= 4096); raw += decoder.decode(item.value, { stream: true }); }
    return raw + decoder.decode();
  } catch (e) { if (e instanceof ApiError) throw e; throw new ApiError(0, null, "Private ML run response unavailable"); }
  finally { clearTimeout(timer); signal?.removeEventListener("abort", abort); controller.signal.removeEventListener("abort", stop); controller.abort();
    if (reader) void reader.cancel().catch(() => {}); else void stream?.cancel().catch(() => {}); }
}
export const getRunAccess = (kind: RunKind, signal?: AbortSignal) => wire(kind === "plan" ? "/requester-access" : "/approver-access", undefined, signal);
export const inspectRunContext = (ref: SubmissionRef, signal?: AbortSignal) => { requireValue(validSubmissionRef(ref)); return wire("/context", ref, signal); };
export const inspectRunPlan = (ref: PlanRef, signal?: AbortSignal) => { requireValue(validPlanRef(ref)); return wire("/inspect", ref, signal); };
export const previewRun = (kind: RunKind, input: RunInput, signal?: AbortSignal) => wire(kind === "plan" ? "/plans" : "/decisions", { ...input, dry_run: true }, signal);
export const commitRun = (kind: RunKind, input: RunInput, pin: string, signal?: AbortSignal) => {
  requireValue(hash(pin)); return wire(kind === "plan" ? "/plans" : "/decisions", { ...input, dry_run: false, expected_intent_sha256: pin }, signal); };
export const recoverRun = (ref: RunRecovery, signal?: AbortSignal) => {
  requireValue(key(ref.requestKey) && hash(ref.intentSha256)); return wire(ref.kind === "plan" ? "/plans/outcome" : "/decisions/outcome", { request_key: ref.requestKey, expected_intent_sha256: ref.intentSha256 }, signal); };
export const checkRun = (ref: PlanRef, signal?: AbortSignal) => { requireValue(validPlanRef(ref)); return wire("/check", ref, signal); };
