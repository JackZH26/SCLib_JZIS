/** Display contract, not a migration or an assertion that these results exist in SCLib.
 * See docs/DISCOVERY_SCIENTIFIC_FIELDS.md. Keep experimental Tc in material_claims.
 */
export const DISCOVERY_FIELD_SCHEMA = "discovery-fields/0.2-draft";
export type FieldGroup = "state" | "stability" | "electronic" | "pairing" | "coherence" | "geometry" | "orders" | "synthesis" | "profiles" | "outcomes" | "evidence";
export type Profile = "epc" | "multiband" | "correlated" | "layered" | "flatband" | "f_electron" | "interface";
export type FeatureRole = "context" | "conditional_input" | "post_outcome" | "audit_only";
export type ValueKind = "number" | "text" | "artifact";

export const FIELD_GROUPS: { id: FieldGroup; label: string; description: string }[] = [
  { id: "state", label: "Identity / state", description: "Composition, sample and controlled conditions. Each row binds a selected state and next action." },
  { id: "stability", label: "D1 Stability", description: "Existence under specified temperature, pressure, reference phases and methods; not a direct Tc prediction." },
  { id: "electronic", label: "D2 Electronic state", description: "Normal-state low-energy electrons with orbital, normalization and model definitions. Higher DOS is not universally better." },
  { id: "pairing", label: "D3 Pairing", description: "EPC, correlated and multiband quantities coexist. Missing λ is not adverse pairing evidence; mechanisms may remain unresolved." },
  { id: "coherence", label: "D4 Dimensionality / coherence", description: "Distinguish geometric thickness, electronic dimensionality and coherence. Measured superconducting quantities are post-outcome by default." },
  { id: "geometry", label: "D5 Geometry / symmetry", description: "Coordinate revisions, active sites and local geometry. Space groups are categories; a larger number is not better." },
  { id: "orders", label: "D6 Competing order / disorder", description: "Separate static order, fluctuations, defects and transport. Magnetism has no universal score penalty." },
  { id: "synthesis", label: "D7 Synthesis / action", description: "Condition accessibility and next actions, not an additional measure of pairing strength." },
  { id: "profiles", label: "Family / mechanism extensions", description: "Overlapping profiles for moiré, interface, heavy-fermion and layered systems, not mutually exclusive mechanisms." },
  { id: "outcomes", label: "SC observations / post-outcome", description: "Separate Tc criteria and coherence observations. Excluded from prospective Tc inputs by default; a null result is not Tc=0." },
  { id: "evidence", label: "Evidence / methods", description: "Provenance, review, applicability and reproducibility. Paper and chunk counts do not directly earn physics points." },
];

export interface ScientificFieldDefinition {
  key: string; label: string; group: FieldGroup; kind: ValueKind; unit: string;
  definition: string; requiredContext: string; profiles: readonly Profile[];
  featureRole: FeatureRole; tier: "core" | "extension";
  requiresNormalization: boolean;
  comparisonScope: string; monotonicity: "not_assumed"; sortable: false;
}
type Options = Partial<Pick<ScientificFieldDefinition, "profiles" | "featureRole" | "tier" | "requiredContext">>;
function f(key: string, label: string, group: FieldGroup, kind: ValueKind, unit: string, definition: string, options: Options = {}): ScientificFieldDefinition {
  return { key, label, group, kind, unit, definition, profiles: [], featureRole: "conditional_input", tier: "core",
    requiredContext: "Same verified state; specific event/result, source locator, method and availability time. Preserve original units and uncertainty.",
    comparisonScope: "Compare only compatible states, definitions, units, normalization and method domains. No default cross-family numerical ranking.",
    requiresNormalization: ["dos_ef", "sommerfeld_gamma", "moire_filling", "quantum_metric", "superfluid_weight"].includes(key),
    monotonicity: "not_assumed", sortable: false, ...options };
}
const ext: Options = { tier: "extension" };
const context: Options = { featureRole: "context" };
const posterior: Options = { tier: "extension", featureRole: "post_outcome" };
const audit: Options = { featureRole: "audit_only" };
const epc: Options = { profiles: ["epc"] };
const corr: Options = { tier: "extension", profiles: ["correlated", "f_electron"] };
const flat: Options = { tier: "extension", profiles: ["flatband", "interface"] };

