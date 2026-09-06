import { API_BASE } from "./api";

export const PHYSICAL_DIMENSIONS = [
  ["stability", "Stability"], ["electronic", "Electronic"],
  ["pairing", "Pairing"], ["coherence", "Coherence"],
  ["geometry", "Geometry"], ["competing_order", "Competing order"],
] as const;

export const RPS_ACTION_CONTRACT = "rps-action-contract/1";
export const ACTION_RESOURCES = ["cpu_core_hours", "gpu_hours", "memory_gib", "storage_gib", "human_hours"] as const;
type EvidencePolarity = "supporting" | "opposing" | "mixed" | "neutral" | "unknown";
type EvidenceReference = { id: string; sha256: string };
export interface ActionRequirements {
  schema_version: typeof RPS_ACTION_CONTRACT;
  template_ref: EvidenceReference;
  template_review: EvidenceReference;
  template: {
    version: string; title: string; action_kind: string; scope: string;
    prerequisite_completeness_rationale: string;
    prerequisites: { key: string; description: string; dependency_kind: string; critical: boolean; allow_not_applicable: boolean }[];
    resource_rules: Record<string, "required" | "optional" | "not_applicable">;
  };
  prerequisites: { key: string; status: string; rationale: string; evidence: EvidenceReference[]; dependency_ids: string[] }[];
  dependencies: { id: string; kind: string; status: string; rationale: string; evidence: EvidenceReference[] }[];
  resources: { resource: string; applicability: "required" | "unknown" | "not_applicable"; rationale: string; evidence: EvidenceReference[] }[];
}

export interface RpsRelease {
  id: string;
  manifest_sha256: string;
  campaign_id: string;
  campaign_version: string;
  objective: string;
  published_at: string;
  evidence_cutoff: string;
  total: number;
}
export interface RpsResult {
  eligibility: "eligible" | "pending" | "ineligible" | "reference_only";
  reason_codes: string[];
  rank_group: "discovery" | "mechanism";
  policy_version: string;
  action_contract_version: typeof RPS_ACTION_CONTRACT;
  action_requirements_hash: string;
  execution_constraint_reasons: string[];
  score_raw: number | null;
  score_display: number | null;
  score_upper: number | null;
  p_lower: number; p_upper: number;
  g_lower: number; g_upper: number;
  a_lower: number | null; a_upper: number | null;
  assessed_weight: number;
  contributions: {
    baseline: number; physical: number; gain: number; action: number | null;
    rounding: number | null; dimensions: Record<string, number>;
    dimension_reasons: Record<string, string>;
    dimension_explanations: Record<string, {
      evidence_polarity: EvidencePolarity; reason_codes: string[];
      anchor_contribution: number | null; uncertainty_discount: number | null;
      missing_support_contribution: number;
    }>;
  };
}
export interface RpsRow {
  id: string; revision: number; rank: number | null;
  material_id: string; state_id: string; action_id: string;
  formula: string; family: string; state_summary: string; action_summary: string;
  role: string;
  action_template: { id: string; version: string; sha256: string; review_id: string };
  dimensions: Record<string, {
    status: "assessed" | "unknown"; anchor: number | null;
    lower: number; upper: number; missing_reason: string | null; evidence_polarity: EvidencePolarity;
  }>;
  result: RpsResult;
}
export interface RpsPage {
  schema_version: "rps-page/1.2";
  release_id: string; manifest_sha256: string; policy_hash: string;
  campaign: { id: string; version: string; objective: string };
  evidence_cutoff: string; items: RpsRow[]; total: number;
  group: string; release_total: number;
  offset: number; limit: number; has_more: boolean;
}
export interface RpsDetail {
  schema_version: "rps-detail/1.2";
  release_id: string; manifest_sha256: string;
  result: RpsResult;
  assessment: {
    id: string; revision: number;
    material: { id: string }; state: { id: string }; action: { id: string };
    dimensions: Record<string, { rationale: string; rule_id: string; missing_reason: string | null; evidence_polarity: EvidencePolarity }>;
    action_requirements: ActionRequirements;
    outcomes: { observation: string; decision: string }[];
    costs: { resource: string; lower: number; upper: number | null; basis: string }[];
  };
  state: { pressure_status: string; pressure_gpa: number | null; phase: string; sample_context: string };
  action: { kind: string; action_requirements_hash: string; conversion_target_pressure_gpa?: number | null; conversion_rationale?: string | null };
  evidence: { id: string; sha256: string; source: {
    title: string; url: string; source_version: string; locator: string; validity: string;
  } }[];
}

