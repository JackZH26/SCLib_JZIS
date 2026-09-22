/** Closed private display contracts. Pins are server observations, not source authentication. */
type Obj = Record<string, unknown>;
export const TASK_VERSION = "source-task-operation/1.0.0";
export const ACTION_VERSION = "timeline-cache-invalidation/1.0.0";
const negativeKeys = ["propagation_complete", "timeline_rebuilt", "scientific_acceptance", "ml_training_approved", "source_reinstatement", "external_cache_invalidated"];
export interface TaskSemantics {
  action_version: typeof ACTION_VERSION; propagation_complete: false; timeline_rebuilt: false;
  scientific_acceptance: false; ml_training_approved: false; source_reinstatement: false;
  external_cache_invalidated: false; currentness: "historical_receipt_not_live_projection_state";
}
export interface TaskCapabilities extends Omit<TaskSemantics, "currentness"> {
  version: "source-task-capabilities/1.0.0"; actor_user_id: string; actor_grant_id: string; can_read: true; can_write: true;
}
export type TaskOperation = { version: typeof TASK_VERSION; operation: "enqueue"; request_key: string; event_id: string;
  expected_event_sha256: string; expected_inventory_sha256: string }
  | { version: typeof TASK_VERSION; operation: "execute"; request_id: string; expected_request_sha256: string;
      execution_key: string; expected_predecessor_id: string | null; expected_predecessor_sha256: string | null };
export interface TaskRequest {
  id: string; event_id: string; event_sha256: string; source_snapshot_sha256: string;
  inventory_version: "source-impact/1.0.0"; inventory_sha256: string; action_version: typeof ACTION_VERSION;
  requester_id: string; requester_grant_id: string; request_key: string; record_sha256: string; created_at: string;
}
export type AttemptStatus = "succeeded" | "obsolete" | "blocked" | "retryable_failure" | "exhausted";
export interface TaskAttempt {
  id: string; request_id: string; attempt_number: number; predecessor_id: string | null;
  executor_id: string; executor_grant_id: string; execution_key: string; status: AttemptStatus; outcome_code: string;
  state_present: boolean; state_changed: boolean; record_sha256: string; created_at: string;
}
export interface TaskHistory {
  request: TaskRequest; attempts: TaskAttempt[]; stored_state: "queued" | AttemptStatus; retry_scheduled: false; receipt_semantics: TaskSemantics;
}
export interface TaskPreview {
  version: "source-task-preview/1.0.0"; operation: TaskOperation["operation"]; actor_user_id: string; actor_grant_id: string;
  operation_sha256: string; preview_sha256: string; predicted_status: "queued" | AttemptStatus;
  predicted_outcome_code: string | null; can_commit: true; database_mutated: false; replayed: boolean; receipt_semantics: TaskSemantics;
}
export interface TaskReceipt {
  version: "source-task-operation-receipt/1.0.0"; operation: TaskOperation["operation"]; actor_user_id: string; actor_grant_id: string;
  operation_sha256: string; preview_sha256: string; request: TaskRequest; attempt: TaskAttempt | null;
  replayed: boolean; committed: true; requires_outer_commit: false; executed_now: boolean; receipt_semantics: TaskSemantics;
}
export interface LifecycleEvent {
  id: string; paper_id: string | null; work_id: string | null; revision: number; predecessor_id: string | null;
  old_snapshot_sha256: string | null; snapshot_sha256: string; prior_status: string | null; observed_status: string;
  event_kind: "baseline_observed" | "lifecycle_change" | "catalogue_revision"; record_sha256: string; created_at: string;
}
export interface LifecycleHistory {
  source_kind: "paper" | "work"; source_id: string; status: string | null; head: LifecycleEvent | null; events: LifecycleEvent[];
  next_before_revision: number | null; direct_lifecycle_review_required: boolean; lifecycle_review_required: boolean;
  effective_lifecycle_revision: string | null; scientific_acceptance: false; ml_training_approved: false; source_reinstatement: false;
}
export const SUPPORTED_SCOPES = ["direct_event_source_and_current_accepted_work_paper_mapping", "explicit_claim_paper_and_work_references",
  "exact_top_level_material_record_paper_references", "record_backed_material_descendant_governance_and_zero_point_timeline_candidates",
  "claim_material_context_not_record_support", "direct_chunk_and_hydride_paper_references", "active_and_inactive_timeline_paper_and_record_backed_material_references",
  "direct_ml_example_label_claim_work_and_record_backed_material_references", "reached_example_dataset_membership", "reached_object_frozen_pins_and_publication_proposal_references"];
