import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MaterialProviderAvailabilityProvider, useMaterialProviderAvailability } from "@/components/MaterialProviderAvailability";
import type { MaterialProviderAvailabilitySnapshot } from "@/components/MaterialProviderAvailability";
import { ExternalMaterialReferences } from "@/components/ExternalMaterialReferences";
import { ExternalStructureReferences } from "@/components/ExternalStructureReferences";
import { ExternalCalculationReferences } from "@/components/ExternalCalculationReferences";
import { ExternalSuperconReferences } from "@/components/ExternalSuperconReferences";
import { mapMaterialProviderAvailability } from "@/lib/material-provider-availability";
import { NOMAD_GAP_SCHEMA } from "@/lib/nomad-electronic-references";
import {
  getMaterialExternalReferences, getMaterialStructureReferences,
  getMaterialCalculationReferences, getMaterialSuperconReferences,
} from "@/lib/api";
import type {
  ExternalMaterialReference, ExternalMaterialReferences as MPReport,
  ExternalCalculationReference, MaterialCalculationReferences,
  ExternalStructureReference, MaterialStructureReferences,
  ExternalSuperconReference, MaterialSuperconReferences, SuperconReferenceQuantity,
} from "@/lib/api";
import nbSnapshot from "../fixtures/mdr-supercon-nb-240322.json";
import laSmSnapshot from "../fixtures/mdr-supercon-la-sm-240322.json";

vi.mock("@/lib/api", () => ({
  getMaterialExternalReferences: vi.fn(), getMaterialStructureReferences: vi.fn(),
  getMaterialCalculationReferences: vi.fn(), getMaterialSuperconReferences: vi.fn(),
}));

