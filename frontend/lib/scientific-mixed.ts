/** Closed wire consistency for server-verified Result–passage bridge metadata. */
import type { AskResponse, MixedEvidenceAssociation, ScientificMixedEvidence } from "@/lib/api";
import { knownEvidenceProvenance } from "@/lib/evidence-provenance";
import { knownInputBudget, knownPackingInventory, knownPackingSummary } from "@/lib/evidence-packing";
import { knownSourceVisibility } from "@/lib/material-visibility";
import { knownScientificLookup, knownScientificQuery, knownScientificResults } from "@/lib/scientific-query";

type Row = Record<string, unknown>;
const row = (value: unknown): value is Row => value !== null && typeof value === "object" && !Array.isArray(value);
const keys = (value: unknown, fields: string[]): value is Row => row(value) && Object.keys(value).length === fields.length && fields.every(field => Object.hasOwn(value, field));
const integer = (value: unknown, min = 0, max = 20): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= min && value <= max;
const hash = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
const uuid = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
const text = (value: unknown, max: number): value is string => typeof value === "string" && Array.from(value).length <= max;
const choice = (value: unknown, options: string[]) => typeof value === "string" && options.includes(value);
const reasons = ["numerical_explanation_not_established", "reviewed_result_passage_bridge_missing", "no_matching_extraction",
  "no_original_context", "combined_source_limit", "mixed_lookup_unavailable", "mixed_context_unavailable", "mixed_currentness_unavailable",
  "retrieval_generation_changed", "retrieval_source_changed", "retrieval_source_no_longer_eligible", "retrieval_grouping_changed",
  "retrieval_currentness_unavailable", "retrieval_currentness_timeout", "evidence_packing_unavailable"];

const notRequested: ScientificMixedEvidence = { version: "scientific-mixed-evidence/1.1.0", status: "not_requested",
  result_count: 0, source_count: 0, max_selected_inputs: 0, associations: [], reason_codes: [],
  scientific_acceptance: false, independent_support_count: null };

function association(input: unknown, version: string): input is MixedEvidenceAssociation {
  const shared = ["parent_result_revision_id", "result_source_snapshot_sha256", "source_index", "source_vector_id",
    "source_evidence_revision_id", "source_evidence_record_sha256", "source_content_sha256", "catalogue_relation", "status", "reason_code"];
  const bridge = ["bridge_revision_id", "bridge_record_sha256", "claim_identity_sha256", "sample_identity_sha256", "source_locator_sha256"];
  if (!keys(input, version === "scientific-mixed-evidence/1.0.0" ? shared : [...shared, ...bridge])
    || !uuid(input.parent_result_revision_id) || !hash(input.result_source_snapshot_sha256) || !integer(input.source_index, 1)
    || typeof input.source_vector_id !== "string" || !/^ig62_[0-9a-f]{32}_[0-9a-f]{64}$/.test(input.source_vector_id)
    || !uuid(input.source_evidence_revision_id) || !hash(input.source_evidence_record_sha256) || !hash(input.source_content_sha256)
    || !choice(input.catalogue_relation, ["same_snapshot", "not_same_snapshot"])) return false;
  if (version === "scientific-mixed-evidence/1.0.0") {
    return input.status === "not_established" && input.reason_code === "reviewed_result_passage_bridge_missing";
  }
  const pins = bridge.map(field => input[field]);
  const established = input.status === "established";
  return (established || input.status === "not_established")
    && (established ? input.reason_code === "reviewed_result_passage_bridge_current" : input.reason_code === "reviewed_result_passage_bridge_missing")
    && (established ? uuid(pins[0]) && pins.slice(1).every(hash) : pins.every(value => value === null));
}

