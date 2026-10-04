import { structureReference, type StructureReference, type Vector3 } from "@/lib/discovery-structures";

export const SITE_CANDIDATE_VERSION = "discovery-site-candidates/1.0.0";
export const SITE_CANDIDATE_LIMIT = 8;
export const SUPERCELL_ATOM_LIMIT = 96;
const symbols = new Set("H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og".split(" "));

export type SupercellAtom = {
  id: string; label: string; element: string; fractional: Vector3; occupancy: 1;
  source_site_label: string; source_expanded_index: number; cell_translation: Vector3;
};
export type SupercellModel = {
  reference: StructureReference; repeats: Vector3; atoms: SupercellAtom[];
  cell: { a: number; b: number; c: number; alpha: number; beta: number; gamma: number };
};
export type SiteOperation = { kind: "substitution"; element: string } | { kind: "vacancy"; element: null };
export type SiteCandidate = {
  id: string; parent_id: string; operation: SiteOperation; target_atom: SupercellAtom;
  composition: Record<string, number>; atoms: SupercellAtom[]; cif: string; cif_sha256: string;
  nominal_change: { changed_sites: 1; original_species_sites: number; original_total_sites: number;
    species_site_fraction: number; original_total_site_fraction: number; basis: string };
};
export type SiteCandidateBatch = {
  version: string; parent_id: string; source_cif_sha256: string; source_reference: StructureReference;
  baseline: Omit<SupercellModel, "reference">; candidates: SiteCandidate[];
  boundary: { status: string; charge_state: null; temperature_k: null; pressure_gpa: null;
    relaxed: false; energy_calculated: false; stability_validated: false; tc_calculated: false;
    catalogue_association: string; scientific_acceptance: false; ml_training_approved: false;
    database_write: false; symmetry_unique_candidates: false };
  construction: { supercell: string; coordinate_basis: string; source_merge_tolerance_angstrom: number;
    output_space_group: string; uncertainty: string; species_deduplication: string };
};

export function supercellModel(referenceId: string, repeats: number[]): SupercellModel {
  const reference = structureReference(referenceId);
  if (repeats.length !== 3 || repeats.some(value => !Number.isInteger(value) || value < 1 || value > 4)) {
    throw new Error("Each repeat must be an integer from 1 to 4.");
  }
  if (reference.sites.some(site => site.occupancy.value !== 1 || (site.occupancy.raw === null
    ? !("basis" in site.occupancy && site.occupancy.basis === "cif_dictionary_default")
    : !/^1(?:\.0*)?$/.test(site.occupancy.raw)))) {
    throw new Error("This source has partial or uncertain occupancy. An explicit disorder model is required before making ordered site candidates.");
  }
  if ("host_context" in reference && reference.host_context?.coincident_site_pairs) {
    throw new Error("This source has coincident sites. An explicit ordered model is required before making site candidates.");
  }
  const count = repeats.reduce((a, b) => a * b, 1) * reference.display_unit_cell_sites.length;
  if (count > SUPERCELL_ATOM_LIMIT) throw new Error(`This supercell has ${count} sites; the preview limit is ${SUPERCELL_ATOM_LIMIT}. Reduce the repeats.`);
  const atoms: SupercellAtom[] = [];
  for (let i = 0; i < repeats[0]; i++) for (let j = 0; j < repeats[1]; j++) for (let k = 0; k < repeats[2]; k++) {
    reference.display_unit_cell_sites.forEach((site, index) => {
      const translation: Vector3 = [i, j, k];
      atoms.push({ id: `image-${index}-cell-${i}-${j}-${k}`, label: `S${atoms.length + 1}`, element: site.element,
        fractional: site.fractional.map((coordinate, axis) => (coordinate + translation[axis]) / repeats[axis]) as Vector3,
        occupancy: 1, source_site_label: site.source_site_label, source_expanded_index: index, cell_translation: translation });
    });
  }
  const l = reference.lattice;
  return { reference, repeats: [...repeats] as Vector3, atoms,
    cell: { a: l.a.value * repeats[0], b: l.b.value * repeats[1], c: l.c.value * repeats[2],
      alpha: l.alpha.value, beta: l.beta.value, gamma: l.gamma.value } };
}

/** Parse explicit element choices. Isotopes, ionic charges and implicit aliases are not accepted. */
export function siteOperations(input: string, includeVacancy: boolean, originalElement: string): SiteOperation[] {
  const parts = input.trim() ? input.split(",").map(value => value.trim()) : [];
  if (parts.length > 32) throw new Error("Enter a short comma-separated list of element symbols.");
  if (parts.some(value => !symbols.has(value))) throw new Error("Use exact element symbols separated by commas, such as Al, Ca. Charges and isotopes need a separate model.");
  const unique = [...new Set(parts)];
  if (unique.includes(originalElement)) throw new Error(`Replacing ${originalElement} with itself does not create a candidate.`);
  const operations: SiteOperation[] = unique.map(element => ({ kind: "substitution", element }));
  if (includeVacancy) operations.push({ kind: "vacancy", element: null });
  if (!operations.length) throw new Error("Enter replacement elements or include a vacancy.");
  if (operations.length > SITE_CANDIDATE_LIMIT) throw new Error(`This request has ${operations.length} candidates; the limit is ${SITE_CANDIDATE_LIMIT}. Reduce the element list.`);
  return operations;
}

export function compositionOf(atoms: SupercellAtom[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const atom of atoms) counts[atom.element] = (counts[atom.element] ?? 0) + 1;
  return Object.fromEntries(Object.entries(counts).sort(([a], [b]) => a.localeCompare(b, "en")));
}

