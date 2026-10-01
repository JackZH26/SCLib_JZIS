import type {
  ExternalMaterialReferences,
  MaterialCalculationReferences,
  MaterialStructureReferences,
  MaterialSuperconReferences,
} from "@/lib/api";

export type MaterialReferenceProvider = "MP" | "COD" | "NOMAD" | "MDR";
export type ProviderAvailabilityStatus = "not_requested" | "loading" | "available" | "no_match" | "not_applicable" | "unavailable";

export const MATERIAL_PROVIDER_ANCHORS: Record<MaterialReferenceProvider, string> = {
  MP: "materials-project-references",
  COD: "cod-structure-references",
  NOMAD: "nomad-calculation-references",
  MDR: "mdr-supercon-references",
};
export const MATERIAL_PROVIDER_LABELS: Record<MaterialReferenceProvider, string> = {
  MP: "Materials Project", COD: "COD", NOMAD: "NOMAD", MDR: "MDR SuperCon",
};

/** Returned references are a recovery route, never a filled catalogue property. */
export interface ProviderFieldAvailability {
  provider: MaterialReferenceProvider;
  field: string;
  reference_count: number;
  reference_ids: string[];
  review_required_count: number;
  scope: string;
  anchor: string;
  association_status: "sample_and_state_unreviewed";
}
export interface MaterialProviderAvailability {
  provider: MaterialReferenceProvider;
  status: ProviderAvailabilityStatus;
  returned_count: number;
  truncated: boolean;
  anchor: string;
  fields: Record<string, ProviderFieldAvailability>;
}

export type MaterialProviderReport = ExternalMaterialReferences | MaterialStructureReferences | MaterialCalculationReferences | MaterialSuperconReferences;

export function emptyProviderAvailability(provider: MaterialReferenceProvider, status: ProviderAvailabilityStatus = "not_requested"): MaterialProviderAvailability {
  return { provider, status, returned_count: 0, truncated: false, anchor: MATERIAL_PROVIDER_ANCHORS[provider], fields: {} };
}

const supplied = (value: unknown) => typeof value === "string" && value.trim().length > 0;
const finite = (value: unknown) => typeof value === "number" && Number.isFinite(value);
const boolean = (value: unknown) => typeof value === "boolean";
const scope: Record<MaterialReferenceProvider, string> = {
  MP: "Computed composition reference; sample, phase and conditions unassociated",
  COD: "Crystal structure reference with its own measurement conditions; sample and phase unassociated",
  NOMAD: "Calculation task metadata; sample, phase and conditions unassociated",
  MDR: "Curated source row; sample, phase and Tc conditions unassociated",
};

/** Map only fields actually supplied in the validated, bounded provider response.
 * Total search matches and coordinate flags are deliberately not field values.
 */
