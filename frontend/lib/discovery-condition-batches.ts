/** Private batch traceability. Requested conditions remain researcher proposals. */
import { CONDITION_SWEEP_VERSION, estimateConditionSweep, type ConditionSweepAxes, type ConditionSweepManifest, type ConditionSweepParent, type ConditionSweepScenario, type ConditionSweepSourcePins } from "./discovery-condition-sweep";
import { designClosed, designHash, designId, designProof, knownDesignBaseline, knownDesignReceipt, knownResearchDesign, type DesignCapabilities, type DesignEligibility, type DesignReceipt, type DesignObject } from "./discovery-designs";
import { expressionCanonical, expressionSha, parseExpressionJson } from "./source-expressions";

export const CONDITION_BATCH_VERSION = "discovery-condition-batch/1.0.0";
export const CONDITION_BATCH_REQUEST_VERSION = "discovery-condition-batch-operation/1.0.0";
export const CONDITION_BATCH_MAX_BYTES = 16384;
export const CONDITION_BATCH_MAX_MANIFEST_BYTES = 4194304;
export const CONDITION_BATCH_AUTHORITY = { scientific_acceptance: false, canonical_promotions: 0, ml_training_approved: false, public_release: false, calculation_executed: false, scope: "private_owner_condition_batch" } as const;
const AUTH_KEYS = Object.keys(CONDITION_BATCH_AUTHORITY).join(" ");
const RECORD_AUTH_KEYS = "scientific_acceptance canonical_promotions ml_training_approved public_release calculation_executed";
const OPERATIONS = ["retain_batch", "propose_candidate_child"] as const;
const HOLD_REASONS = ["source_context_changed", "material_not_currently_eligible", "native_event_held", "source_lifecycle_held", "parent_revision_changed", "parent_withdrawn"];
export type ConditionBatchAuthority = typeof CONDITION_BATCH_AUTHORITY;
export type ConditionBatchCapabilities = ConditionBatchAuthority & { version: string; request_version: string; actor_user_id: string; session_version: number; curator_grant_id: string; can_write: true; operations: typeof OPERATIONS; max_page_size: 8; max_operation_bytes: 16384; max_manifest_bytes: 4194304 };
export type ConditionBatchPin = { id: string; record_sha256: string; manifest_sha256: string };
export type ConditionBatchRequest = { version: typeof CONDITION_BATCH_REQUEST_VERSION; request_key: string } & (
  { operation: "retain_batch"; payload: { parent: ConditionSweepParent; axes: ConditionSweepAxes; expected_input_sha256: string; expected_manifest_sha256: string } }
  | { operation: "propose_candidate_child"; payload: { batch: ConditionBatchPin; candidate_sha256: string } });