export const UNSUPPORTED_SCOPES = ["transitive_research_event_and_ml_feature_dependencies", "source_revision_capture_and_shadow_import_lineage",
  "indirect_extracted_material_mentions_in_other_sources", "research_samples_and_structure_lineage", "hydride_material_context_not_already_reached_by_supported_paths",
  "malformed_or_non_exact_json_reference_identity", "file_backed_rps_evidence", "cached_answers_and_external_vector_index_state", "dependencies_created_after_this_database_snapshot"];
const TABLES = ["papers", "works", "paper_work_map", "material_claims", "materials", "chunks", "hydride_tc_parameters",
  "timeline_projection_points", "ml_examples", "ml_dataset_snapshots", "research_releases", "research_publication_proposals"];
const RELATIONS = ["direct_source", "accepted_work_mapping", "accepted_work_source", "explicit_claim_paper", "explicit_claim_work", "record_source",
  "claim_material_context", "inherited_parent_governance", "direct_chunk_source", "direct_hydride_source", "existing_timeline_source", "existing_timeline_material",
  "example_label_claim", "example_explicit_work", "example_material_governance", "dataset_example_membership", "historical_frozen_reference", "historical_publication_proposal"];
export interface SourceImpact {
  version: "source-impact/1.0.0"; event: { id: string; record_sha256: string; source_snapshot_sha256: string; revision: number; source_kind: "paper" | "work"; source_id: string };
  nodes: { table: string; row_id: string; relations: { kind: string; via_table: string; via_id: string }[] }[];
  counts: Record<string, number>; node_count: number; timeline_candidate_material_ids: string[];
  complete_for_declared_scope: true; propagation_complete: false; scientific_acceptance: false; ml_training_approved: false; source_reinstatement: false;
  supported_scopes: string[]; unsupported_scopes: string[]; next_actions: { domain: string; status: "not_scheduled" }[];
  limits: { papers: 1000; nodes: 2000; relations: 4000; parent_depth: 32; descriptor_bytes: 1048576 }; inventory_sha256: string;
  observation: { observed_at: string; transaction_isolation: "repeatable read" | "serializable"; currentness: "current_in_database_snapshot";
    persisted: false; refresh_scheduled: false; graph_binding: "relationships_only_not_scientific_row_hashes" };
}

