/** Layout fixtures only. Never publish, export as evidence, or send to the RPS API. */
import { FIELD_BY_KEY, type Profile, type ScientificValue, type ValueProvenance } from "./discovery-field-registry";

export interface DiscoveryDemoRow {
  id: string;
  formula: string;
  family: string;
  pressure: number | null;
  spaceGroup: string;
  hull: number | null;
  dos: number | null;
  lambda: number | null;
  omegaLog: number | null;
  physical: number;
  gain: number;
  execution: number;
  dimensions: (number | null)[];
  score: number | null;
  action: string;
  previewOnly: true;
  stateId: string;
  actionId: string;
  profiles: Profile[];
  fields: Record<string, ScientificValue>;
}

// All numbers, family labels, actions and rankings below are synthetic.
// Familiar formulas are typography examples, not claims about these materials.
const seeds: [string, string, number | null, string, number | null, number | null, number | null, number | null, (number | null)[], number, number, string][] = [
  ["MgB₂", "Boride", 0, "P6/mmm", 8, 2.42, 1.08, 680, [100, 75, 75, 75, 100, 75], 75, 87.5, "DFPT check"],
  ["LaH₁₀", "Hydride", 160, "Fm−3m", 24, 1.83, 2.45, 1120, [75, 100, 100, 50, 75, 75], 75, 62.5, "Pressure scan"],
  ["FeSe₀.₅Te₀.₅", "Iron-based", 0, "P4/nmm", 16, 4.16, null, null, [75, 75, 75, 75, 100, 50], 75, 75, "Magnetic audit"],
  ["CaC₆", "Carbon-based", 0, "R−3m", 12, 2.07, 0.84, 420, [75, 75, 75, 75, 75, 75], 75, 75, "Phonon check"],
  ["YBa₂Cu₃O₇−δ", "Cuprate", 0, "Pmmm", 32, 3.62, null, null, [75, 75, 75, 75, 100, 50], 75, 62.5, "Doping series"],
  ["Nd₀.₈Sr₀.₂NiO₂", "Nickelate", 0, "P4/mmm", 44, 3.08, null, null, [50, 75, 75, 50, 100, 50], 75, 62.5, "Phase matching"],
  ["NbSe₂", "Chalcogenide", 0, "P6₃/mmc", 6, 2.91, 0.73, 240, [100, 75, 50, 75, 75, 50], 50, 75, "CDW check"],
  ["CsV₃Sb₅", "Pnictide", 0, "P6/mmm", 18, 5.28, null, null, [75, 75, 50, 50, 100, 25], 75, 50, "Competing order"],
  ["H₃S", "Hydride", 140, "Im−3m", 21, 1.62, 1.91, 980, [75, 75, 100, 50, 75, 50], 37.5, 50, "Stability window"],
  ["LiFeAs", "Iron-based", 0, "P4/nmm", 28, 3.74, null, null, [75, 75, 50, 50, 75, 50], 50, 62.5, "Band comparison"],
  ["BaSi₂", "Silicide", 12, "Pnma", null, 1.36, null, null, [null, 75, 50, null, 50, 50], 50, 50, "Structure search"],
  ["Sr₂RuO₄", "Ruthenate", null, "I4/mmm", null, null, null, null, [75, null, null, 50, 75, null], 0, 50, "Resolve conditions"],
  ["CeCoIn₅", "Intermetallic", 0, "P4/mmm", null, null, null, null, [50, 50, 50, null, 50, 50], 50, 50, "Normal-state model audit"],
  ["C · twisted bilayer", "Carbon-based", 0, "—", null, null, null, null, [50, 50, 50, 50, 75, 50], 50, 62.5, "Filling / geometry audit"],
  ["κ-(BEDT-TTF)₂Cu[N(CN)₂]Br", "Organic", 0, "—", null, null, null, null, [50, 50, 50, null, 50, 50], 25, 62.5, "Molecular packing audit"],
  ["FeSe / SrTiO₃", "Heterostructure", 0, "—", null, null, null, null, [50, 75, 50, 50, 50, 50], 50, 50, "Interface boundary audit"],
];

