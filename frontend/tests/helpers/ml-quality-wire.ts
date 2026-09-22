/** Pure-kernel synthetic presentation data, explicitly not authenticated HTTP. */
import rich from "../fixtures/ml-pilot-quality-synthetic.batch76-final.json";
import type { EvidenceSnapshot } from "@/lib/ml-pilot-evidence";
import type { ReviewBasis } from "@/lib/ml-pilot-reviews";
import { evidenceBasis, evidenceNative } from "./ml-evidence-wire";
export const qualityFixture = rich;
export const qualityBasis: ReviewBasis = { ...evidenceBasis,
  input_pins: rich.document_projection.input_pins, selection_sha256: rich.document_projection.selection_sha256,
  review_log_sha256: rich.document_projection.review_log_sha256, review_record_count: rich.document_projection.review_record_count,
  recorded_recommendation: "narrow", declared_canary_sha256: rich.canary_check.canary_sha256 };
// Only the genuine native zero-context fixture tests complete account+HTTP binding.
// This explicit adapter exercises presentation of richer pure-kernel output.
export const qualityProof: EvidenceSnapshot = { account: JSON.parse(evidenceNative.complete).account_snapshot,
  contextCount: rich.canary_check.context_file_count, contextBytes: rich.canary_check.context_bytes_hashed,
  canarySha256: rich.canary_check.canary_sha256, implementationSha256: rich.canary_check.implementation_sha256,
  inputSha256: "a".repeat(64) };
export const qualityFiles = (FileType: typeof File) => ({ canary: new FileType([Buffer.from(rich.canary_base64, "base64")], "synthetic-canary.json"),
  conclusion: new FileType([Buffer.from(rich.conclusion_base64, "base64")], "synthetic-conclusion.json") });
