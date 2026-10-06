import type { ResearchAtom, ResearchCatalogue, ResearchCell } from "@/lib/discovery-research-catalogue";
import { generateCombinedCandidates, type CombinedBatch } from "@/lib/discovery-combined-candidates";
import { coordinateSha256, supercellModel } from "@/lib/discovery-site-candidates";

export type PreparedResearchModel = {
  batch: CombinedBatch;
  candidateId: string;
  lineage: {
    catalogue_version: string; catalog_state_id: string; original_occurrence_ids: string[];
    /** Primary occurrence; all other original artifacts remain accessible by their occurrence IDs. */
    original_cif_sha256: string; generated_cif_sha256: string; generated_candidate_id: string;
    coordinate_model_equivalent: true;
  };
};

function requireValue(value: unknown): asserts value { if (!value) throw new Error("The research model does not match its retained coordinate state."); }
const round = (value: number) => Number(value.toPrecision(14));
const canonical = (value: unknown): string => {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") return `{${Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([key, child]) => `${JSON.stringify(key)}:${canonical(child)}`).join(",")}}`;
  return JSON.stringify(value);
};
const exact = (a: unknown, b: unknown) => requireValue(canonical(a) === canonical(b));
const atomProjection = (a: ResearchAtom): ResearchAtom => ({ id: a.id, label: a.label, element: a.element, fractional: a.fractional.map(round) as [number, number, number], occupancy: a.occupancy, source_site_label: a.source_site_label });
const cellProjection = (c: ResearchCell) => Object.fromEntries(Object.entries(c).map(([key, value]) => [key, round(value)]));

/**
 * Replays an already server-validated catalogue state through the existing generator.
 * This is coordinate equivalence at the retained CIF precision, not relaxation or
 * a physical equivalence judgment. It neither imports Node crypto nor mutates inputs.
 */
