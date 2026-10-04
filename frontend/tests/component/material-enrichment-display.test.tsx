import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MaterialEnrichment } from "@/components/MaterialEnrichment";
import { getMaterialEnrichment, type MaterialEnrichmentReport } from "@/lib/api";
import { MaterialProviderAvailabilityProvider, useProviderAvailabilityPublisher } from "@/components/MaterialProviderAvailability";
import { emptyProviderAvailability } from "@/lib/material-provider-availability";
import { materialRecoveryMetadata } from "@/lib/material-recovery-metadata";

vi.mock("@/lib/api", () => ({ getMaterialEnrichment: vi.fn() }));
function candidate(field: string, rawValue: unknown, quantity: Record<string, unknown> | null = null, overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return { candidate_id: `candidate:${field}`, field, raw_value: rawValue, value: quantity?.value ?? rawValue, quantity,
    source: { paper_id: "paper:synthetic", kind: "original_passage", source_revision: "test-capture", content_sha256: "1".repeat(64), source_url: "https://arxiv.org/html/0912.2752v2", locator: { table: "1", row: 2 }, span: { char_start: 0, char_end: 10, text_sha256: "2".repeat(64) } }, reason_codes: ["material_state_association_requires_review"], ...overrides };
}
function report(candidates: Record<string, unknown>[]): MaterialEnrichmentReport {
  return { version: "materials-enrichment/1.0.0", scientific_acceptance: false, database_changed: false, counts: {}, candidates,
    coverage: [{ material_id: "synthetic", formula: "Synthetic fixture", fields: [...new Set(candidates.map(item => String(item.field)))].map(field => ({ field, status: "pending_review", retained_present: false, candidate_count: candidates.filter(item => item.field === field).length, reason_codes: [], routes: ["source_table_and_supplement"] })) }] };
}
function quantity(value: number | null, unit: string, overrides: Record<string, unknown> = {}) {
  return { status: "parsed", relation: "exact", value, lower: null, upper: null, uncertainty: null, approximate: false, errors: [], unit, raw_unit: unit, ...overrides };
}
async function renderCandidates(candidates: Record<string, unknown>[]) {
  vi.mocked(getMaterialEnrichment).mockResolvedValue(report(candidates));
  const view = render(<MaterialEnrichment materialId="synthetic" />);
  await waitFor(() => expect(screen.getByText(`Source recovery candidates (${candidates.length})`)).toBeInTheDocument());
  return view;
}
function candidateRow(label: string): HTMLLIElement {
  const title = screen.getByText((text, element) => element?.tagName === "P" && element.className.includes("font-medium") && text.startsWith(label));
  return title.closest("li")!;
}
function ProviderProbe({ materialId }: { materialId: string }) {
  const publish = useProviderAvailabilityPublisher(materialId, "MDR");
  return <button onClick={() => publish({ ...emptyProviderAvailability("MDR", "available"), returned_count: 2, truncated: true, fields: {
    lattice_a: { field: "lattice_a", provider: "MDR", reference_count: 2, reference_ids: ["mdr:1", "mdr:2"], review_required_count: 2,
      scope: "Raw source lattice column; unit, structure and sample association require review", anchor: "mdr-supercon-references", association_status: "sample_and_state_unreviewed" },
  } })}>Open synthetic MDR lookup</button>;
}

