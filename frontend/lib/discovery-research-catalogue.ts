// Server loader; clients import types only. Dataset pins are separate from generic validation.
import { createHash } from "node:crypto";
import data from "@/lib/discovery-research-catalogues/2026-10-06-retained-coordinate-proposals-v2.json";
import pins from "@/lib/discovery-research-catalogues/2026-10-06-retained-coordinate-proposals-v2.pins.json";
import { structureReference } from "@/lib/discovery-structures";

export type ResearchCell = Record<"a" | "b" | "c" | "alpha" | "beta" | "gamma", number>;
export type ResearchAtom = { id: string; label: string; element: string; fractional: [number, number, number]; occupancy: 1; source_site_label: string };
export type ResearchEdit = { target_id: string; source_site_label: string; original_element: string; kind: "substitution" | "vacancy"; element: string | null };
export type ResearchSource = { id: string; provider: "COD"; record_id: string; revision: number; cif_sha256: string; cif_url: string; entry_url: string;
  formula: string; phase: string | null; license: string; license_url: string; license_basis: string; capture_kind: "revision_url" | "mutable_current_file" };
export type ResearchParent = { id: string; source_id: string; reference_id: string; repeats: [number, number, number]; cell: ResearchCell; atoms: ResearchAtom[]; legacy_parent_id: string };
export type ResearchConditions = { pressure_gpa: null; temperature_k: null; charge_state: null; magnetic_state: null };
export type ResearchAxis = "stability" | "electronic" | "pairing" | "coherence" | "geometry" | "competing_order";
export type ResearchState = { id: string; group_id: string; parent_id: string; formula: string; composition: Record<string, number>;
  cell: ResearchCell; atoms: ResearchAtom[]; edits: ResearchEdit[]; strain_micro_percent: number; status: "unrelaxed"; conditions: ResearchConditions;
  occurrence_ids: string[]; primary_occurrence_id: string; score: null; rank: null; formal_approval: null;
  physical_axes: Record<ResearchAxis, { status: "unknown"; value: null }>;
  next_action: { kind: "state_method_input_review"; summary: string } };
export type ResearchGroup = { id: string; formula: string; reduced_formula: string; composition: Record<string, number>; source_id: string; host_formula: string; state_ids: string[] };
export type ResearchOccurrence = { id: string; state_id: string; legacy_candidate_id: string; source_batch_sha256: string; source_locator: string; cif_text: string; cif_sha256: string };
export type ResearchCatalogue = { schema_version: "research-proposal-catalog/2.0.0"; version: string; selection_basis: string;
  formal_scientific_release: false; rps_release: false; human_scientific_review: null;
  counts: { source_entries: number; coordinate_states: number; composition_groups: number; duplicate_occurrences: number };
  sources: ResearchSource[]; parents: ResearchParent[]; states: ResearchState[]; groups: ResearchGroup[]; occurrences: ResearchOccurrence[] };