export async function prepareResearchModel(input: ResearchCatalogue, stateId: string): Promise<PreparedResearchModel> {
  requireValue(JSON.stringify(input).length <= 1024 * 1024);
  const catalog = structuredClone(input);
  exact([catalog.schema_version, catalog.formal_scientific_release, catalog.rps_release, catalog.human_scientific_review], ["research-proposal-catalog/2.0.0", false, false, null]);
  requireValue(catalog.states.length <= 100 && catalog.occurrences.length <= 200);
  const matches = catalog.states.filter(s => s.id === stateId); requireValue(matches.length === 1);
  const state = matches[0], parent = catalog.parents.find(p => p.id === state.parent_id); requireValue(parent);
  const source = catalog.sources.find(s => s.id === parent.source_id); requireValue(source);
  exact(parent.reference_id, `cod-${source.record_id}`);
  const baseline = supercellModel(parent.reference_id, parent.repeats);
  exact([source.provider, source.cif_sha256, source.revision, source.cif_url], ["COD", baseline.reference.source.file_sha256, baseline.reference.source.captured_revision, baseline.reference.source.cif_url]);
  exact(parent.atoms, baseline.atoms.map(atomProjection)); exact(parent.cell, cellProjection(baseline.cell));
  exact(state.conditions, { pressure_gpa: null, temperature_k: null, charge_state: null, magnetic_state: null });
  exact([state.status, state.score, state.rank, state.formal_approval], ["unrelaxed", null, null, null]);
  exact(state.physical_axes, Object.fromEntries(["stability", "electronic", "pairing", "coherence", "geometry", "competing_order"].map(axis => [axis, { status: "unknown", value: null }])));
  requireValue(Number.isInteger(state.strain_micro_percent) && Math.abs(state.strain_micro_percent) <= 10000000);
  requireValue(state.edits.length <= 3 && new Set(state.edits.map(e => e.target_id)).size === state.edits.length && (state.edits.length > 0 || state.strain_micro_percent !== 0));
  exact(state.edits.map(e => e.target_id), state.edits.map(e => e.target_id).sort());
  for (const edit of state.edits) {
    const target = baseline.atoms.find(a => a.id === edit.target_id); requireValue(target);
    exact([edit.original_element, edit.source_site_label], [target.element, target.source_site_label]);
    requireValue(edit.kind === "vacancy" ? edit.element === null : edit.kind === "substitution" && typeof edit.element === "string");
  }
  const originalOccurrences = catalog.occurrences.filter(o => o.state_id === state.id);
  requireValue(originalOccurrences.length > 0 && new Set(originalOccurrences.map(o => o.id)).size === originalOccurrences.length);
  exact(state.occurrence_ids, originalOccurrences.map(o => o.id));
  exact(state.primary_occurrence_id, state.occurrence_ids[0]);
  const primary = originalOccurrences[0];
  // Copy and validate before the first await so later caller edits cannot change the model.
  const sites = state.edits.length ? state.edits.map(edit => ({ targetId: edit.target_id, replacements: edit.kind === "substitution" ? edit.element! : "", vacancy: edit.kind === "vacancy", unchanged: false }))
    : [{ targetId: baseline.atoms[0].id, replacements: "", vacancy: false, unchanged: true }];
  const batch = await generateCombinedCandidates({ referenceId: parent.reference_id, repeats: parent.repeats, sites, strain: String(state.strain_micro_percent / 1000000) });
  requireValue(batch.candidates.length === 1);
  exact(parent.legacy_parent_id, batch.parent_id);
  exact(state.id, `proposal-state:${await coordinateSha256(canonical({ parent_id: state.parent_id, edits: state.edits, strain_micro_percent: state.strain_micro_percent, conditions: state.conditions, status: state.status }))}`);
  const candidate = batch.candidates[0];
  exact(state.atoms, candidate.atoms.map(atomProjection)); exact(state.cell, cellProjection(candidate.cell)); exact(state.composition, candidate.composition);
  const formulaCounts: Record<string, number> = {};
  requireValue(/^(?:[A-Z][a-z]?(?:[1-9][0-9]*)?)+$/.test(state.formula));
  for (const match of state.formula.matchAll(/([A-Z][a-z]?)([0-9]*)/g)) { requireValue(!Object.hasOwn(formulaCounts, match[1])); formulaCounts[match[1]] = Number(match[2] || 1); }
  exact(state.composition, formulaCounts);
  for (const occurrence of originalOccurrences) {
    requireValue(occurrence.cif_text.length <= 65536 && occurrence.cif_text.endsWith("\n"));
    exact(await coordinateSha256(occurrence.cif_text), occurrence.cif_sha256);
    exact(occurrence.id, `proposal-occurrence:${await coordinateSha256(canonical({ source_batch_sha256: occurrence.source_batch_sha256, source_locator: occurrence.source_locator, legacy_candidate_id: occurrence.legacy_candidate_id, cif_sha256: occurrence.cif_sha256 }))}`);
    const lines = occurrence.cif_text.split("\n");
    requireValue(lines.includes(`# Source CIF SHA-256: ${source.cif_sha256}`) && lines.includes(`# Source: ${source.cif_url}`));
    requireValue(lines.includes("_symmetry_space_group_name_H-M 'P 1'") && lines.includes("_symmetry_Int_Tables_number 1"));
    for (const [key, value] of Object.entries(state.cell)) {
      const tag = `_cell_${key.length === 1 ? "length" : "angle"}_${key} `, rows = lines.filter(line => line.startsWith(tag));
      requireValue(rows.length === 1 && Number(rows[0].slice(tag.length)) === value);
    }
    requireValue(lines.filter(line => line === "_atom_site_occupancy").length === 1);
    const rows = lines.slice(lines.indexOf("_atom_site_occupancy") + 1).filter(Boolean).map(line => line.split(/\s+/));
    requireValue(rows.length === state.atoms.length);
    rows.forEach((row, i) => { const expected = state.atoms[i]; requireValue(row.length === 6 && row[0] === expected.label && row[1] === expected.element && row[5] === "1"); exact(row.slice(2, 5).map(Number), expected.fractional); });
  }
  return { batch, candidateId: candidate.id, lineage: { catalogue_version: catalog.version, catalog_state_id: state.id,
    original_occurrence_ids: [...state.occurrence_ids], original_cif_sha256: primary.cif_sha256, generated_cif_sha256: candidate.cif_sha256,
    generated_candidate_id: candidate.id, coordinate_model_equivalent: true } };
}