export function compositionLabel(composition: Record<string, number>): string {
  return Object.entries(composition).map(([element, count]) => `${element}${count === 1 ? "" : count}`).join(" ");
}

export async function coordinateSha256(value: string): Promise<string> {
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, "0")).join("");
}

function coordinateCif(model: SupercellModel, atoms: SupercellAtom[], target: SupercellAtom, operation: SiteOperation): string {
  const fixed = (value: number) => Number(value.toPrecision(14)).toString();
  return ["data_sclib_site_candidate", "# Unrelaxed ordered coordinate proposal. No energy, stability or Tc calculation.",
    `# Source CIF SHA-256: ${model.reference.source.file_sha256}`, `# Source: ${model.reference.source.cif_url}`,
    `# Supercell repeats: ${model.repeats.join(" ")}`, `# Target atom: ${target.id}; original element: ${target.element}`,
    `# Operation: ${operation.kind}${operation.element ? ` to ${operation.element}` : ""}`,
    "# Charge and target temperature/pressure are unspecified. Choose an electronic/magnetic model before calculation.",
    "# Coordinates derive from source-declared symmetry expansion with 0.001 A periodic merge tolerance.",
    "# Original source uncertainties remain in the JSON manifest; proposal uncertainties are not estimated.",
    "_audit_creation_method 'SCLib ordered supercell with one explicit site modification; unrelaxed'",
    `_cell_length_a ${fixed(model.cell.a)}`, `_cell_length_b ${fixed(model.cell.b)}`, `_cell_length_c ${fixed(model.cell.c)}`,
    `_cell_angle_alpha ${fixed(model.cell.alpha)}`, `_cell_angle_beta ${fixed(model.cell.beta)}`, `_cell_angle_gamma ${fixed(model.cell.gamma)}`,
    "_symmetry_space_group_name_H-M 'P 1'", "_symmetry_Int_Tables_number 1", "loop_", "_symmetry_equiv_pos_as_xyz", "'x,y,z'",
    "loop_", "_atom_site_label", "_atom_site_type_symbol", "_atom_site_fract_x", "_atom_site_fract_y", "_atom_site_fract_z", "_atom_site_occupancy",
    ...atoms.map(atom => [atom.label, atom.element, ...atom.fractional.map(fixed), "1"].join(" ")), ""].join("\n");
}

export async function generateSiteCandidates(referenceId: string, repeats: number[], targetId: string, replacements: string, includeVacancy: boolean): Promise<SiteCandidateBatch> {
  const baseline = supercellModel(referenceId, repeats);
  const target = baseline.atoms.find(atom => atom.id === targetId);
  if (!target) throw new Error("Choose an atom from the current supercell.");
  const operations = siteOperations(replacements, includeVacancy, target.element);
  const parentPayload = { version: SITE_CANDIDATE_VERSION, source_sha256: baseline.reference.source.file_sha256,
    repeats: baseline.repeats, cell: baseline.cell, atoms: baseline.atoms };
  const parentId = `supercell:${await coordinateSha256(JSON.stringify(parentPayload))}`;
  const candidates: SiteCandidate[] = [];
  const speciesSites = baseline.atoms.filter(atom => atom.element === target.element).length;
  for (const operation of operations) {
    const atoms = baseline.atoms.flatMap(atom => atom.id === target.id && operation.kind === "vacancy" ? []
      : [{ ...atom, fractional: [...atom.fractional] as Vector3, cell_translation: [...atom.cell_translation] as Vector3,
        element: atom.id === target.id && operation.kind === "substitution" ? operation.element : atom.element }]);
    const cif = coordinateCif(baseline, atoms, target, operation);
    const cifHash = await coordinateSha256(cif);
    const candidateId = `site-candidate:${await coordinateSha256(JSON.stringify({ version: SITE_CANDIDATE_VERSION, parent_id: parentId, target_atom_id: target.id, operation, cif_sha256: cifHash }))}`;
    candidates.push({ id: candidateId, parent_id: parentId, operation, target_atom: structuredClone(target), atoms, composition: compositionOf(atoms), cif, cif_sha256: cifHash,
      nominal_change: { changed_sites: 1, original_species_sites: speciesSites, original_total_sites: baseline.atoms.length,
        species_site_fraction: 1 / speciesSites, original_total_site_fraction: 1 / baseline.atoms.length,
        basis: "One changed site divided by original sites of the selected chemical species; not a measured defect/dopant concentration." } });
  }
  return { version: SITE_CANDIDATE_VERSION, parent_id: parentId, source_cif_sha256: baseline.reference.source.file_sha256,
    source_reference: baseline.reference, baseline: { repeats: baseline.repeats, cell: baseline.cell, atoms: baseline.atoms }, candidates,
    boundary: { status: "unrelaxed_ordered_site_proposals", charge_state: null, temperature_k: null, pressure_gpa: null,
      relaxed: false, energy_calculated: false, stability_validated: false, tc_calculated: false, catalogue_association: "unestablished",
      scientific_acceptance: false, ml_training_approved: false, database_write: false, symmetry_unique_candidates: false },
    construction: { supercell: "diagonal integer repeats; original vectors multiplied by repeats",
      coordinate_basis: "first symmetry image retained in the pinned source display expansion, translated and divided by repeats; no idealization",
      source_merge_tolerance_angstrom: 0.001, output_space_group: "P1 with explicitly enumerated sites; no post-modification symmetry inferred",
      uncertainty: "Source raw tokens remain in source_reference; new coordinates and cell uncertainties not estimated",
      species_deduplication: "exact element symbols deduplicated in input order; no symmetry-equivalence claim across site choices" } };
}