const mpRow = (extra: Partial<ExternalMaterialReference> = {}): ExternalMaterialReference => ({
  id: "mp-aaaaaciu", url: "https://next-gen.materialsproject.org/materials/mp-aaaaaciu", formula: "Nb", knowledge_origin: "Computed",
  sample_identity_established: false, phase_identity_established: false, space_group: "Im-3m", crystal_system: "cubic",
  lattice: { a: 3.3, b: 3.3, c: 3.3 }, band_gap_ev: 0, density_g_cm3: 8.5, volume_angstrom3: null,
  energy_above_hull_ev_atom: 0, formation_energy_ev_atom: 0, is_metal: true, is_stable: false,
  origins: [], last_updated: null, source_snapshot_sha256: "a".repeat(64), functional: "Not resolved from summary; inspect source tasks", ...extra,
});
const mpReport = (extra: Partial<MPReport> = {}): MPReport => ({
  version: "material-external-references/1.0.0", status: "available", reason: null, candidates: [mpRow()], truncated: false,
  retrieved_at: null, scientific_acceptance: false, sample_identity_established: false,
  reference_conditions: "Computed reference conditions", methodology_url: "https://docs.materialsproject.org", ...extra,
});
const codQuantity = (value: number, unit = "Å") => ({ value, unit, uncertainty: null, raw_value: String(value), raw_uncertainty: null, uncertainty_type: "unreported" as const, source_field: "a", uncertainty_source_field: "siga" });
const codRow = (extra: Partial<ExternalStructureReference> = {}): ExternalStructureReference => ({
  id: "4002152", url: "https://www.crystallography.net/cod/4002152.html", cif_url: "https://www.crystallography.net/cod/4002152.cif",
  knowledge_origin: "Observed", declared_formula: "Nb", cell_content_formula: "Nb", composition_relation: "same_composition", match_level: "same_composition",
  space_group: "Im-3m", hall_symbol: null, space_group_number: 229, lattice: { a: codQuantity(3.3) }, volume: null,
  measurement_conditions: { cell_temperature: codQuantity(298, "K"), diffraction_temperature: null, cell_pressure: codQuantity(100, "kPa"), diffraction_pressure: null },
  method: "powder diffraction", method_status: "reported", source_revision: null, revision_status: "unreported", source_updated: null,
  source_snapshot_sha256: "a".repeat(64), source_status: null, provider_flags: null,
  bibliography: { doi: null, doi_url: null, title: null, journal: null, year: null }, provider_has_coordinates: true,
  coordinate_model_validated: false, cif_validation_status: "external_file_not_validated", sample_identity_established: false, phase_identity_established: false, ...extra,
});
const codReport = (extra: Partial<MaterialStructureReferences> = {}): MaterialStructureReferences => ({
  version: "material-crystal-references/1.0.0", provider: "COD", formula: "Nb", query_formula: "Nb", status: "available", reason: null,
  references: [codRow()], retrieved_at: null, matches_total: 200, inspected_entries: 21, truncated: true, source_response_sha256: "a".repeat(64),
  scientific_acceptance: false, sample_identity_established: false, phase_identity_established: false, database_changed: false,
  scope: "external", reference_conditions: "Structure measurement conditions", methodology_url: "https://wiki.crystallography.net/cod_mysql_schema/", ...extra,
});
const nomadRow = (extra: Partial<ExternalCalculationReference> = {}): ExternalCalculationReference => ({
  id: "task_nb", url: "https://nomad-lab.eu/prod/v1/gui/search/entries/entry/id/task_nb", archive_url: "https://nomad-lab.eu/prod/v1/api/v1/entries/task_nb/archive",
  formula: "Nb", material_id: null, upload_id: null, method: "DFT", program: "VASP", parser: null, structural_type: "bulk",
  xc_functional_names: ["GGA_X_PBE"], xc_functional_type: "GGA", spin_polarized: false, dft_metadata_status: "reported",
  dft_metadata_scope: "reported_underlying_dft_metadata_not_complete_method", space_group: "Im-3m", space_group_number: 229, crystal_system: "cubic",
  source_references: [], source_snapshot_sha256: "a".repeat(64), knowledge_origin: "Computed", method_status: "reported", conditions_status: "not_inspected",
  match_level: "fixed_composition_only", sample_identity_established: false, phase_identity_established: false, ...extra,
});
const nomadReport = (extra: Partial<MaterialCalculationReferences> = {}): MaterialCalculationReferences => ({
  version: "material-calculation-references/1.0.0", provider: "NOMAD", formula: "Nb", query_formula: "Nb", status: "available", reason: null,
  references: [nomadRow()], retrieved_at: null, matches_total: 999, inspected_entries: 21, truncated: true,
  scientific_acceptance: false, sample_identity_established: false, phase_identity_established: false, scope: "external",
  reference_conditions: "Not inspected", methodology_url: "https://docs.nomad-lab.eu", ...extra,
});
const mdrReport = (references: ExternalSuperconReference[]): MaterialSuperconReferences => ({
  ...nbSnapshot as MaterialSuperconReferences, references, matches_total: references.length, omitted_rows: 0, truncated: false,
});
const mdrQuantity = (field: string, extra: Partial<SuperconReferenceQuantity> = {}): SuperconReferenceQuantity => ({
  field, label: field, raw_value: "9", value: 9, raw_unit: "K", unit: "K", status: "reported",
  meaning: "Synthetic raw source value", temperature_raw: null, direction: null, source_method_raw: null, method_label: null, method_status: "not_supplied", ...extra,
});
const mdrRow = (quantities: SuperconReferenceQuantity[]): ExternalSuperconReference => ({ ...nbSnapshot.references[0] as ExternalSuperconReference, quantities });

function Probe() {
  const snapshot = useMaterialProviderAvailability();
  return <output data-testid="availability">{JSON.stringify(snapshot)}</output>;
}
const readSnapshot = () => JSON.parse(screen.getByTestId("availability").textContent!) as MaterialProviderAvailabilitySnapshot;
function MPPage({ materialId }: { materialId: string }) {
  return <MaterialProviderAvailabilityProvider materialId={materialId}><Probe /><ExternalMaterialReferences materialId={materialId} /></MaterialProviderAvailabilityProvider>;
}
const openMP = () => fireEvent.click(screen.getByText("Materials Project calculated references"));