export const SCIENTIFIC_FIELDS: readonly ScientificFieldDefinition[] = [
  f("composition_status", "Composition status", "state", "text", "", "Exact, variable, interval or unresolved composition. Unknown δ is not zero.", context),
  f("composition_basis", "Composition basis", "state", "text", "", "Distinguish nominal, measured and computational compositions. Retain doping definitions, sites and isotopes in the state.", context),
  f("isotope_specification", "Isotopes", "state", "text", "", "Nuclides, masses and abundances. Do not assume a specific isotope without evidence.", context),
  f("state_status", "State status", "state", "text", "", "Proposed, reported, realized or unresolved. Planned conditions are not realized conditions.", context),
  f("sample_form", "Sample form", "state", "text", "", "Bulk, film, interface, heterostructure or model. A computational model is not an experimental sample.", context),
  f("pressure_gpa", "Pressure P", "state", "number", "GPa", "Pressure or pressure interval for this state. Missing pressure is not ambient pressure.", context),
  f("stress_mode", "Stress mode", "state", "text", "", "Hydrostatic, quasihydrostatic, uniaxial or another defined mode. Retain pressure medium, calibration temperature and loading path.", context),
  f("temperature_k", "Characterization T", "state", "number", "K", "Requires a temperature role. This is neither Tc nor an electronic-smearing temperature.", context),
  f("magnetic_field_t", "Applied field", "state", "number", "T", "External field magnitude, with orientation, reference frame and measurement protocol.", context),
  f("doping_definition", "Doping / site", "state", "text", "", "Species, site, concentration and counting basis. Nominal doping is not a Hall number or a measured carrier count.", context),
  f("strain_tensor", "Strain", "state", "artifact", "", "Strain tensor with reference structure and frame. Nominal lattice mismatch is not measured strain.", context),
  f("substrate", "Substrate", "state", "text", "", "Composition, orientation and termination. A free-standing bulk state may have an explicit not-applicable reason.", context),
  f("gate_voltage_v", "Gate voltage", "state", "number", "V", "Electrode definitions, dual-gate configuration and charge calibration. Gate voltage does not automatically determine doping.", { ...flat, ...context }),
  f("structure_family", "Structure family", "state", "text", "", "Prototype, layered, Kagome or other structural classification; separate from chemical family and research lane.", context),
  f("electronic_motif", "Electronic motif", "state", "text", "", "Source-backed multiorbital, flat-band, f-electron or other descriptors. Multiple or unresolved assignments are allowed.", context),
  f("mechanism_profiles", "Research profiles", "state", "text", "", "EPC, multiband, correlated, layered, flat-band, f-electron and interface profiles may overlap. They do not establish a mechanism.", context),

  f("structure_evidence_status", "Structure evidence", "stability", "text", "", "Measured or computed coordinates, description-only records and availability. A formula alone cannot support a DFPT run.", audit),
  f("formation_energy_per_atom", "Formation energy ΔE", "stability", "number", "eV/atom", "Internal-energy difference relative to specified elemental reference states. May be negative; do not substitute formation enthalpy ΔH."),
  f("formation_enthalpy_per_atom", "Formation enthalpy ΔH", "stability", "number", "eV/atom", "Difference in H=E+PV relative to specified elemental references at the same pressure. Identify nuclear and thermal corrections.", ext),
  f("energy_above_hull", "Energy above hull", "stability", "number", "eV/atom", "Hull distance at a matched pressure, method and competing-phase set. An ambient-pressure hull does not establish high-pressure stability."),
  f("phonon_min_frequency", "Minimum phonon frequency", "stability", "number", "THz", "Negative values denote imaginary modes by display convention. Retain q coverage, acoustic-mode treatment and numerical tolerance; Γ alone does not cover the Brillouin zone."),
  f("phonon_approximation", "Phonon approximation", "stability", "text", "", "Harmonic or anharmonic treatment, independent of classical or quantum nuclear treatment.", epc),
  f("nuclear_treatment", "Nuclear treatment", "stability", "text", "", "Classical or quantum nuclei. Retain masses, zero-point and thermal corrections, and the pressure definition.", epc),
  f("stability_assessment", "Stability assessment", "stability", "text", "", "A conditional judgment with a defined scope. Harmonic imaginary modes do not permanently exclude anharmonically stabilized structures."),
  f("free_energy_difference", "Interphase ΔG", "stability", "number", "eV/atom", "Gibbs free-energy difference between specified phases at a defined temperature and pressure. Do not mix E, H or Helmholtz F; retain nuclear and entropy methods and errors.", ext),
  f("elastic_tensor", "Elastic tensor", "stability", "artifact", "GPa", "Tensor, strain convention, coordinate frame and stability criterion. A single modulus is not a substitute.", ext),

  f("band_gap", "Band gap", "electronic", "number", "eV", "Specify direct or indirect gap, normal state and method. A zero DFT gap does not prove experimental metallicity."),
  f("dos_ef", "DOS(EF)", "electronic", "number", "states/eV", "Requires normalization per atom, cell, formula unit or moiré cell, with spin-summed or per-spin convention."),
  f("normal_state_transport_class", "Normal-state transport", "electronic", "text", "", "Metallic, semiconducting, localized or unresolved, with criterion and temperature range. Conductivity alone does not determine priority."),
  f("active_orbitals", "Active orbitals", "electronic", "text", "", "Atoms, orbitals and projection model. Orbital weights cannot be inferred directly from elemental composition."),
  f("bandwidth", "Bandwidth W", "electronic", "number", "eV", "Specify the energy window, orbital or band subspace and normal-state model.", ext),
  f("carrier_density_3d", "Bulk carriers n₃D", "electronic", "number", "cm⁻³", "Volume density with Hall or model definition. A multiband Hall number is not the total carrier count.", ext),
  f("carrier_density_2d", "Sheet carriers n₂D", "electronic", "number", "cm⁻²", "Sheet density. Do not use an arbitrary thickness to convert it into a bulk density for cross-family ranking.", ext),
  f("fermi_velocity", "Fermi velocity", "electronic", "number", "m/s", "Band-, pocket- and direction-resolved velocity; not always a single scalar.", ext),
  f("effective_mass", "Effective mass", "electronic", "number", "mₑ", "Distinguish band, cyclotron, thermodynamic and renormalized mass definitions.", ext),
  f("carrier_energy_scale", "Carrier energy scale", "electronic", "number", "eV", "A physical energy relative to a band edge or a defined model, not an arbitrary DFT Fermi-energy zero.", ext),
  f("van_hove_offset", "vHS offset", "electronic", "number", "eV", "Signed band or saddle-point energy relative to EF, with the interaction model.", ext),
  f("fermi_surface", "Fermi surface / bands", "electronic", "artifact", "", "Fermi-surface sheets, band-resolved DOS and pocket or subspace definitions.", { ...ext, profiles: ["multiband", "correlated"] }),

  f("pairing_assertions", "Pairing evidence", "pairing", "text", "", "Source-backed claims and alternative explanations. Unresolved mechanisms are valid; prevent post-outcome explanations from leaking the prediction target.", audit),
  f("electron_phonon_lambda", "λₑₚ", "pairing", "number", "1", "Specify the EPC definition and computation chain. Distinct from the London penetration depth λL.", epc),
  f("omega_log", "ωlog", "pairing", "number", "K", "Temperature representation of the EPC logarithmic frequency. Its energy is kB×ωlog_K; do not multiply by ℏ again.", epc),
  f("mu_star", "μ*", "pairing", "number", "1", "Coulomb pseudopotential assumption or source, cutoff energy and sensitivity. Not a measured constant for every material.", epc),
  f("pairing_solver", "Pairing solver", "pairing", "text", "", "Eliashberg, analytical formula or another model, with version and domain. Separate analytical inference from numerical calculation.", audit),
  f("alpha2f", "α²F spectrum", "pairing", "artifact", "", "Spectrum artifact, frequency units and grid, normalization, and same-chain λ, ωlog and spectral moments.", { ...ext, ...epc }),
  f("lambda_band_matrix", "λᵢⱼ matrix", "pairing", "artifact", "1", "Specify band labels, conventions and interband/intraband terms. Not equivalent to a single average λ.", { ...ext, profiles: ["epc", "multiband"] }),
  f("hubbard_u", "U", "pairing", "number", "eV", "Correlated subspace, local orbitals, calculated or fitted U source and double-counting convention.", corr),
  f("hund_j", "JH", "pairing", "number", "eV", "Hund coupling definition in the same subspace. Distinct from exchange J.", corr),
  f("exchange_j", "Exchange J", "pairing", "number", "eV", "Exchange model, bond or wavevector and sign convention. Distinct from Hund JH.", corr),
  f("u_over_w", "U/W", "pairing", "number", "1", "U and W from the same subspace, window and method. Report undefined values or bounds when W is zero or comparable to its error; do not truncate a verified large ratio.", corr),
  f("susceptibility_qw", "χ(q,ω)", "pairing", "artifact", "", "Separate experimental, Lindhard and approximate responses. Retain units, temperature, q–ω grid and channel.", corr),
  f("phonon_to_carrier_ratio", "kBωlog / Ecarrier", "pairing", "number", "1", "Physical energy-scale ratio within the same state and model. For ωlog in K use kB, not ℏ; the denominator cannot be an arbitrary Fermi-energy zero.", { ...ext, ...epc }),
  f("interband_scattering", "Interband scattering", "pairing", "number", "meV", "Band labels, scattering channel, temperature and conventions such as ħ/τ. Do not substitute an average scattering rate.", { ...ext, profiles: ["multiband"] }),
  f("charge_transfer_energy", "Charge-transfer energy", "pairing", "number", "eV", "Specify ligand–metal orbital subspace, normal-state model and energy reference.", corr),
  f("quasiparticle_weight", "Quasiparticle weight Z", "electronic", "number", "1", "Orbital or band, temperature and self-energy definition. Normal-state renormalization is not automatically inverse effective mass.", corr),

  f("dimensionality", "Effective dimensionality", "coherence", "text", "", "Specify geometric, electronic or coherence dimensionality. A film is not automatically electronically two-dimensional."),
  f("active_layer_count", "Active layers", "coherence", "number", "layers", "Define active layers, cell or repeat unit, and model region. Bulk form does not imply one active layer.", { profiles: ["layered", "interface"] }),
  f("thickness_nm", "Thickness", "coherence", "number", "nm", "Geometric thickness with measurement or model definition. Do not automatically divide sheet quantities by thickness."),
  f("coherence_assertions", "Coherence evidence", "coherence", "text", "", "Normal-state or superconducting evidence and its availability time. Superconducting-state evidence is excluded from prospective inputs by default.", { featureRole: "post_outcome" }),
  f("phase_stiffness", "Phase stiffness", "coherence", "number", "meV", "Definition, prefactor, dimensionality, temperature and direction. Independent prospective calculations require a separate task-specific review.", posterior),
  f("superfluid_weight", "Superfluid weight", "coherence", "artifact", "", "Tensor, conventions, units, 2D/3D normalization and conventional/geometric contributions. Do not force it into a universal scalar.", posterior),
  f("penetration_depth", "London λL", "coherence", "number", "nm", "Penetration depth, direction, temperature and fitting model. Distinct from dimensionless λₑₚ.", posterior),
  f("coherence_length", "Coherence length ξ", "coherence", "number", "nm", "Direction, definition and source. Values inferred from target-related Hc2 are post-outcome information.", posterior),

  f("space_group", "Space group", "geometry", "text", "", "Separate reported and computed assignments. Retain coordinate revision, symprec and angular tolerance; crystallographic symmetry does not establish magnetic time-reversal symmetry."),
  f("volume_per_atom", "Volume per atom", "geometry", "number", "Å³/atom", "Specify structure, composition, pressure and occupancy. A vacuum-containing 2D cell does not define a comparable bulk volume."),
  f("lattice_structure", "Lattice / coordinates", "geometry", "artifact", "", "Lattice matrix, fractional coordinates, occupancies, Wyckoff sites and structure revision. Preserve coordinates before idealization."),
  f("bond_length", "Active bond length", "geometry", "number", "Å", "Specify atom selection, periodic unwrapping, bond class and mean or distribution definition."),
  f("bond_angle", "Active bond angle", "geometry", "number", "°", "Specify the atom triplet, such as Ni–O–Ni or Fe–X–Fe. Different bond types cannot be ranked as the same descriptor."),
  f("layer_spacing", "Layer spacing", "geometry", "number", "Å", "Identify active layers and direction. The lattice parameter c is not automatically an interlayer distance.", { profiles: ["layered", "interface"] }),
  f("buckling_normalized", "Normalized buckling", "geometry", "number", "1", "Use a local Cartesian fitted plane after periodic unwrapping and a defined normalization length; not fractional-z standard deviation.", { profiles: ["layered"] }),
  f("stacking_sequence", "Stacking sequence", "geometry", "text", "", "Layer order, registry and structural identity such as 2222/1313. A reduced formula alone is insufficient."),
  f("symmetry_modes", "Distortions / modes", "geometry", "artifact", "", "Reference parent phase, mode normalization, tilts and rotations, with separate inversion and time-reversal evidence.", ext),
  f("t_perp_over_parallel", "t⊥/t∥", "geometry", "number", "1", "Same Wannier subspace, window, model and hopping paths. Report undefined values or bounds if the denominator is zero or comparable to its error; do not truncate reliable large ratios.", { ...ext, profiles: ["layered", "correlated"] }),

  f("magnetic_order", "Static magnetic order", "orders", "text", "", "Configuration, wavevector, temperature, pressure and probe. Magnetic fluctuations are not static order."),
  f("competing_orders", "Charge / spin / nematic order", "orders", "text", "", "Multiple source-backed assignments with scope and ordering temperatures. Not universally adverse evidence."),
  f("oxygen_defect_status", "Oxygen / defect sites", "orders", "text", "", "Oxygen stoichiometry, apical/planar sites and occupancies, distinguishing nominal and measured values. Oxygen-free does not mean defect-free."),
  f("residual_resistivity", "Residual resistivity", "orders", "number", "μΩ·cm", "Bulk resistivity with normal-state fitting or measurement range and direction. Distinct from sheet resistance."),
  f("sheet_resistance", "Sheet resistance", "orders", "number", "Ω/□", "2D normal-state temperature range, direction and contact/measurement definition. No arbitrary bulk thickness is required.", { ...ext, profiles: ["layered", "interface", "flatband"] }),
  f("rrr", "RRR", "orders", "number", "1", "ρ(T1)/ρ(T2); retain both temperatures, normal-state conditions and direction."),
  f("magnetic_energy_difference", "Magnetic-state ΔE", "orders", "number", "meV/atom", "Reference and target magnetic configurations at the same method and structure. Retain the sign.", ext),
  f("ordering_temperature", "Ordering temperature", "orders", "number", "K", "Identify the order, criterion and conditions. Distinct from superconducting Tc.", ext),
  f("scattering_rate", "Scattering energy scale", "orders", "number", "meV", "Energy representation with definition, relation to τ and channel. Separate intra- and interband scattering.", ext),

  f("synthesis_status", "Synthesis status", "synthesis", "text", "", "Proposed, reported, reproduced or failed, bound to a specific route and conditions.", audit),
  f("synthesis_route", "Precursors / process", "synthesis", "text", "", "Precursors, reaction or annealing temperature, pressure, duration and treatment history. Not a unique material constant.", context),
  f("pressure_release_status", "Decompression retention", "synthesis", "text", "", "Initial and final pressures, path, lifetime and environment. A high-pressure structure is not assumed to survive at ambient pressure.", audit),
  f("next_validation_step", "Next action", "synthesis", "text", "", "Selected action and question to distinguish. Changing the action requires reassessment, not maximization over unlimited trial actions.", audit),
  f("action_cost", "Resource costs", "synthesis", "artifact", "", "Cost vectors and intervals for CPU core-hours, GPU-hours, human-hours, memory and other required resources under a shared budget.", audit),
  f("action_stop_rule", "Stop / redirect rule", "synthesis", "text", "", "At least two meaningful outcomes and their corresponding decisions. An unexecuted action is not a failure.", audit),

  f("anion_height", "Anion height", "profiles", "number", "Å", "Selected active plane, anion set and structure revision, for example in iron-based systems.", { ...ext, profiles: ["layered", "correlated"] }),
  f("twist_angle", "Twist angle", "profiles", "number", "°", "Layer identities, angle convention, heterostrain and supercell. A formula alone cannot identify a moiré structure.", flat),
  f("moire_filling", "Moiré filling ν", "profiles", "number", "e/cell", "Per moiré cell, with degeneracy and charge-neutrality reference. Retain sign and calibration.", flat),
  f("displacement_field", "D/ε₀", "profiles", "number", "V/nm", "Specify the D/ε₀ representation, direction and dual-gate calibration. Do not confuse it with bare D in C/m².", flat),
  f("dielectric_environment", "Dielectric / screening", "profiles", "text", "", "Encapsulation materials, layer thicknesses, frequency or static dielectric definition, and screening model.", flat),
  f("isolation_gap", "Band-isolation gap", "profiles", "number", "meV", "Gap between the selected flat-band subspace and neighboring bands, with model conditions.", flat),
  f("quantum_metric", "Quantum metric", "profiles", "artifact", "", "Projected subspace, gij tensor, coordinates/gauge, k grid, integration domain and normalization. Not a universal scalar.", flat),
  f("topological_invariant", "Topological invariant", "profiles", "text", "", "Invariant type, bands or subspace, and symmetry assumptions. A nonzero invariant does not guarantee superconductivity.", flat),
  f("kondo_temperature", "Kondo temperature", "profiles", "number", "K", "Definition, fitting model and normal-state range. Different experimental definitions are not directly comparable.", { ...ext, profiles: ["f_electron"] }),
  f("normal_coherence_temperature", "Normal-state coherence T", "profiles", "number", "K", "Normal-state coherence criterion, for example in heavy fermions; distinct from superconducting phase coherence.", { ...ext, profiles: ["f_electron"] }),
  f("sommerfeld_gamma", "Specific-heat γ", "profiles", "number", "mJ/mol/K²", "Normal-state fitting range, magnetic field and molar basis, such as formula units or f atoms.", { ...ext, profiles: ["f_electron", "correlated"] }),
  f("f_electron_valence", "f-electron valence", "profiles", "text", "", "Atom or mixed-valence assignment, experimental or model definition and uncertainty. Do not substitute an integer formal valence.", { ...ext, profiles: ["f_electron"] }),
  f("interface_stack", "Interface stack", "profiles", "artifact", "", "Layer compositions and thicknesses, terminations, orientations, spacings, strain reference and structure revision.", { ...ext, profiles: ["interface"] }),
  f("sc_origin_scope", "Intrinsic / proximity-induced", "profiles", "text", "", "Source-backed intrinsic, proximity, induced or unresolved claim. An interface alone does not establish the origin.", { ...posterior, profiles: ["interface"] }),

  f("tc_onset", "Tc onset", "outcomes", "number", "K", "Experimental onset criterion, signal, field and temperature sweep. Reference a dedicated Tc claim, not materials.tc_max.", { featureRole: "post_outcome" }),
  f("tc_zero", "Tc zero", "outcomes", "number", "K", "Zero-resistance criterion, detection resolution and sample. Not a substitute for bulk superconductivity evidence.", { featureRole: "post_outcome" }),
  f("tc_midpoint", "Tc midpoint", "outcomes", "number", "K", "Resistive midpoint baseline or percentage and criterion, with a separate Tc claim.", { featureRole: "post_outcome" }),
  f("tc_heat_capacity", "Tc heat capacity", "outcomes", "number", "K", "Specific-heat anomaly criterion, background subtraction and field, with a separate Tc claim.", { featureRole: "post_outcome" }),
  f("tc_magnetic", "Tc magnetic", "outcomes", "number", "K", "Diamagnetic or susceptibility criterion, field and background subtraction. Separate from resistive onset.", { featureRole: "post_outcome" }),
  f("sc_evidence_status", "SC observation status", "outcomes", "text", "", "Transition, not detected, disputed or unknown. A null result needs Tmin, Tmax and a criterion; never default to Tc=0.", { featureRole: "post_outcome" }),
  f("measurement_window", "Measurement window / limits", "outcomes", "text", "", "Tmin, Tmax, signal sensitivity, external field and sweep path, defining the scope of a null result.", { featureRole: "post_outcome" }),
  f("shielding_fraction", "Shielding fraction", "outcomes", "number", "%", "FC/ZFC protocol, demagnetization factor and volume or mass normalization. Not automatically the superconducting volume fraction.", posterior),
  f("gap_mev", "SC gap Δ", "outcomes", "number", "meV", "Band, direction, temperature, probe and fitting model. Multiband results may have multiple components.", posterior),
  f("upper_critical_field", "μ₀Hc2", "outcomes", "number", "T", "Specify the μ₀H representation, direction, temperature and extrapolation method.", posterior),
  f("lower_critical_field", "μ₀Hc1", "outcomes", "number", "T", "Direction, temperature, demagnetization correction and flux-entry versus lower-critical-field definition.", posterior),
  f("critical_current_density", "Critical current Jc", "outcomes", "number", "A/cm²", "Transport or magnetization estimate, cross-sectional geometry, temperature, field and criterion. Define 2D sheet current separately.", posterior),
  f("bkt_temperature", "TBKT", "outcomes", "number", "K", "Measurement or model criterion for a 2D BKT transition and finite-size scope. Do not substitute an arbitrary resistive Tc.", posterior),
  f("kf_coherence_length", "kFξ", "outcomes", "number", "1", "Matched pocket and direction for kF and ξ. A ξ inferred from target-related Hc2 or Δ is post-outcome by default.", posterior),
  f("tc_over_tf", "Tc/TF", "outcomes", "number", "1", "Post-outcome diagnostic. TF is a defined Fermi temperature, not an arbitrary Fermi-energy zero or a spin-fluctuation temperature.", posterior),
  f("gap_ratio", "2Δ/kBTc", "outcomes", "number", "1", "Post-outcome ratio depending on target Tc. Retain the same state and references to all input results.", posterior),
  f("predicted_tc", "Model Tc (not observed)", "outcomes", "number", "K", "Model or formula output is separate from experimental Tc. It cannot be recycled as a ground-truth Tc training input.", { featureRole: "audit_only" }),

  f("knowledge_origin", "Knowledge origin", "evidence", "text", "", "Observed, Computed, Inferred or AI-Proposed, independent of extraction method and review status.", audit),
  f("source_locator", "Source / locator", "evidence", "text", "", "DOI/arXiv, version, paper or supplement page/figure/table, primary/cited role and correction links for every result.", audit),
  f("review_validity", "Review / validity", "evidence", "text", "", "Extraction correctness, scientific validity and reproduction are separate judgments. Do not average or maximize conflicting claims.", audit),
  f("state_match", "State matching", "evidence", "text", "", "Sample, composition/isotopes, structure, temperature, pressure, boundary conditions and tolerances. A shared source does not establish a shared state.", audit),
  f("method_applicability", "Method applicability", "evidence", "text", "", "A successful software run does not prove theoretical applicability. Retain normal-state, correlation and nonadiabatic limitations.", audit),
  f("run_manifest", "Run settings / artifacts", "evidence", "artifact", "", "Code/version, XC, pseudopotential hash, cutoffs, k/q meshes, SOC/U, convergence, input/output structures and failure stage.", audit),
  f("independent_work_count", "Independent works", "evidence", "number", "works", "Deduplicate the same result across preprint, journal article and review. This is not a chunk count and does not directly earn points.", audit),
  f("ood_status", "Model OOD status", "evidence", "text", "", "Domain-of-applicability diagnostic for a specific model and training-set version, not a permanent material property.", audit),
];