const axes: ResearchAxis[] = ["stability", "electronic", "pairing", "coherence", "geometry", "competing_order"];
const cellKeys = ["a", "b", "c", "alpha", "beta", "gamma"] as const;
const conditions: ResearchConditions = { pressure_gpa: null, temperature_k: null, charge_state: null, magnetic_state: null };
const symbols = new Set("H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og".split(" "));
const hash = (text: string) => createHash("sha256").update(text, "utf8").digest("hex");
export function researchCanonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(researchCanonicalJson).join(",")}]`;
  if (value !== null && typeof value === "object") return `{${Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([key, child]) => `${JSON.stringify(key)}:${researchCanonicalJson(child)}`).join(",")}}`;
  if (typeof value === "number") {
    requireValue(Number.isFinite(value));
    const text = String(value);
    if (!text.includes("e")) return text;
    const [coefficient, exponent] = text.split("e"), negative = coefficient.startsWith("-");
    const [whole, fraction = ""] = coefficient.replace("-", "").split(".");
    const digits = whole + fraction, point = whole.length + Number(exponent);
    const decimal = point <= 0 ? `0.${"0".repeat(-point)}${digits}` : point >= digits.length ? digits + "0".repeat(point - digits.length) : `${digits.slice(0, point)}.${digits.slice(point)}`;
    return (negative ? "-" : "") + decimal;
  }
  return JSON.stringify(value);
}
const identity = (prefix: string, value: unknown) => `${prefix}:${hash(researchCanonicalJson(value))}`;
function requireValue(value: unknown): asserts value { if (!value) throw new Error("Research catalogue integrity validation failed."); }
const exact = (a: unknown, b: unknown) => requireValue(researchCanonicalJson(a) === researchCanonicalJson(b));
const round = (value: number) => Number(value.toPrecision(14));
function closed(value: unknown, keys: string[]): asserts value is Record<string, unknown> {
  requireValue(value !== null && typeof value === "object" && !Array.isArray(value));
  exact(Object.keys(value).sort(), [...keys].sort());
}
function bounded(value: unknown) {
  let nodes = 0;
  function visit(item: unknown, depth: number): void {
    requireValue(++nodes <= 50000 && depth <= 15);
    if (typeof item === "string") requireValue(item.length <= 65536 && !["/Users/", "/var/", "jack@"].some(v => item.includes(v)));
    else if (typeof item === "number") requireValue(Number.isFinite(item));
    else if (item !== null && typeof item === "object") {
      requireValue(Array.isArray(item) || Object.getPrototypeOf(item) === Object.prototype || Object.getPrototypeOf(item) === null);
      requireValue(Object.keys(item).length <= 200);
      for (const [key, child] of Object.entries(item)) { visit(key, depth + 1); visit(child, depth + 1); }
    } else requireValue(item === null || typeof item === "boolean");
  }
  visit(value, 0);
  requireValue(Buffer.byteLength(JSON.stringify(value)) <= 1024 * 1024);
}
function unique<T extends { id: string }>(items: T[], limit: number): Map<string, T> {
  requireValue(Array.isArray(items) && items.length > 0 && items.length <= limit);
  const map = new Map(items.map(item => [item.id, item]));
  requireValue(map.size === items.length && items.every(item => typeof item.id === "string"));
  return map;
}
function atoms(value: ResearchAtom[]) {
  requireValue(Array.isArray(value) && value.length > 0 && value.length <= 96);
  requireValue(new Set(value.map(a => a.id)).size === value.length && new Set(value.map(a => a.label)).size === value.length);
  for (const a of value) {
    closed(a, ["id", "label", "element", "fractional", "occupancy", "source_site_label"]);
    requireValue(typeof a.id === "string" && typeof a.label === "string" && typeof a.source_site_label === "string" && symbols.has(a.element));
    requireValue(a.occupancy === 1 && Array.isArray(a.fractional) && a.fractional.length === 3 && a.fractional.every(v => Number.isFinite(v) && v >= 0 && v < 1));
  }
}
function cell(value: ResearchCell) {
  closed(value, [...cellKeys]);
  requireValue(cellKeys.every(key => Number.isFinite(value[key]) && value[key] > 0 && (key.length === 1 || value[key] < 180)));
}
function composition(value: ResearchAtom[]) {
  const result: Record<string, number> = {};
  for (const atom of value) result[atom.element] = (result[atom.element] ?? 0) + 1;
  return result;
}
const gcd = (a: number, b: number): number => b ? gcd(b, a % b) : a;
const reduced = (value: Record<string, number>) => { const divisor = Object.values(value).reduce(gcd); return Object.fromEntries(Object.entries(value).map(([e, n]) => [e, n / divisor])); };
function formulaComposition(text: string): Record<string, number> {
  requireValue(typeof text === "string" && text.length <= 128 && /^(?:[A-Z][a-z]?(?:[1-9][0-9]*)?)+$/.test(text));
  const result: Record<string, number> = {};
  for (const match of text.matchAll(/([A-Z][a-z]?)([0-9]*)/g)) {
    requireValue(symbols.has(match[1]) && !Object.hasOwn(result, match[1]));
    result[match[1]] = Number(match[2] || 1);
  }
  return result;
}
function verifyCif(occurrence: ResearchOccurrence, state: ResearchState, source: ResearchSource) {
  requireValue(hash(occurrence.cif_text) === occurrence.cif_sha256 && occurrence.cif_text.endsWith("\n"));
  const lines = occurrence.cif_text.split("\n");
  requireValue(lines.includes("_symmetry_space_group_name_H-M 'P 1'") && lines.includes("_symmetry_Int_Tables_number 1"));
  requireValue(lines.includes(`# Source CIF SHA-256: ${source.cif_sha256}`) && lines.includes(`# Source: ${source.cif_url}`));
  for (const key of cellKeys) {
    const tag = `_cell_${key.length === 1 ? "length" : "angle"}_${key} `;
    const rows = lines.filter(line => line.startsWith(tag));
    requireValue(rows.length === 1 && Number(rows[0].slice(tag.length)) === state.cell[key]);
  }
  requireValue(lines.filter(line => line === "_atom_site_occupancy").length === 1);
  const rows = lines.slice(lines.indexOf("_atom_site_occupancy") + 1).filter(Boolean).map(line => line.split(/\s+/));
  requireValue(rows.length === state.atoms.length);
  rows.forEach((row, i) => {
    const a = state.atoms[i];
    requireValue(row.length === 6 && row[0] === a.label && row[1] === a.element && row[5] === "1");
    requireValue(row.slice(2, 5).every((v, axis) => /^[-+0-9.eE]+$/.test(v) && Number(v) === a.fractional[axis]));
  });
}

