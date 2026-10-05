// Server-side catalog loader. Client components import only these types and receive validated props.
import { createHash } from "node:crypto";
import catalog from "@/lib/discovery-proposal-catalogues/2026-10-06-mgb2-site-proposals-v1.json";

export const RESEARCH_PROPOSAL_VERSION = "2026-10-06-mgb2-site-proposals-v1";
export const RESEARCH_PROPOSAL_MAX_BYTES = 1024 * 1024;
export type ResearchProposalAxis = "stability" | "electronic" | "pairing" | "coherence" | "geometry" | "competing_order";
export const RESEARCH_PROPOSAL_AXES: ResearchProposalAxis[] = [
  "stability", "electronic", "pairing", "coherence", "geometry", "competing_order",
];

const SOURCE = {
  provider: "COD", record_id: "1526507", revision: 176429,
  cif_sha256: "0eb4eaf6098974db2698bf97a0cd443ffff9a2fc3f6ba8ca31afbebd06c5363d",
  cif_url: "https://www.crystallography.net/cod/1526507.cif@176429",
  entry_url: "https://www.crystallography.net/cod/1526507.html",
  license: "CC0-1.0", license_url: "https://creativecommons.org/publicdomain/zero/1.0/",
  license_basis: "The captured COD entry links to CC0; the frozen CIF header states public domain. This records source evidence, not a new rights approval.",
} as const;
const CELL = { a: 6.1646, b: 6.1646, c: 7.02922, alpha: 90, beta: 90, gamma: 120 };
const TARGET = { id: "image-0-cell-0-0-0", label: "S1", source_label: "Mg1", element: "Mg", fractional: [0, 0, 0] };
const PARENT_ID = "supercell:9ebd97739a4c539e3a64540963d2b9183791fe129bd66f28ed9178fd3e1fe590";
const NEXT_ACTION = {
  kind: "state_method_input_review",
  summary: "Review the charge, magnetic state, pressure conditions and calculation methods; prepare a reproducible input before relaxation.",
} as const;
// Independent pins from the audited original generated CIF bytes, not hashes trusted from the JSON.
const STRUCTURES = [
  { formula: "Mg7AlB16", element: "Al", composition: { Mg: 7, Al: 1, B: 16 }, atom_count: 24,
    sha256: "1317bd3658d1e779cb1284962b4a14d0e17e8f45811d28ff933b297afb5e4f9a" },
  { formula: "Mg7CaB16", element: "Ca", composition: { Mg: 7, Ca: 1, B: 16 }, atom_count: 24,
    sha256: "02fa239a5863c5ec5e7b59f3710410b6aa238dd358987a8cb8ff31584d1e14da" },
  { formula: "Mg7B16", element: null, composition: { Mg: 7, B: 16 }, atom_count: 23,
    sha256: "29cedc2e7b0a93ec1d09f818a8bc0d41dead3b94d0a08a774f938997781da4a0" },
] as const;

export type ResearchProposal = {
  id: string;
  formula: string;
  host_formula: "MgB2";
  operation: {
    kind: "substitution" | "vacancy";
    element: "Al" | "Ca" | null;
    target: { id: string; label: string; source_label: string; element: "Mg"; fractional: [number, number, number] };
    repeats: [2, 2, 2]; changed_mg_sites: 1; host_mg_sites: 8; mg_site_fraction: 0.125;
  };
  structure: {
    atom_count: number; composition: Record<string, number>;
    cell: Record<"a" | "b" | "c" | "alpha" | "beta" | "gamma", number>;
    cif_text: string; cif_sha256: string;
  };
  status: "unrelaxed";
  score: null;
  rank: null;
  conditions: { pressure_gpa: null; temperature_k: null; charge_state: null; magnetic_state: null };
  formal_approval: null;
  physical_axes: Record<ResearchProposalAxis, { status: "unknown"; value: null }>;
  next_action: typeof NEXT_ACTION;
};