export const FIELD_BY_KEY = Object.fromEntries(SCIENTIFIC_FIELDS.map(field => [field.key, field])) as Record<string, ScientificFieldDefinition>;
export const OVERVIEW_KEYS = ["sample_form", "pressure_gpa", "mechanism_profiles", "structure_evidence_status", "normal_state_transport_class", "next_validation_step"];

export type KnowledgeOrigin = "Observed" | "Computed" | "Inferred" | "AI-Proposed";
export interface ValueProvenance {
  stateId: string; eventId: string; resultId: string; origin: KnowledgeOrigin;
  locator: string; method: string; review: "pending" | "approved" | "disputed";
  normalization?: string; context: string; synthetic: boolean;
}
type KnownPayload =
  | ({ kind: "number"; unit: string; original?: { value: string; unit: string; conversion: string }; uncertainty?: { value: number; definition: string } } & (
      { value: number; qualifier: "exact" | "lt" | "le" | "gt" | "ge" } |
      { value: null; qualifier: "interval"; lower: number; upper: number }
    ))
  | { kind: "text"; value: string }
  | { kind: "artifact"; value: { id: string; label: string } };
export type ScientificValue =
  | ({ availability: "known"; applicability: "applicable"; provenance: ValueProvenance } & KnownPayload)
  | { availability: "unknown" | "not_reported" | "not_extracted" | "not_computed" | "unavailable" | "failed" | "conflicted"; applicability: "applicable" | "undetermined"; reason: string; value: null }
  | { availability: "not_applicable"; applicability: "not_applicable"; reason: string; value: null };