/** Generic structural contract; integrity is separate from scientific review and ranking. */
export function validateResearchCatalogue(value: unknown): ResearchCatalogue {
  bounded(value);
  closed(value, ["schema_version", "version", "selection_basis", "formal_scientific_release", "rps_release", "human_scientific_review", "counts", "sources", "parents", "states", "groups", "occurrences"]);
  const catalog = value as unknown as ResearchCatalogue;
  exact(catalog.schema_version, "research-proposal-catalog/2.0.0");
  requireValue(typeof catalog.version === "string" && /^[a-z0-9-]{1,100}$/.test(catalog.version) && typeof catalog.selection_basis === "string" && catalog.selection_basis.length > 0);
  exact([catalog.formal_scientific_release, catalog.rps_release, catalog.human_scientific_review], [false, false, null]);
  const sources = unique(catalog.sources, 100), parents = unique(catalog.parents, 100), states = unique(catalog.states, 100), groups = unique(catalog.groups, 100), occurrences = unique(catalog.occurrences, 200);
  for (const source of catalog.sources) {
    closed(source, ["id", "provider", "record_id", "revision", "cif_sha256", "cif_url", "entry_url", "formula", "phase", "license", "license_url", "license_basis", "capture_kind"]);
    exact(source.provider, "COD");
    const reference = structureReference(`cod-${source.record_id}`), original = reference.source;
    exact(source.id, identity("proposal-source", { cif_sha256: source.cif_sha256, record_id: reference.id }));
    exact([source.revision, source.cif_sha256, source.cif_url, source.entry_url, source.formula, source.license, source.license_url, source.license_basis, source.capture_kind],
      [original.captured_revision, original.file_sha256, original.cif_url, original.entry_url, reference.formula, original.license, original.license_url, original.license_basis, original.download_is_mutable_current_file ? "mutable_current_file" : "revision_url"]);
    exact(source.phase, "host_context" in reference ? reference.host_context?.phase ?? null : null);
  }
  for (const parent of catalog.parents) {
    closed(parent, ["id", "source_id", "reference_id", "repeats", "cell", "atoms", "legacy_parent_id"]);
    const source = sources.get(parent.source_id); requireValue(source);
    exact(parent.reference_id, `cod-${source.record_id}`);
    requireValue(/^supercell:[a-f0-9]{64}$/.test(parent.legacy_parent_id));
    requireValue(Array.isArray(parent.repeats) && parent.repeats.length === 3 && parent.repeats.every(n => Number.isInteger(n) && n >= 1 && n <= 4));
    const reference = structureReference(parent.reference_id);
    requireValue(reference.sites.every(site => site.occupancy.value === 1 && (site.occupancy.raw === null ? "basis" in site.occupancy && site.occupancy.basis === "cif_dictionary_default" : /^1(?:\.0*)?$/.test(site.occupancy.raw))));
    requireValue(!("host_context" in reference && reference.host_context?.coincident_site_pairs));
    const expectedAtoms: ResearchAtom[] = [];
    for (let i = 0; i < parent.repeats[0]; i++) for (let j = 0; j < parent.repeats[1]; j++) for (let k = 0; k < parent.repeats[2]; k++) {
      reference.display_unit_cell_sites.forEach((site, index) => expectedAtoms.push({ id: `image-${index}-cell-${i}-${j}-${k}`, label: `S${expectedAtoms.length + 1}`, element: site.element,
        fractional: site.fractional.map((v, axis) => round((v + [i, j, k][axis]) / parent.repeats[axis])) as [number, number, number], occupancy: 1, source_site_label: site.source_site_label }));
    }
    atoms(parent.atoms); cell(parent.cell); exact(parent.atoms, expectedAtoms);
    exact(parent.cell, Object.fromEntries(cellKeys.map((key, i) => [key, round(reference.lattice[key].value * (i < 3 ? parent.repeats[i] : 1))])));
    exact(parent.id, identity("proposal-parent", { source_id: parent.source_id, reference_id: parent.reference_id, repeats: parent.repeats, cell: parent.cell, atoms: parent.atoms }));
  }
  for (const state of catalog.states) {
    closed(state, ["id", "group_id", "parent_id", "formula", "composition", "cell", "atoms", "edits", "strain_micro_percent", "status", "conditions", "occurrence_ids", "primary_occurrence_id", "score", "rank", "formal_approval", "physical_axes", "next_action"]);
    const parent = parents.get(state.parent_id); requireValue(parent);
    requireValue(Array.isArray(state.edits) && state.edits.length <= 3 && new Set(state.edits.map(e => e.target_id)).size === state.edits.length);
    exact(state.edits.map(e => e.target_id), state.edits.map(e => e.target_id).sort());
    for (const edit of state.edits) {
      closed(edit, ["target_id", "source_site_label", "original_element", "kind", "element"]);
      const target = parent.atoms.find(a => a.id === edit.target_id); requireValue(target);
      exact([edit.original_element, edit.source_site_label], [target.element, target.source_site_label]);
      requireValue(edit.kind === "vacancy" ? edit.element === null : edit.kind === "substitution" && typeof edit.element === "string" && symbols.has(edit.element) && edit.element !== target.element);
    }
    requireValue(Number.isInteger(state.strain_micro_percent) && Math.abs(state.strain_micro_percent) <= 10000000 && (state.edits.length > 0 || state.strain_micro_percent !== 0));
    const expected = parent.atoms.flatMap(a => { const edit = state.edits.find(e => e.target_id === a.id); return edit?.kind === "vacancy" ? [] : [{ ...a, element: edit?.element ?? a.element }]; });
    atoms(state.atoms); cell(state.cell); exact(state.atoms, expected);
    exact(state.cell, Object.fromEntries(cellKeys.map(key => [key, round(parent.cell[key] * (key.length === 1 ? 1 + state.strain_micro_percent / 100000000 : 1))])));
    exact(state.composition, composition(state.atoms)); exact(formulaComposition(state.formula), state.composition);
    exact(state.status, "unrelaxed"); exact(state.conditions, conditions);
    exact(state.id, identity("proposal-state", { parent_id: state.parent_id, edits: state.edits, strain_micro_percent: state.strain_micro_percent, conditions: state.conditions, status: state.status }));
    exact([state.score, state.rank, state.formal_approval], [null, null, null]);
    exact(state.physical_axes, Object.fromEntries(axes.map(axis => [axis, { status: "unknown", value: null }])));
    exact(state.next_action, { kind: "state_method_input_review", summary: "Review the state, methods and reproducible inputs before relaxation." });
    requireValue(Array.isArray(state.occurrence_ids) && state.occurrence_ids.length > 0 && new Set(state.occurrence_ids).size === state.occurrence_ids.length && state.primary_occurrence_id === state.occurrence_ids[0]);
    exact(state.occurrence_ids, catalog.occurrences.filter(o => o.state_id === state.id).map(o => o.id));
    requireValue(groups.get(state.group_id)?.state_ids.includes(state.id));
  }
  for (const group of catalog.groups) {
    closed(group, ["id", "formula", "reduced_formula", "composition", "source_id", "host_formula", "state_ids"]);
    const source = sources.get(group.source_id); requireValue(source);
    exact(group.host_formula, source.formula); exact(formulaComposition(group.reduced_formula), group.composition);
    exact(reduced(formulaComposition(group.formula)), group.composition);
    exact(group.id, identity("proposal-group", { source_id: group.source_id, composition: group.composition }));
    requireValue(group.state_ids.length > 0);
    exact(group.state_ids, catalog.states.filter(s => s.group_id === group.id).map(s => s.id));
    for (const id of group.state_ids) { const state = states.get(id); requireValue(state); exact(reduced(state.composition), group.composition); exact(parents.get(state.parent_id)?.source_id, source.id); }
  }
  for (const occurrence of catalog.occurrences) {
    closed(occurrence, ["id", "state_id", "legacy_candidate_id", "source_batch_sha256", "source_locator", "cif_text", "cif_sha256"]);
    const state = states.get(occurrence.state_id); requireValue(state);
    requireValue(/^(?:site|combined)-candidate:[a-f0-9]{64}$/.test(occurrence.legacy_candidate_id) && /^[a-f0-9]{64}$/.test(occurrence.source_batch_sha256) && /^\/candidates\/(?:0|[1-9][0-9]*)$/.test(occurrence.source_locator));
    exact(occurrence.id, identity("proposal-occurrence", { source_batch_sha256: occurrence.source_batch_sha256, source_locator: occurrence.source_locator, legacy_candidate_id: occurrence.legacy_candidate_id, cif_sha256: occurrence.cif_sha256 }));
    const parent = parents.get(state.parent_id); requireValue(parent); const source = sources.get(parent.source_id); requireValue(source);
    verifyCif(occurrence, state, source);
  }
  requireValue(catalog.parents.every(p => catalog.states.some(s => s.parent_id === p.id)) && catalog.sources.every(s => catalog.parents.some(p => p.source_id === s.id)));
  exact(catalog.counts, { source_entries: occurrences.size, coordinate_states: states.size, composition_groups: groups.size, duplicate_occurrences: occurrences.size - states.size });
  return JSON.parse(JSON.stringify(catalog)) as ResearchCatalogue;
}

export function getResearchCatalogue(): ResearchCatalogue {
  const catalog = validateResearchCatalogue(data);
  exact(catalog.version, pins.version);
  exact(hash(researchCanonicalJson(catalog)), pins.sha256);
  return catalog;
}
