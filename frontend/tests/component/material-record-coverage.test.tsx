import { webcrypto } from "node:crypto";
import type { ReactNode } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MaterialEnrichment } from "@/components/MaterialEnrichment";
import { getMaterialEnrichment, type MaterialEnrichmentReport, type MaterialRecordCoverage } from "@/lib/api";
import { projectRecordCoverage, recordCoverageFieldRows, recordCoverageReasonLabel, verifiedRecordCoverage } from "@/lib/material-record-coverage";
import { MaterialRecordFieldCoverage } from "@/components/MaterialRecordFieldCoverage";
import { materialRecoveryMetadata } from "@/lib/material-recovery-metadata";
import { expressionCanonical, expressionSha } from "@/lib/source-expressions";
import nativeCoverage from "../fixtures/material-record-coverage-native.synthetic.json";

const linkDestinations = vi.hoisted(() => vi.fn());
// Model the framework's configured route prefix so this test checks delegation
// to AppLink/NextLink rather than a bare anchor. A built deployment owns routing.
vi.mock("next/link", () => ({ default: ({ href, children, prefetch, className }: { href: string; children?: ReactNode; prefetch?: boolean; className?: string }) => {
  linkDestinations(href, prefetch);
  return <a href={`${process.env.NEXT_PUBLIC_BASE_PATH || ""}${href}`} className={className}>{children}</a>;
} }));
vi.mock("@/lib/api", () => ({ getMaterialEnrichment: vi.fn() }));
beforeEach(() => { vi.resetAllMocks(); vi.stubGlobal("crypto", webcrypto); vi.stubEnv("NEXT_PUBLIC_BASE_PATH", ""); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); });
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
  expect(screen.queryByText(/^Inspect .* records \(/)).not.toBeInTheDocument();
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
  expect(screen.queryByText(/^Inspect .* records \(/)).not.toBeInTheDocument();
});

it("opens the verified per-record field view only on demand with named local scrolling", async () => {
  vi.mocked(getMaterialEnrichment).mockResolvedValue(await report());
  render(<MaterialEnrichment materialId="synthetic" />);
  fireEvent.click(await screen.findByText("Inspect field coverage and recovery routes"));
  const summary = screen.getByText("Inspect Measurement method records (5)", { selector: "summary" });
  expect(summary.closest("details")).not.toHaveAttribute("open");
  fireEvent.click(summary);
  const region = screen.getByRole("region", { name: "Scrollable Measurement method record coverage" });
  region.focus(); expect(region).toHaveFocus(); expect(region).toHaveAttribute("tabindex", "0");
  const table = within(region);
  expect(table.getAllByRole("row")).toHaveLength(6);
  expect(table.getAllByText("Retained value")).toHaveLength(4);
  expect(table.getByText("Not applicable")).toBeInTheDocument();
  expect(table.getByRole("link", { name: "paper:0" })).toHaveAttribute("href", "/paper/paper%3A0");
  expect(linkDestinations).toHaveBeenCalledWith("/paper/paper%3A0", false);
  expect(table.getByText("legacy:0")).toBeInTheDocument();
  expect(table.getByText("Computed")).toBeInTheDocument();
  expect(table.getAllByText("No reason supplied in this snapshot.")).toHaveLength(5);
});

it("delegates encoded source IDs to the app router under a configured deployment prefix", async () => {
  vi.stubEnv("NEXT_PUBLIC_BASE_PATH", "/sclib-preview");
  const c = await coverage();
  c.records[0].paper_id = "arxiv:cond-mat/0612431";
  const { coverage_sha256: _, ...body } = c;
  c.coverage_sha256 = await expressionSha(expressionCanonical(body));
  render(<MaterialRecordFieldCoverage coverage={c} field="pressure_gpa" label="Pressure" />);
  fireEvent.click(screen.getByText("Inspect Pressure records (5)", { selector: "summary" }));
  expect(screen.getByRole("link", { name: "arxiv:cond-mat/0612431" })).toHaveAttribute("href", "/sclib-preview/paper/arxiv%3Acond-mat%2F0612431");
  expect(linkDestinations).toHaveBeenCalledWith("/paper/arxiv%3Acond-mat%2F0612431", false);
});