describe("actual provider field mapping", () => {
  it("counts supplied values in returned MP structures, preserves zero/false and ignores method placeholders", () => {
    const availability = mapMaterialProviderAvailability("MP", mpReport({ candidates: [mpRow(), mpRow({ id: "mp-2", space_group: null, lattice: {}, band_gap_ev: null, is_stable: null })], truncated: true }));
    expect(availability.returned_count).toBe(2);
    expect(availability.truncated).toBe(true);
    expect(availability.fields.space_group.reference_count).toBe(1);
    expect(availability.fields.band_gap_ev.reference_count).toBe(1);
    expect(availability.fields.is_stable.reference_count).toBe(1);
    expect(availability.fields.calculation_method).toBeUndefined();
    expect(availability.fields.tc_kelvin).toBeUndefined();
    expect(availability.fields.pressure_gpa).toBeUndefined();
    expect(availability.fields.lambda_eph).toBeUndefined();
    expect(availability.fields.space_group.association_status).toBe("sample_and_state_unreviewed");
  });
  it("does not treat COD coordinates flags or structure pressure/method as supplied Tc conditions", () => {
    const availability = mapMaterialProviderAvailability("COD", codReport());
    expect(availability.returned_count).toBe(1);
    expect(availability.fields.lattice_a.reference_count).toBe(1);
    expect(availability.fields.measurement_temperature_k.scope).toMatch(/Crystal cell or diffraction temperature; not the selected Tc/);
    expect(availability.fields.structure_measurement_pressure.reference_count).toBe(1);
    expect(availability.fields.structure_method.reference_count).toBe(1);
    for (const field of ["pressure_gpa", "measurement_method", "atomic_sites", "site_occupancies", "tc_kelvin"]) expect(availability.fields[field]).toBeUndefined();
    expect(availability.fields.space_group.reference_count).not.toBe(codReport().matches_total);
  });
  it("keeps NOMAD XC/spin as task metadata and counts only returned field hits", () => {
    const availability = mapMaterialProviderAvailability("NOMAD", nomadReport({ references: [nomadRow(), nomadRow({ id: "missing_metadata", space_group: null, space_group_number: null, xc_functional_names: null, xc_functional_type: null, spin_polarized: null, dft_metadata_status: "not_supplied" })] }));
    expect(availability.returned_count).toBe(2);
    expect(availability.fields.space_group.reference_count).toBe(1);
    expect(availability.fields.dft_spin_polarization.reference_count).toBe(1);
    expect(availability.fields.xc_functional.reference_count).toBe(1);
    expect(availability.fields.xc_functional.scope).toMatch(/not pairing symmetry/);
    expect(availability.fields.dft_spin_polarization.scope).toMatch(/not observed magnetism/);
    for (const field of ["pairing_symmetry", "is_unconventional", "competing_order", "lambda_eph", "pressure_gpa"]) expect(availability.fields[field]).toBeUndefined();
  });
  it("counts a zero electronic gap once per task rather than once per spin channel", () => {
    const source = nomadRow({ electronic: {
      version: "nomad-electronic-references/1.0.0", scope: "task_electronic_band_gaps_not_superconducting_gaps", unit_schema_url: NOMAD_GAP_SCHEMA,
      status: "reported", band_gaps: [0, 1].map(spin_channel_index => ({ source_kind: "dos_electronic", group_index: 0, spin_channel_index, spin_polarized: true, gap_type: null, value_j: 0, value_ev: 0 })),
    } });
    const availability = mapMaterialProviderAvailability("NOMAD", nomadReport({ references: [source, nomadRow({ id: "not_inspected" })] }));
    expect(availability.fields.band_gap_ev.reference_count).toBe(1);
    for (const field of ["is_metal", "gap_structure", "gap_energy_source_value", "pairing_symmetry", "tc_kelvin"]) expect(availability.fields[field]).toBeUndefined();
    const unresolved = mapMaterialProviderAvailability("NOMAD", nomadReport({ references: [{ ...source, method: null, method_status: "unresolved", knowledge_origin: "Unresolved" }] }));
    expect(unresolved.fields.band_gap_ev.review_required_count).toBe(1);
    source.electronic!.band_gaps[0].value_ev = 1;
    expect(mapMaterialProviderAvailability("NOMAD", nomadReport({ references: [source] })).fields.band_gap_ev).toBeUndefined();
  });
  it("keeps MDR test limits, widths and maximum pressure separate from Tc, and penetration length separate from electron–phonon coupling", () => {
    const availability = mapMaterialProviderAvailability("MDR", mdrReport([mdrRow([
      mdrQuantity("tcn"), mdrQuantity("tcwidth"), mdrQuantity("pmax", { unit: null, raw_unit: null, status: "unit_not_supplied" }),
      mdrQuantity("penet", { unit: "nm", raw_unit: "nm" }), mdrQuantity("cohere", { unit: "Å", raw_unit: "A" }),
    ])]));
    expect(availability.fields.tc_kelvin).toBeUndefined();
    expect(availability.fields.tc_criterion).toBeUndefined();
    expect(availability.fields.pressure_gpa).toBeUndefined();
    expect(availability.fields.lambda_eph).toBeUndefined();
    expect(availability.fields.lambda_london_nm.reference_count).toBe(1);
    expect(availability.fields.xi_gl_nm.reference_count).toBe(1);
    expect(availability.fields.minimum_temperature_k.scope).toMatch(/not Tc/);
    expect(availability.fields.transition_width_source_value.scope).toMatch(/not another Tc/);
    expect(availability.fields.maximum_applied_pressure_source_value.scope).toMatch(/not the selected Tc pressure/);
    expect(availability.fields.maximum_applied_pressure_source_value.review_required_count).toBe(1);
  });
  it("counts the actual packaged La–Sm source row's 80% Meissner fraction without filling a selected property", () => {
    const report = laSmSnapshot as MaterialSuperconReferences;
    const row = report.references.find(item => item.source_row_id === "155423")!;
    expect(row.quantities.find(item => item.field === "vols")).toMatchObject({
      raw_value: "80", value: 80, raw_unit: null, unit: "%", status: "reported",
      meaning: "source_column_reports_percent",
    });
    expect(row.source_row_sha256).toBe("dd94673bafe2b3d7612d8355deb00037d6c7240f07283370566499317ae2236f");
    const availability = mapMaterialProviderAvailability("MDR", report);
    expect(availability.fields.meissner_fraction_percent).toMatchObject({
      reference_count: 1, reference_ids: ["mdr:240322:oxide_metallic:155423"],
      review_required_count: 0, association_status: "sample_and_state_unreviewed",
    });
    expect(availability.fields.meissner_fraction_percent.scope).toMatch(/Source Meissner volume fraction/);
  });
  it("counts all existing MDR auxiliary coverage fields while deduplicating directions and preserving scientific roles", () => {
    const quantities = [
      mdrQuantity("hc1zero", { unit: "T", raw_unit: "T" }), mdrQuantity("hc1t", { unit: "T", raw_unit: "T" }),
      mdrQuantity("gap", { unit: "meV", raw_unit: "meV" }), mdrQuantity("gapene", { unit: "dimensionless", raw_unit: null }),
      mdrQuantity("gamma", { unit: "mJ/(mol K²)", raw_unit: "mJ/mol.K2" }),
      mdrQuantity("debyet", { unit: null, raw_unit: null, status: "unit_not_supplied" }),
      mdrQuantity("isotope", { unit: "dimensionless", raw_unit: null }),
      mdrQuantity("dtcdp", { unit: "K/GPa", raw_unit: "K/GPa" }),
      mdrQuantity("pmax", { unit: null, raw_unit: null, status: "unit_not_supplied" }),
      mdrQuantity("vols", { unit: "%", raw_unit: null }), mdrQuantity("tcwidth"), mdrQuantity("tcn"),
    ];
    const availability = mapMaterialProviderAvailability("MDR", mdrReport([mdrRow(quantities)]));
    for (const field of ["hc1_source_value", "gap_energy_source_value", "gap_ratio_source_value",
      "electronic_specific_heat_coefficient_source_value", "debye_temperature_source_value", "isotope_effect_exponent",
      "dtc_dp_source_value", "maximum_applied_pressure_source_value", "meissner_fraction_percent",
      "transition_width_source_value", "minimum_temperature_k"]) {
      expect(availability.fields[field].reference_count, field).toBe(1);
    }
    expect(availability.fields.hc1_source_value.review_required_count).toBe(0);
    expect(availability.fields.debye_temperature_source_value.review_required_count).toBe(1);
    expect(availability.fields.gap_ratio_source_value.scope).toMatch(/dimensionless/);
    expect(availability.fields.isotope_effect_exponent.scope).toMatch(/isotope and sample association remain unreviewed/);
    expect(availability.fields.dtc_dp_source_value.scope).toMatch(/not a Tc measurement pressure/);
    for (const field of ["tc_kelvin", "tc_criterion", "pressure_gpa", "lambda_eph", "pairing_symmetry"]) expect(availability.fields[field]).toBeUndefined();
  });
  it("retains unresolved raw values, absent units and undocumented method codes as review-required references", () => {
    const availability = mapMaterialProviderAvailability("MDR", mdrReport([mdrRow([
      mdrQuantity("tcn", { raw_value: "2–4", value: null, status: "value_requires_review" }),
      mdrQuantity("pmax", { unit: null, raw_unit: null, status: "unit_not_supplied" }),
      mdrQuantity("gap", { unit: null, raw_unit: "mV", status: "unit_requires_review" }),
      mdrQuantity("gamma", { unit: "mJ/(mol K²)", raw_unit: "mJ/mol.K2", source_method_raw: "3", method_label: null, method_status: "requires_review" }),
      // A directly invoked mapper remains conservative if scalar metadata is
      // internally inconsistent; panels separately reject malformed contracts.
      mdrQuantity("vols", { unit: "%", raw_unit: null, value: null }),
      mdrQuantity("unmapped_source_column"),
    ])]));
    for (const field of ["minimum_temperature_k", "maximum_applied_pressure_source_value", "gap_energy_source_value",
      "electronic_specific_heat_coefficient_source_value", "meissner_fraction_percent"]) {
      expect(availability.fields[field]).toMatchObject({ reference_count: 1, review_required_count: 1 });
    }
    expect(availability.fields.unmapped_source_column).toBeUndefined();
    expect(availability.fields.tc_kelvin).toBeUndefined();
    expect(availability.fields.pressure_gpa).toBeUndefined();
  });
  it("counts distinct MDR rows, separates explicit criteria and retains unresolved source values as review-required references", () => {
    const generic = mapMaterialProviderAvailability("MDR", mdrReport([mdrRow([mdrQuantity("tc")])]));
    expect(generic.fields.tc_kelvin.reference_count).toBe(1);
    expect(generic.fields.tc_criterion).toBeUndefined();
    const availability = mapMaterialProviderAvailability("MDR", mdrReport([mdrRow([
      mdrQuantity("tc"), mdrQuantity("t1"), mdrQuantity("t2"),
      mdrQuantity("tcsus", { raw_value: "9–10", value: null, status: "value_requires_review" }),
      mdrQuantity("lata", { unit: "Å", raw_unit: "A" }),
      mdrQuantity("hc2t", { unit: "T", raw_unit: "T", temperature_raw: "4.2" }),
    ])]));
    expect(availability.fields.tc_kelvin.reference_count).toBe(1);
    expect(availability.fields.tc_kelvin.review_required_count).toBe(1);
    expect(availability.fields.tc_criterion.reference_count).toBe(1);
    expect(availability.fields.lattice_a.review_required_count).toBe(1);
    expect(availability.fields.measurement_temperature_k.review_required_count).toBe(1);
    expect(availability.fields.measurement_temperature_k.scope).toMatch(/no resolved unit/);
    expect(availability.fields.hc2_tesla.reference_count).toBe(1);
  });
  it.each(["no_match", "not_applicable", "unavailable"] as const)("does not report field hits for %s", status => {
    const availability = mapMaterialProviderAvailability("MP", mpReport({ status, candidates: [] }));
    expect(availability.status).toBe(status);
    expect(availability.returned_count).toBe(0);
    expect(availability.fields).toEqual({});
  });
});

