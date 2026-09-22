import { File as NodeFile } from "node:buffer";
import { webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MlPilotQualityReport, pilotEffortText } from "@/components/MlPilotQualityReport";
import { parseEvidenceSnapshot, prepareEvidence } from "@/lib/ml-pilot-evidence";
import { PILOT_AVAILABILITY, PILOT_FIELDS, preparePilotQualityReport } from "@/lib/ml-pilot-quality";
import { evidenceBasis, evidenceFiles, evidenceNative } from "../helpers/ml-evidence-wire";
import { qualityBasis, qualityFiles, qualityFixture, qualityProof } from "../helpers/ml-quality-wire";
import { sha } from "../helpers/ml-review-wire";

const fileType = NodeFile as unknown as typeof File, scroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollIntoView");
beforeEach(() => { vi.stubGlobal("crypto", webcrypto); Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: vi.fn() }); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals();
  if (scroll) Object.defineProperty(HTMLElement.prototype, "scrollIntoView", scroll); else Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView"); });
async function richReport() { const f = qualityFiles(fileType); return preparePilotQualityReport(f.canary, f.conclusion, qualityBasis, qualityProof); }

describe("bound pilot field presentation", () => {
  it("uses the genuine native byte proof and original files for an honest zero-result report", async () => {
    const f = evidenceFiles(fileType), upload = await prepareEvidence(evidenceNative.reference, evidenceBasis, f.originals, f.canary, []);
    const proof = parseEvidenceSnapshot(evidenceNative.complete, evidenceNative.actor_user_id, evidenceNative.reference, evidenceBasis, upload);
    const value = await preparePilotQualityReport(f.canary, f.originals.conclusion, evidenceBasis, proof);
    expect(value.selected).toBe(60); expect(value.atomicResults).toBe(0); expect(value.fields).toHaveLength(11);
    expect(value.effort.recordedMinutes).toBeNull(); expect(value.fields.every(f => f.action === "defer" && f.candidateRecovered === 0)).toBe(true);
    render(<MlPilotQualityReport value={value} />);
    expect(screen.getByText(/No atomic results were recovered/)).toBeInTheDocument();
    expect(screen.getByText(/not 100% missingness/)).toBeInTheDocument();
    expect(screen.getByText("Not established")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Pilot field recovery and curation effort" })).toHaveFocus();
  });
  it("preserves event versus result denominators, all statuses, partial timing and recorded proposals", async () => {
    const value = await richReport();
    expect([value.selected, value.reviewRecords, value.atomicResults, value.associations]).toEqual([60, 66, 9, 10]);
    expect(value.outcomes.recovered).toBe(9); expect(value.outcomes.unresolved).toBe(1);
    expect(value.effort).toEqual({ recordedMinutes: 2.5, recordedRecords: 2, totalRecords: 66 });
    expect(value.fields.find(f => f.field === "source_locator")!.effort.recordedMinutes).toBe(1.25);
    expect(value.fields.find(f => f.field === "method")!.effort).toEqual({ recordedMinutes: 0, recordedRecords: 1, totalRecords: 66 });
    expect(value.fields.find(f => f.field === "tc_value")!.effort.recordedMinutes).toBeNull();
    expect(value.fields.find(f => f.field === "source_revision")!.candidateRecovered).toBe(10); // > 9 distinct result IDs, legitimately.
    expect(value.fields.find(f => f.field === "tc_value")!.availability.not_applicable).toBe(1);
    expect(PILOT_AVAILABILITY.every(k => value.fields.find(f => f.field === "structure_identity")!.availability[k] > 0)).toBe(true);
    expect(value.decisions).toEqual({ accepted: 8, pending: 1, rejected: 0 });
    expect(value.errors).toEqual({ source: 1, normalization: 1, state_association: 1, extraction: 1 });
    expect(value.fields.map(f => f.action)).toEqual(PILOT_FIELDS.map((_, i) => ["keep", "narrow", "defer"][i % 3]));
  });
  it("shows escaped private rationale, disjoint units and frozen group denominators without network or approval", async () => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher); const storage = vi.spyOn(Storage.prototype, "setItem");
    const value = await richReport(); const { container } = render(<MlPilotQualityReport value={value} />);
    expect(screen.getByText(/SYNTHETIC <script>/)).toBeInTheDocument(); expect(container.querySelectorAll("script,img,a,iframe")).toHaveLength(0);
    expect(screen.getByText(/website does not choose, endorse or apply/)).toBeInTheDocument();
    const table = within(screen.getByRole("region", { name: "Priority field recovery and proposals" })).getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(12);
    const method = within(table).getByRole("row", { name: /^Method / }); expect(within(method).getByText(/0 recorded min · 1\/66/)).toBeInTheDocument();
    const tc = within(table).getByRole("row", { name: /^Tc value / }); expect(within(tc).getByText(/Not recorded · 0\/66/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Frozen-group recovery and effort"));
    fireEvent.change(screen.getByLabelText("Frozen selection group"), { target: { value: "1" } });
    const group = within(screen.getByRole("region", { name: "Selected group field recovery" })); expect(group.getAllByText("0/40")).toHaveLength(11);
    fireEvent.change(screen.getByLabelText("Group dimension"), { target: { value: "source_class" } });
    expect(screen.getByLabelText("Frozen selection group")).toHaveValue("0");
    expect(screen.getByText(/Source class: synthetic-table. Selected events: 30/)).toBeInTheDocument();
    expect(fetcher).not.toHaveBeenCalled(); expect(storage).not.toHaveBeenCalled();
  });
  it.each(["canary", "conclusion", "proof", "limit", "abort"])("refuses an unbound or unavailable original: %s", async mode => {
    const f = qualityFiles(fileType), proof = structuredClone(qualityProof), c = new AbortController();
    if (mode === "canary") f.canary = new NodeFile(["changed"], "canary") as unknown as File;
    if (mode === "conclusion") f.conclusion = new NodeFile(["changed"], "conclusion") as unknown as File;
    if (mode === "proof") proof.canarySha256 = "f".repeat(64);
    if (mode === "limit") Object.defineProperty(f.canary, "size", { value: 32 * 1024 * 1024 + 1 });
    if (mode === "abort") c.abort();
    await expect(preparePilotQualityReport(f.canary, f.conclusion, qualityBasis, proof, c.signal)).rejects.toThrow();
  });
  it.each(["version", "authority", "approval", "counts", "independence", "statuses", "status_sum", "candidate_denominator", "timing_missing", "timing_count",
    "atomic_denominator", "group_count", "group_field", "group_unknown", "duplicate_action", "action", "recommendation", "extra_action"])("rejects malformed displayed statistics even in an explicitly synthetic resealed parser test: %s", async mode => {
    // These self-authored pins/proofs do NOT pass authenticated server replay.
    const bundle = JSON.parse(Buffer.from(qualityFixture.canary_base64, "base64").toString()), conclusion = JSON.parse(Buffer.from(qualityFixture.conclusion_base64, "base64").toString());
    const a = bundle.accounting;
    if (mode === "version") bundle.version = "ml08-canary/1.1.0";
    if (mode === "authority") bundle.authority.scientific_acceptance = true;
    if (mode === "approval") a.ready_for_final_human_signoff = true;
    if (mode === "counts") a.counts.selected_candidates = 59;
    if (mode === "independence") a.counts.independent_work_count = 9;
    if (mode === "statuses") a.atomic_field_missingness.counts.pressure.invented = 1;
    if (mode === "status_sum") a.atomic_field_missingness.counts.pressure.ambiguous = 8;
    if (mode === "candidate_denominator") a.candidate_field_recovery.pressure.selected_candidate_denominator = 9;
    if (mode === "timing_missing") a.curation_time_by_field.tc_value.recorded_minutes = 1;
    if (mode === "timing_count") a.curation_time.records_with_timing = true;
    if (mode === "atomic_denominator") a.atomic_field_missingness.denominator = 60;
    if (mode === "group_count") delete a.time_and_denominators_by_group.family["synthetic-family-b"];
    if (mode === "group_field") a.time_and_denominators_by_group.family["synthetic-family-b"].candidates_with_any_reported_field.source_revision = 1;
    if (mode === "group_unknown") a.time_and_denominators_by_group.formula_guessed = {};
    if (mode === "duplicate_action") conclusion.field_actions[1] = conclusion.field_actions[0];
    if (mode === "action") conclusion.field_actions[0].action = "train_now";
    if (mode === "recommendation") conclusion.recommendation = "go";
    if (mode === "extra_action") conclusion.field_actions[0].approved = true;
    const raw = JSON.stringify(bundle), basis = structuredClone(qualityBasis), proof = structuredClone(qualityProof);
    basis.declared_canary_sha256 = proof.canarySha256 = sha(raw); conclusion.canary_bundle_sha256 = proof.canarySha256;
    const final = JSON.stringify(conclusion); basis.input_pins.conclusion_file_sha256 = sha(final);
    await expect(preparePilotQualityReport(new NodeFile([raw], "canary") as unknown as File, new NodeFile([final], "conclusion") as unknown as File, basis, proof)).rejects.toThrow();
  });
  it("distinguishes missing, zero and rounded measured effort", () => {
    expect(pilotEffortText({ recordedMinutes: null, recordedRecords: 0, totalRecords: 66 })).toMatch(/^Not recorded/);
    expect(pilotEffortText({ recordedMinutes: 0, recordedRecords: 1, totalRecords: 66 })).toMatch(/^0 recorded min/);
    expect(pilotEffortText({ recordedMinutes: .1 + .2, recordedRecords: 2, totalRecords: 66 })).toMatch(/^≈ 0.3 recorded min/);
  });
  it("pins the immutable pure-kernel fixture, generator and packaged source inventory", () => {
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-pilot-quality-synthetic.batch76-final.json")))).toBe("4324bdf073bfd2d3f7b922e76f04a000bbcd84927bdd8e38df66c2639ae786e2");
    expect(qualityFixture.fixture_notice).toContain("no authenticated HTTP");
    expect(sha(readFileSync(resolve(process.cwd(), "..", "scripts/tests/test_ml_pilot_quality_fixture.py")))).toBe(qualityFixture.capture_test_sha256);
    for (const [name, pin] of Object.entries(qualityFixture.canary_implementation.files)) expect(sha(readFileSync(resolve(process.cwd(), "..", "api/services", name)))).toBe(pin);
  });
});
