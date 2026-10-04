import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MaterialEnrichment } from "@/components/MaterialEnrichment";
import { getMaterialEnrichment, type MaterialEnrichmentReport } from "@/lib/api";
import { materialRecoveryMetadata } from "@/lib/material-recovery-metadata";

vi.mock("@/lib/api", () => ({ getMaterialEnrichment: vi.fn() }));
const literalSeed = JSON.parse(readFileSync(resolve(process.cwd(), "../api/services/resources/material_enrichment_seed.json"), "utf8"));
const classificationSeed = JSON.parse(readFileSync(resolve(process.cwd(), "../api/services/resources/material_classification_seed.json"), "utf8"));
const literalRows: Record<string, unknown>[] = literalSeed.reports.flatMap((row: { candidates: Record<string, unknown>[] }) => row.candidates);
const classRows: Record<string, unknown>[] = classificationSeed.candidates;
const materialIds = [...new Set(literalRows.map(row => String(row.material_id)))];
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
function report(materialId = materialIds[0]): MaterialEnrichmentReport {
  return {
    version: "materials-enrichment/1.0.0", scientific_acceptance: false, database_changed: false,
    input_sha256: "1".repeat(64), report_sha256: "2".repeat(64), candidates: clone(literalRows.filter(row => row.material_id === materialId)),
    classification_candidates: clone(classRows.filter(row => row.material_id === materialId)),
    candidates_truncated: true, counts: { candidate_facts: 120, candidate_facts_returned: 100, candidate_facts_omitted: 20 },
    inspection_scope: { records_total: 500, records_inspected: 32, records_truncated: true, papers_total: 12, papers_inspected: 8, papers_truncated: true, chunks_inspected: 40, chunks_limit: 40, characters_inspected: 119500, characters_limit: 120000 },
    coverage: [{ material_id: materialId, formula: "Source-scoped test material", fields: [{ field: "tc_criterion", status: "not_extracted", retained_present: false, candidate_count: 0, reason_codes: ["source_assertion_subject_or_scope_requires_review", "retained_record_inventory_not_fully_inspected"], routes: ["source_fulltext_and_supplement"] }], source_coverage: {
      "paper:read": { scope: "bounded_current_chunks_not_complete_source", fulltext_checked: false, supplement_checked: false, indexed_chunks_total: 18, bounded_indexed_chunks_total: 15, chunks_considered: 8, chunks_inspected: 6, chunks_supplied: 5, excluded_chunks_total: 1, omitted_chunks_total: 12, omitted_chunk_reasons: { indexed_chunk_length_outside_bounds: 3, chunk_inspection_limit: 7, character_inspection_limit: 2 }, excluded_chunk_reasons: { derived_source: 1 }, truncated: true, reason_codes: ["chunk_inspection_limit", "character_inspection_limit", "derived_source"] },
      "paper:unsampled": { scope: "bounded_current_chunks_not_complete_source", indexed_chunks_total: null, bounded_indexed_chunks_total: null, chunks_considered: 0, chunks_inspected: 0, chunks_supplied: 0, excluded_chunks_total: 0, omitted_chunks_total: null, truncated: true, reason_codes: ["paper_sampling_limit"] },
    } }],
  };
}
const readBlob = (blob: Blob): Promise<string> => new Promise((resolve, reject) => {
  const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = reject; reader.readAsText(blob);
});