describe("optional shared provider availability", () => {
  beforeEach(() => vi.resetAllMocks());
  it("publishes the real La–Sm row's Meissner availability only after validating and opening its source panel", async () => {
    vi.mocked(getMaterialSuperconReferences).mockResolvedValue(laSmSnapshot as MaterialSuperconReferences);
    render(<MaterialProviderAvailabilityProvider materialId="La0.4Sm0.6O0.5F0.5BiS2"><Probe /><ExternalSuperconReferences materialId="La0.4Sm0.6O0.5F0.5BiS2" /></MaterialProviderAvailabilityProvider>);
    expect(getMaterialSuperconReferences).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("MDR SuperCon references"));
    await waitFor(() => expect(readSnapshot().providers.MDR?.status).toBe("available"));
    expect(readSnapshot().providers.MDR?.returned_count).toBe(2);
    expect(readSnapshot().fields.meissner_fraction_percent[0]).toMatchObject({
      reference_count: 1, reference_ids: ["mdr:240322:oxide_metallic:155423"],
      review_required_count: 0, association_status: "sample_and_state_unreviewed",
    });
    expect(readSnapshot().fields.pressure_gpa).toBeUndefined();
    expect(screen.getByText("80 %")).toBeInTheDocument();
  });
  it("does not request providers until each panel is opened, then aggregates actual source-specific references", async () => {
    vi.mocked(getMaterialExternalReferences).mockResolvedValue(mpReport());
    vi.mocked(getMaterialStructureReferences).mockResolvedValue(codReport());
    vi.mocked(getMaterialCalculationReferences).mockResolvedValue(nomadReport());
    vi.mocked(getMaterialSuperconReferences).mockResolvedValue(nbSnapshot as MaterialSuperconReferences);
    render(<MaterialProviderAvailabilityProvider materialId="Nb"><Probe /><ExternalMaterialReferences materialId="Nb" /><ExternalStructureReferences materialId="Nb" /><ExternalCalculationReferences materialId="Nb" /><ExternalSuperconReferences materialId="Nb" /></MaterialProviderAvailabilityProvider>);
    for (const request of [getMaterialExternalReferences, getMaterialStructureReferences, getMaterialCalculationReferences, getMaterialSuperconReferences]) expect(request).not.toHaveBeenCalled();
    expect(readSnapshot().providers).toEqual({});
    openMP();
    await waitFor(() => expect(readSnapshot().providers.MP?.status).toBe("available"));
    expect(getMaterialStructureReferences).not.toHaveBeenCalled();
    expect(getMaterialCalculationReferences).not.toHaveBeenCalled();
    expect(getMaterialSuperconReferences).not.toHaveBeenCalled();
    expect(readSnapshot().fields.space_group).toHaveLength(1);
    fireEvent.click(screen.getByText("Crystal structure references · COD"));
    await waitFor(() => expect(readSnapshot().providers.COD?.status).toBe("available"));
    fireEvent.click(screen.getByText("NOMAD calculation references"));
    await waitFor(() => expect(readSnapshot().providers.NOMAD?.status).toBe("available"));
    expect(readSnapshot().fields.space_group.map(entry => entry.provider)).toEqual(["MP", "COD", "NOMAD"]);
    expect(readSnapshot().fields.tc_kelvin).toBeUndefined();
    fireEvent.click(screen.getByText("MDR SuperCon references"));
    await waitFor(() => expect(readSnapshot().providers.MDR?.status).toBe("available"));
    expect(readSnapshot().providers.MDR?.returned_count).toBe(19);
    expect(readSnapshot().fields.tc_kelvin[0].reference_count).toBe(19);
    expect(readSnapshot().fields.tc_criterion[0].reference_count).toBeLessThanOrEqual(19);
    expect(document.getElementById("materials-project-references")).not.toBeNull();
    expect(document.getElementById("cod-structure-references")).not.toBeNull();
    expect(document.getElementById("nomad-calculation-references")).not.toBeNull();
    expect(document.getElementById("mdr-supercon-references")).not.toBeNull();
  });
  it("clears pending availability when collapsed, aborts the request and suppresses a late response", async () => {
    let resolveRequest!: (value: MPReport) => void;
    vi.mocked(getMaterialExternalReferences).mockImplementationOnce(() => new Promise(resolve => { resolveRequest = resolve; }));
    render(<MPPage materialId="Nb" />);
    openMP();
    await waitFor(() => expect(readSnapshot().providers.MP?.status).toBe("loading"));
    const signal = vi.mocked(getMaterialExternalReferences).mock.calls[0][1];
    openMP();
    await waitFor(() => expect(signal?.aborted).toBe(true));
    expect(readSnapshot().providers.MP?.status).toBe("not_requested");
    await act(async () => resolveRequest(mpReport()));
    expect(readSnapshot().fields).toEqual({});
    expect(screen.queryByText("mp-aaaaaciu ↗")).not.toBeInTheDocument();
  });
  it("resets hits and errors on material change without automatically querying the next material", async () => {
    vi.mocked(getMaterialExternalReferences).mockResolvedValueOnce(mpReport()).mockRejectedValueOnce(new Error("B unavailable"));
    const view = render(<MPPage materialId="A" />);
    openMP();
    await waitFor(() => expect(readSnapshot().fields.space_group?.length).toBe(1));
    view.rerender(<MPPage materialId="B" />);
    expect(readSnapshot().materialId).toBe("B");
    expect(readSnapshot().providers).toEqual({});
    expect(getMaterialExternalReferences).toHaveBeenCalledTimes(1);
    openMP();
    await waitFor(() => expect(readSnapshot().providers.MP?.status).toBe("unavailable"));
    expect(readSnapshot().fields).toEqual({});
    view.rerender(<MPPage materialId="C" />);
    expect(readSnapshot().providers).toEqual({});
    expect(screen.queryByText(/Reference service unavailable/)).not.toBeInTheDocument();
    expect(getMaterialExternalReferences).toHaveBeenCalledTimes(2);
  });
  it("does not publish an old material response after navigation", async () => {
    let resolveA!: (value: MPReport) => void;
    vi.mocked(getMaterialExternalReferences).mockImplementationOnce(() => new Promise(resolve => { resolveA = resolve; })).mockResolvedValueOnce(mpReport({ status: "no_match", candidates: [] }));
    const view = render(<MPPage materialId="A" />);
    openMP();
    await waitFor(() => expect(getMaterialExternalReferences).toHaveBeenCalledTimes(1));
    const signal = vi.mocked(getMaterialExternalReferences).mock.calls[0][1];
    view.rerender(<MPPage materialId="B" />);
    expect(signal?.aborted).toBe(true);
    expect(getMaterialExternalReferences).toHaveBeenCalledTimes(1);
    openMP();
    await waitFor(() => expect(readSnapshot().providers.MP?.status).toBe("no_match"));
    await act(async () => resolveA(mpReport()));
    expect(readSnapshot().providers.MP?.status).toBe("no_match");
    expect(readSnapshot().fields).toEqual({});
  });
  it("rejects a promoted scientific contract without exposing its values as available fields", async () => {
    vi.mocked(getMaterialExternalReferences).mockResolvedValue({ ...mpReport(), scientific_acceptance: true } as unknown as MPReport);
    render(<MPPage materialId="Nb" />);
    openMP();
    await waitFor(() => expect(readSnapshot().providers.MP?.status).toBe("unavailable"));
    expect(readSnapshot().fields).toEqual({});
  });
  it("returns no shared state standalone while preserving a functional lazy panel", async () => {
    vi.mocked(getMaterialExternalReferences).mockResolvedValue(mpReport());
    render(<><Probe /><ExternalMaterialReferences materialId="Nb" /></>);
    expect(screen.getByTestId("availability")).toHaveTextContent("null");
    expect(getMaterialExternalReferences).not.toHaveBeenCalled();
    openMP();
    expect(await screen.findByRole("link", { name: "mp-aaaaaciu ↗" })).toBeInTheDocument();
    expect(screen.getByTestId("availability")).toHaveTextContent("null");
  });
});
