/** Closed adjudication wire admission. Server checks remain authoritative. */
import { knownReviewDossier, knownReviewImpact, type ReviewDossier, type ReviewQueueItem } from "./scientific-review";

export type ReviewScope = "extraction_fidelity" | "scientific_result";
export type ReviewDecision = "accept" | "reject" | "request_clarification";
export type CheckValue = "satisfied" | "not_applicable" | "unresolved";
export const REVIEW_PROFILES = {
  "native-sampled-frequency-extraction/1.0.0": { scope: "extraction_fidelity", proposition: "retained_native_sampled_frequency_minimum" },
  "recorded-sampled-frequency-fidelity/1.0.0": { scope: "extraction_fidelity", proposition: "recorded_sampled_frequency_minimum" },
  "sampled-phonon-minimum-review/1.0.0": { scope: "scientific_result", proposition: "sampled_frequency_minimum_only" },
} as const;
export type ReviewProfile = keyof typeof REVIEW_PROFILES;
export const REVIEW_LIMITATIONS = [
  "conditions_remain_as_reported", "no_automatic_ml_or_publication_authority",
  "not_a_full_zone_stability_assessment", "review_does_not_establish_upstream_execution",
  "scope_is_sampled_q_points_only",
] as const;
export const REVIEW_CHECKS = ["source_match", "quantity_and_units", "state_association", "method_and_scope"] as const;
export const REVIEW_REASONS: Record<ReviewDecision, string[]> = {
  accept: ["evidence_and_scope_match"],
  reject: ["source_mismatch", "quantity_or_unit_mismatch", "state_association_mismatch", "method_or_scope_mismatch", "scientific_concern"],
  request_clarification: ["insufficient_evidence", "unresolved_state", "unresolved_method", "conflicting_evidence"],
};
export type EvidenceRef = { artifact_id: string; bytes_sha256: string };
export interface ScopeStatus {
  scope: ReviewScope; profile_version: ReviewProfile | null; decision_id: string | null; decision_sha256: string | null;
  decision: ReviewDecision | null; effective_status: "unreviewed" | "accepted" | "rejected" | "clarification_required" | "stale" | "source_held" | "reviewer_unavailable" | "dependency_review_held";
  reason_codes: string[]; scientific_scope_accepted: boolean;
}
export interface AdjudicationTarget {
  property_id: string; subject_id: string; subject_sha256: string; event_id: string; event_revision: number;
  impact_sha256: string; available_profiles: ReviewProfile[]; required_artifacts: EvidenceRef[];
  heads: { scope: ReviewScope; decision_id: string | null }[];
  status: { version: "scientific-result-review-status/1.0.0"; property_id: string; subject_sha256: string;
    scopes: ScopeStatus[]; revision_sha256: string; ml_training_approved: false; public_release_authorized: false };
  impact: ReviewDossier["impact"]; dossier: ReviewDossier; reason_codes: string[];
}
export interface AdjudicationContext {
  version: "scientific-adjudication-context/1.0.0"; actor_user_id: string; actor_grant_id: string | null;
  can_review: boolean; max_items: 20; targets: AdjudicationTarget[];
}
export interface AdjudicationItem {
  decision_id: string; subject_id: string; property_id: string; scope: ReviewScope; profile_version: ReviewProfile;
  expected_subject_sha256: string; expected_previous_decision_id: string | null; expected_impact_sha256: string;
  decision: ReviewDecision; reason_code: string; rationale: string; proposition: string; limitations: string[];
  checks: Record<typeof REVIEW_CHECKS[number], CheckValue>; evidence_refs: EvidenceRef[];
  source_inspection_attested: boolean; resolves_decision_id: string | null; extraction_decision_id: string | null;
}
export interface AdjudicationRequest {
  version: "scientific-result-adjudication/1.0.0"; request_key: string; items: AdjudicationItem[];
}
interface PreviewItem {
  decision_id: string; subject_id: string; property_id: string; scope: ReviewScope; profile_version: ReviewProfile;
  decision: ReviewDecision; subject_sha256: string; expected_previous_decision_id: string | null; impact_sha256: string;
}
export interface AdjudicationPreview {
  version: "scientific-adjudication-preview/1.0.0"; actor_user_id: string; actor_grant_id: string;
  request_key: string; request_sha256: string; preview_sha256: string; can_commit: true; items: PreviewItem[];
  database_mutated: false; ml_training_approved: false; public_release_authorized: false;
}
export interface AdjudicationReceipt {
  version: "scientific-adjudication-receipt/1.0.0"; request_id: string; request_key: string; request_sha256: string;
  preview_sha256: string; committed: true; replayed: boolean;
  items: { decision_id: string; subject_id: string; property_id: string; scope: ReviewScope;
    profile_version: ReviewProfile; decision: ReviewDecision; decision_sha256: string }[];
  ml_training_approved: false; public_release_authorized: false;
}
type Row = Record<string, unknown>;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const HASH = /^[0-9a-f]{64}$/;
const object = (v: unknown): v is Row => v !== null && typeof v === "object" && !Array.isArray(v);
const keys = (v: unknown, fields: string[]): v is Row => object(v) && Object.keys(v).length === fields.length && fields.every(k => Object.hasOwn(v, k));
const uuid = (v: unknown): v is string => typeof v === "string" && UUID.test(v);
const hash = (v: unknown): v is string => typeof v === "string" && HASH.test(v);
const nullableUuid = (v: unknown) => v === null || uuid(v);
const scope = (v: unknown): v is ReviewScope => v === "extraction_fidelity" || v === "scientific_result";
const decision = (v: unknown): v is ReviewDecision => v === "accept" || v === "reject" || v === "request_clarification";
const profile = (v: unknown): v is ReviewProfile => typeof v === "string" && Object.hasOwn(REVIEW_PROFILES, v);
const integer = (v: unknown, max: number, min = 0): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max;
const codes = (v: unknown): v is string[] => Array.isArray(v) && v.length <= 100 && v.every(c => typeof c === "string" && /^[a-z][a-z0-9_]{0,119}$/.test(c)) && new Set(v).size === v.length;
const list = (v: unknown, max: number): v is unknown[] => Array.isArray(v) && v.length <= max;
function refs(v: unknown): v is EvidenceRef[] {
  return list(v, 50) && v.every(r => keys(r, ["artifact_id", "bytes_sha256"]) && uuid(r.artifact_id) && hash(r.bytes_sha256))
    && new Set(v.map(r => (r as EvidenceRef).artifact_id)).size === v.length
    && v.every((r, i) => i === 0 || (v[i - 1] as EvidenceRef).artifact_id < (r as EvidenceRef).artifact_id);
}
function reviewStatus(v: unknown): v is ScopeStatus {
  if (!keys(v, ["scope", "profile_version", "decision_id", "decision_sha256", "decision", "effective_status", "reason_codes", "scientific_scope_accepted"])
    || !scope(v.scope) || !codes(v.reason_codes) || typeof v.scientific_scope_accepted !== "boolean"
    || !["unreviewed", "accepted", "rejected", "clarification_required", "stale", "source_held", "reviewer_unavailable", "dependency_review_held"].includes(v.effective_status as string)) return false;
  if (v.decision_id === null) {
    return v.profile_version === null && v.decision_sha256 === null && v.decision === null
      && v.effective_status === "unreviewed" && v.scientific_scope_accepted === false;
  }
  if (!uuid(v.decision_id) || !hash(v.decision_sha256) || !decision(v.decision) || !profile(v.profile_version)
    || REVIEW_PROFILES[v.profile_version].scope !== v.scope) return false;
  if (v.effective_status === "unreviewed") return false;
  if (v.effective_status === "accepted" && v.decision !== "accept"
    || v.effective_status === "rejected" && v.decision !== "reject"
    || v.effective_status === "clarification_required" && v.decision !== "request_clarification") return false;
  return v.scientific_scope_accepted === (v.scope === "scientific_result" && v.effective_status === "accepted");
}
function target(v: unknown, expected: ReviewQueueItem): v is AdjudicationTarget {
  if (!keys(v, ["property_id", "subject_id", "subject_sha256", "event_id", "event_revision", "impact_sha256", "available_profiles", "required_artifacts", "heads", "status", "impact", "dossier", "reason_codes"])
    || v.property_id !== expected.property_id || v.event_id !== expected.event_id || v.event_revision !== expected.event_revision
    || !uuid(v.property_id) || !uuid(v.event_id) || !integer(v.event_revision, 2147483647, 1) || !uuid(v.subject_id)
    || !hash(v.subject_sha256) || !hash(v.impact_sha256) || !list(v.available_profiles, 3) || !v.available_profiles.every(profile)
    || new Set(v.available_profiles).size !== v.available_profiles.length || !refs(v.required_artifacts) || !codes(v.reason_codes)
    || !list(v.heads, 2) || v.heads.length !== 2 || !v.heads.every(h => keys(h, ["scope", "decision_id"]) && scope(h.scope) && nullableUuid(h.decision_id))
    || new Set(v.heads.map(h => (h as { scope: string }).scope)).size !== 2
    || !keys(v.status, ["version", "property_id", "subject_sha256", "scopes", "revision_sha256", "ml_training_approved", "public_release_authorized"])
    || v.status.version !== "scientific-result-review-status/1.0.0" || v.status.property_id !== v.property_id || v.status.subject_sha256 !== v.subject_sha256
    || !hash(v.status.revision_sha256) || v.status.ml_training_approved !== false || v.status.public_release_authorized !== false
    || !list(v.status.scopes, 2) || v.status.scopes.length !== 2 || !v.status.scopes.every(reviewStatus)
    || new Set(v.status.scopes.map(s => (s as ScopeStatus).scope)).size !== 2 || knownReviewImpact(v.impact) === null
    || knownReviewDossier(v.dossier, expected) === null) return false;
  const dossier = v.dossier as ReviewDossier;
  if (JSON.stringify(dossier.impact) !== JSON.stringify(v.impact)
    || !v.required_artifacts.every(ref => dossier.sources.some(s => s.artifact_id === ref.artifact_id && s.hash_status === "verified" && s.bytes_sha256 === ref.bytes_sha256))) return false;
  return v.heads.every(h => v.status && (v.status as AdjudicationTarget["status"]).scopes.find(s => s.scope === (h as AdjudicationTarget["heads"][number]).scope)?.decision_id === (h as AdjudicationTarget["heads"][number]).decision_id);
}
export function knownAdjudicationContext(value: unknown, expected: ReviewQueueItem[]): AdjudicationContext | null {
  if (!expected.length || expected.length > 20 || new Set(expected.map(v => v.property_id)).size !== expected.length
    || !keys(value, ["version", "actor_user_id", "actor_grant_id", "can_review", "max_items", "targets"])
    || value.version !== "scientific-adjudication-context/1.0.0" || !uuid(value.actor_user_id)
    || !nullableUuid(value.actor_grant_id) || typeof value.can_review !== "boolean" || value.can_review && value.actor_grant_id === null
    || value.max_items !== 20 || !list(value.targets, 20) || value.targets.length !== expected.length
    || new Set(value.targets.map(v => object(v) ? v.property_id : null)).size !== expected.length) return null;
  for (const row of value.targets) {
    const item = expected.find(e => object(row) && e.property_id === row.property_id);
    if (!item || !target(row, item)) return null;
  }
  return value as unknown as AdjudicationContext;
}
export function currentScope(target: AdjudicationTarget, selectedScope: ReviewScope): ScopeStatus {
  return target.status.scopes.find(s => s.scope === selectedScope)!;
}
export function knownAdjudicationRequest(value: unknown, context: AdjudicationContext): AdjudicationRequest | null {
  if (!context.can_review || !context.actor_grant_id
    || !keys(value, ["version", "request_key", "items"]) || value.version !== "scientific-result-adjudication/1.0.0"
    || typeof value.request_key !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:+@-]{0,159}$/.test(value.request_key)
    || !list(value.items, 20) || value.items.length !== context.targets.length || value.items.length === 0
    || new Set(value.items.map(v => object(v) ? v.property_id : null)).size !== value.items.length
    || new Set(value.items.map(v => object(v) ? v.decision_id : null)).size !== value.items.length) return null;
  for (const item of value.items) {
    if (!keys(item, ["decision_id", "subject_id", "property_id", "scope", "profile_version", "expected_subject_sha256", "expected_previous_decision_id",
      "expected_impact_sha256", "decision", "reason_code", "rationale", "proposition", "limitations", "checks", "evidence_refs",
      "source_inspection_attested", "resolves_decision_id", "extraction_decision_id"])
      || !uuid(item.decision_id) || !scope(item.scope) || !profile(item.profile_version) || !decision(item.decision)
      || !REVIEW_REASONS[item.decision].includes(item.reason_code as string)
      || typeof item.rationale !== "string" || item.rationale.length > 4000 || Array.from(item.rationale.trim()).length < 20
      || Array.from(item.rationale).length > 2000 || /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]/.test(item.rationale)
      || Array.from(item.rationale).some(c => c.codePointAt(0)! >= 0xd800 && c.codePointAt(0)! <= 0xdfff)
      || !Array.isArray(item.limitations) || JSON.stringify(item.limitations) !== JSON.stringify(REVIEW_LIMITATIONS)
      || REVIEW_PROFILES[item.profile_version].scope !== item.scope || REVIEW_PROFILES[item.profile_version].proposition !== item.proposition
      || !keys(item.checks, [...REVIEW_CHECKS]) || !Object.values(item.checks).every(c => ["satisfied", "not_applicable", "unresolved"].includes(c as string))
      || !refs(item.evidence_refs) || typeof item.source_inspection_attested !== "boolean"
      || !nullableUuid(item.resolves_decision_id) || !nullableUuid(item.extraction_decision_id)) return null;
    const selected = context.targets.find(t => t.property_id === item.property_id);
    if (!selected || item.subject_id !== selected.subject_id || item.expected_subject_sha256 !== selected.subject_sha256
      || item.expected_impact_sha256 !== selected.impact_sha256 || !selected.available_profiles.includes(item.profile_version)
      || item.expected_previous_decision_id !== currentScope(selected, item.scope).decision_id
      || item.evidence_refs.some(ref => !selected.required_artifacts.some(r => r.artifact_id === ref.artifact_id && r.bytes_sha256 === ref.bytes_sha256))) return null;
    if (item.decision === "accept") {
      if (!item.source_inspection_attested || !item.evidence_refs.length || Object.values(item.checks).some(c => c !== "satisfied")
        || item.evidence_refs.length !== selected.required_artifacts.length) return null;
      const previous = currentScope(selected, item.scope);
      const negative = previous.decision === "reject" || previous.decision === "request_clarification";
      if (item.resolves_decision_id !== (negative ? previous.decision_id : null)) return null;
      const fidelity = currentScope(selected, "extraction_fidelity");
      if (item.scope === "scientific_result" && (fidelity.effective_status !== "accepted" || fidelity.decision !== "accept"
        || item.extraction_decision_id !== fidelity.decision_id)) return null;
    } else if (item.resolves_decision_id !== null || item.extraction_decision_id !== null) return null;
    if (item.scope === "extraction_fidelity" && item.extraction_decision_id !== null) return null;
  }
  const result = value as unknown as AdjudicationRequest;
  if (result.items.reduce((sum, item) => sum + item.evidence_refs.length, 0) > 200
    || new TextEncoder().encode(JSON.stringify(result)).length > 128 * 1024) return null;
  return result;
}
export function knownAdjudicationPreview(value: unknown, request: AdjudicationRequest, context: AdjudicationContext): AdjudicationPreview | null {
  if (!keys(value, ["version", "actor_user_id", "actor_grant_id", "request_key", "request_sha256", "preview_sha256", "can_commit", "items",
    "database_mutated", "ml_training_approved", "public_release_authorized"])
    || value.version !== "scientific-adjudication-preview/1.0.0" || value.actor_user_id !== context.actor_user_id
    || value.actor_grant_id !== context.actor_grant_id || !uuid(value.actor_grant_id)
    || value.request_key !== request.request_key || !hash(value.request_sha256) || !hash(value.preview_sha256)
    || value.can_commit !== true || value.database_mutated !== false || value.ml_training_approved !== false || value.public_release_authorized !== false
    || !list(value.items, 20) || value.items.length !== request.items.length) return null;
  for (const [index, item] of value.items.entries()) {
    const sent = request.items[index];
    if (!keys(item, ["decision_id", "subject_id", "property_id", "scope", "profile_version", "decision", "subject_sha256", "expected_previous_decision_id", "impact_sha256"])
      || ["decision_id", "subject_id", "property_id", "scope", "profile_version", "decision", "expected_previous_decision_id"].some(k => item[k] !== sent[k as keyof AdjudicationItem])
      || item.subject_sha256 !== sent.expected_subject_sha256 || item.impact_sha256 !== sent.expected_impact_sha256) return null;
  }
  return value as unknown as AdjudicationPreview;
}
export function knownAdjudicationReceipt(value: unknown, request: AdjudicationRequest, preview: AdjudicationPreview): AdjudicationReceipt | null {
  if (!keys(value, ["version", "request_id", "request_key", "request_sha256", "preview_sha256", "committed", "replayed", "items",
    "ml_training_approved", "public_release_authorized"])
    || value.version !== "scientific-adjudication-receipt/1.0.0" || !uuid(value.request_id)
    || value.request_key !== request.request_key || value.request_sha256 !== preview.request_sha256 || value.preview_sha256 !== preview.preview_sha256
    || value.committed !== true || typeof value.replayed !== "boolean" || value.ml_training_approved !== false || value.public_release_authorized !== false
    || !list(value.items, 20) || value.items.length !== request.items.length) return null;
  for (const [index, item] of value.items.entries()) {
    const sent = request.items[index];
    if (!keys(item, ["decision_id", "subject_id", "property_id", "scope", "profile_version", "decision", "decision_sha256"])
      || ["decision_id", "subject_id", "property_id", "scope", "profile_version", "decision"].some(k => item[k] !== sent[k as keyof AdjudicationItem])
      || !hash(item.decision_sha256)) return null;
  }
  return value as unknown as AdjudicationReceipt;
}