describe("Current bounded recovery metadata and source scope", () => {
  beforeEach(() => vi.resetAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("exports every newly supported source field with raw tokens, roles and spans without exporting arbitrary nested context", () => {
    const id = materialIds[0], body = report(id), base = clone(body.candidates[0]);
    const fields = ["hc1_source_value", "gap_energy_source_value", "gap_ratio_source_value", "electronic_specific_heat_coefficient_source_value", "debye_temperature_source_value", "isotope_effect_exponent", "dtc_dp_source_value", "maximum_applied_pressure_source_value", "meissner_fraction_percent", "transition_width_source_value", "minimum_temperature_k", "t_cdw_k", "t_afm_k", "t_sdw_k"];
    const valueSpan = { char_start: 20, char_end: 28, text_sha256: "3".repeat(64) };
    body.candidates = fields.map((field, index) => ({ ...clone(base), candidate_id: `enrichment:${index.toString(16).padStart(64, "0")}`, field,
      raw_value: "0.590(5) meV", value: "0.590(5) meV", quantity: null,
      subject: { field_role: "reported_property", private_notes: "PRIVATE SOURCE VALUE" },
      source_value: { raw_value: "0.590(5) meV", raw_unit: "meV", raw_uncertainty: "(5)", normalization: "none", role: "reported_property", field_cue: "synthetic test label", qualifiers: ["model_or_calculation_context"], value_span: { ...valueSpan, private_notes: "PRIVATE SOURCE VALUE" }, unit_span: null, cue_span: valueSpan, private_notes: "PRIVATE SOURCE VALUE", raw_record: { secret: "PRIVATE SOURCE VALUE" } },
    }));
    const exported = materialRecoveryMetadata(body, id)!;
    expect(exported.candidates.map(row => row.field)).toEqual(fields);
    expect(exported.returned_window.rejected_candidate_count).toBe(0);
    for (const row of exported.candidates) {
      expect(row.quantity).toBeNull();
      expect(row.subject).toEqual({ field_role: "reported_property" });
      expect(row.source_value).toEqual({ raw_value: "0.590(5) meV", raw_unit: "meV", raw_uncertainty: "(5)", normalization: "none", role: "reported_property", field_cue: "synthetic test label", qualifiers: ["model_or_calculation_context"], value_span: valueSpan, unit_span: null, cue_span: valueSpan });
      expect(row.scientific_acceptance).toBe(false);
    }
    expect(JSON.stringify(exported)).not.toContain("PRIVATE SOURCE VALUE");
  });

  it("keeps each paper’s actual budget and exclusions distinct, with unknown unsampled counts", async () => {
    vi.mocked(getMaterialEnrichment).mockResolvedValue(report());
    render(<MaterialEnrichment materialId={materialIds[0]} />);
    const heading = await screen.findByText("Per-paper inspection scope (2)");
    expect(heading.closest("details")).not.toHaveAttribute("open");
    fireEvent.click(heading);
    const sampled = screen.getByText("paper:read").closest("li")!, omitted = screen.getByText("paper:unsampled").closest("li")!;
    expect(sampled).toHaveTextContent("Shared chunk budget reached (7 chunks)");
    expect(sampled).toHaveTextContent("Shared character budget reached; whole chunk omitted (2 chunks)");
    expect(sampled).toHaveTextContent("Derived text is excluded from original-source recovery (1 chunk)");
    expect(omitted).toHaveTextContent("Not sampled · paper limit");
    expect(within(omitted).getByText("Indexed").nextElementSibling).toHaveTextContent("Not inspected");
    expect(within(omitted).getByText("Omitted").nextElementSibling).toHaveTextContent("Not inspected");
    expect(within(omitted).getByText("Read").nextElementSibling).toHaveTextContent("0");
    expect(screen.getByText(/Reading or supplying a chunk does not mean the full paper or supplement was checked/)).toBeInTheDocument();
    expect(screen.getByText("Statement subject or scope needs review").closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText("Some retained records were outside this sample")).toBeInTheDocument();
  });

  it("preserves all 39 real seed identities, scientific quantities and full retained refs without promoting the projection", () => {
    const exported = materialIds.flatMap(id => materialRecoveryMetadata(report(id), id)!.candidates);
    expect(exported).toHaveLength(39);
    expect(exported.map(row => row.candidate_id).sort()).toEqual(literalRows.map(row => row.candidate_id).sort());
    for (const row of exported) {
      const original = literalRows.find(item => item.candidate_id === row.candidate_id)!;
      expect(row.retained_result_refs).toEqual(original.retained_result_refs);
      expect(row.disposition).toBe("pending"); expect(row.scientific_acceptance).toBe(false); expect(row.material_state_reviewed).toBe(false);
      const quantity = original.quantity as Record<string, unknown> | null;
      if (quantity) for (const key of ["raw_value", "raw_unit", "value", "lower", "upper", "uncertainty", "relation", "status", "unit"]) {
        if (Object.hasOwn(quantity, key)) expect((row.quantity as Record<string, unknown>)[key]).toEqual(quantity[key]);
      }
      expect((row.source as Record<string, unknown>).content_sha256).toBe((original.source as Record<string, unknown>).content_sha256);
    }
    const classId = String(classRows[0].material_id), body = materialRecoveryMetadata(report(classId), classId)!;
    expect(body.classification_candidates).toHaveLength(2);
    expect(body.classification_candidates.map(row => row.candidate_id)).toEqual(classRows.map(row => row.candidate_id));
    for (const row of body.classification_candidates) {
      const original = classRows.find(item => item.candidate_id === row.candidate_id)!;
      expect(row.claim).toEqual(original.claim); expect(row.retained_result_refs).toEqual(original.retained_result_refs);
      expect((row.subject as Record<string, unknown>).binding_proposal).toEqual((original.subject as Record<string, unknown>).binding_proposal);
    }
    expect(body).toMatchObject({ scientific_acceptance: false, database_changed: false, public_release: false, disposition: "pending" });
    expect(body.inspection_scope).toMatchObject({ records_total: 500, records_inspected: 32, chunks_limit: 40 });
    expect(body.counts).toMatchObject({ candidate_facts_omitted: 20 });
    expect(body.source_coverage["paper:unsampled"].omitted_chunks_total).toBeNull();
  });

  it("retains table-unit location and separate header/label pins without caption text", () => {
    const body = report(), row = body.candidates[0];
    const pin = { char_start: 2, char_end: 5, text_sha256: "a".repeat(64) };
    row.field = "debye_temperature_source_value";
    row.raw_value = row.value = "501"; row.quantity = null;
    row.source_value = { raw_value: "501", raw_unit: "K", normalization: "none", unit_basis: "table_row_label",
      value_span: pin, unit_span: pin, cue_span: pin };
    row.table_binding = { version: "captured-table-binding/1.0.0", header_span: pin, label_span: pin,
      caption_span: { ...pin, private_notes: "PRIVATE_TABLE_SENTINEL" }, caption: "PRIVATE_TABLE_SENTINEL" };
    const output = materialRecoveryMetadata(body, materialIds[0])!;
    expect(output.candidates[0].source_value).toMatchObject({ raw_value: "501", raw_unit: "K", unit_basis: "table_row_label" });
    expect(output.candidates[0].table_binding).toEqual({ version: "captured-table-binding/1.0.0", header_span: pin, label_span: pin, caption_span: pin });
    expect(JSON.stringify(output)).not.toContain("PRIVATE_TABLE_SENTINEL");
  });

  it("allowlists recursively rather than dumping private text from real structured quantities, bindings or record references", () => {
    const id = materialIds.find(id => literalRows.some(row => row.material_id === id && row.field === "composition_identity"))!;
    const body = report(id), tc = body.candidates.find(row => row.quantity)!;
    const secret = "PRIVATE_EXPORT_SENTINEL";
    Object.assign(body, { private_notes: secret, source_excerpt: secret, raw_record: { formula: secret } });
    Object.assign(tc, { private_notes: secret, evidence_text: secret, source_excerpt: secret, raw_record: { source_locator: secret } });
    Object.assign(tc.quantity as object, { source_context: { note: secret }, private_notes: secret });
    Object.assign(tc.source as object, { evidence_text: secret, source_excerpt: secret, private_notes: secret });
    Object.assign((tc.source as Record<string, unknown>).locator as object, { private_notes: secret });
    Object.assign(tc.subject as object, { private_notes: secret, raw_record: { formula: secret } });
    Object.assign((tc.retained_result_refs as object[])[0], { raw_record: { paper_id: secret } });
    const composition = body.candidates.find(row => row.field === "composition_identity")!;
    Object.assign(composition.raw_value as object, { private_notes: secret });
    const occupancy = body.candidates.find(row => row.field === "site_occupancies")!;
    Object.assign((occupancy.raw_value as Record<string, unknown>).fractions_raw as object, { private_notes: secret });
    Object.assign(body.coverage[0].source_coverage!["paper:read"], { private_notes: secret, source_excerpt: secret });
    const exported = materialRecoveryMetadata(body, id)!;
    const json = JSON.stringify(exported);
    expect(json).not.toContain(secret);
    expect(json).not.toMatch(/"(?:private_notes|evidence_text|source_excerpt|raw_record|source_context)"/);
    const exportedOccupancy = exported.candidates.find(row => row.field === "site_occupancies")!;
    expect((exportedOccupancy.raw_value as Record<string, unknown>).fractions_raw).toEqual({ Fe: "0.953(4)", Pt: "0.047(4)" });
    expect((exported.candidates.find(row => row.field === "composition_identity")!.raw_value as Record<string, unknown>).refined_formula_raw).toBe((composition.raw_value as Record<string, unknown>).refined_formula_raw);
    expect(exported.returned_window.literal_exported).toBe(body.candidates.length);
  });

  it("refuses material mismatches and promoted candidates, and rejects credential-bearing provenance URLs", () => {
    expect(materialRecoveryMetadata(report(), "other-material")).toBeNull();
    const id = materialIds[0], body = report(id);
    body.candidates[0].scientific_acceptance = true;
    (body.candidates[1].source as Record<string, unknown>).source_url = "https://user:private@arxiv.org/html/0912.2752v2";
    const projected = materialRecoveryMetadata(body, id)!;
    expect(projected.returned_window.rejected_candidate_count).toBe(1);
    expect(projected.candidates.some(row => row.candidate_id === body.candidates[0].candidate_id)).toBe(false);
    expect(JSON.stringify(projected)).not.toContain("user:private");
    body.scientific_acceptance = true as false;
    expect(materialRecoveryMetadata(body, id)).toBeNull();
  });

  it("downloads only the current response and removes the old-material download during pending navigation", async () => {
    const blobs: Blob[] = [];
    const originalCreate = Object.getOwnPropertyDescriptor(URL, "createObjectURL"), originalRevoke = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn((blob: Blob) => { blobs.push(blob); return "blob:recovery"; }) });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementationOnce(() => { throw new Error("Synthetic download failure"); }).mockImplementation(() => {});
    try {
      const a = materialIds[0], b = materialIds[1];
      let resolveB!: (value: MaterialEnrichmentReport) => void;
      vi.mocked(getMaterialEnrichment).mockResolvedValueOnce(report(a)).mockImplementationOnce(() => new Promise(resolve => { resolveB = resolve; }));
      const view = render(<MaterialEnrichment materialId={a} />);
      fireEvent.click(await screen.findByRole("button", { name: "Download recovery metadata (JSON)" }));
      expect(screen.getByText("Metadata download is unavailable for this request.")).toBeInTheDocument();
      expect(document.querySelector('a[href="blob:recovery"]')).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: "Download recovery metadata (JSON)" }));
      expect(screen.queryByText("Metadata download is unavailable for this request.")).not.toBeInTheDocument();
      const first = JSON.parse(await readBlob(blobs[1]));
      expect(first.material.material_id).toBe(a);
      expect(first.candidates.map((row: Record<string, unknown>) => row.candidate_id)).toEqual(literalRows.filter(row => row.material_id === a).map(row => row.candidate_id));
      const candidateId = String(report(a).candidates[0].candidate_id);
      expect(screen.getByText(candidateId).closest("details")).not.toHaveAttribute("open");
      view.rerender(<MaterialEnrichment materialId={b} />);
      expect(screen.queryByRole("button", { name: "Download recovery metadata (JSON)" })).not.toBeInTheDocument();
      expect(screen.queryByText(candidateId)).not.toBeInTheDocument();
      expect(blobs).toHaveLength(2);
      await act(async () => resolveB(report(b)));
      fireEvent.click(await screen.findByRole("button", { name: "Download recovery metadata (JSON)" }));
      const second = JSON.parse(await readBlob(blobs[2]));
      expect(second.material.material_id).toBe(b);
      expect(second.candidates.every((row: Record<string, unknown>) => row.material_id === b)).toBe(true);
      expect(second.candidates.some((row: Record<string, unknown>) => row.candidate_id === candidateId)).toBe(false);
      await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalled());
    } finally {
      if (originalCreate) Object.defineProperty(URL, "createObjectURL", originalCreate); else delete (URL as unknown as Record<string, unknown>).createObjectURL;
      if (originalRevoke) Object.defineProperty(URL, "revokeObjectURL", originalRevoke); else delete (URL as unknown as Record<string, unknown>).revokeObjectURL;
    }
  });
});