/** Missing metadata is rolling legacy compatibility; malformed present metadata is not. */
export function knownScientificMixedResponse(response: unknown, rawQuery: string): ScientificMixedEvidence | null {
  if (!row(response)) return null;
  const mixed = response.scientific_mixed;
  if (mixed === undefined) return notRequested;
  if (!keys(mixed, ["version", "status", "result_count", "source_count", "max_selected_inputs", "associations", "reason_codes",
    "scientific_acceptance", "independent_support_count"])
    || !choice(mixed.version, ["scientific-mixed-evidence/1.0.0", "scientific-mixed-evidence/1.1.0"])
    || !choice(mixed.status, ["not_requested", "completed", "unavailable"])
    || !integer(mixed.result_count) || !integer(mixed.source_count) || !integer(mixed.max_selected_inputs)
    || !Array.isArray(mixed.associations) || mixed.associations.length > 100
    || !mixed.associations.every(item => association(item, mixed.version as string))
    || !Array.isArray(mixed.reason_codes) || mixed.reason_codes.length > 8
    || mixed.reason_codes.some(reason => typeof reason !== "string" || !reasons.includes(reason))
    || new Set(mixed.reason_codes).size !== mixed.reason_codes.length
    || mixed.scientific_acceptance !== false || mixed.independent_support_count !== null) return null;
  if (mixed.status === "not_requested") return mixed.result_count === 0 && mixed.source_count === 0 && mixed.max_selected_inputs === 0
    && mixed.associations.length === 0 && mixed.reason_codes.length === 0 ? mixed as unknown as ScientificMixedEvidence : null;

  const query = knownScientificQuery(response.scientific_query, rawQuery);
  const lookup = knownScientificLookup(response.scientific_lookup);
  const budget = knownInputBudget(response.input_budget);
  const mixedIntent = query?.intent === "mixed" || query?.intent === "comparison"
    && (query.requested_fields.length > 0 || query.constraints.length > 0 || query.evidence_constraints.length > 0);
  if (!query || query.status !== "resolved" || !mixedIntent || !lookup || !budget || budget.status !== "not_requested"
    || response.answer_mode !== "abstention" || response.assessment_scope !== "none" || response.scientific_support_status !== "not_checked"
    || !Array.isArray(response.claim_assessments) || response.claim_assessments.length !== 0 || response.tokens_used !== 0
    || !Array.isArray(response.sources) || response.sources.length > 20 || response.sources.some(source => !row(source))) return null;
  const results = knownScientificResults(response.scientific_results, lookup, response.retrieval_generation, query);
  if (!results) return null;
  const sources = response.sources as AskResponse["sources"];
  if (!knownPackingSummary(response.evidence_packing, sources)) return null;
  if (mixed.status === "unavailable") return mixed.result_count === 0 && mixed.source_count === 0 && mixed.associations.length === 0
    && mixed.reason_codes.length > 0 && sources.length === 0 && results.length === 0 && lookup.status === "unavailable"
    ? mixed as unknown as ScientificMixedEvidence : null;
  if (lookup.status !== "completed" || mixed.max_selected_inputs < 1 || mixed.result_count + mixed.source_count > mixed.max_selected_inputs
    || mixed.result_count !== results.length || mixed.source_count !== sources.length
    || mixed.associations.length !== mixed.result_count * mixed.source_count
    || !mixed.reason_codes.includes("numerical_explanation_not_established")
    || mixed.reason_codes.includes("reviewed_result_passage_bridge_missing") !== (
      mixed.version === "scientific-mixed-evidence/1.0.0" || mixed.associations.length === 0
      || mixed.associations.some(item => item.status === "not_established"))
    || mixed.reason_codes.includes("no_matching_extraction") !== (results.length === 0)
    || mixed.reason_codes.includes("no_original_context") !== (sources.length === 0)) return null;
  const packing = knownPackingInventory(sources);
  if (!packing) return null;
  // Completed result validation above already requires a closed generation pin.
  const pin = response.retrieval_generation as NonNullable<AskResponse["retrieval_generation"]>;
  const vectorPattern = new RegExp(`^ig62_${pin.generation_id!.replaceAll("-", "") }_[0-9a-f]{64}$`);
  const originalVectors = new Set<string>();
  for (const [index, source] of sources.entries()) {
    const evidence = knownEvidenceProvenance(source.evidence_provenance);
    const visibility = knownSourceVisibility(source.source_visibility);
    const visibilityInput = source.source_visibility as unknown;
    if (source.index !== index + 1 || !text(source.title, 20000) || !text(source.authors_short, 20000)
      || !text(source.snippet, 8192) || source.section !== null && !text(source.section, 2048)
      || source.year !== null && !integer(source.year, 0, 9999)
      || !evidence || evidence.chunk_kind !== "original_passage" || evidence.currentness === "stale" || evidence.permission_status === "restricted"
      || !visibility || !visibility.bibliography_available || !visibility.reported_claim_filter_eligible
      || !row(visibilityInput) || !choice(visibilityInput.source_status, ["active", "unknown"])
      || visibilityInput.lifecycle_review_required !== undefined && visibilityInput.lifecycle_review_required !== false
      || !Array.isArray(visibilityInput.warning_codes) || visibilityInput.warning_codes.length > 100
      || visibilityInput.warning_codes.some(code => typeof code !== "string" || !/^[a-zA-Z0-9_.:-]{1,120}$/.test(code))
      || ["retracted", "corrected", "disputed"].includes(visibility.source_status)
      || !vectorPattern.test(packing[index].chunk_id) || results.some(result => result.binding.vector_id === packing[index].chunk_id)) return null;
    originalVectors.add(packing[index].chunk_id);
  }
  if (originalVectors.size !== sources.length) return null;
  const parents = new Map(results.map(result => [result.binding.parent_result_revision_id, result]));
  const seen = new Set<string>(), snapshots = new Map<string, string>();
  for (const item of mixed.associations) {
    const result = parents.get(item.parent_result_revision_id), source = sources[item.source_index - 1];
    const key = `${item.parent_result_revision_id}:${item.source_index}`;
    if (!result || !source || seen.has(key)) return null;
    const evidence = source.evidence_provenance!, selected = source.packing_info!;
    if (item.source_vector_id !== selected.chunk_id || item.source_evidence_revision_id !== evidence.evidence_revision_id
      || item.source_evidence_record_sha256 !== evidence.evidence_record_sha256 || item.source_content_sha256 !== evidence.content_sha256
      || snapshots.has(item.parent_result_revision_id) && snapshots.get(item.parent_result_revision_id) !== item.result_source_snapshot_sha256) return null;
    const same = result.binding.paper_id === source.paper_id && item.result_source_snapshot_sha256 === selected.source_snapshot_sha256;
    if ((item.catalogue_relation === "same_snapshot") !== same || item.status === "established" && !same) return null;
    snapshots.set(item.parent_result_revision_id, item.result_source_snapshot_sha256);
    seen.add(key);
  }
  return seen.size === results.length * sources.length ? mixed as unknown as ScientificMixedEvidence : null;
}
