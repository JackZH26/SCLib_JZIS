import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ScientificQueryNotice } from "@/components/ScientificQueryNotice";
import { displayQuantity, knownScientificLookup, knownScientificQuery, knownScientificResults } from "@/lib/scientific-query";
import { generation, quantity, scientificLookup, scientificQuery, scientificResult } from "../fixtures/scientific-query";

function show({ query = scientificQuery(), lookup = scientificLookup(), results = [scientificResult()], pin = generation } = {}) {
  return render(<ScientificQueryNotice query={query} lookup={lookup} results={results} generation={pin} rawQuery={query.raw_query} />);
}

describe("scientific query display contract", () => {
  it("shows source-linked quantities with explicit unreviewed scope and English-owned copy", () => {
    show();
    expect(screen.getByLabelText("Search scientific query")).toHaveTextContent("Original query: Tc > 20 K for MgB₂");
    expect(screen.getByLabelText("Interpreted formulas")).toHaveTextContent("MgB₂ → MgB2 (notation match only; not sample or phase identity)");
    expect(screen.getByLabelText("Interpreted conditions")).toHaveTextContent("Tc: > 20 K");
    expect(screen.getByText("39 K")).toBeVisible();
    expect(screen.getByText("Not reported; not assumed ambient")).toBeVisible();
    expect(screen.getByText("Observed · primary source role · classification resolved")).toBeVisible();
    expect(screen.getByRole("link", { name: "Source paper · extraction 1" })).toHaveAttribute("href", "/paper/synthetic%3AMgB2");
    expect(screen.getByText(/not an original quotation, independent confirmation/)).toBeVisible();
    expect(screen.queryByText(/confidence|probability/i)).not.toBeInTheDocument();
  });

  it("uses code-point offsets for an emoji and preserves Chinese user content", () => {
    const query = scientificQuery("🔬 MgB₂ 的临界温度是多少？");
    query.language = "mixed";
    expect(query.formulas[0].start).toBe(2);
    expect(knownScientificQuery(query, query.raw_query)).toEqual(query);
    show({ query });
    expect(screen.getByLabelText("Search scientific query")).toHaveTextContent(query.raw_query);
    expect(screen.getByRole("heading", { name: "Search query interpretation" })).toBeVisible();
    expect(knownScientificQuery({ ...query, formulas: [{ ...query.formulas[0], start: 3 }] })).toBeNull();
  });

  it("keeps unsupported isotope/state clauses and clarification visible, with no numeric fallback", () => {
    const raw = "Tc of 13C at ambient pressure", query = scientificQuery(raw);
    query.status = "clarification_required";
    query.unresolved_clauses = [{ raw_text: "13C", start: 6, end: 9, reason_code: "isotope_not_supported" }];
    query.clarification_questions = ["Please specify a supported formula without isotope ambiguity."];
    show({ query, lookup: scientificLookup({ status: "clarification_required", returned_count: 0 }), results: [] });
    expect(screen.getByRole("status")).toHaveTextContent("Unresolved conditions have not been silently dropped");
    expect(screen.getByText(/“13C” — isotope not supported/)).toBeVisible();
    expect(screen.getByText("Please specify a supported formula without isotope ambiguity.")).toBeVisible();
    expect(screen.queryByText("39 K")).not.toBeInTheDocument();
  });

  it("preserves interval, upper/lower bounds, uncertainty and schema assumptions", () => {
    expect(displayQuantity(quantity({ relation: "lt", value: null, upper: 100 }))).toBe("< 100 K");
    expect(displayQuantity(quantity({ relation: "ge", value: null, lower: 20 }))).toBe("≥ 20 K");
    expect(displayQuantity(quantity({ relation: "interval", value: null, lower: 20, upper: 30, approximate: true }))).toBe("≈ 20–30 K");
    expect(displayQuantity(quantity({ value: 1234.5, uncertainty: 0.5, uncertainty_interpretation: "unspecified", unit_basis: "field_schema_assumption" })))
      .toBe("1,234.5 ± 0.5 (interpretation unspecified) K (unit assumed from field schema)");
    expect(displayQuantity(quantity({ status: "invalid", value: 100 }))).toBe("Invalid or unresolved");
  });

  it("does not turn computed, cited or non-detection fields into positive evidence", () => {
    const row = scientificResult();
    row.result.result_classification = { knowledge_origin: "Computed", source_role: "cited", classification_status: "resolved" };
    row.result.outcome_state = "not_detected";
    row.result.tc = quantity({ status: "invalid", relation: "unreported", value: null });
    row.result.minimum_temperature = quantity({ value: 2 });
    show({ results: [row] });
    expect(screen.getByText("Computed · cited source role · classification resolved")).toBeVisible();
    expect(screen.getByText("No transition reported within stated conditions")).toBeVisible();
    expect(screen.getByText("Tc field (not positive evidence)")).toBeVisible();
    expect(screen.getByText(/detection adequacy has not been verified/)).toBeVisible();
    expect(screen.getByText("2 K")).toBeVisible();
    expect(screen.getByText("resistivity")).toBeVisible();
    expect(screen.queryByText("Positive report (unreviewed)")).not.toBeInTheDocument();
  });

  it.each(["explicit_ambient_reference", "explicit", "field_schema_assumption"] as const)("labels explicit ambient with %s units as a reference, not a measured zero", unit_basis => {
    const row = scientificResult();
    row.result.pressure = { ...quantity({ value: 0, unit: "GPa", unit_basis }), pressure_state: "explicit_ambient" };
    show({ results: [row] });
    expect(screen.getByText("Explicit ambient reference (not a measured zero)")).toBeVisible();
    expect(screen.queryByText("0 GPa")).not.toBeInTheDocument();
  });

  it.each([false, 0, "", [], {}, { ...scientificQuery(), version: "future" }, { ...scientificQuery(), scientific_acceptance: true }])("fails closed for unknown interpretation %j", query => {
    render(<ScientificQueryNotice query={query} rawQuery={scientificQuery().raw_query} lookup={scientificLookup()} results={[scientificResult()]} generation={generation} />);
    expect(screen.getByRole("status")).toHaveTextContent("No interpreted conditions or numerical records are displayed");
    expect(screen.queryByText("39 K")).not.toBeInTheDocument();
  });

  it("does not display an interpretation for a different raw query", () => {
    render(<ScientificQueryNotice query={scientificQuery()} rawQuery="Current query" />);
    expect(screen.queryByText(/Original query:/)).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("inconsistent with this query");
  });

  it.each(["scientific_acceptance", "ml_training_eligible", "detection_adequacy_verified"])("rejects forged %s rather than showing a verified result", field => {
    const row = scientificResult();
    Object.assign(row.result, { [field]: true });
    expect(knownScientificResults([row], scientificLookup(), generation, scientificQuery())).toBeNull();
    show({ results: [row] });
    expect(screen.getByRole("status")).toHaveTextContent("numerical records are withheld");
    expect(screen.queryByText("39 K")).not.toBeInTheDocument();
  });

  it.each([true, NaN, Infinity, -1])("rejects malformed or negative parsed numeric values %j", value => {
    const row = scientificResult();
    Object.assign(row.result.tc, { value });
    expect(knownScientificResults([row], scientificLookup(), generation, scientificQuery())).toBeNull();
  });

  it.each([
    { generation_id: "55555555-5555-5555-5555-555555555555" },
    { activation_event_id: "55555555-5555-5555-5555-555555555555" },
    { manifest_sha256: "0".repeat(64) }, { parent_result_sha256: "invalid" },
    { vector_id: `ig62_${"5".repeat(32)}_${"c".repeat(64)}` },
    { association_scope: "original_support" }, { evidence_revision_id: null },
  ])("withholds malformed or wrong-generation result binding %j", patch => {
    const row = scientificResult();
    Object.assign(row.binding, patch);
    expect(knownScientificResults([row], scientificLookup(), generation, scientificQuery())).toBeNull();
  });

  it("rejects repeated extraction parents, count mismatch, extra keys and legacy-generation results", () => {
    const row = scientificResult(), query = scientificQuery(), lookup = scientificLookup();
    expect(knownScientificResults([row, row], scientificLookup({ returned_count: 2 }), generation, query)).toBeNull();
    expect(knownScientificResults([], lookup, generation, query)).toBeNull();
    expect(knownScientificResults([{ ...row, approved: true }], lookup, generation, query)).toBeNull();
    expect(knownScientificResults([row], lookup, { ...generation, mode: "legacy_lexical_only" }, query)).toBeNull();
    expect(knownScientificResults([row], lookup, generation, { ...query, status: "clarification_required" })).toBeNull();
  });

  it("rejects inconsistent pressure states instead of inventing ambient conditions", () => {
    const row = scientificResult();
    row.result.pressure.pressure_state = "explicit_ambient";
    expect(knownScientificResults([row], scientificLookup(), generation, scientificQuery())).toBeNull();
  });

  it("rejects contradictory unreported values and uncertainty added to a bound", () => {
    const row = scientificResult();
    row.result.tc.status = "unreported";
    expect(knownScientificResults([row], scientificLookup(), generation, scientificQuery())).toBeNull();
    row.result.tc = quantity({ relation: "lt", value: null, upper: 100, uncertainty: 1, uncertainty_interpretation: "unspecified" });
    expect(knownScientificResults([row], scientificLookup(), generation, scientificQuery())).toBeNull();
    row.result.tc = quantity({ uncertainty: 1, uncertainty_interpretation: null });
    expect(knownScientificResults([row], scientificLookup(), generation, scientificQuery())).toBeNull();
  });

  it("accepts the current 100-character warning bound and never accepts more than 20 reports", () => {
    const row = scientificResult();
    row.result.warning_codes = ["a".repeat(100)];
    expect(knownScientificResults([row], scientificLookup(), generation, scientificQuery())).toEqual([row]);
    row.result.warning_codes = ["a".repeat(101)];
    expect(knownScientificResults([row], scientificLookup(), generation, scientificQuery())).toBeNull();
    expect(knownScientificResults(Array(21).fill(scientificResult()), scientificLookup({ returned_count: 21 }), generation, scientificQuery())).toBeNull();
  });

  it.each([
    { returned_count: true }, { returned_count: 21 }, { has_more: 1 }, { scientific_acceptance: true },
    { reason_codes: ["x", "x"] }, { reason_codes: ["quoted text"] },
    { status: "unavailable", returned_count: 1 }, { returned_count: 0, has_more: true },
  ])("rejects inconsistent lookup envelopes %j", patch => {
    expect(knownScientificLookup({ ...scientificLookup(), ...patch })).toBeNull();
  });

  it("reports unavailable without substitute numbers", () => {
    show({ lookup: scientificLookup({ status: "unavailable", returned_count: 0 }), results: [] });
    expect(screen.getByRole("status")).toHaveTextContent("No fallback numbers or material-wide maxima are substituted");
    expect(screen.queryByText("39 K")).not.toBeInTheDocument();
  });

  it("distinguishes bounded empty lookup from absence and explains incomplete mixed requests", () => {
    show({ query: { ...scientificQuery(), intent: "mixed" }, lookup: scientificLookup({ returned_count: 0 }), results: [] });
    expect(screen.getByText(/does not establish the requested mechanism explanation/)).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("does not establish absence of a material or result");
  });

  it("shows the incomplete-explanation warning prominently for mechanism requests routed by an evidence constraint", () => {
    const query = scientificQuery("computed MgB2 pairing");
    query.intent = "mechanism";
    query.requested_fields = [];
    query.formulas = [{ raw_text: "MgB2", start: 9, end: 13, normalization: {
      version: "formula-query/1.0.0", raw_formula: "MgB2", normalized_formula: "MgB2", status: "normalized", reason_codes: [],
    } }];
    query.evidence_constraints = [{ field: "knowledge_origin", value: "Computed", raw_text: "computed", start: 0, end: 8 }];
    const row = scientificResult();
    row.result.result_classification.knowledge_origin = "Computed";
    row.result.reported_context.measurement_method = "DFT";
    show({ query, results: [row], lookup: scientificLookup({ reason_codes: ["explanatory_synthesis_not_performed"] }) });
    const warning = screen.getByText("This bounded result lookup does not establish the requested mechanism explanation.");
    expect(warning).toBeVisible();
    expect(warning.closest("details")).toBeNull();
    expect(screen.getByLabelText("Interpreted conditions")).toHaveTextContent("Requested origin: Computed");
    expect(screen.getByText("39 K")).toBeVisible();
    expect(screen.getByText(/not an original quotation, independent confirmation/)).toBeVisible();
  });

  it("states that a truncated matching set is not full-corpus coverage", () => {
    show({ lookup: scientificLookup({ has_more: true }) });
    expect(screen.getByText(/first 1 matching extraction records/)).toHaveTextContent("not full-corpus coverage");
  });
});
