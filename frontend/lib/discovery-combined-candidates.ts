import { SITE_CANDIDATE_VERSION, compositionOf, coordinateSha256, siteOperations, supercellModel,
  type SiteOperation, type SupercellAtom, type SupercellModel } from "@/lib/discovery-site-candidates";

export const COMBINED_VERSION = "discovery-combined-site-candidates/1.0.0";
export const COMBINED_LIMIT = 64;
export type SiteChoices = { targetId: string; replacements: string; vacancy: boolean; unchanged: boolean };
export type CombinedInput = { referenceId: string; repeats: number[]; sites: SiteChoices[]; strain: string };
type Choice = SiteOperation | { kind: "unchanged"; element: null };
type Edit = { target: SupercellAtom; operation: SiteOperation };
type Geometry = { atoms: SupercellAtom[]; cell: SupercellModel["cell"]; edits: Edit[]; strain_percent: number };

/** Decimal micro-percent grid: equivalent spellings deduplicate without fuzzy tolerances. */
function strains(input: string) {
  if (typeof input !== "string" || input.length > 256) throw new Error("Enter up to 8 explicit lattice-change percentages.");
  const raw = input.split(",").map(value => value.trim());
  if (raw.length > 32) throw new Error("Enter a short comma-separated lattice-change list.");
  const values = raw.map(token => {
    if (!/^[+-]?(?:\d{1,2}(?:\.\d{0,6})?|\.\d{1,6})$/.test(token)) throw new Error("Use decimal lattice changes with at most 6 decimal places, from −10 to +10 percent.");
    const value = Math.round(Number(token) * 1_000_000);
    if (Math.abs(value) > 10_000_000) throw new Error("Each lattice change must be from −10 to +10 percent.");
    return value === 0 ? 0 : value;
  });
  const unique = [...new Set(values)].sort((a, b) => a - b).map(value => value / 1_000_000);
  if (unique.length > 8) throw new Error("Use at most 8 distinct lattice changes.");
  return { raw_count: raw.length, values: unique };
}

/** Validate and enumerate at most 64 combinations before any asynchronous work. */
export function combinedPlan(input: CombinedInput) {
  const savedInput = structuredClone(input);
  const baseline = supercellModel(savedInput.referenceId, savedInput.repeats);
  if (!Array.isArray(savedInput.sites) || savedInput.sites.length < 1 || savedInput.sites.length > 3) throw new Error("Choose 1 to 3 distinct atomic sites.");
  if (new Set(savedInput.sites.map(site => site.targetId)).size !== savedInput.sites.length) throw new Error("Each atomic site can appear only once. Combine its choices in one row.");
  const axes = savedInput.sites.map(site => {
    const target = baseline.atoms.find(atom => atom.id === site.targetId);
    if (!target) throw new Error("Choose every site from the current supercell.");
    if (typeof site.replacements !== "string" || site.replacements.length > 128 || typeof site.vacancy !== "boolean" || typeof site.unchanged !== "boolean") throw new Error("Invalid site choices.");
    const operations: Choice[] = site.replacements.trim() || site.vacancy ? siteOperations(site.replacements, site.vacancy, target.element) : [];
    if (site.unchanged) operations.push({ kind: "unchanged", element: null });
    if (!operations.length) throw new Error(`Choose a replacement, vacancy or unchanged option for ${target.label}.`);
    operations.sort((a, b) => `${a.kind}:${a.element ?? ""}`.localeCompare(`${b.kind}:${b.element ?? ""}`, "en"));
    const rawCount = (site.replacements.trim() ? site.replacements.split(",").length : 0) + Number(site.vacancy) + Number(site.unchanged);
    return { target, operations, rawCount };
  }).sort((a, b) => baseline.atoms.indexOf(a.target) - baseline.atoms.indexOf(b.target));
  const latticeChanges = strains(savedInput.strain);
  const rawCount = axes.reduce((n, axis) => n * axis.rawCount, latticeChanges.raw_count);
  const count = axes.reduce((n, axis) => n * axis.operations.length, latticeChanges.values.length);
  if (count > COMBINED_LIMIT) throw new Error(`This request has ${count} distinct combinations; the limit is ${COMBINED_LIMIT}. Reduce the choices before generating.`);
  let combinations: Array<Array<{ target: SupercellAtom; operation: Choice }>> = [[]];
  for (const axis of axes) combinations = combinations.flatMap(items => axis.operations.map(operation => [...items, { target: axis.target, operation }]));
  const accepted: Geometry[] = [];
  const excluded: Array<{ reason: "unchanged_baseline" | "empty_cell"; strain_percent: number; choices: Array<{ target_id: string; operation: Choice }> }> = [];
  for (const choices of combinations) for (const strain of latticeChanges.values) {
    const edits: Edit[] = choices.filter((choice): choice is Edit => choice.operation.kind !== "unchanged");
    const changes = new Map(edits.map(edit => [edit.target.id, edit.operation]));
    const atoms = baseline.atoms.flatMap(atom => {
      const change = changes.get(atom.id);
      return change?.kind === "vacancy" ? [] : [{ ...structuredClone(atom), element: change?.kind === "substitution" ? change.element : atom.element }];
    });
    const reason = !atoms.length ? "empty_cell" : !edits.length && strain === 0 ? "unchanged_baseline" : null;
    if (reason) { excluded.push({ reason, strain_percent: strain, choices: choices.map(choice => ({ target_id: choice.target.id, operation: structuredClone(choice.operation) })) }); continue; }
    const factor = 1 + strain / 100;
    accepted.push({ atoms, cell: { ...baseline.cell, a: baseline.cell.a * factor, b: baseline.cell.b * factor, c: baseline.cell.c * factor }, edits: structuredClone(edits), strain_percent: strain });
  }
  return { input: savedInput, baseline, accepted, excluded, counts: { raw_combinations: rawCount, distinct_combinations: count,
    duplicate_choice_combinations: rawCount - count, generated_candidates: accepted.length, unchanged_baselines: excluded.filter(item => item.reason === "unchanged_baseline").length, empty_cells: excluded.filter(item => item.reason === "empty_cell").length } };
}

