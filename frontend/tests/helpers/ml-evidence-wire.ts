/** Original native response strings; fixtures contain synthetic source bytes only. */
import fixture from "../fixtures/ml-pilot-evidence-native.delivery20260923r2.wire.json";
import { parseReviewPreflight, type ReviewDocuments, type ReviewDocumentSet } from "@/lib/ml-pilot-reviews";
import { EVIDENCE_MAGIC } from "@/lib/ml-pilot-evidence";
export const evidenceNative = fixture;
export const evidenceDocuments = (() => { const { version: _v, parameters: _p, ...docs } = fixture.upload; return docs as ReviewDocuments; })();
export const evidenceBasis = parseReviewPreflight(fixture.preflight, fixture.actor_user_id, fixture.reference, evidenceDocuments);
export function evidenceParts() {
  const raw = Buffer.from(fixture.frame_base64, "base64"), prefix = Buffer.byteLength(EVIDENCE_MAGIC);
  const length = parseInt(raw.subarray(prefix, prefix + 8).toString(), 16);
  const metadata = JSON.parse(raw.subarray(prefix + 9, prefix + 9 + length).toString());
  let cursor = prefix + 9 + length;
  const files: Record<string, Buffer> = {};
  for (const row of metadata.files) { files[row.key] = raw.subarray(cursor, cursor + row.size_bytes); cursor += row.size_bytes; }
  if (cursor !== raw.length) throw new Error("Invalid native fixture frame");
  return { files, metadata, raw };
}
export function evidenceFiles(FileType: typeof File) {
  const parts = evidenceParts();
  const originals = Object.fromEntries(["selection", "protocol", "reviews", "conclusion"].map(k => [k, new FileType([parts.files[k]], k)])) as ReviewDocumentSet;
  return { originals, canary: new FileType([parts.files.canary], "canary.json"), contexts: [] as File[] };
}
