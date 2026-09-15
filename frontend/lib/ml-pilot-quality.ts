/** A bound presentation of verified canary accounting, not a second validator. */
import { parsePrivateDiscoveryJSON } from "./discovery-scientific";
import { boundedPilotOperation, pilotBytesHash, pilotHash, PILOT_FILE_LIMIT } from "./ml-pilot-participation";
import { CANARY_LIMIT, type EvidenceSnapshot } from "./ml-pilot-evidence";
import type { ReviewBasis } from "./ml-pilot-reviews";

export const PILOT_FIELDS = ["source_revision", "source_locator", "raw_context", "work_identity", "sample_state", "structure_identity", "tc_value", "tc_criterion", "pressure", "origin", "method"] as const;
export const PILOT_AVAILABILITY = ["reported", "not_reported", "not_accessible", "not_extracted", "ambiguous", "conflicted", "not_applicable"] as const;
export const PILOT_GROUPS = ["family", "source_class", "stratum_id"] as const;
export const PILOT_OUTCOMES = ["recovered", "inaccessible", "irrecoverable", "no_relevant_result", "unresolved"] as const;
const DECISIONS = ["accepted", "pending", "rejected"] as const;
const ERRORS = ["source", "normalization", "state_association", "extraction"] as const;
const COMPARISONS = ["agreement", "disagreement", "resolved", "unresolved", "not_compared"] as const;
type Field = typeof PILOT_FIELDS[number];
type Obj = Record<string, unknown>;
export type PilotTiming = { recordedMinutes: number | null; recordedRecords: number; totalRecords: number };
export type PilotQualityField = { field: Field; candidateRecovered: number; availability: Record<typeof PILOT_AVAILABILITY[number], number>;
  effort: PilotTiming; action: "keep" | "narrow" | "defer"; reason: string };
export type PilotQualityGroup = { label: string; selected: number; effort: PilotTiming; outcomes: Record<typeof PILOT_OUTCOMES[number], number>; recovered: Record<Field, number> };
export type PilotQualityReport = { canarySha256: string; conclusionSha256: string; snapshotStartedAt: string;
  selected: number; reviewRecords: number; atomicResults: number; associations: number; requiredSecondary: number;
  identities: Record<"work_id" | "sample_id" | "state_id" | "structure_id", number>;
  outcomes: Record<typeof PILOT_OUTCOMES[number], number>; decisions: Record<typeof DECISIONS[number], number>;
  errors: Record<typeof ERRORS[number], number>; comparisons: Record<typeof COMPARISONS[number], number>;
  effort: PilotTiming; fields: PilotQualityField[]; groups: Record<typeof PILOT_GROUPS[number], PilotQualityGroup[]>;
  recommendation: "go" | "narrow" | "stop"; rationale: string; limitations: string[] };

function requireValue(v: unknown): asserts v { if (!v) throw new Error("The bound private field report could not be verified."); }
function object(v: unknown, keys?: readonly string[]): Obj {
  requireValue(v !== null && typeof v === "object" && !Array.isArray(v));
  requireValue(!keys || Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k)));
  return v as Obj;
}
function count(v: unknown, maximum = 6000) { requireValue(typeof v === "number" && Number.isSafeInteger(v) && v >= 0 && v <= maximum); return v; }
function text(v: unknown, maximum = 2000) { requireValue(typeof v === "string" && !!v.trim() && Array.from(v).length <= maximum); return v; }
function counter<const K extends string>(v: unknown, keys: readonly K[], maximum: number): Record<K, number> {
  const row = object(v); requireValue(Object.keys(row).every(k => keys.includes(k as K)));
  return Object.fromEntries(keys.map(k => [k, Object.hasOwn(row, k) ? count(row[k], maximum) : 0])) as Record<K, number>;
}
const sum = (v: Record<string, number>) => Object.values(v).reduce((a, b) => a + b, 0);
function timing(minutes: unknown, recorded: unknown, total: number): PilotTiming {
  const n = count(recorded, total);
  requireValue(typeof minutes === "number" && Number.isFinite(minutes) && minutes >= 0 && (n > 0 || minutes === 0));
  return { recordedMinutes: n === 0 ? null : minutes, recordedRecords: n, totalRecords: total };
}

