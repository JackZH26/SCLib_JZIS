import { webcrypto } from "node:crypto";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MaterialEnrichment } from "@/components/MaterialEnrichment";
import { getMaterialEnrichment, type MaterialEnrichmentReport, type MaterialRecordCoverage } from "@/lib/api";
import { projectRecordCoverage, verifiedRecordCoverage } from "@/lib/material-record-coverage";
import { materialRecoveryMetadata } from "@/lib/material-recovery-metadata";
import { expressionCanonical, expressionSha } from "@/lib/source-expressions";
import nativeCoverage from "../fixtures/material-record-coverage-native.synthetic.json";

vi.mock("@/lib/api", () => ({ getMaterialEnrichment: vi.fn() }));
beforeEach(() => { vi.resetAllMocks(); vi.stubGlobal("crypto", webcrypto); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it("consumes the exact Python-generated coverage DTO, including its versioned limitations and zero pressure", async () => {
  const value = await verifiedRecordCoverage(nativeCoverage, "synthetic-native");
  expect(value).toEqual(nativeCoverage);
  expect(value?.fields.find(row => row.field === "pressure_gpa")?.counts).toEqual({ present: 4, missing: 1, unchecked: 0, not_applicable: 0 });
  const unsupported = structuredClone(nativeCoverage); unsupported.limitations[0] = "scientifically_validated";
  expect(projectRecordCoverage(unsupported, "synthetic-native")).toBeNull();
});
// Mixed synthetic result fixture. The actual saved YIn3 DTO is tested separately
// by the backend; these browser tests do not establish new scientific data.
async function coverage(): Promise<MaterialRecordCoverage> {
  const fields = ["pressure_gpa", "measurement_method", "calculation_method"];
  const records = Array.from({ length: 5 }, (_, i) => ({ record_offset: i, result_id: `legacy:${i}`, record_sha256: String(i + 1).repeat(64), paper_id: `paper:${i}`,
    knowledge_origin: i === 0 ? "Computed" : "Observed", classification_status: "resolved",
    fields: fields.map(field => ({ field, status: (field === "pressure_gpa" ? i === 0 ? "missing" : "present" : field === "measurement_method" ? i === 0 ? "not_applicable" : "present" : i === 0 ? "missing" : "not_applicable") as "missing" | "present" | "not_applicable", reason_codes: [] })) }));
  const body = { version: "materials-record-field-coverage/1.0.0" as const, material_id: "synthetic", records_total: 5, records_inspected: 5, records_unchecked: 0, records_limit: 32 as const, record_denominator: "current_eligible_retained_records" as const,
    records, fields: fields.map(field => ({ field, counts: { present: records.filter(row => row.fields.find(f => f.field === field)!.status === "present").length,
      missing: records.filter(row => row.fields.find(f => f.field === field)!.status === "missing").length, unchecked: 0,
      not_applicable: records.filter(row => row.fields.find(f => f.field === field)!.status === "not_applicable").length }, applicability_unknown: 0 })),
    limitations: ["retained_value_presence_is_not_scientific_acceptance", "missing_retained_value_is_not_source_absence", "unchecked_records_have_no_field_or_applicability_assessment", "method_role_exclusions_do_not_assert_a_joint_sample_or_run"], scientific_acceptance: false as const, database_changed: false as const, ml_training_approved: false as const, public_release: false as const };
  return { ...body, coverage_sha256: await expressionSha(expressionCanonical(body)) };
}
async function report(): Promise<MaterialEnrichmentReport> {
  const c = await coverage();
  return { version: "materials-enrichment/1.0.0", scientific_acceptance: false, database_changed: false, counts: {}, candidates: [], record_coverage: c,
    coverage: [{ material_id: "synthetic", formula: "Synthetic", fields: c.fields.map(row => ({ field: row.field, status: row.counts.present ? "retained_present" : "not_extracted", retained_present: !!row.counts.present, candidate_count: 0, reason_codes: [], routes: [] })) }] };
}
it("shows partial field denominators and separate method roles instead of treating any record as complete", async () => {
  vi.mocked(getMaterialEnrichment).mockResolvedValue(await report());
  render(<MaterialEnrichment materialId="synthetic" />);
  const disclosure = await screen.findByText("Inspect field coverage and recovery routes");
  fireEvent.click(disclosure);
  const table = screen.getByRole("region", { name: "Scrollable field coverage and recovery routes" });
  expect(table).toHaveTextContent("4/5 records with retained values");
  const pressure = within(table).getByText("Pressure").closest("tr")!;
  expect(pressure).toHaveTextContent("1 missing · 0 unchecked · 0 not applicable");
  expect(within(table).getByText("Measurement method").closest("tr")).toHaveTextContent("0 missing · 0 unchecked · 1 not applicable");
  expect(within(table).getByText("Calculation method").closest("tr")).toHaveTextContent("1 missing · 0 unchecked · 4 not applicable");
  expect(screen.getByText(/1 fields fully covered/)).toHaveTextContent("2 fields missing or unchecked");
});
it("keeps old responses readable without claiming a record denominator", async () => {
  const r = await report(); delete r.record_coverage;
  vi.mocked(getMaterialEnrichment).mockResolvedValue(r);
  render(<MaterialEnrichment materialId="synthetic" />);
  expect(await screen.findByText(/an extraction in at least one inspected record/)).toBeInTheDocument();
  expect(screen.queryByText(/fields fully covered/)).not.toBeInTheDocument();
});
it("labels an empty retained inventory as unassessed", async () => {
  const r = await report(), c = r.record_coverage!;
  c.records_total = 0; c.records_inspected = 0; c.records = [];
  c.fields.forEach(row => { row.counts = { present: 0, missing: 0, unchecked: 0, not_applicable: 0 }; });
  const { coverage_sha256: _, ...body } = c;
  c.coverage_sha256 = await expressionSha(expressionCanonical(body));
  vi.mocked(getMaterialEnrichment).mockResolvedValue(r);
  render(<MaterialEnrichment materialId="synthetic" />);
  expect(await screen.findByText(/No current eligible retained records for field coverage/)).toBeInTheDocument();
  expect(screen.queryByText(/fields fully covered/)).not.toBeInTheDocument();
});
it("separately counts fields that are not applicable to every inspected result role", async () => {
  const r = await report(), c = r.record_coverage!, row = c.fields.find(f => f.field === "calculation_method")!;
  c.records[0].knowledge_origin = "Observed";
  c.records[0].fields.find(f => f.field === "measurement_method")!.status = "missing";
  c.fields.find(f => f.field === "measurement_method")!.counts = { present: 4, missing: 1, unchecked: 0, not_applicable: 0 };
  row.counts = { present: 0, missing: 0, unchecked: 0, not_applicable: 5 };
  c.records.forEach(record => { record.fields.find(f => f.field === "calculation_method")!.status = "not_applicable"; });
  const { coverage_sha256: _, ...body } = c;
  c.coverage_sha256 = await expressionSha(expressionCanonical(body));
  vi.mocked(getMaterialEnrichment).mockResolvedValue(r);
  render(<MaterialEnrichment materialId="synthetic" />);
  expect(await screen.findByText(/1 fields not applicable to inspected result roles/)).toHaveTextContent("2 fields missing or unchecked");
});
it("exports only bounded coverage metadata and rejects raw extensions or wrong material", async () => {
  const r = await report();
  expect(materialRecoveryMetadata(r, "synthetic")?.record_coverage).toEqual(r.record_coverage);
  expect(projectRecordCoverage({ ...r.record_coverage, raw_record: { source_text: "PRIVATE" } }, "synthetic")).toBeNull();
  expect(projectRecordCoverage(r.record_coverage, "different")).toBeNull();
});
it("rejects inconsistent counts, duplicate offsets, unknown authority and corrupted proofs", async () => {
  const c = await coverage();
  expect(await verifiedRecordCoverage(c, "synthetic")).toEqual(c);
  const changed = structuredClone(c); changed.fields[0].counts.present = 5;
  expect(projectRecordCoverage(changed, "synthetic")).toBeNull();
  const duplicate = structuredClone(c); duplicate.records[1].record_offset = 0;
  expect(projectRecordCoverage(duplicate, "synthetic")).toBeNull();
  expect(projectRecordCoverage({ ...c, scientific_acceptance: true }, "synthetic")).toBeNull();
  const wrongRole = structuredClone(c); wrongRole.records[0].knowledge_origin = "Unknown";
  expect(projectRecordCoverage(wrongRole, "synthetic")).toBeNull();
  expect(await verifiedRecordCoverage({ ...c, coverage_sha256: "0".repeat(64) }, "synthetic")).toBeNull();
});
it("detaches the verified snapshot before the asynchronous digest", async () => {
  const c = await coverage(), original = structuredClone(c);
  let finish!: () => Promise<void>;
  vi.stubGlobal("crypto", { subtle: { digest: vi.fn((algorithm: string, bytes: Uint8Array) => {
    const captured = new Uint8Array(bytes);
    return new Promise<ArrayBuffer>(resolve => { finish = async () => resolve(await webcrypto.subtle.digest(algorithm, captured)); });
  }) } });
  const pending = verifiedRecordCoverage(c, "synthetic"); c.records[0].result_id = "mutated";
  await finish(); expect(await pending).toEqual(original);
});
it("suppresses an invalid denominator response while retaining the material page context", async () => {
  const r = await report(); r.record_coverage!.coverage_sha256 = "0".repeat(64);
  vi.mocked(getMaterialEnrichment).mockResolvedValue(r);
  render(<MaterialEnrichment materialId="synthetic" />);
  expect(await screen.findByText(/Source recovery is unavailable/)).toBeInTheDocument();
  expect(screen.queryByText(/4\/5 records with retained values/)).not.toBeInTheDocument();
});