describe("Recovery candidate quantity and source presentation", () => {
  beforeEach(() => vi.resetAllMocks());

  it("distinguishes a Tc calculation method from experimental measurement and generic source hints", async () => {
    await renderCandidates([
      candidate("tc_kelvin", "116 K", quantity(116, "K"), { subject: { calculation_method: "eliashberg", measurement_method: null, knowledge_origin: "Computed" } }),
      candidate("measurement_method", "x_ray_diffraction", null, { subject: { measurement_method: "x_ray_diffraction", field_role: "source_measurement_method" } }),
    ]);
    const tc = candidateRow("Tc: 116 K");
    expect(tc).toHaveTextContent("Tc calculation method: eliashberg");
    expect(tc).not.toHaveTextContent("Measurement method:");
    expect(candidateRow("Measurement method:")).toHaveTextContent("Source measurement description; association with Tc unresolved");
    expect(screen.queryByRole("link", { name: "Review original field source" })).not.toBeInTheDocument();
  });

  it("exports separate method roles without opening a calculation-method review permission or private metadata", () => {
    const authority = { version: "materials-enrichment/1.0.0", material_id: "synthetic", disposition: "pending", scientific_acceptance: false, ml_training_approved: false, public_release: false, database_changed: false, source_content_checked: false, material_state_reviewed: false };
    const solver = candidate("calculation_method", "eliashberg", null, { ...authority, candidate_id: `enrichment:${"a".repeat(64)}`, subject: { calculation_method: "eliashberg", measurement_method: null, field_role: "tc_calculation_method", private_notes: "PRIVATE METHOD" } });
    const metadata = materialRecoveryMetadata(report([solver]), "synthetic", "2026-10-04T00:00:00Z");
    expect(metadata?.returned_window.literal_exported).toBe(1);
    expect(metadata?.candidates[0]).toMatchObject({ field: "calculation_method", subject: { calculation_method: "eliashberg", measurement_method: null, field_role: "tc_calculation_method" }, scientific_acceptance: false });
    expect(JSON.stringify(metadata)).not.toContain("PRIVATE METHOD");
  });

  it("exposes field coverage as a named keyboard-focusable region after opening its disclosure", async () => {
    const body = report([]);
    body.coverage[0].fields = [{ field: "pressure_gpa", status: "not_extracted", retained_present: false, candidate_count: 0,
      reason_codes: ["source_assertion_subject_or_scope_requires_review"], routes: ["source_fulltext_and_supplement"] }];
    vi.mocked(getMaterialEnrichment).mockResolvedValue(body);
    render(<MaterialEnrichment materialId="synthetic" />);
    const summary = await screen.findByText("Inspect field coverage and recovery routes");
    expect(summary.closest("details")).not.toHaveAttribute("open");
    fireEvent.click(summary);
    const region = screen.getByRole("region", { name: "Scrollable field coverage and recovery routes" });
    region.focus();
    expect(region).toHaveFocus();
    expect(within(region).getByRole("table")).toHaveTextContent("Pressure");
    expect(within(region).getByRole("table")).toHaveTextContent("Not extracted");
    expect(within(region).getByRole("table")).toHaveTextContent("Paper and supplement");
  });

  it("links a literal candidate to its private review scope without importing or selecting a result", async () => {
    const candidateId = `enrichment:${"a".repeat(64)}`;
    await renderCandidates([candidate("maximum_applied_pressure_source_value", "50.8 GPa", null, {
      candidate_id: candidateId,
      source_value: { raw_value: "50.8 GPa", raw_unit: "GPa", normalization: "none", role: "study_extent" },
    })]);
    const link = screen.getByRole("link", { name: "Review original field source" });
    expect(link).toHaveAttribute("href", `/dashboard/research/material-literal-fields?material=synthetic&field=maximum_applied_pressure_source_value&candidate=${encodeURIComponent(candidateId)}`);
    expect(getMaterialEnrichment).toHaveBeenCalledTimes(1);
    expect(link).not.toHaveAttribute("target");
  });

  it("withholds the literal workflow link for unknown fields, malformed pins or converted values", async () => {
    const candidateId = `enrichment:${"a".repeat(64)}`;
    await renderCandidates([
      candidate("unknown_source_value", "7", null, { candidate_id: candidateId, source_value: { normalization: "none" } }),
      candidate("gap_energy_source_value", "4.2 meV", null, { candidate_id: "unbound-candidate", source_value: { normalization: "none" } }),
      candidate("hc1_source_value", "12 mT", quantity(0.012, "tesla"), { candidate_id: candidateId, source_value: { normalization: "none" } }),
    ]);
    expect(screen.queryByRole("link", { name: "Review original field source" })).not.toBeInTheDocument();
  });

  it("preserves literal property units and printed uncertainty without deriving a canonical quantity", async () => {
    await renderCandidates([candidate("gap_energy_source_value", "0.590(5) meV", null, {
      source_value: { raw_value: "0.590(5) meV", raw_unit: "meV", raw_uncertainty: "(5)", normalization: "none", role: "reported_property", field_cue: "superconducting gap", qualifiers: ["model_or_calculation_context"], private_notes: "PRIVATE SOURCE" },
    })]);
    const row = candidateRow("Gap energy:");
    expect(row.querySelector("p")).toHaveTextContent("Gap energy: 0.590(5) meV");
    expect(row.querySelector("p")).not.toHaveTextContent("meV meV");
    expect(row).toHaveTextContent("Printed uncertainty: (5)");
    expect(row).toHaveTextContent("Original source tokens; no unit conversion or uncertainty interpretation");
    expect(row).toHaveTextContent("Value appears in a model or calculation context");
    expect(row).not.toHaveTextContent("exact / parsed");
    expect(row).toHaveTextContent("Review needed");
    expect(document.body.textContent).not.toContain("PRIVATE SOURCE");
  });

  it("distinguishes study pressure and measurement limits from transition conditions", async () => {
    await renderCandidates([
      candidate("maximum_applied_pressure_source_value", "50.8 GPa", null, { source_value: { raw_value: "50.8 GPa", raw_unit: "GPa", normalization: "none", role: "study_extent" } }),
      candidate("minimum_temperature_k", "50 mK", null, { source_value: { raw_value: "50 mK", raw_unit: "mK", normalization: "none", role: "measurement_limit" } }),
      candidate("t_afm_k", "139 K", null, { source_value: { raw_value: "139 K", raw_unit: "K", normalization: "none", role: "reported_order_transition" } }),
    ]);
    expect(candidateRow("Maximum applied pressure:")).toHaveTextContent("Pressure range studied; association with Tc unresolved");
    const minimum = candidateRow("Minimum tested temperature:");
    expect(minimum.querySelector("p")).toHaveTextContent("50 mK");
    expect(minimum).toHaveTextContent("Lowest measurement temperature; not a transition temperature");
    expect(minimum.querySelector("p")).not.toHaveTextContent("0.05 K");
    expect(candidateRow("AFM transition temperature:")).toHaveTextContent("Reported ordering transition; state association pending");
    expect(screen.queryByText("Tc condition; association pending")).not.toBeInTheDocument();
  });

  it("preserves bound and approximation words in source-only display", async () => {
    await renderCandidates([
      candidate("transition_width_source_value", "below 1.5 K", null, { source_value: { raw_value: "below 1.5 K", raw_unit: "K", normalization: "none", role: "reported_property" } }),
      candidate("debye_temperature_source_value", "approximately 492 K", null, { source_value: { raw_value: "approximately 492 K", raw_unit: "K", normalization: "none", role: "reported_property", qualifiers: ["fit_or_estimate_context"] } }),
    ]);
    expect(candidateRow("Transition width:").querySelector("p")).toHaveTextContent("Transition width: below 1.5 K");
    expect(candidateRow("Debye temperature:").querySelector("p")).toHaveTextContent("Debye temperature: approximately 492 K");
    expect(candidateRow("Debye temperature:")).toHaveTextContent("Value appears in a fit, estimate or extrapolation");
    expect(document.body.textContent).not.toContain("exact / parsed");
  });

  it("keeps an incomplete literal search distinct from a claim that the paper did not report a field", async () => {
    const body = report([]);
    body.coverage[0].fields = [{ field: "debye_temperature_source_value", status: "not_found_in_checked_sources", retained_present: false, candidate_count: 0, reason_codes: ["bounded_source_value_grammar_has_incomplete_recall"], routes: ["source_fulltext_and_supplement"] }];
    vi.mocked(getMaterialEnrichment).mockResolvedValue(body);
    render(<MaterialEnrichment materialId="synthetic" />);
    expect(await screen.findByText("Literal extraction does not cover every reported value or table")).toBeInTheDocument();
    expect(screen.getByText("Debye temperature").closest("tr")).toHaveTextContent("No candidate in checked chunks");
    expect(screen.queryByText("Not reported")).not.toBeInTheDocument();
    expect(screen.queryByText("This field has no implemented paper extractor")).not.toBeInTheDocument();
  });

  it.each(["materials-source-statement-extractor/1.0.0", "materials-source-statement-extractor/1.0.1"])("renders pending-scope findings for the supported extractor %s", async (version) => {
    const body = report([]);
    body.classification_extractor_version = version;
    body.classification_review_findings = [{ material_id: "synthetic", fields: ["reported_order"], reason_codes: ["multiple_local_temperature_mentions_require_state_review"] }];
    vi.mocked(getMaterialEnrichment).mockResolvedValue(body);
    render(<MaterialEnrichment materialId="synthetic" />);
    expect(await screen.findByText(/multiple local temperature mentions require state review/)).toBeInTheDocument();
  });

  it("formats parsed values once when original tokens already include their unit", async () => {
    const view = await renderCandidates([candidate("tc_kelvin", "116 K", quantity(116, "K")), candidate("measurement_temperature_k", "250 K", quantity(250, "K")), candidate("pressure_gpa", "140 GPa", quantity(140, "GPa"))]);
    expect(candidateRow("Tc:").querySelector("p")).toHaveTextContent("Tc: 116 K");
    expect(candidateRow("Measurement temperature:").querySelector("p")).toHaveTextContent("Measurement temperature: 250 K");
    expect(candidateRow("Pressure:").querySelector("p")).toHaveTextContent("Pressure: 140 GPa");
    expect(view.container.textContent).not.toMatch(/116 K K|250 K K|140 GPa GPa/);
    expect(within(candidateRow("Tc:")).getByText("Raw source value:").parentElement).toHaveTextContent("116 K");
  });

  it("keeps crystallographic uncertainty and the original parenthetical notation accessible", async () => {
    await renderCandidates([candidate("lattice_a", "3.9772(9)", quantity(3.9772, "angstrom", { uncertainty: 0.0009, raw_unit: "Å" }))]);
    const row = candidateRow("Lattice a:");
    expect(row.querySelector("p")).toHaveTextContent("3.9772 ± 0.0009 Å");
    expect(within(row).getByText("3.9772(9)")).toBeInTheDocument();
    expect(row).toHaveTextContent("exact / parsed");
  });

  it("retains intervals and source frequency units without manufacturing a point or converting to Kelvin", async () => {
    await renderCandidates([candidate("tc_kelvin", "120-130 K", quantity(null, "K", { relation: "interval", lower: 120, upper: 130 })), candidate("omega_log_source_value", "1090 cm^-1", quantity(1090, "cm^-1"))]);
    expect(candidateRow("Tc:").querySelector("p")).toHaveTextContent("120–130 K");
    expect(candidateRow("Tc:")).toHaveTextContent("interval / parsed");
    expect(candidateRow("Logarithmic phonon frequency:").querySelector("p")).toHaveTextContent("1090 cm^-1");
    expect(candidateRow("Logarithmic phonon frequency:").querySelector("p")).not.toHaveTextContent("1090 K");
  });

  it("preserves an invalid source token without appending a guessed unit", async () => {
    await renderCandidates([candidate("tc_kelvin", "unclear temperature token", quantity(237, "K", { status: "invalid", errors: ["unparsed"] }))]);
    const row = candidateRow("Tc:"); expect(row.querySelector("p")).toHaveTextContent("Tc: unclear temperature token");
    expect(row.querySelector("p")).not.toHaveTextContent("237"); expect(row.querySelector("p")).not.toHaveTextContent("token K");
    expect(row).toHaveTextContent("exact / invalid"); expect(row).toHaveTextContent("Review needed");
  });

  it("shows pending composition, site and occupancy dictionaries as labeled scientific context", async () => {
    await renderCandidates([
      candidate("composition_identity", { catalogue_formula: "BaFe1.906Pt0.094As2", source_formula: "BaFe1.90Pt0.10As2", nominal_formula_raw: "BaFe1.90Pt0.10As2", refined_formula_raw: "BaFe1.906(8)Pt0.094(8)As2", relation: "nominal_refined_same_sample_proposal", association_reviewed: false, reviewer_email: "PRIVATE@example.invalid" }),
      candidate("atomic_sites", { site: "As", fractional_coordinate_raw: "z=0.35422(9)", full_coordinates_and_symmetry_reviewed: false }),
      candidate("site_occupancies", { site_elements: ["Fe", "Pt"], fractions_raw: { Fe: "0.953(4)", Pt: "0.047(4)", private_notes: "SECRET" }, interpretation: "source_reported_refined_same_site_ratio", occupancy_and_structure_binding_reviewed: false }),
    ]);
    const composition = candidateRow("Composition identity:");
    expect(composition).toHaveTextContent("Catalogue formula"); expect(composition).toHaveTextContent("BaFe1.906Pt0.094As2"); expect(composition).toHaveTextContent("Refined formula (source)"); expect(composition).toHaveTextContent("BaFe1.906(8)Pt0.094(8)As2"); expect(composition).toHaveTextContent("not automatically equivalent");
    expect(candidateRow("Atomic sites:")).toHaveTextContent("z=0.35422(9)");
    const occupancy = candidateRow("Site occupancies:"); expect(occupancy).toHaveTextContent("Fe occupancy (source)"); expect(occupancy).toHaveTextContent("0.953(4)"); expect(occupancy).toHaveTextContent("Pt occupancy (source)"); expect(occupancy).toHaveTextContent("0.047(4)"); expect(occupancy).toHaveTextContent("do not supply validated coordinates");
    expect(document.body.textContent).not.toMatch(/\[object Object\]|See quantity|PRIVATE@example.invalid|SECRET/);
  });

  it("links the primary source and falls back safely when a supplied URL is not an HTTP source", async () => {
    await renderCandidates([candidate("space_group", "Cmmm"), candidate("crystal_structure", "Tetragonal", null, { source: { paper_id: "paper:synthetic", source_url: "javascript:alert(1)", locator: { section: "Results", private_notes: "PRIVATE" } } })]);
    expect(within(candidateRow("Space group:")).getByRole("link", { name: "Open primary source" })).toHaveAttribute("href", "https://arxiv.org/html/0912.2752v2");
    expect(within(candidateRow("Space group:")).getByRole("link", { name: "Open primary source" })).toHaveAttribute("rel", "noopener noreferrer");
    expect(within(candidateRow("Structure label:")).getByRole("link", { name: "Open linked paper" })).toHaveAttribute("href", "/paper/paper%3Asynthetic");
    expect(document.querySelector('a[href^="javascript:"]')).toBeNull(); expect(document.body.textContent).not.toContain("PRIVATE");
  });

  it("states the record and paper sampling scope rather than implying complete coverage", async () => {
    const body = report([]);
    body.inspection_scope = { records_total: 500, records_inspected: 32, records_truncated: true, papers_total: 12, papers_inspected: 8, papers_truncated: true };
    vi.mocked(getMaterialEnrichment).mockResolvedValue(body);
    render(<MaterialEnrichment materialId="synthetic" />);
    expect(await screen.findByText(/Inspected 32 of 500 eligible retained records across 8 of 12 linked papers/)).toHaveTextContent("remaining records and sources have not been inspected");
  });

  it("states when specialist extraction is needed instead of implying an unsuccessful classification search", async () => {
    const body = report([]);
    body.coverage[0].fields = ["pairing_symmetry", "competing_order"].map(field => ({ field, status: "specialist_extraction_needed", retained_present: false, candidate_count: 0, reason_codes: ["specialist_extractor_not_implemented"], routes: ["source_fulltext_and_supplement"] }));
    vi.mocked(getMaterialEnrichment).mockResolvedValue(body);
    render(<MaterialEnrichment materialId="synthetic" />);
    expect(await screen.findAllByText("Specialist source extraction needed")).toHaveLength(2);
    expect(screen.queryByText("No candidate in checked chunks")).not.toBeInTheDocument();
  });

  it.each([
    "source_assertion_subject_or_scope_requires_review",
    "paper_field_extractor_not_implemented",
    "original_source_capture_not_supplied",
  ])("does not turn an extraction gap into a checked-source or absence claim: %s", async reason => {
    const body = report([]);
    body.coverage[0].fields = [{ field: "pairing_symmetry", status: "not_extracted", retained_present: false, candidate_count: 0, reason_codes: [reason], routes: ["source_fulltext_and_supplement"] }];
    vi.mocked(getMaterialEnrichment).mockResolvedValue(body);
    render(<MaterialEnrichment materialId="synthetic" />);
    expect(await screen.findByText("Not extracted")).toBeInTheDocument();
    expect(screen.queryByText("Source text not checked")).not.toBeInTheDocument();
    expect(screen.queryByText("No candidate in checked chunks")).not.toBeInTheDocument();
    expect(screen.queryByText("Not reported")).not.toBeInTheDocument();
  });

  it("keeps a bounded no-candidate result and unavailable source identity separate from an extraction gap", async () => {
    const body = report([]);
    body.coverage[0].fields = [
      { field: "pairing_symmetry", status: "not_extracted", retained_present: false, candidate_count: 0, reason_codes: ["source_assertion_subject_or_scope_requires_review"], routes: [] },
      { field: "tc_criterion", status: "not_found_in_checked_sources", retained_present: false, candidate_count: 0, reason_codes: ["bounded_extractor_did_not_find_local_candidate"], routes: [] },
      { field: "pressure_gpa", status: "source_unavailable", retained_present: false, candidate_count: 0, reason_codes: ["retained_source_identity_missing"], routes: [] },
    ];
    vi.mocked(getMaterialEnrichment).mockResolvedValue(body);
    render(<MaterialEnrichment materialId="synthetic" />);
    await screen.findByText("Not extracted");
    expect(screen.getByText("Pairing symmetry").closest("tr")).toHaveTextContent("Not extracted");
    expect(screen.getByText("Tc criterion").closest("tr")).toHaveTextContent("No candidate in checked chunks");
    expect(screen.getByText("Pressure").closest("tr")).toHaveTextContent("Source identity unavailable");
    expect(screen.getByText(/A missing candidate does not establish that the paper omitted the property/)).toBeInTheDocument();
  });

  it("separates actual external field references from suggested lookup routes", async () => {
    const body = report([]);
    body.coverage[0].fields = ["lattice_a", "pressure_gpa", "pairing_symmetry"].map(field => ({ field, status: "not_found_in_checked_sources", retained_present: false, candidate_count: 0, reason_codes: [], routes: field === "pairing_symmetry" ? ["source_fulltext_and_supplement"] : ["supercon_source_lookup"] }));
    vi.mocked(getMaterialEnrichment).mockResolvedValue(body);
    render(<MaterialProviderAvailabilityProvider materialId="synthetic"><MaterialEnrichment materialId="synthetic" /><ProviderProbe materialId="synthetic" /></MaterialProviderAvailabilityProvider>);
    expect(await screen.findAllByText("Lookup not opened")).toHaveLength(2);
    expect(screen.getByText("No linked external property lookup")).toBeInTheDocument();
    expect(screen.queryByText(/2 returned source rows/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open synthetic MDR lookup" }));
    const lattice = screen.getByText("Lattice a").closest("tr")!;
    expect(lattice).toHaveTextContent("MDR SuperCon: 2 returned source rows");
    expect(lattice).toHaveTextContent("unit, structure and sample association require review");
    expect(lattice).toHaveTextContent("Count covers the returned window");
    const pressure = screen.getByText("Pressure").closest("tr")!;
    expect(pressure).toHaveTextContent("No returned value for this field");
    expect(pressure).not.toHaveTextContent("2 returned source rows");
    expect(within(lattice).getByRole("link", { name: "MDR SuperCon" })).toHaveAttribute("href", "#mdr-supercon-references");
    expect(screen.getByText(/not completed catalogue fields or independent experiments/)).toBeInTheDocument();
  });

  it("makes onset, zero resistance, unknown pressure and unresolved material binding distinguishable", async () => {
    await renderCandidates([
      candidate("tc_kelvin", "23 K", quantity(23, "K"), { candidate_id: "tc:onset", subject: { tc_criterion: "onset", knowledge_origin: "Observed", pressure_state: "not_reported", measurement_method: "resistivity", identity_basis: "nominal_refined_composition_proposal", source_formula: "BaFe1.90Pt0.10As2", private_notes: "PRIVATE SUBJECT" } }),
      candidate("tc_kelvin", "21.5 K", quantity(21.5, "K"), { candidate_id: "tc:zero", subject: { tc_criterion: "zero_resistance", knowledge_origin: "Observed", pressure_state: "not_reported", identity_basis: "retained_quantity_source_scoped_search_hit" } }),
      candidate("tc_kelvin", "116 K", quantity(116, "K"), { candidate_id: "tc:unknown", subject: { tc_criterion: "unknown", knowledge_origin: "Unknown", pressure_state: "reported", pressure_quantity: quantity(140, "GPa"), identity_basis: "exact_formula_local" } }),
    ]);
    const onset = candidateRow("Tc: 23 K"), zero = candidateRow("Tc: 21.5 K"), unknown = candidateRow("Tc: 116 K");
    expect(onset).toHaveTextContent("Tc criterion: Onset"); expect(onset).toHaveTextContent("Source origin: Observed report"); expect(onset).toHaveTextContent("Measurement method: resistivity"); expect(onset).toHaveTextContent("Nominal/refined sample association pending");
    expect(zero).toHaveTextContent("Tc criterion: Zero resistance"); expect(zero).toHaveTextContent("local material binding unresolved");
    expect(onset).toHaveTextContent("Pressure context: Not reported in source context"); expect(zero).not.toHaveTextContent("0 GPa");
    expect(unknown).toHaveTextContent("Tc criterion: Unknown"); expect(unknown).toHaveTextContent("Pressure context: 140 GPa"); expect(unknown).toHaveTextContent("Source origin: Unknown"); expect(unknown).not.toHaveTextContent("Computed report");
    expect(document.body.textContent).not.toContain("PRIVATE SUBJECT");
    for (const row of [onset, zero, unknown]) expect(row).toHaveTextContent("Review needed");
  });

  it("preserves bounded and uncertain Tc pressure context without converting ambiguous or invalid context to a point", async () => {
    await renderCandidates([
      candidate("tc_kelvin", "120 K", quantity(120, "K"), { candidate_id: "tc:range", subject: { tc_criterion: "midpoint", knowledge_origin: "Computed", pressure_state: "reported", pressure_quantity: quantity(null, "GPa", { relation: "interval", lower: 140, upper: 250 }) } }),
      candidate("tc_kelvin", "121 K", quantity(121, "K"), { candidate_id: "tc:uncertainty", subject: { pressure_state: "reported", pressure_quantity: quantity(140, "GPa", { uncertainty: 2 }) } }),
      candidate("tc_kelvin", "122 K", quantity(122, "K"), { candidate_id: "tc:ambiguous", subject: { pressure_state: "ambiguous", pressure_quantity: quantity(100, "GPa") } }),
      candidate("tc_kelvin", "123 K", quantity(123, "K"), { candidate_id: "tc:invalid", subject: { pressure_state: "reported", pressure_quantity: quantity(999, "GPa", { status: "invalid", errors: ["unparsed"] }) } }),
    ]);
    expect(candidateRow("Tc: 120 K")).toHaveTextContent("Pressure context: 140–250 GPa"); expect(candidateRow("Tc: 120 K")).toHaveTextContent("Source origin: Computed report");
    expect(candidateRow("Tc: 121 K")).toHaveTextContent("Pressure context: 140 ± 2 GPa");
    expect(candidateRow("Tc: 122 K")).toHaveTextContent("Pressure context: Ambiguous in source context"); expect(candidateRow("Tc: 122 K")).not.toHaveTextContent("100 GPa");
    expect(candidateRow("Tc: 123 K")).toHaveTextContent("Pressure context: Unresolved"); expect(candidateRow("Tc: 123 K")).not.toHaveTextContent("999");
  });

  it("distinguishes explicit pressure roles while leaving an unclassified stability-like interval unresolved", async () => {
    await renderCandidates([
      candidate("pressure_gpa", "140 to 250 GPa", quantity(null, "GPa", { relation: "interval", lower: 140, upper: 250 }), { candidate_id: "pressure:unknown", subject: { pressure_state: "ambiguous", knowledge_origin: "Unknown" } }),
      candidate("pressure_gpa", "150 to 260 GPa", quantity(null, "GPa", { relation: "interval", lower: 150, upper: 260 }), { candidate_id: "pressure:stability", subject: { pressure_role: "stability_range" } }),
      candidate("pressure_gpa", "140 GPa", quantity(140, "GPa"), { candidate_id: "pressure:tc", subject: { pressure_role: "tc_condition" } }),
    ]);
    const unresolved = candidateRow("Pressure: 140–250 GPa");
    expect(unresolved).toHaveTextContent("Pressure role: Unresolved; stability ranges are not Tc conditions"); expect(unresolved).toHaveTextContent("Pressure context: Ambiguous in source context");
    expect(unresolved).not.toHaveTextContent("Pressure role: Stability range"); expect(unresolved).not.toHaveTextContent("Pressure role: Tc condition");
    expect(candidateRow("Pressure: 150–260 GPa")).toHaveTextContent("Pressure role: Stability range; not a Tc condition");
    expect(candidateRow("Pressure: 140 GPa")).toHaveTextContent("Pressure role: Tc condition; association pending");
  });

  it("identifies string atomic-site table rows and the pending nominal composition association", async () => {
    await renderCandidates([candidate("atomic_sites", "4d(1/2,0,1/4)", null, { table_row_label: "Fe/Pt", subject: { source_formula: "BaFe1.90Pt0.10As2", identity_basis: "nominal_refined_composition_proposal", knowledge_origin: "Unknown", table_column: 2, reviewer_email: "PRIVATE@example.invalid" } })]);
    const row = candidateRow("Atomic sites:");
    expect(row).toHaveTextContent("Atomic sites: 4d(1/2,0,1/4)"); expect(row).toHaveTextContent("Source table row: Fe/Pt"); expect(row).toHaveTextContent("Source formula: BaFe1.90Pt0.10As2");
    expect(row).toHaveTextContent("Nominal/refined sample association pending"); expect(row).toHaveTextContent("validated coordinates unavailable"); expect(row).not.toHaveTextContent("PRIVATE@example.invalid");
  });

  it("reveals every returned candidate, collapses to 40, and resets expansion on material change", async () => {
    const candidates = Array.from({ length: 41 }, (_, index) => candidate("measurement_method", `Synthetic method ${index + 1}`, null, { candidate_id: `method:${index}` }));
    const view = await renderCandidates(candidates);
    expect(screen.queryByText(/Measurement method: Synthetic method 41/)).not.toBeInTheDocument();
    const show = screen.getByRole("button", { name: "Show remaining candidates (1)" });
    expect(show).toHaveAttribute("aria-expanded", "false"); expect(document.getElementById(show.getAttribute("aria-controls")!)).toHaveProperty("tagName", "UL");
    fireEvent.click(show);
    expect(candidateRow("Measurement method: Synthetic method 41")).toBeInTheDocument(); expect(screen.getByText("Showing 41 of 41 returned candidates.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show fewer candidates" }));
    expect(screen.queryByText(/Measurement method: Synthetic method 41/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show remaining candidates (1)" }));
    const other = report(candidates.map(item => ({ ...item, raw_value: String(item.raw_value).replace("Synthetic", "Other") })));
    other.coverage[0].material_id = "other";
    vi.mocked(getMaterialEnrichment).mockResolvedValue(other);
    view.rerender(<MaterialEnrichment materialId="other" />);
    await waitFor(() => expect(screen.getByText(/^Measurement method: Other method 1$/)).toBeInTheDocument());
    expect(screen.queryByText(/Measurement method: Other method 41/)).not.toBeInTheDocument(); expect(screen.getByRole("button", { name: "Show remaining candidates (1)" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/Measurement method: Synthetic method/)).not.toBeInTheDocument();
  });
});