const object = (v: unknown): v is Obj => v !== null && typeof v === "object" && !Array.isArray(v);
const keys = (v: unknown, expected: string[]): v is Obj => object(v) && Object.keys(v).length === expected.length && expected.every(k => Object.hasOwn(v, k));
export const taskUuid = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v);
const hash = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
export const taskKey = (v: unknown): v is string => typeof v === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(v);
export const sourceId = (v: unknown): v is string => typeof v === "string" && v.trim().length > 0 && Array.from(v).length <= 100 && !/[\u0000-\u001f\u007f-\u009f]/.test(v);
const text = (v: unknown, max = 200): v is string => typeof v === "string" && v.trim().length > 0 && Array.from(v).length <= max && !/[\u0000-\u001f\u007f-\u009f]/.test(v);
const integer = (v: unknown, max: number, min = 0): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max;
const timestamp = (v: unknown): v is string => typeof v === "string" && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(v) && Number.isFinite(Date.parse(v));
const choice = (v: unknown, options: readonly string[]) => typeof v === "string" && options.includes(v);
const nullable = (v: unknown, check: (x: unknown) => boolean) => v === null || check(v);
const bool = (v: unknown) => typeof v === "boolean";
const list = (v: unknown, max: number): v is unknown[] => Array.isArray(v) && v.length <= max;
const equal = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const detached = <T,>(v: unknown): T => JSON.parse(JSON.stringify(v)) as T;
function bounded(v: unknown, bytes: number): boolean { try { return new TextEncoder().encode(JSON.stringify(v)).length <= bytes; } catch { return false; } }
function negative(v: Obj) { return v.action_version === ACTION_VERSION && negativeKeys.every(k => v[k] === false); }
function semantics(v: unknown): v is TaskSemantics { return keys(v, ["action_version", ...negativeKeys, "currentness"]) && negative(v) && v.currentness === "historical_receipt_not_live_projection_state"; }
export function knownTaskCapabilities(v: unknown): TaskCapabilities | null {
  return keys(v, ["version", "actor_user_id", "actor_grant_id", "can_read", "can_write", "action_version", ...negativeKeys])
    && v.version === "source-task-capabilities/1.0.0" && taskUuid(v.actor_user_id) && taskUuid(v.actor_grant_id)
    && v.can_read === true && v.can_write === true && negative(v) ? detached(v) : null;
}
export function knownTaskOperation(v: unknown): TaskOperation | null {
  if (!object(v) || v.version !== TASK_VERSION) return null;
  if (v.operation === "enqueue" && keys(v, ["version", "operation", "request_key", "event_id", "expected_event_sha256", "expected_inventory_sha256"])
    && taskKey(v.request_key) && taskUuid(v.event_id) && hash(v.expected_event_sha256) && hash(v.expected_inventory_sha256)) return detached(v);
  if (v.operation === "execute" && keys(v, ["version", "operation", "request_id", "expected_request_sha256", "execution_key", "expected_predecessor_id", "expected_predecessor_sha256"])
    && taskUuid(v.request_id) && hash(v.expected_request_sha256) && taskKey(v.execution_key) && nullable(v.expected_predecessor_id, taskUuid)
    && nullable(v.expected_predecessor_sha256, hash) && (v.expected_predecessor_id === null) === (v.expected_predecessor_sha256 === null)) return detached(v);
  return null;
}
const requestKeys = ["id", "event_id", "event_sha256", "source_snapshot_sha256", "inventory_version", "inventory_sha256", "action_version", "requester_id", "requester_grant_id", "request_key", "record_sha256", "created_at"];
function taskRequest(v: unknown): v is TaskRequest {
  return keys(v, requestKeys) && [v.id, v.event_id, v.requester_id, v.requester_grant_id].every(taskUuid)
    && [v.event_sha256, v.source_snapshot_sha256, v.inventory_sha256, v.record_sha256].every(hash)
    && v.inventory_version === "source-impact/1.0.0" && v.action_version === ACTION_VERSION && taskKey(v.request_key) && timestamp(v.created_at);
}
const outcomes: Record<AttemptStatus, string[]> = { succeeded: ["timeline_cache_invalidated"], obsolete: ["source_changed", "inventory_changed"],
  blocked: ["request_authority_unavailable", "scope_limit", "inventory_unavailable"], retryable_failure: ["database_busy", "statement_timeout", "serialization_failure"], exhausted: ["database_busy", "statement_timeout", "serialization_failure"] };