export const AVAILABILITY_LABELS = {
  known: "Available", unknown: "Unknown", not_reported: "Not reported", not_extracted: "Not extracted", not_computed: "Not computed",
  unavailable: "Unavailable", failed: "Calculation failed", conflicted: "Conflicted", not_applicable: "Not applicable",
};
export const ROLE_LABELS: Record<FeatureRole, string> = { context: "State / context", conditional_input: "Conditional candidate input", post_outcome: "Post-outcome · excluded from prospective Tc by default", audit_only: "Audit / action · not a physics input" };
export function missingScientificValue(): ScientificValue {
  return { availability: "unknown", applicability: "undetermined", reason: "No result has been acquired and verified for this state. This means neither zero nor not applicable.", value: null };
}
export function formatScientificValue(value: ScientificValue): string {
  if (value.availability !== "known") return AVAILABILITY_LABELS[value.availability];
  if (value.kind === "text") return value.value;
  if (value.kind === "artifact") return value.value.label;
  if (value.qualifier === "interval") return `${value.lower}–${value.upper}`;
  const n = value.value;
  const formatted = Math.abs(n) >= 1e5 || (n !== 0 && Math.abs(n) < .001) ? n.toExponential(2) : n.toLocaleString("en-US", { maximumFractionDigits: 3 });
  const relation = { exact: "", lt: "<", le: "≤", gt: ">", ge: "≥" }[value.qualifier];
  return `${relation}${formatted}${value.uncertainty ? ` ± ${value.uncertainty.value}` : ""}`;
}

