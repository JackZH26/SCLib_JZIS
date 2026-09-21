import { createHash } from "node:crypto";
import type { AskResponse, MixedEvidenceAssociation } from "@/lib/api";
import { generation, scientificLookup, scientificQuery, scientificResult } from "./scientific-query";
import { inputBudget, packedSources, packingSummary } from "./evidence-packing";

/** Synthetic UI contract data only; no reviewed Result–passage bridge. */
export function mixedResponse(raw = "Why is Tc of MgB₂ 39 K?"): AskResponse {
  const result = scientificResult();
  const digest = (value: unknown) => createHash("sha256").update(JSON.stringify(value), "utf8").digest("hex");
  const sourceDigest = digest(["evidence-packing/1.0.0", "source-group", ["source_snapshot", result.binding.paper_id, "b".repeat(64)]]);
  const diversityDigest = digest(["evidence-packing/1.0.0", "diversity-group", ["source_snapshot", sourceDigest]]);
  const sources = packedSources().map((source, index) => ({ ...source, paper_id: result.binding.paper_id,
    packing_info: { ...source.packing_info!, source_group_id: `src:${sourceDigest}`, diversity_group_id: `div:${diversityDigest}`,
      chunk_id: `ig62_${generation.generation_id!.replaceAll("-", "")}_${String(index + 1).repeat(64)}` },
  }));
  const associations: MixedEvidenceAssociation[] = sources.map(source => ({
    parent_result_revision_id: result.binding.parent_result_revision_id,
    result_source_snapshot_sha256: source.packing_info.source_snapshot_sha256!, source_index: source.index,
    source_vector_id: source.packing_info.chunk_id, source_evidence_revision_id: source.evidence_provenance!.evidence_revision_id!,
    source_evidence_record_sha256: source.evidence_provenance!.evidence_record_sha256!,
    source_content_sha256: source.evidence_provenance!.content_sha256, catalogue_relation: "same_snapshot",
    status: "not_established", reason_code: "reviewed_result_passage_bridge_missing",
    bridge_revision_id: null, bridge_record_sha256: null, claim_identity_sha256: null,
    sample_identity_sha256: null, source_locator_sha256: null,
  }));
  return { answer: "UNREVIEWED_MIXED_PROSE must never be rendered", sources, tokens_used: 0, query_time_ms: 10,
    citation_valid: true, citation_warnings: [], guest_remaining: null, remaining: null,
    answer_mode: "abstention", assessment_scope: "none", scientific_support_status: "not_checked", claim_assessments: [],
    lexical_support_checked: false, retrieval_generation: { ...generation },
    scientific_query: { ...scientificQuery(raw), intent: "mixed" }, scientific_results: [result], scientific_lookup: scientificLookup(),
    input_budget: inputBudget({ status: "not_requested", model: null, request_sha256: null, payload_bytes: null,
      input_tokens: null, max_input_tokens: null, generation_started: null }),
    evidence_packing: packingSummary({ candidate_count: 2, reason_counts: {}, reason_codes: [] }),
    scientific_mixed: { version: "scientific-mixed-evidence/1.1.0", status: "completed", result_count: 1, source_count: 2,
      max_selected_inputs: 4, associations, reason_codes: ["numerical_explanation_not_established", "reviewed_result_passage_bridge_missing"],
      scientific_acceptance: false, independent_support_count: null },
  };
}

export function withdrawnMixedResponse(): AskResponse {
  const response = mixedResponse();
  response.sources = [];
  response.scientific_results = [];
  response.scientific_lookup = scientificLookup({ status: "unavailable", returned_count: 0 });
  response.evidence_packing = packingSummary({ status: "withheld", candidate_count: 0, selected_count: 0,
    source_group_count: 0, diversity_group_count: 0, payload_bytes: null, reason_counts: {}, reason_codes: ["selected_context_withheld"] });
  response.scientific_mixed = { ...response.scientific_mixed!, status: "unavailable", source_count: 0, result_count: 0,
    associations: [], reason_codes: ["retrieval_source_changed"] };
  return response;
}
