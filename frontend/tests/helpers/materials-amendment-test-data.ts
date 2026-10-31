import type { AmendmentDetail, AmendmentList, ProposalDetail, ProposalEvidence, ProposalQueue } from "../../lib/materials-proposal-review";
import { amendmentFields } from "../../lib/materials-proposal-review";
import { access, authority, detail, evidence, queue, quote } from "./materials-proposal-test-data";

export type AmendmentCapture = { capabilities: unknown; queue: ProposalQueue; cases: { run_id: string; pages: ProposalDetail[];
  evidence: Record<string, ProposalEvidence[]>; amendments: { listing: AmendmentList; details: Record<string, AmendmentDetail> } }[] };
// Deliberately synthetic source; the emoji detects Python/JavaScript offset drift.
const blockText = `😀 ${quote}`, id = "d".repeat(64), anchor = { block_id: "B1", start_char: 2, end_char: Array.from(blockText).length, quote };
const author = { kind: "assistant", identity: "Synthetic assistant revision", thread_id: "synthetic-test" };
const summary = { id, parent_run_id: detail.run.run_id, parent_packet_hash: detail.run.packet_sha256, created_at: "2026-10-24T00:00:00Z", author, selected_result_ids: ["I1"] };
const graph = { schema_version: "materials-ner/13", work_id: detail.run.work_id, ...Object.fromEntries(Object.entries(detail.entities).map(([key, rows]) => [key, rows.map(row => row.payload)])), results: detail.results.map(row => row.payload) };
const amendment = { schema: "materials-proposal-amendment/1", amendment_id: id, ...summary, parent_graph_hash: "e".repeat(64), baseline_hash: "f".repeat(64), work_id: detail.run.work_id,
  graph, bundle: { work_id: detail.run.work_id, documents: [{ id: "D1" }], blocks: [{ id: "B1", document_id: "D1", locator: "synthetic:line-1", text: blockText, sha256: "1".repeat(64) }] },
  changes: [{ path: "/results/0/definition/criterion", before: "unspecified", after: "zero_resistance", reason: "Synthetic revision", anchors: [anchor] }],
  reviews: [{ result_id: "I1", fields: Object.fromEntries(amendmentFields.map(field => [field, { disposition: "supported", note: "Synthetic assistant note", anchors: [anchor] }])), holds: ["independent_scientific_review_required"] }],
  affected_result_ids: ["I1"], unreviewed_result_ids: [], validation: {}, source_scope: "Synthetic fixture only", independent_review: false, scientific_acceptance: false, ml_training_eligible: false, canonical_writes: false };
delete (amendment as { id?: string }).id;
const mapping = { schema: "materials-reviewed-tc-mapping/1", amendment_id: id, note: "Synthetic pending mapping", records: [{ source_result_id: "I1", parent_run_id: detail.run.run_id, amendment_id: id,
  source_sample_id: "S1", source_state_id: "ST1", source_protocol_id: "P1", sample_pointer: "/graph/samples/0", state_pointer: "/graph/states/0", protocol_pointer: "/graph/protocols/0", review_pointer: "/reviews/0", source_evidence_pointer: "/graph/results/0/evidence",
  target_table: "material_claims", target_id: null, holds: ["independent_scientific_review_required"], ready_for_canonical_insert: false, scientific_acceptance: false, ml_training_eligible: false }] };
export const syntheticAmendments: AmendmentCapture = { capabilities: access, queue, cases: [{ run_id: detail.run.run_id, pages: [detail], evidence: { I1: [evidence] },
  amendments: { listing: { version: "materials-proposal-amendment/1", items: [summary], authority }, details: { [id]: { amendment, mapping, storage_hash: "2".repeat(64), authority } as unknown as AmendmentDetail } } }] };
