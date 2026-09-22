import type { AskSource, EvidencePackingSelection, EvidencePackingSummary, RagInputBudgetReport } from "@/lib/api";
import { evidenceProvenance } from "./evidence-provenance";
import { sourceVisibility } from "./material-visibility";

export function packingInfo(patch: Partial<EvidencePackingSelection> = {}): EvidencePackingSelection {
  return { version: "evidence-pack-item/1.0.0", position: 1, chunk_id: "synthetic:chunk-1",
    source_group_id: `src:${"a".repeat(64)}`, source_snapshot_sha256: "b".repeat(64), diversity_group_id: `div:${"c".repeat(64)}`,
    source_group_basis: "source_snapshot", group_basis: "source_snapshot", role_hint: "methods", selection_reason: "source_diversity",
    scientific_acceptance: false, ...patch };
}

export function packedSources(): AskSource[] {
  return [1, 2].map(index => ({ index, paper_id: "synthetic:same-paper", arxiv_id: null, title: "Synthetic source — 原始文献",
    authors_short: "Synthetic author", year: 2026, section: index === 1 ? "Methods" : "Results", snippet: `Synthetic passage ${index}`,
    source_visibility: sourceVisibility(), evidence_provenance: evidenceProvenance({ chunk_kind: "original_passage",
      evidence_revision_id: `00000000-0000-4000-8000-00000000000${index}`, evidence_record_sha256: String(index).repeat(64),
      content_sha256: String(index).repeat(64), parent_result_revision_id: null, parent_result_sha256: null, extraction_version: null, rendering_version: null }),
    packing_info: packingInfo({ position: index, chunk_id: `synthetic:chunk-${index}`, role_hint: index === 1 ? "methods" : "results",
      selection_reason: index === 1 ? "source_diversity" : "complementary_role" }) }));
}

export function packingSummary(patch: Partial<EvidencePackingSummary> = {}): EvidencePackingSummary {
  return { version: "evidence-packing/1.0.0", status: "packed", candidate_count: 3, selected_count: 2, source_group_count: 1,
    diversity_group_count: 1, payload_bytes: 2048, byte_budget: 4096, byte_count_method: "utf8-full-payload/1", max_chunks: 20,
    max_per_source: 3, max_per_work: 3, reason_counts: { payload_budget: 1 }, reason_codes: ["payload_budget_excluded"],
    independent_support_count: null, independence_status: "independence_not_established", scientific_acceptance: false, ...patch };
}

export function inputBudget(patch: Partial<RagInputBudgetReport> = {}): RagInputBudgetReport {
  return { status: "counted", model: "gemini-2.5-flash", profile: "sclib-gemini-text-rag/1.0.0", request_sha256: "d".repeat(64),
    payload_bytes: 2048, byte_limit: 4096, input_tokens: 500, max_input_tokens: 1024, count_method: "provider_count_tokens",
    generation_started: true, scientific_acceptance: false, ...patch };
}