export function mapMaterialProviderAvailability(provider: MaterialReferenceProvider, report: MaterialProviderReport): MaterialProviderAvailability {
  const result = emptyProviderAvailability(provider, report.status);
  result.truncated = report.truncated === true;
  if (report.status !== "available") return result;
  const reviewIds: Record<string, Set<string>> = {};
  const add = (field: string, id: string, reviewRequired = false, fieldScope = scope[provider]) => {
    const entry = result.fields[field] ??= {
      provider, field, reference_count: 0, reference_ids: [], review_required_count: 0,
      scope: fieldScope, anchor: result.anchor, association_status: "sample_and_state_unreviewed",
    };
    // A row with several criteria or directions still counts as one reference.
    if (!entry.reference_ids.includes(id)) {
      entry.reference_ids.push(id);
      entry.reference_count++;
    }
    if (reviewRequired && !(reviewIds[field] ??= new Set()).has(id)) {
      reviewIds[field].add(id);
      entry.review_required_count++;
    }
  };
  if (provider === "MP") {
    const rows = (report as ExternalMaterialReferences).candidates.filter(row => row.sample_identity_established === false && row.phase_identity_established === false);
    result.returned_count = rows.length;
    for (const row of rows) {
      if (supplied(row.space_group)) add("space_group", row.id);
      if (supplied(row.crystal_system)) add("crystal_structure", row.id);
      for (const axis of ["a", "b", "c"]) if (finite(row.lattice?.[axis])) add(`lattice_${axis}`, row.id);
      for (const field of ["band_gap_ev", "density_g_cm3", "volume_angstrom3", "energy_above_hull_ev_atom", "formation_energy_ev_atom"] as const) if (finite(row[field])) add(field, row.id);
      for (const field of ["is_metal", "is_stable"] as const) if (boolean(row[field])) add(field, row.id);
      if (supplied(row.functional) && !/^(?:not resolved|not supplied|unresolved|unknown)\b/i.test(row.functional)) add("calculation_method", row.id, false, "Reported functional metadata; full calculation method and conditions unreviewed");
    }
  } else if (provider === "COD") {
    const rows = (report as MaterialStructureReferences).references;
    result.returned_count = rows.length;
    for (const row of rows) {
      if (supplied(row.space_group) || finite(row.space_group_number) || supplied(row.hall_symbol)) add("space_group", row.id);
      for (const axis of ["a", "b", "c"]) {
        const q = row.lattice?.[axis];
        if (q && finite(q.value) && q.unit === "Å") add(`lattice_${axis}`, row.id, q.uncertainty_type === "unresolved");
      }
      if (row.volume && finite(row.volume.value) && row.volume.unit === "Å³") add("volume_angstrom3", row.id, row.volume.uncertainty_type === "unresolved");
      if ([row.measurement_conditions?.cell_temperature, row.measurement_conditions?.diffraction_temperature].some(q => q && finite(q.value) && q.unit === "K")) {
        add("measurement_temperature_k", row.id, false, "Crystal cell or diffraction temperature; not the selected Tc measurement temperature");
      }
      // Diffraction method and pressure describe the structure measurement, not Tc.
      if (supplied(row.method)) add("structure_method", row.id, row.method_status !== "reported");
      if ([row.measurement_conditions?.cell_pressure, row.measurement_conditions?.diffraction_pressure].some(q => q && finite(q.value) && q.unit === "kPa")) add("structure_measurement_pressure", row.id);
    }
  } else if (provider === "NOMAD") {
    const rows = (report as MaterialCalculationReferences).references;
    result.returned_count = rows.length;
    for (const row of rows) {
      if (supplied(row.space_group) || finite(row.space_group_number)) add("space_group", row.id);
      if (supplied(row.crystal_system) || supplied(row.structural_type)) add("crystal_structure", row.id);
      if (supplied(row.method)) add("calculation_method", row.id, row.method_status !== "reported");
      if (Array.isArray(row.xc_functional_names) && row.xc_functional_names.some(supplied) || supplied(row.xc_functional_type)) add("xc_functional", row.id, row.dft_metadata_status === "requires_review", "Underlying DFT functional metadata; not pairing symmetry or a complete calculation method");
      if (boolean(row.spin_polarized)) add("dft_spin_polarization", row.id, row.dft_metadata_status === "requires_review", "Calculation spin setting; not observed magnetism or competing order");
    }
  } else {
    const rows = (report as MaterialSuperconReferences).references;
    result.returned_count = rows.length;
    const tcFields = new Set(["tc", "t1", "t2", "t3", "tcsus"]);
    const criterionFields = new Set(["t1", "t2", "t3", "tcsus"]);
    const quantityFields: Record<string, string> = {
      lata: "lattice_a", latb: "lattice_b", latc: "lattice_c",
      hc2zero: "hc2_tesla", phc2zero: "hc2_tesla", nhc2zero: "hc2_tesla", hc2t: "hc2_tesla", phc2t: "hc2_tesla", nhc2t: "hc2_tesla",
      penet: "lambda_london_nm", ppenet: "lambda_london_nm", npenet: "lambda_london_nm",
      cohere: "xi_gl_nm", pcohere: "xi_gl_nm", ncohere: "xi_gl_nm",
    };
    for (const row of rows) {
      if (supplied(row.structure?.space_group) || finite(row.structure?.space_group_number) || supplied(row.structure?.space_group_number_raw)) add("space_group", row.id, true);
      if (supplied(row.structure?.common_name)) add("crystal_structure", row.id, true);
      if (supplied(row.sample_form?.raw_code) || supplied(row.sample_form?.label)) add("sample_form", row.id, true);
      if (supplied(row.sample_identifier)) add("sample_identifier", row.id, true);
      if (supplied(row.tc_method?.raw_code) || supplied(row.tc_method?.label)) add("measurement_method", row.id, true, "Raw Tc source-method code; interpretation and sample association require review");
      if (supplied(row.structure_method?.raw_code) || supplied(row.structure_method?.label)) add("structure_method", row.id, true);
      for (const q of row.quantities) {
        if (!supplied(q.raw_value)) continue;
        const unresolved = q.status !== "reported";
        if (tcFields.has(q.field)) add("tc_kelvin", row.id, unresolved);
        if (criterionFields.has(q.field)) add("tc_criterion", row.id, false, "Explicit resistance or susceptibility criterion in a source row; not associated with the selected Tc");
        const field = quantityFields[q.field];
        if (field) add(field, row.id, unresolved || q.field.startsWith("lat"), q.field.startsWith("lat") ? "Raw source lattice column; unit, structure and sample association require review" : scope.MDR);
        if (supplied(q.temperature_raw)) add("measurement_temperature_k", row.id, true, "Raw source quantity temperature condition with no resolved unit; not the selected Tc temperature");
        // tcn is a non-superconducting test limit, tcwidth a width, pmax an
        // applied-pressure maximum. None supplies Tc or its pressure condition.
        // London penetration lengths supply no electron–phonon coupling lambda.
      }
    }
  }
  return result;
}
