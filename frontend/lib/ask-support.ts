import type { AskResponse, AskScientificSupportStatus, AskSource } from "@/lib/api";
import { knownSourceVisibility } from "@/lib/material-visibility";

export const SCIENTIFIC_SUPPORT_POLICY_VERSION = "scientific-claim-support/1.0.0";

/** An index is linkable only when it names exactly one supplied source. */
export function resolveAskSource(index: unknown, sources: AskSource[]): AskSource | null {
  if (!Number.isSafeInteger(index) || Number(index) < 1) return null;
  const matches = sources.filter(source => source.index === index);
  if (matches.length !== 1 || typeof matches[0].paper_id !== "string" || !matches[0].paper_id.trim()) return null;
  return matches[0];
}

export function supportEvidenceSource(index: unknown, paperId: unknown, sources: AskSource[]): AskSource | null {
  const source = resolveAskSource(index, sources);
  return source && typeof paperId === "string" && source.paper_id === paperId ? source : null;
}

export function excerptSourceIsHeld(source: AskSource): boolean {
  const visibility = knownSourceVisibility(source.source_visibility);
  return !!visibility && (!visibility.bibliography_available || !visibility.reported_claim_filter_eligible || ["retracted", "corrected", "disputed"].includes(visibility.source_status));
}

const SUPPORT_LABELS: Record<AskScientificSupportStatus, string> = {
  supported: "Excerpt consistency checks passed",
  contradicted: "Excerpt checks found a conflict",
  undetermined: "Scientific support remains undetermined",
  not_checked: "Scientific support not checked",
};

export function supportStatusLabel(status: unknown): string {
  return typeof status === "string" && Object.hasOwn(SUPPORT_LABELS, status)
    ? SUPPORT_LABELS[status as AskScientificSupportStatus] : SUPPORT_LABELS.not_checked;
}

/** Rolling API compatibility must never turn the legacy citation flag into support. */
export function displayedAskSupportStatus(response: AskResponse): AskScientificSupportStatus {
  if (response.support_policy_version !== SCIENTIFIC_SUPPORT_POLICY_VERSION || response.assessment_scope !== "generated_draft") return "not_checked";
  const status = response.scientific_support_status;
  if (!status || !Object.hasOwn(SUPPORT_LABELS, status)) return "not_checked";
  if (status !== "supported") return status;
  const claims = response.claim_assessments ?? [];
  const coverage = response.support_coverage;
  if (response.citation_indices_valid !== true || !coverage || coverage.truncated !== false ||
      !Number.isSafeInteger(coverage.total_claims) || coverage.total_claims !== claims.length ||
      coverage.assessed_claims !== claims.length || coverage.supported_claims !== claims.length ||
      coverage.contradicted_claims !== 0 || coverage.undetermined_claims !== 0 ||
      claims.length === 0 || response.sources.length === 0 || claims.some(claim =>
    claim.status !== "supported" || !claim.evidence?.some(evidence =>
      typeof evidence.excerpt === "string" && evidence.excerpt.trim() &&
      claim.cited_indices.includes(evidence.source_index) && (() => {
        const source = supportEvidenceSource(evidence.source_index, evidence.paper_id, response.sources);
        return source && !excerptSourceIsHeld(source);
      })()))) return "undetermined";
  return "supported";
}