function project(bundle: Obj, conclusion: Obj, basis: ReviewBasis, proof: EvidenceSnapshot): PilotQualityReport {
  requireValue(bundle.version === "ml08-canary/1.2.0" && bundle.scope === "private_replayable_human_asserted_pilot_not_scientific_acceptance"
    && bundle.selection_sha256 === basis.selection_sha256 && bundle.review_log_sha256 === basis.review_log_sha256
    && bundle.context_bytes_embedded === false && bundle.training_execution === "disabled"
    && Array.isArray(bundle.reviews_including_superseded) && bundle.reviews_including_superseded.length === basis.review_record_count);
  const authority = object(bundle.authority, ["scientific_acceptance", "scientific_pilot_accepted", "human_identity_authenticated", "reviewer_independence_authenticated",
    "actual_event_existence_verified", "source_permissions_verified", "source_content_scientifically_verified", "public_release", "ml_training_approved", "run_authorization_granted"]);
  requireValue(Object.values(authority).every(v => v === false));
  const input = object(bundle.input_pins, ["selection_file_sha256", "reviews_file_sha256", "protocol_file_sha256"]);
  requireValue(Object.keys(input).every(k => input[k] === basis.input_pins[k as keyof ReviewBasis["input_pins"]]));
  const a = object(bundle.accounting);
  requireValue(a.schema_version === "ml08-accounting/1.0.0" && a.status === "review_in_progress" && a.scientific_acceptance === false && a.ready_for_review === true
    && a.ready_for_final_human_signoff === false && Array.isArray(a.errors) && a.errors.length === 0
    && Array.isArray(a.final_gaps) && a.final_gaps.length === 1 && a.final_gaps[0] === "conclusion_not_submitted"
    && a.selection_sha256 === basis.selection_sha256 && a.review_log_sha256 === basis.review_log_sha256);
  const c = object(a.counts, ["target_candidates", "selected_candidates", "primary_reviewed_candidates", "unreviewed_candidates", "review_records_including_superseded",
    "required_secondary_candidates", "event_result_associations", "atomic_results_in_effective_reviews", "independent_work_count", "independent_replication_count"]);
  requireValue(c.target_candidates === 60 && c.selected_candidates === 60 && c.primary_reviewed_candidates === 60 && c.unreviewed_candidates === 0
    && c.review_records_including_superseded === basis.review_record_count && c.independent_work_count === null && c.independent_replication_count === null);
  const reviewRecords = count(c.review_records_including_superseded, 2000), selected = 60, atomicResults = count(c.atomic_results_in_effective_reviews), associations = count(c.event_result_associations);
  const requiredSecondary = count(c.required_secondary_candidates, selected);
  requireValue(reviewRecords >= 61 && requiredSecondary > 0 && atomicResults <= associations && (atomicResults !== 0 || associations === 0));
  const outcomes = counter(a.event_outcomes, PILOT_OUTCOMES, selected), decisions = counter(a.atomic_result_decisions, DECISIONS, atomicResults);
  requireValue(sum(outcomes) === selected && sum(decisions) === atomicResults);
  object(a.reported_identity_counts, ["work_id", "sample_id", "state_id", "structure_id"]);
  const identities = counter(a.reported_identity_counts, ["work_id", "sample_id", "state_id", "structure_id"], atomicResults);
  const errors = counter(a.error_counts_separate_from_missingness, ERRORS, atomicResults * 50), comparisons = counter(a.agreement_counts, COMPARISONS, selected * 2);
  requireValue(sum(errors) <= atomicResults * 50 && sum(comparisons) <= selected * 2);
  const totalTime = object(a.curation_time, ["recorded_active_minutes_all_revisions", "records_with_timing", "review_record_denominator", "missing_time_is_not_zero"]);
  requireValue(totalTime.review_record_denominator === reviewRecords && totalTime.missing_time_is_not_zero === true);
  const effort = timing(totalTime.recorded_active_minutes_all_revisions, totalTime.records_with_timing, reviewRecords);
  requireValue(conclusion.schema_version === "ml08-conclusion/1.0.0" && conclusion.status === "submitted_for_signoff"
    && conclusion.selection_sha256 === basis.selection_sha256 && conclusion.review_log_sha256 === basis.review_log_sha256
    && conclusion.canary_bundle_sha256 === basis.declared_canary_sha256 && conclusion.recommendation === basis.recorded_recommendation
    && ["go", "narrow", "stop"].includes(conclusion.recommendation as string)
    && Array.isArray(conclusion.field_actions) && conclusion.field_actions.length === PILOT_FIELDS.length);
  const actions = new Map<Field, { action: PilotQualityField["action"]; reason: string }>();
  for (const value of conclusion.field_actions) {
    const action = object(value, ["field", "action", "reason"]);
    requireValue(PILOT_FIELDS.includes(action.field as Field) && !actions.has(action.field as Field) && ["keep", "narrow", "defer"].includes(action.action as string));
    actions.set(action.field as Field, { action: action.action as PilotQualityField["action"], reason: text(action.reason) });
  }
  const missingness = object(a.atomic_field_missingness, ["denominator", "counts"]);
  requireValue(missingness.denominator === atomicResults);
  const missingCounts = object(missingness.counts, PILOT_FIELDS), recovery = object(a.candidate_field_recovery, PILOT_FIELDS), fieldTime = object(a.curation_time_by_field, PILOT_FIELDS);
  const fields = PILOT_FIELDS.map(field => {
    const recovered = object(recovery[field], ["candidates_with_any_reported_result", "selected_candidate_denominator"]);
    requireValue(recovered.selected_candidate_denominator === selected);
    const candidateRecovered = count(recovered.candidates_with_any_reported_result, selected), availability = counter(missingCounts[field], PILOT_AVAILABILITY, atomicResults);
    requireValue(sum(availability) === atomicResults && (atomicResults > 0 || candidateRecovered === 0));
    const t = object(fieldTime[field], ["recorded_minutes", "records_with_timing", "review_record_denominator"]);
    requireValue(t.review_record_denominator === reviewRecords);
    return { field, candidateRecovered, availability, effort: timing(t.recorded_minutes, t.records_with_timing, reviewRecords), ...actions.get(field)! };
  });
  const groupings = object(a.time_and_denominators_by_group, PILOT_GROUPS);
  const groups = Object.fromEntries(PILOT_GROUPS.map(dimension => {
    const raw = object(groupings[dimension]); requireValue(Object.keys(raw).length > 0 && Object.keys(raw).length <= selected);
    const entries = Object.entries(raw).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([label, value]) => {
      const g = object(value, ["selected_candidates", "primary_reviewed_candidates", "recorded_active_minutes_all_revisions", "review_records", "records_with_timing", "event_outcomes", "candidates_with_any_reported_field"]);
      const n = count(g.selected_candidates, selected), r = count(g.review_records, reviewRecords);
      requireValue(n > 0 && g.primary_reviewed_candidates === n && r >= n);
      const outcomes = counter(g.event_outcomes, PILOT_OUTCOMES, n);
      requireValue(sum(outcomes) === n);
      object(g.candidates_with_any_reported_field, PILOT_FIELDS);
      return { label: text(label, 200), selected: n, effort: timing(g.recorded_active_minutes_all_revisions, g.records_with_timing, r), outcomes,
        recovered: counter(g.candidates_with_any_reported_field, PILOT_FIELDS, n) };
    });
    requireValue(entries.reduce((s, g) => s + g.selected, 0) === selected && entries.reduce((s, g) => s + g.effort.totalRecords, 0) === reviewRecords
      && entries.reduce((s, g) => s + g.effort.recordedRecords, 0) === effort.recordedRecords
      && fields.every(f => entries.reduce((s, g) => s + g.recovered[f.field], 0) === f.candidateRecovered));
    return [dimension, entries];
  })) as PilotQualityReport["groups"];
  requireValue(Array.isArray(conclusion.limitations) && conclusion.limitations.length <= 50);
  return { canarySha256: proof.canarySha256, conclusionSha256: basis.input_pins.conclusion_file_sha256, snapshotStartedAt: proof.account.snapshot_started_at,
    selected, reviewRecords, atomicResults, associations, requiredSecondary, identities, outcomes, decisions, errors, comparisons, effort, fields, groups,
    recommendation: conclusion.recommendation as PilotQualityReport["recommendation"], rationale: text(conclusion.rationale), limitations: conclusion.limitations.map(v => text(v)) };
}

