// Client-safe verification of a statically published, hash-bound detail file.
import type { SourceHypothesisBrowseCandidate, SourceHypothesisDetail } from "./discovery-source-hypotheses";

function check(value: unknown): asserts value { if (!value) throw new Error("The source-candidate detail could not be verified."); }

export async function verifySourceHypothesisDetail(bytes: Uint8Array, expected: SourceHypothesisBrowseCandidate): Promise<SourceHypothesisDetail> {
  check(bytes.byteLength === expected.detail.bytes && bytes.byteLength <= 1024 * 1024 && /^[a-f0-9]{64}$/.test(expected.detail.sha256));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const hash = Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, "0")).join("");
  check(hash === expected.detail.sha256);
  const detail = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as SourceHypothesisDetail;
  check(detail.schema_version === "source-computed-hypothesis-detail/1.0.0" && detail.catalogue_version === "2026-10-07-source103-v1"
    && detail.dataset_source.doi === "10.24435/materialscloud:qv-bq" && detail.dataset_source.url === "https://archive.materialscloud.org/records/3kbt5-r3n56");
  const row = detail.candidate;
  check(row.id === expected.id && row.source_state === expected.source_state && row.control_state === expected.control_state
    && row.formula === expected.formula && row.route === "geometry_construction" && row.status === "unscored_research_hypothesis" && row.support_grade === 3
    && JSON.stringify(row.composition) === JSON.stringify(expected.composition) && JSON.stringify(row.source_tc) === JSON.stringify(expected.source_tc)
    && JSON.stringify(row.lambda_difference.range) === JSON.stringify(expected.lambda_difference_range));
  for (const value of [row.formal_RPS, row.rank, row.success_probability, row.human_scientific_review, row.experimental_superconductivity,
    row.room_temperature_support, row.quantified_physical_bandwidth, row.quantified_mobile_carrier_density, row.whole_BZ_stability, row.global_thermodynamic_stability]) check(value === null);
  return detail;
}
