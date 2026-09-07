import type { EvidenceProvenance } from "@/lib/api";

/** Synthetic descriptor, never a grant or an experimental result. */
export function evidenceProvenance(patch: Partial<EvidenceProvenance> = {}): EvidenceProvenance {
  return { version: "rag-evidence/1.0.0", chunk_kind: "derived_fact",
    evidence_revision_id: "00000000-0000-4000-8000-000000000001", evidence_record_sha256: "a".repeat(64),
    content_sha256: "b".repeat(64), parent_result_revision_id: "00000000-0000-4000-8000-000000000002",
    parent_result_sha256: "c".repeat(64), extraction_version: "synthetic-extractor/1", rendering_version: "synthetic-renderer/1",
    source_capture_id: null, source_locator: {}, root_status: "unresolved", permission_status: "unresolved",
    currentness: "current", warning_codes: [], support_eligible: false, independent_evidence: false,
    scientific_acceptance: false, ...patch };
}
