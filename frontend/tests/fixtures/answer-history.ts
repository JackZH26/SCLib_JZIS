/** Synthetic display fixtures only; not a database-authenticated receipt. */
import mixedWire from "./scientific-mixed-http.json";
import type { AnswerEvidenceItem, HistoryDetail } from "@/lib/answer-history";

export const historyId = "11111111-1111-4111-8111-111111111111";
export const historySha = "a".repeat(64);
export function historyDetailFixture(): HistoryDetail {
  const response = structuredClone(mixedWire);
  const { guest_remaining: _guest, remaining: _remaining, ...stored } = response;
  const sources: AnswerEvidenceItem[] = response.sources.map(source => ({
    kind: "source", position: source.index, paper_id: source.paper_id, chunk_id: source.packing_info!.chunk_id,
    content_sha256: source.evidence_provenance.content_sha256,
    member_record_sha256: historySha, chunk_revision_sha256: source.packing_info!.chunk_id.slice(-64),
    vector_sha256: historySha, source_snapshot_sha256: source.packing_info!.source_snapshot_sha256,
    evidence_revision_id: source.evidence_provenance.evidence_revision_id,
    evidence_record_sha256: source.evidence_provenance.evidence_record_sha256,
    parent_result_revision_id: source.evidence_provenance.parent_result_revision_id,
    parent_result_sha256: source.evidence_provenance.parent_result_sha256,
    selection_input_sha256: historySha, selection_generation_pin_sha256: historySha,
    selection_grouping_sha256: historySha, has_evidence_pin: true,
  }));
  const results: AnswerEvidenceItem[] = response.scientific_results.map(({ binding }, index) => ({
    kind: "scientific_result", position: index + 1, paper_id: binding.paper_id, chunk_id: binding.vector_id,
    content_sha256: binding.content_sha256, member_record_sha256: historySha,
    chunk_revision_sha256: binding.vector_id.slice(-64), vector_sha256: historySha,
    source_snapshot_sha256: response.scientific_mixed.associations.find(item => item.parent_result_revision_id === binding.parent_result_revision_id)!.result_source_snapshot_sha256,
    evidence_revision_id: binding.evidence_revision_id, evidence_record_sha256: binding.evidence_record_sha256,
    parent_result_revision_id: binding.parent_result_revision_id, parent_result_sha256: binding.parent_result_sha256,
    selection_input_sha256: historySha, selection_generation_pin_sha256: historySha,
    selection_grouping_sha256: historySha, has_evidence_pin: true,
  }));
  return {
    version: "ask-history-detail/1.0.0", result_current_evidence: {},
    entry: { id: historyId, question: response.scientific_query.raw_query, answer: response.answer,
      sources: response.sources, current_evidence: {}, receipt: { version: "ask-history-receipt-summary/1.0.0", status: "recorded", receipt_sha256: historySha },
      tokens_used: response.tokens_used, latency_ms: response.query_time_ms, language: "auto", created_at: "2026-09-09T00:00:00Z" },
    evidence: { status: "verified", binding_scope: "generation_members", historical_integrity_verified: true,
      scientific_acceptance: false, ml_training_approved: false, public_release_authorized: false, currentness_revalidated: false, reason_codes: [],
      receipt: { version: "ask-answer-evidence/1.0.0", history_id: historyId, record_sha256: historySha,
        request_sha256: historySha, response_sha256: historySha, bindings_sha256: historySha,
        request: { question: response.scientific_query.raw_query, language: "auto", max_sources: response.scientific_mixed.max_selected_inputs },
        response: stored,
        bindings: { version: "ask-answer-evidence/1.0.0", mode: "generation_bound",
          generation_id: response.retrieval_generation.generation_id, activation_event_id: response.retrieval_generation.activation_event_id,
          manifest_sha256: response.retrieval_generation.manifest_sha256, items: [...sources, ...results] } } },
  } as unknown as HistoryDetail;
}

export function legacyHistoryFixture(): HistoryDetail {
  const value = historyDetailFixture();
  value.entry.receipt = { version: "ask-history-receipt-summary/1.0.0", status: "legacy_unpinned", receipt_sha256: null };
  value.evidence = { status: "legacy_unpinned", binding_scope: null, receipt: null, historical_integrity_verified: false,
    scientific_acceptance: false, ml_training_approved: false, public_release_authorized: false,
    currentness_revalidated: false, reason_codes: ["legacy_receipt_not_recorded"] };
  return value;
}

export function emptyHistoryFixture(generation = true): HistoryDetail {
  const value = historyDetailFixture(), receipt = value.evidence.receipt!, response = receipt.response;
  response.sources = []; response.scientific_results = []; response.scientific_query = null;
  response.answer = "No source input was selected. No numerical or scientific conclusion is inferred.";
  response.scientific_mixed = { version: "scientific-mixed-evidence/1.0.0", status: "not_requested",
    result_count: 0, source_count: 0, max_selected_inputs: 0, associations: [], reason_codes: [],
    scientific_acceptance: false, independent_support_count: null };
  response.scientific_lookup = { ...response.scientific_lookup!, status: "not_requested", returned_count: 0, reason_codes: [], has_more: false };
  response.evidence_packing = { ...response.evidence_packing!, status: "not_requested", candidate_count: 0, selected_count: 0,
    source_group_count: 0, diversity_group_count: 0, payload_bytes: null, byte_budget: null, reason_counts: {}, reason_codes: ["packing_not_requested"] };
  receipt.bindings.items = []; receipt.bindings.mode = "no_selected_evidence";
  value.evidence.binding_scope = "no_selected_evidence";
  if (!generation) {
    response.retrieval_generation = { version: "index-read/1.0.0", mode: "legacy_lexical_only", generation_id: null, activation_event_id: null, manifest_sha256: null };
    Object.assign(receipt.bindings, { generation_id: null, activation_event_id: null, manifest_sha256: null });
  }
  value.entry.sources = []; value.entry.answer = response.answer;
  return value;
}