const demoProfiles: Profile[][] = [
  ["epc", "multiband"], ["epc"], ["correlated", "multiband", "layered"], ["epc", "layered"],
  ["correlated", "layered"], ["correlated", "layered", "interface"], ["epc", "layered"], ["correlated", "multiband", "layered"],
  ["epc"], ["correlated", "multiband"], [], ["correlated", "multiband"], ["f_electron", "correlated"],
  ["flatband", "layered", "interface"], ["correlated", "layered"], ["interface", "layered", "multiband"],
];

// Sparse examples illustrate semantics, not scientific completeness. Every value is synthetic.
function makeFields(index: number, stateId: string, row: { pressure: number | null; spaceGroup: string; hull: number | null; dos: number | null; lambda: number | null; omegaLog: number | null; action: string }, profiles: Profile[]): Record<string, ScientificValue> {
  const fields: Record<string, ScientificValue> = {};
  const provenance = (key: string, normalization?: string): ValueProvenance => ({
    stateId, eventId: `${stateId}:event-demo`, resultId: `${stateId}:${key}`, origin: "AI-Proposed", review: "pending",
    locator: "Synthetic layout fixture — no paper, observation or calculation", method: "Invented UI example; not a physical result",
    context: "Same synthetic state only; no validated cross-source join", normalization, synthetic: true,
  });
  const number = (key: string, value: number | null, normalization?: string) => {
    fields[key] = value === null ? { availability: "not_computed", applicability: "undetermined", reason: "This computation is not provided in the demo. It is neither inapplicable nor adverse physical evidence.", value: null }
      : { availability: "known", applicability: "applicable", kind: "number", value, unit: FIELD_BY_KEY[key].unit, qualifier: "exact", provenance: provenance(key, normalization) };
  };
  const text = (key: string, value: string) => { fields[key] = { availability: "known", applicability: "applicable", kind: "text", value, provenance: provenance(key) }; };
  const artifact = (key: string, label: string, normalization?: string) => { fields[key] = { availability: "known", applicability: "applicable", kind: "artifact", value: { id: `${stateId}:mock-${key}`, label }, provenance: provenance(key, normalization) }; };
  const notApplicable = (key: string, reason: string) => { fields[key] = { availability: "not_applicable", applicability: "not_applicable", reason, value: null }; };

  text("state_status", "Proposed · demo");
  text("sample_form", [5, 13, 15].includes(index) ? "Interface model" : "Bulk model");
  text("composition_status", index === 4 ? "Variable δ · unresolved" : index === 13 || index === 15 ? "Stack-defined model" : "Nominal · demo");
  text("composition_basis", "Nominal model · not measured");
  number("pressure_gpa", row.pressure);
  if (row.pressure === null) fields.pressure_gpa = { availability: "unknown", applicability: "applicable", reason: "Pressure is undefined; do not default to ambient pressure.", value: null };
  text("mechanism_profiles", profiles.length ? profiles.join(" + ") : "Unresolved");
  text("structure_evidence_status", "Mock only · no coordinates");
  if (row.spaceGroup !== "—") text("space_group", row.spaceGroup);
  number("energy_above_hull", row.hull === null ? null : row.hull / 1000);
  number("dos_ef", row.dos, "per formula unit; spin summed (synthetic)");
  number("electron_phonon_lambda", row.lambda); number("omega_log", row.omegaLog);
  text("next_validation_step", row.action);
  text("normal_state_transport_class", "Unresolved · demo");
  text("knowledge_origin", "AI-Proposed · synthetic");
  text("review_validity", "Not reviewed · mock only");
  text("state_match", "No real evidence matched");
  if (![5, 13, 15].includes(index)) notApplicable("substrate", "This demo explicitly defines a free-standing bulk model with no substrate; this is not inferred from its material family.");
  if (index === 0) {
    text("structure_family", "Hexagonal prototype"); text("electronic_motif", "Multiband");
    number("band_gap", 0); number("mu_star", .12); text("phonon_approximation", "Harmonic · demo");
    artifact("lambda_band_matrix", "2 × 2 matrix · demo");
  }
  if (index === 1 || index === 8) {
    text("stress_mode", "Hydrostatic model"); text("nuclear_treatment", "Quantum · proposed");
    text("phonon_approximation", "Anharmonic · proposed"); number("phonon_min_frequency", index === 1 ? .4 : -.15);
    text("pressure_release_status", "Not evaluated");
  }
  if (index === 2 || index === 9 || index === 15) {
    text("active_orbitals", "Fe 3d · demo"); number("anion_height", 1.42);
    fields.magnetic_order = { availability: "conflicted", applicability: "applicable", reason: "Illustrative conflict. Real data must retain each original claim and source rather than averaging them.", value: null };
  }
  if (index === 4 || index === 5) {
    text("active_orbitals", index === 4 ? "Cu dx²−y² + O p · demo" : "Ni dx²−y² / dz² · demo");
    text("doping_definition", "Nominal site fraction · demo");
    fields.oxygen_defect_status = { availability: "not_extracted", applicability: "applicable", reason: "Oxygen deficiency and sites await verification; do not set δ to zero.", value: null };
    number("active_layer_count", index === 4 ? 2 : 1); number("layer_spacing", 3.35);
    number("bond_angle", 168); number("buckling_normalized", .035);
    number("u_over_w", 1.8, "same hypothetical orbital model, demo only");
    if (index === 5) { text("substrate", "SrTiO₃ · demo"); number("thickness_nm", 9); }
  }
  if (index === 7) text("structure_family", "Kagome");
  if (index === 10) fields.energy_above_hull = { availability: "failed", applicability: "undetermined", reason: "Illustrative calculation failure; not a label of instability or absence of superconductivity.", value: null };
  if (index === 12) {
    number("kondo_temperature", 38); number("normal_coherence_temperature", 26);
    number("sommerfeld_gamma", 240, "per mol formula unit; hypothetical normal-state fit"); text("f_electron_valence", "Mixed / unresolved · demo");
  }
  if (index === 13) {
    text("structure_family", "Moiré bilayer"); number("twist_angle", 1.08); number("moire_filling", -2.2, "e per moiré cell relative to neutrality; demo");
    number("carrier_density_2d", 1.3e12); number("bandwidth", .012); number("isolation_gap", 22);
    text("dimensionality", "2D electronic model"); number("displacement_field", .25); text("dielectric_environment", "Encapsulated model · demo");
    notApplicable("carrier_density_3d", "This demo uses a 2D sheet model without a bulk-thickness definition; an equivalent 3D carrier density is undefined.");
    notApplicable("volume_per_atom", "This 2D model has no comparable physical 3D volume; a vacuum-containing supercell volume cannot serve as a bulk descriptor.");
    artifact("quantum_metric", "Projected tensor · demo", "Hypothetical projected subspace / BZ integral convention; demonstration only");
  }
  if (index === 14) { text("structure_family", "Molecular dimers · demo"); text("electronic_motif", "Molecular π model"); }
  if (index === 15) { text("substrate", "SrTiO₃ · demo"); artifact("interface_stack", "2-layer stack · demo"); number("thickness_nm", .6); text("sc_origin_scope", "Unresolved"); }
  return fields;
}

const commonWeights = [0.2, 0.2, 0.25, 0.15, 0.1, 0.1];
export const DISCOVERY_DEMO_ROWS: DiscoveryDemoRow[] = seeds.map((seed, index): DiscoveryDemoRow => {
  const [formula, family, pressure, spaceGroup, hull, dos, lambda, omegaLog, dimensions, gain, execution, action] = seed;
  // A common-weight arithmetic illustration, not a calibrated family assessment.
  const physical = dimensions.reduce<number>((sum, value, i) => sum + (value ?? 0) * commonWeights[i], 0);
  const raw = 1000 + 45 * physical + 27 * gain + 18 * execution;
  const id = `DEMO-${String(index + 1).padStart(2, "0")}`;
  const stateId = `${id}:state-1`;
  const profiles = demoProfiles[index];
  return {
    id, formula, family, pressure, stateId, actionId: `${id}:action-1`, profiles,
    spaceGroup, hull, dos, lambda, omegaLog, physical, gain, execution, dimensions,
    score: gain > 0 ? Math.round(raw / 50) * 50 : null, action, previewOnly: true,
    fields: makeFields(index, stateId, { pressure, spaceGroup, hull, dos, lambda, omegaLog, action }, profiles),
  };
}).sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