/** Reads only the already supplied local copies, after the UI's byte proof.
 * Raw hashes bind the copy; server replay, not this view, verifies the ledger. */
export async function preparePilotQualityReport(canary: File, conclusion: File, basis: ReviewBasis, proof: EvidenceSnapshot, signal?: AbortSignal): Promise<PilotQualityReport> {
  requireValue(proof.canarySha256 === basis.declared_canary_sha256 && pilotHash(proof.canarySha256) && pilotHash(basis.input_pins.conclusion_file_sha256)
    && canary?.size > 0 && canary.size <= CANARY_LIMIT && conclusion?.size > 0 && conclusion.size <= PILOT_FILE_LIMIT);
  return boundedPilotOperation(async (active, interrupted) => {
    const read = async (file: File, pin: string, limit: number) => {
      const bytes = new Uint8Array(await Promise.race([file.arrayBuffer(), interrupted]));
      requireValue(!active.aborted && bytes.length === file.size && bytes.length <= limit && await pilotBytesHash(bytes) === pin);
      return object(parsePrivateDiscoveryJSON(new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes), limit).value);
    };
    const bundle = await read(canary, basis.declared_canary_sha256, CANARY_LIMIT);
    const final = await read(conclusion, basis.input_pins.conclusion_file_sha256, PILOT_FILE_LIMIT);
    requireValue(!active.aborted);
    return project(bundle, final, basis, proof);
  }, signal, 30000);
}