function combinedCif(model: SupercellModel, geometry: Geometry): string {
  const number = (value: number) => Number(value.toPrecision(14)).toString();
  return ["data_sclib_combined_candidate", "# Unrelaxed ordered coordinate proposal; no energy, stability or Tc calculation.",
    `# Source: ${model.reference.source.cif_url}`, `# Source CIF SHA-256: ${model.reference.source.file_sha256}`,
    `# Supercell repeats: ${model.repeats.join(" ")}`, `# Uniform linear lattice change (%): ${geometry.strain_percent}`,
    ...geometry.edits.map(edit => `# ${edit.target.id}: ${edit.target.element} -> ${edit.operation.element ?? "vacancy"}`),
    "# Charge, magnetic state and target temperature/pressure are unspecified.",
    "# Source expansion uses a 0.001 A periodic merge tolerance; fractional coordinates are not idealized.",
    "# Source uncertainties remain in the JSON; new uncertainties are not estimated.",
    "_audit_creation_method 'SCLib explicit site modifications and uniform lattice change; unrelaxed'",
    ...(["a", "b", "c"] as const).map(axis => `_cell_length_${axis} ${number(geometry.cell[axis])}`),
    ...(["alpha", "beta", "gamma"] as const).map(angle => `_cell_angle_${angle} ${number(geometry.cell[angle])}`),
    "_symmetry_space_group_name_H-M 'P 1'", "_symmetry_Int_Tables_number 1", "loop_", "_symmetry_equiv_pos_as_xyz", "'x,y,z'",
    "loop_", "_atom_site_label", "_atom_site_type_symbol", "_atom_site_fract_x", "_atom_site_fract_y", "_atom_site_fract_z", "_atom_site_occupancy",
    ...geometry.atoms.map(atom => [atom.label, atom.element, ...atom.fractional.map(number), "1"].join(" ")), ""].join("\n");
}