export type ResearchProposalCatalog = {
  schema_version: "research-proposal-catalog/1.0.0";
  version: typeof RESEARCH_PROPOSAL_VERSION;
  formal_scientific_release: false;
  rps_release: false;
  human_scientific_review: null;
  source: typeof SOURCE;
  reference: { formula: "MgB2"; role: "reference"; counts_as_proposal: false };
  proposals: ResearchProposal[];
};

function requireValue(condition: unknown): asserts condition {
  if (!condition) throw new Error("Research proposal catalog is invalid.");
}

function object(value: unknown, keys: readonly string[]): Record<string, unknown> {
  requireValue(value !== null && typeof value === "object" && !Array.isArray(value));
  const record = value as Record<string, unknown>;
  requireValue(Object.keys(record).length === keys.length && keys.every(key => Object.hasOwn(record, key)));
  return record;
}

function exact(value: unknown, expected: unknown): void {
  if (Array.isArray(expected)) {
    requireValue(Array.isArray(value) && value.length === expected.length);
    expected.forEach((item, index) => exact(value[index], item));
  } else if (expected !== null && typeof expected === "object") {
    const record = object(value, Object.keys(expected));
    Object.entries(expected).forEach(([key, item]) => exact(record[key], item));
  } else requireValue(value === expected);
}

function bounded(value: unknown): void {
  let nodes = 0;
  let textBytes = 0;
  const visit = (item: unknown, depth: number): void => {
    requireValue(++nodes <= 20000 && depth <= 12);
    if (typeof item === "string") {
      textBytes += Buffer.byteLength(item, "utf8");
      requireValue(item.length <= 65536 && textBytes <= RESEARCH_PROPOSAL_MAX_BYTES);
    } else if (typeof item === "number") requireValue(Number.isFinite(item));
    else if (item !== null && typeof item === "object") {
      requireValue(Array.isArray(item) || Object.getPrototypeOf(item) === Object.prototype || Object.getPrototypeOf(item) === null);
      const entries = Object.entries(item);
      requireValue(entries.length <= 100);
      for (const [key, child] of entries) { visit(key, depth + 1); visit(child, depth + 1); }
    } else requireValue(item === null || typeof item === "boolean");
  };
  visit(value, 0);
  requireValue(Buffer.byteLength(JSON.stringify(value), "utf8") <= RESEARCH_PROPOSAL_MAX_BYTES);
}

const hash = (value: string) => createHash("sha256").update(value, "utf8").digest("hex");

/** Parse only the pinned explicit-site CIF format, never arbitrary crystallographic syntax. */
function verifyCif(text: string, composition: unknown, atomCount: number, replacement: "Al" | "Ca" | null): void {
  const lines = text.split("\n");
  requireValue(text.endsWith("\n") && lines.includes("_symmetry_space_group_name_H-M 'P 1'"));
  requireValue(lines.includes(`# Source CIF SHA-256: ${SOURCE.cif_sha256}`));
  requireValue(lines.includes(`# Source: ${SOURCE.cif_url}`));
  for (const [key, value] of Object.entries(CELL)) {
    const prefix = ["a", "b", "c"].includes(key) ? "_cell_length_" : "_cell_angle_";
    requireValue(lines.includes(`${prefix}${key} ${value}`));
  }
  const start = lines.indexOf("_atom_site_occupancy");
  requireValue(start > 0);
  const rows = lines.slice(start + 1).filter(line => line !== "").map(line => line.split(" "));
  requireValue(rows.length === atomCount);
  const counts: Record<string, number> = {};
  const expanded = [[0, 0, 0], [0.3333, 0.6667, 0.5], [0.6666000000000001, 0.3333, 0.5]];
  const expected: { label: string; element: string; fractional: number[] }[] = [];
  let index = 0;
  for (let i = 0; i < 2; i++) for (let j = 0; j < 2; j++) for (let k = 0; k < 2; k++) {
    expanded.forEach((fractional, sourceIndex) => {
      const label = `S${++index}`;
      const element = label === "S1" ? replacement : sourceIndex === 0 ? "Mg" : "B";
      if (element !== null) expected.push({ label, element, fractional: fractional.map((v, axis) => (v + [i, j, k][axis]) / 2) });
    });
  }
  rows.forEach((row, i) => {
    requireValue(row.length === 6 && row[0] === expected[i].label && row[1] === expected[i].element && row[5] === "1");
    requireValue(row.slice(2, 5).every((v, axis) => Number.isFinite(Number(v)) && Math.abs(Number(v) - expected[i].fractional[axis]) <= 1e-12));
    counts[row[1]] = (counts[row[1]] ?? 0) + 1;
  });
  exact(composition, counts);
}

