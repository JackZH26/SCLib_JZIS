// Client-safe, versioned provisional ordinal policy. Bounds are support ranges, never probabilities.
export const evidenceVersion = "2026-10-08-evidence103-v1";
export const rubricVersion = "discovery-provisional-support/1.0.0";
export type ResearchGoal = "source_pairing" | "ambient_300K";
export type EvidenceLevel = "E0" | "E1" | "E2" | "E3" | "E4" | "E5";
export type SupportAxis = "stability" | "electronic" | "pairing" | "coherence" | "geometry" | "competition";
export type Anchor = "unknown" | "source_pairing" | "independent_positive" | "robust_positive" | "adverse";
export const commonWeights: Readonly<Record<SupportAxis, number>> = { stability: 20, electronic: 20, pairing: 25, coherence: 15, geometry: 10, competition: 10 };
export const supportAnchors: Readonly<Record<Anchor, readonly [number, number]>> = {
  unknown: [0, 100], source_pairing: [25, 50], independent_positive: [50, 75], robust_positive: [75, 100], adverse: [0, 25],
};
export type AxisEvidence = { anchor: Anchor; quantified_for_goal: boolean; scope: string };
export type SupportAssessment = {
  grade: "A" | "B" | "C" | "U"; lower: number; upper: number; coverage_percent: number;
  goal: ResearchGoal; target_fit: "source_theory" | "no_direct_support";
  evidence_level: EvidenceLevel; unresolved_identity: boolean; adverse_axes: SupportAxis[];
  axes: Record<SupportAxis, AxisEvidence>;
};
export type ResearchEvidenceSummary = {
  evidence_level: "E1"; source_pairing_quantified: true;
  geometry_causality_quantified: false; ambient_300K_direct_support: null;
  counterevidence_count: number; joint_adverse_count: number; discordant_count: number;
  detail: { url: string; bytes: number; sha256: string };
};
export type CounterEvidence = {
  comparison_origin: "frozen_countercontrol" | "selected_source_control";
  countercontrol_index: number | null; control_reference: string; direction: "joint_adverse" | "discordant";
  lambda_target_minus_control_range: [number, number]; lambda_unit: "dimensionless" | "percent";
  source_tc_target_minus_control_K: number; scope: string; causal_geometry_effect: null;
};
export type DiscoveryEvidenceCard = {
  schema_version: "discovery-evidence-card/1.0.0"; version: string;
  id: string; source_state: string; formula: string; source_catalogue_sha256: string; source_detail_sha256: string;
  evidence_level: "E1"; evidence_basis: string;
  prior: { category: string; exact_experimental_status: "unresolved"; search_completeness: "unknown"; summary: string; case_context: string;
    sources: { title: string; url: string; doi?: string }[]; claim_boundary: string };
  bottleneck: { summary: string; ambient_scope: string; attention_tags: string[]; counterevidence: CounterEvidence[]; unknowns: string[] };
  proposed_contribution: { status: "proposed_not_completed"; intervention: string; target_state: string; selected_control: string;
    next_action: string; falsifier: string; new_state_inheritance: string };
};

/** Fixed weights; missing evidence keeps [0,100] and never borrows another axis's weight. */
export function assessSupport(axes: Record<SupportAxis, AxisEvidence>, goal: ResearchGoal, evidence_level: EvidenceLevel,
  identityKnown = true): SupportAssessment {
  let lower = 0, upper = 0, coverage = 0;
  const adverse_axes: SupportAxis[] = [];
  for (const axis of Object.keys(commonWeights) as SupportAxis[]) {
    const observation = axes[axis], weight = commonWeights[axis];
    if (!observation || !Object.hasOwn(supportAnchors, observation.anchor)) throw new Error("Invalid support anchor");
    if (observation.anchor === "source_pairing" && (axis !== "pairing" || goal !== "source_pairing")) throw new Error("Source pairing evidence does not correspond to this target");
    if (observation.anchor === "unknown" && observation.quantified_for_goal) throw new Error("Unknown evidence cannot count as quantified coverage");
    const [lo, hi] = supportAnchors[observation.anchor];
    lower += weight * lo / 100; upper += weight * hi / 100;
    if (observation.quantified_for_goal) coverage += weight;
    if (observation.anchor === "adverse") adverse_axes.push(axis);
  }
  const level = Number(evidence_level.slice(1));
  if (!Number.isInteger(level) || level < 0 || level > 5) throw new Error("Invalid evidence level");
  // Provisional 75/55 policy anchors are not calibrated physical thresholds.
  const grade = !identityKnown ? "U" : adverse_axes.length || level < 2 ? "C"
    : lower >= 75 && level >= 3 && coverage === 100 ? "A" : lower >= 55 && coverage >= 75 ? "B" : "C";
  return { grade, lower, upper, coverage_percent: coverage, goal, evidence_level, unresolved_identity: !identityKnown,
    target_fit: goal === "ambient_300K" ? "no_direct_support" : "source_theory", adverse_axes, axes };
}