function statusPair(status: unknown, outcome: unknown) { return choice(status, Object.keys(outcomes)) && choice(outcome, outcomes[status as AttemptStatus]); }
function attempt(v: unknown): v is TaskAttempt {
  return keys(v, ["id", "request_id", "attempt_number", "predecessor_id", "executor_id", "executor_grant_id", "execution_key", "status", "outcome_code", "state_present", "state_changed", "record_sha256", "created_at"])
    && [v.id, v.request_id, v.executor_id, v.executor_grant_id].every(taskUuid) && integer(v.attempt_number, 5, 1)
    && nullable(v.predecessor_id, taskUuid) && (v.attempt_number === 1) === (v.predecessor_id === null) && v.predecessor_id !== v.id
    && taskKey(v.execution_key) && statusPair(v.status, v.outcome_code) && hash(v.record_sha256) && timestamp(v.created_at)
    && bool(v.state_present) && bool(v.state_changed) && (v.state_changed === false || v.state_present === true)
    && (v.status === "succeeded" || v.state_present === false && v.state_changed === false)
    && (v.status !== "retryable_failure" || v.attempt_number < 5) && (v.status !== "exhausted" || v.attempt_number === 5);
}
export function knownTaskHistory(v: unknown, requestId: string): TaskHistory | null {
  if (!bounded(v, 32 * 1024) || !keys(v, ["request", "attempts", "stored_state", "retry_scheduled", "receipt_semantics"])
    || !taskRequest(v.request) || v.request.id !== requestId || !list(v.attempts, 5) || !v.attempts.every(attempt)
    || v.retry_scheduled !== false || !semantics(v.receipt_semantics)) return null;
  const rows = v.attempts as TaskAttempt[];
  if (new Set(rows.map(r => r.id)).size !== rows.length || new Set(rows.map(r => r.execution_key)).size !== rows.length
    || rows.some((row, n) => row.request_id !== requestId || row.attempt_number !== n + 1
      || row.predecessor_id !== (n ? rows[n - 1].id : null) || n > 0 && rows[n - 1].status !== "retryable_failure")
    || v.stored_state !== (rows.at(-1)?.status ?? "queued")) return null;
  return detached(v);
}
export function knownTaskPreview(v: unknown, operation: TaskOperation, access: TaskCapabilities, operationSha: string): TaskPreview | null {
  return bounded(v, 8192) && keys(v, ["version", "operation", "actor_user_id", "actor_grant_id", "operation_sha256", "preview_sha256", "predicted_status", "predicted_outcome_code", "can_commit", "database_mutated", "replayed", "receipt_semantics"])
    && v.version === "source-task-preview/1.0.0" && v.operation === operation.operation
    && v.actor_user_id === access.actor_user_id && taskUuid(v.actor_grant_id) && (v.replayed === true || v.actor_grant_id === access.actor_grant_id)
    && hash(operationSha) && v.operation_sha256 === operationSha && hash(v.preview_sha256) && v.can_commit === true && v.database_mutated === false
    && bool(v.replayed) && semantics(v.receipt_semantics)
    && (operation.operation === "enqueue" ? v.predicted_status === "queued" && v.predicted_outcome_code === null : statusPair(v.predicted_status, v.predicted_outcome_code)) ? detached(v) : null;
}
export function knownTaskReceipt(v: unknown, expected: { actorId: string; operation?: TaskOperation; operationSha?: string; preview?: TaskPreview; requestKey?: string; requestId?: string; executionKey?: string }): TaskReceipt | null {
  if (!bounded(v, 32 * 1024) || !keys(v, ["version", "operation", "actor_user_id", "actor_grant_id", "operation_sha256", "preview_sha256", "request", "attempt", "replayed", "committed", "requires_outer_commit", "executed_now", "receipt_semantics"])
    || v.version !== "source-task-operation-receipt/1.0.0" || !choice(v.operation, ["enqueue", "execute"])
    || v.actor_user_id !== expected.actorId || !taskUuid(v.actor_grant_id) || !hash(v.operation_sha256) || !hash(v.preview_sha256)
    || !taskRequest(v.request) || !bool(v.replayed) || v.committed !== true || v.requires_outer_commit !== false || !bool(v.executed_now)
    || !semantics(v.receipt_semantics)) return null;
  if (v.operation === "enqueue" ? v.attempt !== null || v.request.requester_id !== expected.actorId || v.request.requester_grant_id !== v.actor_grant_id || v.executed_now !== false
    : !attempt(v.attempt) || v.attempt.request_id !== v.request.id || v.attempt.executor_id !== expected.actorId || v.attempt.executor_grant_id !== v.actor_grant_id
      || v.executed_now !== (!v.replayed && v.attempt.status === "succeeded")) return null;
  if (expected.requestKey !== undefined && (v.operation !== "enqueue" || v.request.request_key !== expected.requestKey)
    || expected.requestId !== undefined && v.request.id !== expected.requestId
    || expected.executionKey !== undefined && (v.operation !== "execute" || (v.attempt as TaskAttempt).execution_key !== expected.executionKey)) return null;
  const op = expected.operation;
  if (op && (!hash(expected.operationSha) || v.operation_sha256 !== expected.operationSha || v.operation !== op.operation || (op.operation === "enqueue"
    ? v.request.request_key !== op.request_key || v.request.event_id !== op.event_id || v.request.event_sha256 !== op.expected_event_sha256 || v.request.inventory_sha256 !== op.expected_inventory_sha256
    : v.request.id !== op.request_id || v.request.record_sha256 !== op.expected_request_sha256 || (v.attempt as TaskAttempt).execution_key !== op.execution_key
      || (v.attempt as TaskAttempt).predecessor_id !== op.expected_predecessor_id))) return null;
  if (expected.preview && (v.preview_sha256 !== expected.preview.preview_sha256 || v.operation_sha256 !== expected.preview.operation_sha256
    || v.actor_grant_id !== expected.preview.actor_grant_id || ((v.attempt as TaskAttempt | null)?.status ?? "queued") !== expected.preview.predicted_status
    || ((v.attempt as TaskAttempt | null)?.outcome_code ?? null) !== expected.preview.predicted_outcome_code)) return null;
  return detached(v);
}
function lifecycleEvent(v: unknown): v is LifecycleEvent {
  return keys(v, ["id", "paper_id", "work_id", "revision", "predecessor_id", "old_snapshot_sha256", "snapshot_sha256", "prior_status", "observed_status", "event_kind", "record_sha256", "created_at"])
    && taskUuid(v.id) && nullable(v.paper_id, sourceId) && nullable(v.work_id, taskUuid) && (v.paper_id === null) !== (v.work_id === null)
    && integer(v.revision, 2147483647, 1) && nullable(v.predecessor_id, taskUuid) && (v.revision === 1) === (v.predecessor_id === null)
    && nullable(v.old_snapshot_sha256, hash) && hash(v.snapshot_sha256) && nullable(v.prior_status, x => text(x, 20))
    && text(v.observed_status, 20) && choice(v.event_kind, ["baseline_observed", "lifecycle_change", "catalogue_revision"])
    && hash(v.record_sha256) && timestamp(v.created_at);
}
export function knownLifecycleHistory(v: unknown, kind: "paper" | "work", id: string): LifecycleHistory | null {
  if (!bounded(v, 256 * 1024) || !keys(v, ["source_kind", "source_id", "status", "head", "events", "next_before_revision", "direct_lifecycle_review_required", "lifecycle_review_required", "effective_lifecycle_revision", "scientific_acceptance", "ml_training_approved", "source_reinstatement"])
    || v.source_kind !== kind || v.source_id !== id || !(kind === "paper" ? sourceId(id) : taskUuid(id))
    || !nullable(v.status, x => text(x, 40)) || !nullable(v.head, lifecycleEvent) || !list(v.events, 100) || !v.events.every(lifecycleEvent)
    || !nullable(v.next_before_revision, x => integer(x, 2147483647, 1)) || !bool(v.direct_lifecycle_review_required) || !bool(v.lifecycle_review_required)
    || v.direct_lifecycle_review_required !== (v.head !== null) || !nullable(v.effective_lifecycle_revision, hash)
    || v.lifecycle_review_required !== (v.effective_lifecycle_revision !== null) || v.head !== null && v.lifecycle_review_required !== true
    || v.scientific_acceptance !== false || v.ml_training_approved !== false || v.source_reinstatement !== false) return null;
  const rows = v.events as LifecycleEvent[], head = v.head as LifecycleEvent | null;
  if ([...rows, ...(head ? [head] : [])].some(row => row[kind === "paper" ? "paper_id" : "work_id"] !== id)
    || new Set(rows.map(row => row.id)).size !== rows.length || rows.some((row, n) => !head || row.revision > head.revision
      || n > 0 && (rows[n - 1].revision !== row.revision + 1 || rows[n - 1].predecessor_id !== row.id))
    || head && rows.length > 0 && rows[0].revision === head.revision && !equal(rows[0], head)
    || v.next_before_revision !== null && (!rows.length || v.next_before_revision !== rows.at(-1)?.revision)) return null;
  return detached(v);
}
export function knownSourceImpact(v: unknown, selected: LifecycleEvent): SourceImpact | null {
  if (!bounded(v, 1048576) || !keys(v, ["version", "event", "nodes", "counts", "node_count", "timeline_candidate_material_ids", "complete_for_declared_scope", "propagation_complete", "scientific_acceptance", "ml_training_approved", "source_reinstatement", "supported_scopes", "unsupported_scopes", "next_actions", "limits", "inventory_sha256", "observation"])
    || v.version !== "source-impact/1.0.0" || !keys(v.event, ["id", "record_sha256", "source_snapshot_sha256", "revision", "source_kind", "source_id"])
    || v.event.id !== selected.id || v.event.record_sha256 !== selected.record_sha256 || v.event.source_snapshot_sha256 !== selected.snapshot_sha256
    || v.event.revision !== selected.revision || v.event.source_kind !== (selected.paper_id === null ? "work" : "paper") || v.event.source_id !== (selected.paper_id ?? selected.work_id)
    || !list(v.nodes, 2000) || v.node_count !== v.nodes.length || !object(v.counts) || !hash(v.inventory_sha256)
    || !list(v.timeline_candidate_material_ids, 2000) || !v.timeline_candidate_material_ids.every(sourceId)
    || new Set(v.timeline_candidate_material_ids).size !== v.timeline_candidate_material_ids.length
    || v.complete_for_declared_scope !== true || v.propagation_complete !== false || v.scientific_acceptance !== false || v.ml_training_approved !== false || v.source_reinstatement !== false
    || !equal(v.supported_scopes, SUPPORTED_SCOPES) || !equal(v.unsupported_scopes, UNSUPPORTED_SCOPES)
    || !keys(v.limits, ["papers", "nodes", "relations", "parent_depth", "descriptor_bytes"]) || v.limits.papers !== 1000 || v.limits.nodes !== 2000 || v.limits.relations !== 4000 || v.limits.parent_depth !== 32 || v.limits.descriptor_bytes !== 1048576
    || !keys(v.observation, ["observed_at", "transaction_isolation", "currentness", "persisted", "refresh_scheduled", "graph_binding"])
    || !timestamp(v.observation.observed_at) || !choice(v.observation.transaction_isolation, ["repeatable read", "serializable"])
    || v.observation.currentness !== "current_in_database_snapshot" || v.observation.persisted !== false || v.observation.refresh_scheduled !== false || v.observation.graph_binding !== "relationships_only_not_scientific_row_hashes"
    || !list(v.next_actions, 4) || v.next_actions.length !== 4 || !v.next_actions.every((row, n) => keys(row, ["domain", "status"]) && row.status === "not_scheduled"
      && row.domain === ["material_and_timeline_projection_review", "retrieval_context_review", "prospective_ml_membership_review", "frozen_reference_review"][n])) return null;
  const counts: Record<string, number> = {}, ids = new Set<string>(); let relationCount = 0;
  for (const node of v.nodes) {
    if (!keys(node, ["table", "row_id", "relations"]) || !choice(node.table, TABLES) || !text(node.row_id) || !list(node.relations, 4000) || !node.relations.length) return null;
    const key = node.table + ":" + node.row_id;
    if (ids.has(key)) return null; ids.add(key); counts[node.table as string] = (counts[node.table as string] ?? 0) + 1;
    const links = new Set<string>();
    for (const rel of node.relations) {
      if (!keys(rel, ["kind", "via_table", "via_id"]) || !choice(rel.kind, RELATIONS) || !choice(rel.via_table, [...TABLES, "source_lifecycle_events"]) || !text(rel.via_id)) return null;
      const link = JSON.stringify(rel); if (links.has(link)) return null; links.add(link); relationCount += 1;
    }
  }
  if (relationCount > 4000 || Object.keys(v.counts).length !== Object.keys(counts).length
    || Object.entries(counts).some(([name, count]) => v.counts && (v.counts as Obj)[name] !== count)) return null;
  return detached(v);
}
export async function taskOperationSha256(operation: TaskOperation): Promise<string> {
  const validated = knownTaskOperation(operation);
  if (!validated) throw new Error("Invalid source operation");
  const canonical = JSON.stringify(Object.fromEntries(Object.entries(validated).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)));
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical))), byte => byte.toString(16).padStart(2, "0")).join("");
}