export type ConditionBatchChild = { design_id: string; revision_id: string; record_sha256: string };
export type ConditionBatchReceipt = ConditionBatchAuthority & { version: string; receipt_id: string; receipt_sha256: string; operation: ConditionBatchRequest["operation"]; actor_user_id: string; actor_grant_id: string; actor_session_version: number; request_key: string; request_sha256: string; preview_sha256: string; request_canonical_json: string; preview_canonical_json: string; receipt_canonical_json: string; batch_id: string; batch_record_sha256: string; input_sha256: string; manifest_sha256: string; candidate_sha256: string | null; child: DesignReceipt | null; replayed: boolean; dry_run: boolean; pending_ledger_written: boolean };
export type ConditionBatchEntry = ConditionBatchAuthority & { id: string; record_sha256: string; parent: ConditionSweepParent; source_pins: ConditionSweepSourcePins; input_sha256: string; manifest_sha256: string; scenario_total: number; eligibility: DesignEligibility; receipt: ConditionBatchReceipt };
export type ConditionBatchPage = ConditionBatchAuthority & { version: string; actor_user_id: string; session_version: number; offset: number; limit: 8; total: number; entries: ConditionBatchEntry[] };
export type ConditionBatchScenario = ConditionSweepScenario & { child: ConditionBatchChild | null };
export type ConditionBatchDetail = ConditionBatchAuthority & { version: string; actor_user_id: string; session_version: number; entry: ConditionBatchEntry; offset: number; limit: 8; scenario_total: number; scenarios: ConditionBatchScenario[] };
export type ConditionBatchRecovery = { actorId: string; requestKey: string; requestSha: string; previewSha: string; receiptSha: string; receiptId: string };
/** Only verified identities/hashes survive leaving the page. No proposal or source values. */
export type ConditionBatchSaveRecovery = ConditionBatchRecovery & { inputSha: string };
export type ConditionBatchExpected = { request: ConditionBatchRequest; manifest?: ConditionSweepManifest; batch?: ConditionBatchEntry; scenario?: ConditionSweepScenario; recovery?: ConditionBatchRecovery };
const COMMON_RECORD_KEYS = `id actor_user_id actor_grant_id actor_session_version operation request_key request_json payload request_sha256 preview_json preview_sha256 ${RECORD_AUTH_KEYS}`;
const BATCH_RECORD_KEYS = `${COMMON_RECORD_KEYS} parent source_pins input_json input_sha256 manifest_sha256 scenario_total`;
const LINK_RECORD_KEYS = `${COMMON_RECORD_KEYS} batch_id batch_record_sha256 manifest_sha256 candidate_sha256 child_revision_id child_design_id child_record_sha256`;
const RECEIPT_KEYS = `version receipt_id receipt_sha256 operation actor_user_id actor_grant_id actor_session_version request_key request_sha256 preview_sha256 request_canonical_json preview_canonical_json receipt_canonical_json batch_id batch_record_sha256 input_sha256 manifest_sha256 candidate_sha256 child replayed dry_run pending_ledger_written ${AUTH_KEYS}`;
function snapshot<T>(value: T): T | null { try { return structuredClone(value); } catch { return null; } }
function integer(value: unknown, maximum = Number.MAX_SAFE_INTEGER): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 && value <= maximum; }
function same(a: unknown, b: unknown): boolean { try { return expressionCanonical(a) === expressionCanonical(b); } catch { return false; } }
function authority(value: DesignObject) { return Object.entries(CONDITION_BATCH_AUTHORITY).every(([k, v]) => value[k] === v); }
function scoped(value: DesignObject, cap: ConditionBatchCapabilities) { return value.version === CONDITION_BATCH_VERSION && value.actor_user_id === cap.actor_user_id && value.session_version === cap.session_version && authority(value); }
function parent(value: unknown): value is ConditionSweepParent { return designClosed(value, "design_id revision_id revision record_sha256") && designId(value.design_id) && designId(value.revision_id) && integer(value.revision, 1000) && value.revision > 0 && designHash(value.record_sha256); }
function sourcePins(value: unknown): value is ConditionSweepSourcePins { return designClosed(value, "baseline context_sha256 projection_sha256 event_id state_id producer_run_id") && knownDesignBaseline(value.baseline) && value.baseline.kind !== "unanchored" && value.context_sha256 === value.baseline.expected_context_sha256 && designHash(value.projection_sha256) && ["event_id", "state_id", "producer_run_id"].every(k => value[k] === null || designId(value[k])) && (value.baseline.kind !== "retained_result" || ["event_id", "state_id", "producer_run_id"].every(k => value[k] === null)); }
function childPin(value: unknown): value is ConditionBatchChild { return designClosed(value, "design_id revision_id record_sha256") && designId(value.design_id) && designId(value.revision_id) && designHash(value.record_sha256); }
function eligible(value: unknown): value is DesignEligibility { return designClosed(value, "eligible reason_codes") && typeof value.eligible === "boolean" && Array.isArray(value.reason_codes) && value.reason_codes.length <= HOLD_REASONS.length && new Set(value.reason_codes).size === value.reason_codes.length && value.reason_codes.every(r => typeof r === "string" && HOLD_REASONS.includes(r)) && value.eligible === (value.reason_codes.length === 0); }
export function knownConditionBatchCapabilities(value: unknown, design: DesignCapabilities): ConditionBatchCapabilities | null {
  return designClosed(value, `version request_version actor_user_id session_version curator_grant_id can_write operations max_page_size max_operation_bytes max_manifest_bytes ${AUTH_KEYS}`)
    && value.version === CONDITION_BATCH_VERSION && value.request_version === CONDITION_BATCH_REQUEST_VERSION && value.actor_user_id === design.actor_user_id && designId(value.actor_user_id) && value.session_version === design.session_version && integer(value.session_version) && value.curator_grant_id === design.curator_grant_id && designId(value.curator_grant_id) && value.can_write === true
    && same(value.operations, OPERATIONS) && value.max_page_size === 8 && value.max_operation_bytes === CONDITION_BATCH_MAX_BYTES && value.max_manifest_bytes === CONDITION_BATCH_MAX_MANIFEST_BYTES && authority(value) ? snapshot(value) as unknown as ConditionBatchCapabilities : null;
}
export function knownConditionBatchRequest(value: unknown): value is ConditionBatchRequest {
  try {
    if (!designClosed(value, "version request_key operation payload") || value.version !== CONDITION_BATCH_REQUEST_VERSION || typeof value.request_key !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$/.test(value.request_key) || new TextEncoder().encode(expressionCanonical(value)).length > CONDITION_BATCH_MAX_BYTES) return false;
    const p = value.payload;
    if (value.operation === "retain_batch") return designClosed(p, "parent axes expected_input_sha256 expected_manifest_sha256") && parent(p.parent) && designHash(p.expected_input_sha256) && designHash(p.expected_manifest_sha256) && estimateConditionSweep(p.axes).unique_cartesian_count > 0;
    return value.operation === "propose_candidate_child" && designClosed(p, "batch candidate_sha256") && designClosed(p.batch, "id record_sha256 manifest_sha256") && designId(p.batch.id) && designHash(p.batch.record_sha256) && designHash(p.batch.manifest_sha256) && designHash(p.candidate_sha256);
  } catch { return false; }
}
async function inputProof(record: DesignObject) {
  const input = await designProof(record.input_json, record.input_sha256, CONDITION_BATCH_MAX_BYTES);
  if (!designClosed(input, "version parent source_pins axes") || input.version !== CONDITION_SWEEP_VERSION || !parent(input.parent) || !sourcePins(input.source_pins) || !same(input.parent, record.parent) || !same(input.source_pins, record.source_pins)) return null;
  try { return estimateConditionSweep(input.axes).unique_cartesian_count === record.scenario_total ? input : null; } catch { return null; }
}
export function knownConditionBatchSaveRecovery(value: unknown): value is ConditionBatchSaveRecovery {
  return designClosed(value, "actorId requestKey requestSha previewSha receiptSha receiptId inputSha") && designId(value.actorId) && designId(value.receiptId) && typeof value.requestKey === "string" && /^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$/.test(value.requestKey) && ["requestSha", "previewSha", "receiptSha", "inputSha"].every(k => designHash(value[k]));
}
export async function knownConditionBatchReceipt(value: unknown, cap: ConditionBatchCapabilities, design: DesignCapabilities, expected?: ConditionBatchExpected, stage: "preview" | "commit" | "outcome" | "history" = "history"): Promise<ConditionBatchReceipt | null> {
  return verifiedReceipt(value, cap, design, expected, stage);
}
/** GET-only recovery of an already-verified preview's exact immutable seal. */
export async function knownConditionBatchOutcome(value: unknown, cap: ConditionBatchCapabilities, design: DesignCapabilities, recovery: ConditionBatchSaveRecovery): Promise<ConditionBatchReceipt | null> {
  const pins = snapshot(recovery);
  return knownConditionBatchSaveRecovery(pins) ? verifiedReceipt(value, cap, design, undefined, "outcome", pins) : null;
}
async function verifiedReceipt(value: unknown, cap: ConditionBatchCapabilities, design: DesignCapabilities, expected: ConditionBatchExpected | undefined, stage: "preview" | "commit" | "outcome" | "history", sealedRecovery?: ConditionBatchSaveRecovery): Promise<ConditionBatchReceipt | null> {
  value = snapshot(value); cap = snapshot(cap)!; design = snapshot(design)!; expected = expected ? snapshot(expected) ?? undefined : undefined;
  if (!designClosed(value, RECEIPT_KEYS) || value.version !== CONDITION_BATCH_VERSION || !authority(value) || value.actor_user_id !== cap.actor_user_id || !designId(value.receipt_id) || !designId(value.batch_id) || !designId(value.actor_grant_id) || !integer(value.actor_session_version) || !designHash(value.batch_record_sha256) || !designHash(value.input_sha256) || !designHash(value.manifest_sha256) || typeof value.replayed !== "boolean" || typeof value.dry_run !== "boolean" || value.pending_ledger_written !== !value.dry_run) return null;
  if (sealedRecovery && (stage !== "outcome" || sealedRecovery.actorId !== value.actor_user_id || sealedRecovery.requestKey !== value.request_key || sealedRecovery.requestSha !== value.request_sha256 || sealedRecovery.previewSha !== value.preview_sha256 || sealedRecovery.receiptSha !== value.receipt_sha256 || sealedRecovery.receiptId !== value.receipt_id || sealedRecovery.inputSha !== value.input_sha256)) return null;
  const record = await designProof(value.receipt_canonical_json, value.receipt_sha256, 196608), request = await designProof(value.request_canonical_json, value.request_sha256, CONDITION_BATCH_MAX_BYTES), preview = await designProof(value.preview_canonical_json, value.preview_sha256, 4096);
  if (!knownConditionBatchRequest(request) || !designClosed(record, request.operation === "retain_batch" ? BATCH_RECORD_KEYS : LINK_RECORD_KEYS) || !preview || value.operation !== request.operation || value.request_key !== request.request_key || record.id !== value.receipt_id || record.request_json !== value.request_canonical_json || record.preview_json !== value.preview_canonical_json || !same(record.payload, request.payload)
      || !["actor_user_id", "actor_grant_id", "actor_session_version", "operation", "request_key", "request_sha256", "preview_sha256"].every(k => record[k] === value[k]) || !RECORD_AUTH_KEYS.split(" ").every(k => record[k] === CONDITION_BATCH_AUTHORITY[k as keyof ConditionBatchAuthority])) return null;
  const actor = { actor_user_id: value.actor_user_id, actor_grant_id: value.actor_grant_id, actor_session_version: value.actor_session_version };
  const common = { version: CONDITION_BATCH_VERSION, actor, request_sha256: value.request_sha256, receipt_id: value.receipt_id, batch_id: value.batch_id };
  if (request.operation === "retain_batch") {
    const input = await inputProof(record);
    if (!input || value.receipt_id !== value.batch_id || value.receipt_sha256 !== value.batch_record_sha256 || !parent(record.parent) || !sourcePins(record.source_pins) || !integer(record.scenario_total, 64) || record.scenario_total === 0 || value.child !== null || value.candidate_sha256 !== null
        || value.input_sha256 !== record.input_sha256 || value.manifest_sha256 !== record.manifest_sha256 || !same(request.payload.parent, record.parent) || !same(request.payload.axes, input.axes) || request.payload.expected_input_sha256 !== record.input_sha256 || request.payload.expected_manifest_sha256 !== record.manifest_sha256
        || !same(preview, { ...common, parent: record.parent, input_sha256: record.input_sha256, manifest_sha256: record.manifest_sha256, scenario_total: record.scenario_total })) return null;
    if (expected?.manifest && (!same(expected.manifest.parent, record.parent) || !same(expected.manifest.source_pins, record.source_pins) || expected.manifest.input_canonical_json !== record.input_json || expected.manifest.input_sha256 !== record.input_sha256 || expected.manifest.manifest_sha256 !== record.manifest_sha256 || !same(expected.manifest.actor, { actor_user_id: value.actor_user_id, session_version: value.actor_session_version, curator_grant_id: value.actor_grant_id }))) return null;
    if (expected?.manifest && !await knownConditionBatchManifest(expressionCanonical(expected.manifest), { ...CONDITION_BATCH_AUTHORITY, id: value.batch_id as string, record_sha256: value.batch_record_sha256 as string, parent: record.parent, source_pins: record.source_pins, input_sha256: record.input_sha256 as string, manifest_sha256: record.manifest_sha256 as string, scenario_total: record.scenario_total as number, eligibility: { eligible: true, reason_codes: [] }, receipt: value as unknown as ConditionBatchReceipt })) return null;
  } else {
    const batch = expected?.batch, scenario = expected?.scenario;
    if (!designHash(value.candidate_sha256) || value.candidate_sha256 !== request.payload.candidate_sha256 || !same(request.payload.batch, { id: value.batch_id, record_sha256: value.batch_record_sha256, manifest_sha256: value.manifest_sha256 })
        || !["batch_id", "batch_record_sha256", "manifest_sha256", "candidate_sha256"].every(k => record[k] === value[k]) || !designId(record.child_design_id) || !designId(record.child_revision_id) || !designHash(record.child_record_sha256)) return null;
    if (!sealedRecovery) {
      if (!batch || !scenario || batch.id !== value.batch_id || batch.record_sha256 !== value.batch_record_sha256 || batch.manifest_sha256 !== value.manifest_sha256 || batch.input_sha256 !== value.input_sha256 || scenario.candidate_sha256 !== value.candidate_sha256) return null;
      const verifiedBatch = await knownEntry(batch, cap, design), manifest = verifiedBatch && expected?.manifest ? await knownConditionBatchManifest(expressionCanonical(expected.manifest), verifiedBatch) : null;
      if (!manifest || !same({ candidate_id: scenario.candidate_id, candidate_sha256: scenario.candidate_sha256, conditions: scenario.conditions, proposal: scenario.proposal }, manifest.scenarios.find(s => s.candidate_sha256 === value.candidate_sha256))) return null;
    }
    const child = await knownDesignReceipt(value.child, design, undefined, value.dry_run ? "preview" : "history");
    const body = child ? await designProof(child.receipt_canonical_json, child.receipt_sha256, 196608) : null;
    const pin = { design_id: record.child_design_id, revision_id: record.child_revision_id, record_sha256: record.child_record_sha256 };
    if (!child || !body || child.operation !== "propose" || child.revision !== 1 || child.design_id !== pin.design_id || child.receipt_id !== pin.revision_id || child.receipt_sha256 !== pin.record_sha256 || child.dry_run !== value.dry_run || child.pending_ledger_written !== value.pending_ledger_written || child.actor_user_id !== value.actor_user_id || child.actor_grant_id !== value.actor_grant_id || child.actor_session_version !== value.actor_session_version
        || !sealedRecovery && (!same(body.design, scenario!.proposal) || !same(body.baseline, batch!.source_pins.baseline) || !same(body.parent, { design_id: batch!.parent.design_id, revision_id: batch!.parent.revision_id, record_sha256: batch!.parent.record_sha256 }) || body.context_sha256 !== batch!.source_pins.context_sha256 || body.projection_sha256 !== batch!.source_pins.projection_sha256)
        || !same(preview, { ...common, batch_record_sha256: value.batch_record_sha256, manifest_sha256: value.manifest_sha256, candidate_sha256: value.candidate_sha256, child: pin })) return null;
  }
  if (expected && (!same(expected.request, request) || expected.recovery && (expected.recovery.actorId !== value.actor_user_id || expected.recovery.requestKey !== value.request_key || expected.recovery.requestSha !== value.request_sha256 || stage !== "preview" && (expected.recovery.previewSha !== value.preview_sha256 || expected.recovery.receiptSha !== value.receipt_sha256 || expected.recovery.receiptId !== value.receipt_id)))) return null;
  if (stage === "preview" ? value.replayed ? value.dry_run : !value.dry_run || value.actor_grant_id !== cap.curator_grant_id || value.actor_session_version !== cap.session_version
    : value.dry_run || stage === "outcome" && !value.replayed || stage === "commit" && !value.replayed && (value.actor_grant_id !== cap.curator_grant_id || value.actor_session_version !== cap.session_version)) return null;
  return value as unknown as ConditionBatchReceipt;
}
async function knownEntry(value: unknown, cap: ConditionBatchCapabilities, design: DesignCapabilities): Promise<ConditionBatchEntry | null> {
  if (!designClosed(value, `id record_sha256 parent source_pins input_sha256 manifest_sha256 scenario_total eligibility receipt ${AUTH_KEYS}`) || !authority(value) || !parent(value.parent) || !sourcePins(value.source_pins) || !eligible(value.eligibility) || !integer(value.scenario_total, 64) || value.scenario_total === 0) return null;
  const receipt = await knownConditionBatchReceipt(value.receipt, cap, design), body = receipt ? await designProof(receipt.receipt_canonical_json, receipt.receipt_sha256, 196608) : null;
  return receipt?.operation === "retain_batch" && body && value.id === receipt.batch_id && value.record_sha256 === receipt.batch_record_sha256 && ["parent", "source_pins", "input_sha256", "manifest_sha256", "scenario_total"].every(k => same(value[k], body[k])) ? value as unknown as ConditionBatchEntry : null;
}
export async function knownConditionBatchPage(value: unknown, cap: ConditionBatchCapabilities, design: DesignCapabilities, offset: number): Promise<ConditionBatchPage | null> {
  value = snapshot(value); cap = snapshot(cap)!; design = snapshot(design)!;
  if (!integer(offset, 1000) || !designClosed(value, `version actor_user_id session_version offset limit total entries ${AUTH_KEYS}`) || !scoped(value, cap) || value.offset !== offset || value.limit !== 8 || !integer(value.total) || !Array.isArray(value.entries) || value.entries.length !== Math.min(8, Math.max(0, value.total - offset))) return null;
  const entries = await Promise.all(value.entries.map(e => knownEntry(e, cap, design)));
  return entries.every(e => e !== null) && new Set(entries.map(e => e!.id)).size === entries.length ? { ...value, entries } as unknown as ConditionBatchPage : null;
}
// Mirrors the local sweep's exact decimal identity; Number is admission only.
function decimalIdentity(raw: string): string {
  const p = /^(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/.exec(raw)!;
  const f = p[2] ?? p[3] ?? "", digits = `${p[1] ?? ""}${f}`.replace(/^0+/, ""), c = digits.replace(/0+$/, "");
  return digits ? `${c}e${BigInt(p[4] ?? "0") - BigInt(f.length) + BigInt(digits.length - c.length)}` : "0e0";
}
function conditions(axes: ConditionSweepAxes) {
  estimateConditionSweep(axes);
  const p = new Map<string, ConditionSweepAxes["pressures"][number]>(), t = new Map<string, string | null>();
  for (const value of axes.pressures) { const key = value.kind === "specified" ? `specified:${decimalIdentity(value.raw_gpa!)}` : value.kind; if (!p.has(key)) p.set(key, value); }
  for (const value of axes.temperatures_k) { const key = value === null ? "unknown" : `specified:${decimalIdentity(value)}`; if (!t.has(key)) t.set(key, value); }
  const sorted = <T,>(map: Map<string, T>) => [...map.entries()].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0);
  return sorted(p).flatMap(([pressure_identity, pressure]) => sorted(t).map(([temperature_identity, temperature_k]) => ({ pressure_identity, temperature_identity, conditions: { pressure, temperature_k } })));
}
async function scenarioValid(value: unknown, input: DesignObject, position: number, manifest?: ConditionSweepManifest) {
  if (!designClosed(value, "candidate_id candidate_sha256 conditions proposal child") || !knownResearchDesign(value.proposal) || !same(value.proposal.target_conditions, value.conditions) || !(value.child === null || childPin(value.child))) return false;
  const option = conditions(input.axes as ConditionSweepAxes)[position];
  if (!option || !same(value.conditions, option.conditions)) return false;
  const sha = await expressionSha(expressionCanonical({ version: "discovery-condition-sweep-candidate/1.0.0", parent_record_sha256: (input.parent as ConditionSweepParent).record_sha256, pressure_identity: option.pressure_identity, temperature_identity: option.temperature_identity }));
  return value.candidate_sha256 === sha && value.candidate_id === `condition-scenario:${sha}` && (!manifest || same({ candidate_id: value.candidate_id, candidate_sha256: value.candidate_sha256, conditions: value.conditions, proposal: value.proposal }, manifest.scenarios[position]));
}
export async function knownConditionBatchDetail(value: unknown, cap: ConditionBatchCapabilities, design: DesignCapabilities, batchId: string, offset: number, manifest?: ConditionSweepManifest): Promise<ConditionBatchDetail | null> {
  value = snapshot(value); cap = snapshot(cap)!; design = snapshot(design)!; manifest = manifest ? snapshot(manifest) ?? undefined : undefined;
  if (!designId(batchId) || !integer(offset, 63) || !designClosed(value, `version actor_user_id session_version entry offset limit scenario_total scenarios ${AUTH_KEYS}`) || !scoped(value, cap) || value.offset !== offset || value.limit !== 8 || !Array.isArray(value.scenarios)) return null;
  const entry = await knownEntry(value.entry, cap, design);
  if (!entry || entry.id !== batchId || value.scenario_total !== entry.scenario_total || value.scenarios.length !== Math.min(8, Math.max(0, entry.scenario_total - offset)) || manifest && (manifest.manifest_sha256 !== entry.manifest_sha256 || manifest.input_sha256 !== entry.input_sha256)) return null;
  const record = await designProof(entry.receipt.receipt_canonical_json, entry.record_sha256, 196608), input = record ? await inputProof(record) : null;
  if (!input || !(await Promise.all(value.scenarios.map((s, i) => scenarioValid(s, input, offset + i, manifest)))).every(Boolean) || new Set(value.scenarios.map(s => (s as ConditionBatchScenario).child?.revision_id).filter(Boolean)).size !== value.scenarios.filter(s => (s as ConditionBatchScenario).child !== null).length) return null;
  return { ...value, entry } as unknown as ConditionBatchDetail;
}
export async function knownConditionBatchManifest(text: unknown, entry: ConditionBatchEntry): Promise<ConditionSweepManifest | null> {
  entry = snapshot(entry)!;
  try {
    if (typeof text !== "string" || new TextEncoder().encode(text).length > CONDITION_BATCH_MAX_MANIFEST_BYTES + 128) return null;
    const value = parseExpressionJson(text);
    if (!designClosed(value, "version scope actor parent source_pins input_canonical_json input_sha256 estimate scenarios budget_totals scientific_acceptance canonical_promotions ml_training_approved public_release calculation_executed database_changed batch_saved atomic_sites_generated manifest_sha256") || expressionCanonical(value) !== text || value.version !== CONDITION_SWEEP_VERSION || value.scope !== "local_private_condition_sweep" || !same(value.parent, entry.parent) || !same(value.source_pins, entry.source_pins) || value.input_sha256 !== entry.input_sha256 || value.manifest_sha256 !== entry.manifest_sha256 || !same(value.actor, { actor_user_id: entry.receipt.actor_user_id, session_version: entry.receipt.actor_session_version, curator_grant_id: entry.receipt.actor_grant_id }) || !RECORD_AUTH_KEYS.split(" ").every(k => value[k] === CONDITION_BATCH_AUTHORITY[k as keyof ConditionBatchAuthority]) || !["database_changed", "batch_saved", "atomic_sites_generated"].every(k => value[k] === false) || !Array.isArray(value.scenarios) || value.scenarios.length !== entry.scenario_total) return null;
    const { manifest_sha256, ...body } = value;
    if (new TextEncoder().encode(expressionCanonical(body)).length > CONDITION_BATCH_MAX_MANIFEST_BYTES || await expressionSha(expressionCanonical(body)) !== manifest_sha256) return null;
    const record = await designProof(entry.receipt.receipt_canonical_json, entry.record_sha256, 196608), input = record ? await inputProof(record) : null;
    if (!designClosed(record, BATCH_RECORD_KEYS) || record.id !== entry.id || entry.receipt.receipt_id !== entry.id || entry.receipt.receipt_sha256 !== entry.record_sha256 || !["parent", "source_pins", "input_sha256", "manifest_sha256", "scenario_total"].every(k => same(record[k], entry[k as keyof ConditionBatchEntry])) || !["actor_user_id", "actor_grant_id", "actor_session_version"].every(k => record[k] === entry.receipt[k as keyof ConditionBatchReceipt]) || !RECORD_AUTH_KEYS.split(" ").every(k => record[k] === CONDITION_BATCH_AUTHORITY[k as keyof ConditionBatchAuthority]) || !input || record.input_json !== value.input_canonical_json || !same(value.parent, input.parent) || !same(value.source_pins, input.source_pins) || !same(value.estimate, estimateConditionSweep(input.axes))) return null;
    if (!(await Promise.all(value.scenarios.map((s, i) => scenarioValid({ ...(s as DesignObject), child: null }, input, i)))).every(Boolean) || value.scenarios.some(s => !designClosed(s, "candidate_id candidate_sha256 conditions proposal"))) return null;
    const first = (value.scenarios[0] as ConditionSweepScenario).proposal;
    if (value.scenarios.some(s => !same({ ...(s as ConditionSweepScenario).proposal, target_conditions: first.target_conditions }, first)) || !same(value.budget_totals, first.next_action.budget.map(b => ({ resource: b.resource, unit: b.unit, status: b.status === "unknown" ? "unknown" : "not_aggregated", total: null })))) return null;
    return value as unknown as ConditionSweepManifest;
  } catch { return null; }
}
