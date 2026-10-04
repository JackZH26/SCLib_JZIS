import snapshot from "@/public/research-pilots/discovery-structure-coordinates-2026-10-04.json";

export type StructureReference = typeof snapshot.references[number];
export type Vector3 = [number, number, number];
export const structureCoordinatesFilename = "discovery-structure-coordinates-2026-10-04.json";
export const structureCoordinatesSha256 = "ab7f7034d094646e9210cf430f84b6cf81fb2f2adc4f3791c08c2109b218b69b";

export function structureAssetPath(filename: string) {
  return `${process.env.NEXT_PUBLIC_BASE_PATH || ""}/research-pilots/${filename}`;
}

/** The shipped finite source inventory; callers cannot insert a catalogue association. */
export function structureReferences(): StructureReference[] {
  return structuredClone(snapshot.references);
}

export function structureReference(id: string): StructureReference {
  const reference = snapshot.references.find(item => item.id === id);
  if (!reference) throw new Error("Choose a captured structure reference.");
  return structuredClone(reference);
}

/** Cartesian basis uses a along x and b in the xy plane. Distances are in Å. */
export function latticeBasis(reference: StructureReference, scale = 1): Vector3[] {
  if (!Number.isFinite(scale) || scale <= 0) throw new Error("Invalid lattice scale.");
  const { a, b, c, alpha, beta, gamma } = reference.lattice;
  const radians = Math.PI / 180;
  const cx = c.value * Math.cos(beta.value * radians);
  const cy = c.value * (Math.cos(alpha.value * radians) - Math.cos(beta.value * radians) * Math.cos(gamma.value * radians)) / Math.sin(gamma.value * radians);
  const cz = Math.sqrt(c.value ** 2 - cx ** 2 - cy ** 2);
  return [[a.value * scale, 0, 0], [b.value * Math.cos(gamma.value * radians) * scale, b.value * Math.sin(gamma.value * radians) * scale, 0], [cx * scale, cy * scale, cz * scale]];
}

export function fractionalToCartesian(fractional: number[], basis: Vector3[]): Vector3 {
  return [0, 1, 2].map(axis => fractional.reduce((sum, coordinate, index) => sum + coordinate * basis[index][axis], 0)) as Vector3;
}

export function unitCellVolume(reference: StructureReference): number {
  const [a, b, c] = latticeBasis(reference);
  return a[0] * b[1] * c[2];
}

export function parseLatticeChange(input: string): number | null {
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(input.trim())) return null;
  const value = Number(input);
  return Number.isFinite(value) && value >= -10 && value <= 10 ? value : null;
}

export function latticeProposal(id: string, changePercent: number) {
  if (!Number.isFinite(changePercent) || changePercent < -10 || changePercent > 10) throw new Error("Enter a lattice change from −10% to +10%.");
  const reference = structureReference(id);
  const factor = 1 + changePercent / 100;
  return {
    version: "discovery-uniform-lattice-proposal/1.0.0",
    status: "unrelaxed_geometric_proposal",
    source_reference: reference,
    transformation: { kind: "uniform_lattice_scaling", linear_change_percent: changePercent, scale_factor: factor,
      fractional_coordinates_changed: false, occupancies_changed: false, angles_changed: false,
      atomic_relaxation_performed: false, symmetry_operations: "retained from source" },
    proposed_cell: {
      a_angstrom: reference.lattice.a.value * factor, b_angstrom: reference.lattice.b.value * factor,
      c_angstrom: reference.lattice.c.value * factor,
      alpha_degrees: reference.lattice.alpha.value, beta_degrees: reference.lattice.beta.value,
      gamma_degrees: reference.lattice.gamma.value,
      geometric_volume_angstrom_cubed: unitCellVolume(reference) * factor ** 3,
      volume_change_percent: (factor ** 3 - 1) * 100,
      uncertainty: null, uncertainty_status: "not_estimated_for_proposal",
    },
    sites: reference.sites,
    declared_symmetry_operations: reference.declared_symmetry_operations,
    proposed_conditions: { temperature_k: null, pressure_gpa: null },
    results: { tc_k: null, energy_ev: null, phonon_stability: null },
    scope: { stable_host_validated: false, calculation_executed: false, catalogue_sample_association: "unestablished",
      scientific_acceptance: false, ml_training_approved: false, automatic_database_write: false },
    next_checks: ["Review source identity, symmetry and occupancies for the intended sample.",
      "Choose an explicit disorder or ordered-supercell model for any partial occupancy.",
      "Select calculation settings and relax the intended structure and state.",
      "Evaluate stability and superconducting quantities with method-specific evidence."],
  };
}

/** A new coordinate CIF, not a rewrite of the source or a solver-ready input deck. */
export function latticeProposalCif(id: string, changePercent: number): string {
  const proposal = latticeProposal(id, changePercent);
  const reference = proposal.source_reference;
  const cell = proposal.proposed_cell;
  const derived = (value: number) => Number(value.toPrecision(12)).toString();
  return [
    `data_sclib_${id.replaceAll("-", "_")}_unrelaxed`,
    "# SCLib geometric proposal. No relaxation, stability calculation or Tc prediction.",
    "# Source coordinates and occupancy tokens are retained; lengths use source central values.",
    "# Source uncertainties are in the JSON manifest; proposal uncertainties are not estimated.",
    "# No source measurement temperature or pressure is assigned to this proposed cell.",
    "# Partial occupancy remains an average model; resolve disorder before atomistic calculation.",
    `# Source: ${reference.source.cif_url}`,
    `# Source SHA-256: ${reference.source.file_sha256}`,
    `# Source COD header revision: ${reference.source.captured_revision}`,
    `# Linear lattice change (%): ${changePercent}`,
    "_audit_creation_method 'SCLib uniform lattice scaling; unrelaxed geometric proposal'",
    `_cell_length_a ${derived(cell.a_angstrom)}`,
    `_cell_length_b ${derived(cell.b_angstrom)}`,
    `_cell_length_c ${derived(cell.c_angstrom)}`,
    `_cell_angle_alpha ${reference.lattice.alpha.raw}`,
    `_cell_angle_beta ${reference.lattice.beta.raw}`,
    `_cell_angle_gamma ${reference.lattice.gamma.raw}`,
    `_symmetry_space_group_name_H-M '${reference.space_group}'`,
    `_symmetry_Int_Tables_number ${reference.space_group_number}`,
    "loop_", "_symmetry_equiv_pos_as_xyz",
    ...reference.declared_symmetry_operations.map(operation => `'${operation}'`),
    "loop_", "_atom_site_label", "_atom_site_type_symbol", "_atom_site_fract_x", "_atom_site_fract_y", "_atom_site_fract_z", "_atom_site_occupancy",
    ...reference.sites.map(site => [site.label, site.element, ...site.fractional.map(coordinate => coordinate.raw), site.occupancy.raw].join(" ")),
    "",
  ].join("\n");
}