/** Closed, version-pinned public data. Integrity is not a scientific or publication approval. */
export function parseResearchProposalCatalog(value: unknown): ResearchProposalCatalog {
  bounded(value);
  const root = object(value, ["schema_version", "version", "formal_scientific_release", "rps_release", "human_scientific_review", "source", "reference", "proposals"]);
  exact(root.schema_version, "research-proposal-catalog/1.0.0");
  exact(root.version, RESEARCH_PROPOSAL_VERSION);
  exact(root.formal_scientific_release, false);
  exact(root.rps_release, false);
  exact(root.human_scientific_review, null);
  exact(root.source, SOURCE);
  exact(root.reference, { formula: "MgB2", role: "reference", counts_as_proposal: false });
  requireValue(Array.isArray(root.proposals) && root.proposals.length <= 100 && root.proposals.length === STRUCTURES.length);
  const ids = new Set<string>();
  for (const item of root.proposals) {
    const proposal = object(item, ["id", "formula", "host_formula", "operation", "structure", "status", "score", "rank", "conditions", "formal_approval", "physical_axes", "next_action"]);
    const pin = STRUCTURES.find(candidate => candidate.formula === proposal.formula);
    requireValue(pin);
    const operation = { kind: pin.element === null ? "vacancy" : "substitution", element: pin.element };
    const id = `site-candidate:${hash(JSON.stringify({ version: "discovery-site-candidates/1.0.0", parent_id: PARENT_ID, target_atom_id: TARGET.id, operation, cif_sha256: pin.sha256 }))}`;
    exact(proposal.id, id);
    requireValue(!ids.has(id)); ids.add(id);
    exact(proposal.host_formula, "MgB2");
    exact(proposal.operation, { ...operation, target: TARGET, repeats: [2, 2, 2], changed_mg_sites: 1, host_mg_sites: 8, mg_site_fraction: 0.125 });
    const structure = object(proposal.structure, ["atom_count", "composition", "cell", "cif_text", "cif_sha256"]);
    exact(structure.atom_count, pin.atom_count);
    exact(structure.composition, pin.composition);
    exact(structure.cell, CELL);
    exact(structure.cif_sha256, pin.sha256);
    requireValue(typeof structure.cif_text === "string" && hash(structure.cif_text) === pin.sha256);
    verifyCif(structure.cif_text, structure.composition, pin.atom_count, pin.element);
    exact(proposal.status, "unrelaxed");
    exact(proposal.score, null); exact(proposal.rank, null); exact(proposal.formal_approval, null);
    exact(proposal.conditions, { pressure_gpa: null, temperature_k: null, charge_state: null, magnetic_state: null });
    const axes = object(proposal.physical_axes, RESEARCH_PROPOSAL_AXES);
    RESEARCH_PROPOSAL_AXES.forEach(axis => exact(axes[axis], { status: "unknown", value: null }));
    exact(proposal.next_action, NEXT_ACTION);
  }
  return JSON.parse(JSON.stringify(value)) as ResearchProposalCatalog;
}

export function getResearchProposalCatalog(): ResearchProposalCatalog {
  return parseResearchProposalCatalog(catalog);
}