it("uses eligible inventory positions without inventing unchecked rows or joining raw indices", async () => {
  const c = await coverage();
  c.records_total = 8; c.records_unchecked = 3;
  c.records.forEach((record, index) => { record.record_offset = 7 - index; });
  c.fields.forEach(field => { field.counts.unchecked = 3; });
  c.records[0].fields.find(field => field.field === "pressure_gpa")!.reason_codes = ["no_retained_value_in_inspected_record", "future_scope_reason"];
  const { coverage_sha256: _, ...body } = c;
  c.coverage_sha256 = await expressionSha(expressionCanonical(body));
  const original = expressionCanonical(c);
  render(<MaterialRecordFieldCoverage coverage={c} field="pressure_gpa" label="Pressure" />);
  fireEvent.click(screen.getByText("Inspect Pressure records (5)", { selector: "summary" }));
  const table = within(screen.getByRole("region", { name: "Scrollable Pressure record coverage" }));
  expect(table.getByText("Eligible record 8")).toBeInTheDocument();
  expect(table.queryByText("Eligible record 1")).not.toBeInTheDocument();
  expect(table.getAllByRole("row")).toHaveLength(6);
  expect(table.getByText("This inspected record has no retained value.")).toBeInTheDocument();
  expect(table.getByText("Unmapped reason code: future_scope_reason")).toBeInTheDocument();
  expect(screen.getByText(/3 current eligible records are unchecked/)).toHaveTextContent("Their identities and field assessments are not supplied");
  expect(expressionCanonical(c)).toBe(original);
  expect(recordCoverageFieldRows(c, "unsupported_field")).toBeNull();
  expect(recordCoverageReasonLabel("constructor")).toBe("Unmapped reason code: constructor");
});

it("retains source absence and unknown-origin distinctions without fabricating publication or approval", async () => {
  const c = await coverage();
  c.records[0].paper_id = null;
  c.records[0].knowledge_origin = "Unknown"; c.records[0].classification_status = "unknown";
  c.records[0].fields.find(field => field.field === "measurement_method")!.status = "missing";
  c.fields.find(field => field.field === "measurement_method")!.counts = { present: 4, missing: 1, unchecked: 0, not_applicable: 0 };
  c.records[0].fields.find(field => field.field === "pressure_gpa")!.reason_codes = ["no_retained_value_in_inspected_record"];
  const { coverage_sha256: _, ...body } = c;
  c.coverage_sha256 = await expressionSha(expressionCanonical(body));
  render(<MaterialRecordFieldCoverage coverage={c} field="pressure_gpa" label="Pressure" />);
  fireEvent.click(screen.getByText("Inspect Pressure records (5)", { selector: "summary" }));
  const table = within(screen.getByRole("region", { name: "Scrollable Pressure record coverage" }));
  expect(table.getByText("Source ID not supplied")).toBeInTheDocument();
  expect(table.getByText("Unknown")).toBeInTheDocument();
  expect(table.getByText("This inspected record has no retained value.")).toBeInTheDocument();
  expect(table.queryByRole("link", { name: "paper:0" })).not.toBeInTheDocument();
  expect(recordCoverageReasonLabel("method_role_applicability_unresolved")).toBe("The result origin does not establish method applicability.");
});

it("does not expose a forged over-budget inventory through the new record view", async () => {
  const c = await coverage();
  c.records_inspected = 33;
  render(<MaterialRecordFieldCoverage coverage={c} field="pressure_gpa" label="Pressure" />);
  expect(screen.queryByText(/^Inspect Pressure records/)).not.toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});