export function sourceSupport(summary: ResearchEvidenceSummary, goal: ResearchGoal): SupportAssessment {
  const unknown = (scope: string): AxisEvidence => ({ anchor: "unknown", quantified_for_goal: false, scope });
  return assessSupport({
    stability: unknown("Local source relaxation and sampled phonons do not establish global retention under the research target."),
    electronic: unknown("Physical bandwidth and mobile carrier density are unquantified for this target."),
    pairing: goal === "source_pairing" ? { anchor: "source_pairing", quantified_for_goal: true,
      scope: "Source isotropic Eliashberg Tc and coupling are one correlated source-theory chain. They are not independent evidence." }
      : unknown("Source low-temperature calculations provide no direct support for approximately 300 K at ambient pressure; broader material feasibility remains unassessed."),
    coherence: unknown("Target-condition phase stiffness and competing collective orders are unresolved."),
    geometry: unknown("A source contrast is not a quantified causal geometry intervention; method and composition confounds remain."),
    competition: unknown("Exact-state competing phases and decomposition paths are unresolved."),
  }, goal, summary.evidence_level);
}

/** Group ordering, never a calibrated probability or fine potential rank within overlapping bounds. */
export function compareResearchPriority<T extends { formula: string; source_state: string; research_evidence: ResearchEvidenceSummary }>(
  left: T, right: T, goal: ResearchGoal): number {
  const a = sourceSupport(left.research_evidence, goal), b = sourceSupport(right.research_evidence, goal);
  // Comparator evidence concerns the source-response target; it cannot be extrapolated to 300 K.
  const limit = (row: T) => goal === "source_pairing" && row.research_evidence.counterevidence_count > 0 ? 1 : 0;
  const grades = { A: 0, B: 1, C: 2, U: 3 };
  return grades[a.grade] - grades[b.grade] || limit(left) - limit(right)
    || b.coverage_percent - a.coverage_percent
    || new Intl.Collator("en-US", { numeric: true, sensitivity: "base" }).compare(left.formula, right.formula)
    || left.source_state.localeCompare(right.source_state, "en-US");
}

export async function verifyDiscoveryEvidenceCard(bytes: Uint8Array, expected: { id: string; formula: string; source_state: string;
  detail: { sha256: string }; research_evidence: ResearchEvidenceSummary }): Promise<DiscoveryEvidenceCard> {
  const pin = expected.research_evidence.detail;
  if (bytes.byteLength !== pin.bytes || bytes.byteLength > 256 * 1024) throw new Error("Invalid evidence-card size");
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const hash = Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, "0")).join("");
  if (hash !== pin.sha256) throw new Error("Evidence-card hash mismatch");
  const card = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as DiscoveryEvidenceCard;
  if (card.schema_version !== "discovery-evidence-card/1.0.0" || card.version !== evidenceVersion || card.id !== expected.id
    || card.formula !== expected.formula || card.source_state !== expected.source_state || card.source_detail_sha256 !== expected.detail.sha256
    || card.source_catalogue_sha256 !== "4a9089bc569f99ad7f5f469280814fb22bfcc86252b1fb7c1e1be446f8bcac98"
    || card.evidence_level !== "E1" || card.prior.exact_experimental_status !== "unresolved" || card.prior.search_completeness !== "unknown"
    || card.bottleneck.counterevidence.length !== expected.research_evidence.counterevidence_count) throw new Error("Evidence-card scope mismatch");
  return card;
}