async function read<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}/discovery/rps${path}`, {
    credentials: "omit", cache: "no-store", signal: AbortSignal.timeout(15_000),
  });
  if (!response.ok) throw new Error(`RPS request failed (${response.status})`);
  return response.json() as Promise<T>;
}
export async function getRpsReleases() {
  return read<{ schema_version: "rps-catalog/1.2"; status: string; items: RpsRelease[] }>("/releases");
}
export async function getRpsPage(id: string, offset = 0, group = "discovery") {
  return read<RpsPage>(`/releases/${encodeURIComponent(id)}/assessments?offset=${offset}&limit=24&group=${encodeURIComponent(group)}`);
}
export async function getRpsDetail(releaseId: string, assessmentId: string) {
  return read<RpsDetail>(`/releases/${encodeURIComponent(releaseId)}/assessments/${encodeURIComponent(assessmentId)}`);
}

export function verifyRpsPage(page: RpsPage, release: RpsRelease, offset: number, existing: RpsRow[] = [], group = "discovery") {
  if (page.schema_version !== "rps-page/1.2" || page.release_id !== release.id ||
      page.manifest_sha256 !== release.manifest_sha256 || page.offset !== offset ||
      page.release_total !== release.total || page.group !== group || page.total > release.total || page.items.length > page.limit ||
      page.has_more !== (page.offset + page.items.length < page.total)) {
    throw new Error("Release changed or failed verification. Reload the release list.");
  }
  const ids = [...existing, ...page.items].map(row => row.id);
  if (new Set(ids).size !== ids.length) throw new Error("Duplicate assessment in release.");
  for (const row of page.items) {
    if (row.result.action_contract_version !== RPS_ACTION_CONTRACT ||
        !/^[a-f0-9]{64}$/.test(row.result.action_requirements_hash) ||
        !row.action_template?.version || !row.action_template.review_id ||
        !/^[a-f0-9]{64}$/.test(row.action_template.sha256)) {
      throw new Error("Missing reviewed action contract. Scores are hidden.");
    }
    if (row.result.score_display !== null && (row.result.eligibility !== "eligible" ||
        !Number.isFinite(row.result.score_display) || row.result.score_display < 1000 ||
        row.result.score_display > 10000 || row.result.score_display % 50 !== 0)) {
      throw new Error("Invalid public research priority score.");
    }
  }
  return page;
}

export function verifyRpsDetail(detail: RpsDetail, release: RpsRelease, row: RpsRow) {
  if (detail.schema_version !== "rps-detail/1.2" || detail.release_id !== release.id ||
      detail.manifest_sha256 !== release.manifest_sha256 || detail.assessment.id !== row.id ||
      detail.assessment.revision !== row.revision || detail.assessment.material.id !== row.material_id ||
      detail.assessment.state.id !== row.state_id || detail.assessment.action.id !== row.action_id ||
      detail.result.score_raw !== row.result.score_raw || detail.result.score_display !== row.result.score_display ||
      detail.result.eligibility !== row.result.eligibility ||
      detail.result.action_contract_version !== RPS_ACTION_CONTRACT ||
      detail.result.action_requirements_hash !== row.result.action_requirements_hash ||
      detail.action.action_requirements_hash !== row.result.action_requirements_hash) {
    throw new Error("Assessment identity or score mismatch within release.");
  }
  const requirements = detail.assessment.action_requirements;
  if (requirements?.schema_version !== RPS_ACTION_CONTRACT ||
      requirements.template_ref.id !== row.action_template.id ||
      requirements.template_ref.sha256 !== row.action_template.sha256 ||
      requirements.template.version !== row.action_template.version ||
      requirements.template_review.id !== row.action_template.review_id ||
      requirements.resources.length !== ACTION_RESOURCES.length ||
      new Set(requirements.resources.map(item => item.resource)).size !== ACTION_RESOURCES.length ||
      requirements.resources.some(item => !(ACTION_RESOURCES as readonly string[]).includes(item.resource))) {
    throw new Error("Action prerequisites or resource contract mismatch within release.");
  }
  return detail;
}