export async function generateCombinedCandidates(input: CombinedInput) {
  // All mutable caller input is copied and expanded before the first await.
  const plan = combinedPlan(input);
  if (!plan.accepted.length) throw new Error("No changed, nonempty coordinate candidates remain. Add a site modification or a nonzero lattice change.");
  const baseline = plan.baseline;
  const parentId = `supercell:${await coordinateSha256(JSON.stringify({ version: SITE_CANDIDATE_VERSION,
    source_sha256: baseline.reference.source.file_sha256, repeats: baseline.repeats, cell: baseline.cell, atoms: baseline.atoms }))}`;
  const candidates = [];
  for (const geometry of plan.accepted) {
    const cif = combinedCif(baseline, geometry);
    const cifSha = await coordinateSha256(cif);
    const id = `combined-candidate:${await coordinateSha256(JSON.stringify({ version: COMBINED_VERSION, parent_id: parentId, cif_sha256: cifSha }))}`;
    const species = [...new Set(geometry.edits.map(edit => edit.target.element))].sort((a, b) => a.localeCompare(b, "en"));
    candidates.push({ ...geometry, id, parent_id: parentId, composition: compositionOf(geometry.atoms), cif, cif_sha256: cifSha,
      nominal_change: { changed_sites: geometry.edits.length, original_total_sites: baseline.atoms.length,
        original_total_site_fraction: geometry.edits.length / baseline.atoms.length,
        by_original_species: species.map(element => { const denominator = baseline.atoms.filter(atom => atom.element === element).length;
          const numerator = geometry.edits.filter(edit => edit.target.element === element).length;
          return { element, changed_sites: numerator, original_species_sites: denominator, fraction: numerator / denominator }; }),
        basis: "Changed original sites, including replacements and removals; not a measured concentration or carrier density." },
      volume_ratio: (1 + geometry.strain_percent / 100) ** 3 });
  }
  return { version: COMBINED_VERSION, parent_id: parentId, source_reference: baseline.reference,
    baseline: { repeats: baseline.repeats, cell: baseline.cell, atoms: baseline.atoms }, requested: plan.input,
    counts: plan.counts, excluded_combinations: plan.excluded, candidates,
    construction: { operation_order: "explicit site substitutions/removals on the original supercell, then uniform scaling of all lattice vectors",
      coordinate_basis: "fractional coordinates and angles fixed; source symmetry expansion retained without idealization",
      deduplication: "exact species and six-decimal percentages; candidate IDs independent of input row/choice order",
      source_merge_tolerance_angstrom: 0.001, symmetry_unique_candidates: false, output_space_group: "P1 with explicit full occupancy sites",
      range_scope: "Interface bounds do not establish defect convergence or a physical stability interval." },
    boundary: { status: "unrelaxed_combined_coordinate_proposals", charge_state: null, magnetic_state: null, temperature_k: null, pressure_gpa: null,
      relaxed: false, energy_calculated: false, stability_validated: false, tc_calculated: false,
      catalogue_association: "unestablished", scientific_acceptance: false, ml_training_approved: false, database_write: false } };
}
export type CombinedBatch = Awaited<ReturnType<typeof generateCombinedCandidates>>;
export type CombinedCandidate = CombinedBatch["candidates"][number];

/** Exact unmodified parent for paired calculations. Never counted as a new candidate. */
export async function prepareCombinedReferenceControl(batch: CombinedBatch): Promise<CombinedCandidate> {
  const saved = structuredClone(batch);
  const verified = await generateCombinedCandidates(saved.requested);
  if (JSON.stringify(saved) !== JSON.stringify(verified)) throw new Error("The control batch differs from its reproducible source construction.");
  const model = supercellModel(verified.requested.referenceId, verified.requested.repeats);
  const geometry: Geometry = { atoms: model.atoms, cell: model.cell, edits: [], strain_percent: 0 };
  const cif = combinedCif(model, geometry);
  return { ...geometry, id: `reference-control:${verified.parent_id}`, parent_id: verified.parent_id,
    composition: compositionOf(model.atoms), cif, cif_sha256: await coordinateSha256(cif),
    nominal_change: { changed_sites: 0, original_total_sites: model.atoms.length, original_total_site_fraction: 0,
      by_original_species: [], basis: "Unmodified source-derived reference control; not a new material candidate." }, volume_ratio: 1 };
}