/** Display guard only; not a replacement for the future release/import validator. */
export function checkedScientificValue(key: string, value: ScientificValue | undefined, stateId: string): ScientificValue {
  if (!value) return missingScientificValue();
  if (value.availability !== "known") return value;
  const field = FIELD_BY_KEY[key];
  let reason = "";
  if (!field || value.kind !== field.kind) reason = "Value withheld: the type does not match the field definition.";
  else if (value.provenance.stateId !== stateId) reason = "Value withheld: this result belongs to a different state.";
  else if (field.requiresNormalization && !value.provenance.normalization) reason = "Value withheld: required normalization has not been specified.";
  else if (value.kind === "number") {
    if (value.unit !== field.unit) reason = `Source unit ${value.unit} does not match canonical unit ${field.unit}. A versioned conversion is required; the column unit cannot simply be relabeled.`;
    else if (value.qualifier === "interval" ? !Number.isFinite(value.lower) || !Number.isFinite(value.upper) || value.lower > value.upper : !Number.isFinite(value.value)) reason = "Value withheld: a non-finite number or invalid interval.";
    else if (value.uncertainty && (!Number.isFinite(value.uncertainty.value) || value.uncertainty.value < 0 || !value.uncertainty.definition.trim())) reason = "Value withheld: invalid uncertainty value or definition.";
  }
  return reason ? { availability: "unavailable", applicability: "undetermined", reason, value: null } : value;
}
