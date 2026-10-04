import snapshot from "@/public/research-pilots/materials-mdr-organic-240322.json";

export const ORGANIC_ROUTE = "/materials/source-references/organic";
export const ORGANIC_FILE = "materials-mdr-organic-240322.json";
export const ORGANIC_SHA256 = "5da57e0959d1ea0c081460dbf24a62b2eacfcb0d179ad1bfcbc272bdfd2ea3bd";
export const ORGANIC_PAGE_SIZE = 20;
export type OrganicRow = typeof snapshot.rows[number];
export type OrganicParams = Record<string, string | string[] | undefined>;
export type OrganicFilters = { q: string; structure: string; field: string; row: string; page: number };
const columns = new Map(snapshot.columns.map((key, index) => [key, index]));
export const organicPropertyFields = ["tc", "tcmax", "pcrit", "pmax", "tcn", "tcmeth", "lata", "latb", "latc", "alpha", "beta", "lgamma", "isotope", "isoel", "dtcdp", "hc1zero", "hc2zero", "dhc2dt", "cohere", "penet", "glpar", "gap", "gapmeth", "gamma", "debyet", "curiet", "neelt"];
const labels: Record<string, string> = { tc: "Tc (critical / atmospheric pressure)", tcmax: "Maximum Tc under pressure", pcrit: "Critical pressure (GPa)", pmax: "Pressure at maximum Tc (raw)", tcn: "Non-SC test temperature limit", tcmeth: "Tc method", lata: "Lattice a", latb: "Lattice b", latc: "Lattice c", alpha: "Lattice α", beta: "Lattice β", lgamma: "Lattice γ", isotope: "Isotope exponent", isoel: "Isotope element", dtcdp: "dTc/dP at P = 0", hc1zero: "Hc1 at 0 K", hc2zero: "Hc2 at 0 K", dhc2dt: "−dHc2/dT at Tc", cohere: "Coherence length at 0 K", penet: "Penetration depth at 0 K", glpar: "GL parameter (source glpar)", gap: "Energy gap at 0 K", gapmeth: "Gap method", gamma: "Electronic specific heat coefficient", debyet: "Debye temperature", curiet: "Curie temperature", neelt: "Néel temperature" };
const tcMethods: Record<string, string> = { "1": "Magnetization", "2": "AC susceptibility", "3": "Resistivity", "4": "Heat capacity", "5": "Tunneling", "6": "Infrared spectroscopy", "7": "Thermal conductivity", "8": "Raman spectroscopy", "9": "Nuclear magnetic resonance", "10": "Surface impedance", "11": "Neutron diffraction", "12": "Photoemission spectroscopy", "13": "Microwave transmission", "14": "Other method" };
const gapMethods: Record<string, string> = { "1": "Tunneling", "2": "Infrared spectroscopy", "3": "Thermal conductivity", "4": "Raman spectroscopy", "5": "AC susceptibility", "6": "Nuclear magnetic resonance", "7": "Surface impedance", "8": "Neutron diffraction", "9": "Ultraviolet photoemission spectroscopy", "10": "Microwave transmission" };
const shapes: Record<string, string> = { "1": "Single phase bulk", "2": "Multiphase bulk", "3": "Single crystal bulk", "4": "Film", "5": "Film (single)" };

export const organicAssetPath = (name: string) => `${process.env.NEXT_PUBLIC_BASE_PATH || ""}/research-pilots/${name}`;
export function organicCell(row: OrganicRow, field: string): string { const i = columns.get(field); return i === undefined ? "" : row.values[i]; }
export function organicLabel(field: string): string { return labels[field] ?? snapshot.source_labels[columns.get(field) ?? -1] ?? field; }
export function organicCode(field: string, value: string): string {
  if (!value) return "Not supplied";
  const label = (field === "tcmeth" ? tcMethods : field === "gapmeth" ? gapMethods : field === "shape" ? shapes : {})[value];
  return label ? `${label} (code ${value})` : `Unresolved code ${value}`;
}
export function organicSnapshot() { return structuredClone(snapshot); }
export function organicStructures(): string[] { return [...new Set(snapshot.rows.map(row => organicCell(row, "str")).filter(Boolean))].sort((a, b) => a.localeCompare(b, "en")); }

export function organicQuery(params: OrganicParams) {
  const errors: string[] = [];
  const read = (key: string, limit = 128) => {
    const raw = params[key];
    if (raw === undefined) return "";
    if (typeof raw !== "string" || raw.length > limit || /[\u0000-\u001f\u007f]/.test(raw)) { errors.push(`Invalid ${key} filter.`); return ""; }
    return raw.trim();
  };
  const q = read("q"), structure = read("structure"), field = read("field", 32), row = read("row", 10), pageRaw = read("page", 5);
  if (Object.keys(params).some(key => !["q", "structure", "field", "row", "page"].includes(key))) errors.push("Unknown filter parameter.");
  if (structure && !organicStructures().includes(structure)) errors.push("Unknown source structure label.");
  if (field && !organicPropertyFields.includes(field)) errors.push("Unknown property field.");
  if (row && !/^[1-9][0-9]*$/.test(row)) errors.push("Invalid source row ID.");
  if (pageRaw && !/^(0|[1-9][0-9]{0,3})$/.test(pageRaw)) errors.push("Invalid page number.");
  const filters: OrganicFilters = { q, structure, field, row, page: pageRaw && /^(0|[1-9][0-9]{0,3})$/.test(pageRaw) ? Number(pageRaw) : 0 };
  const textFields = ["num", "fullname", "name", "str", "refno", "title", "journal", "commt", "comments", "isoel", "sample"];
  const rows = errors.length ? [] : snapshot.rows.filter(item => (!row || item.id === row)
    && (!structure || organicCell(item, "str") === structure) && (!field || organicCell(item, field) !== "")
    && (!q || textFields.some(key => organicCell(item, key).toLocaleLowerCase("en-US").includes(q.toLocaleLowerCase("en-US")))));
  return { filters, errors, rows: structuredClone(rows), pages: Math.max(1, Math.ceil(rows.length / ORGANIC_PAGE_SIZE)) };
}

export function organicHref(filters: OrganicFilters, page = 0, exportRows = false): string {
  const params = new URLSearchParams();
  for (const key of ["q", "structure", "field", "row"] as const) if (filters[key]) params.set(key, filters[key]);
  if (!exportRows && page) params.set("page", String(page));
  return `${ORGANIC_ROUTE}${exportRows ? "/export" : ""}${params.size ? `?${params}` : ""}`;
}

export function organicExport(params: OrganicParams): string {
  const result = organicQuery(params);
  if (result.errors.length) throw new Error(result.errors.join(" "));
  const { page: _page, ...filters } = result.filters;
  const { rows: _rows, ...metadata } = snapshot;
  return JSON.stringify({ version: "mdr-organic-filtered-export/1.0.0", source_snapshot_sha256: ORGANIC_SHA256,
    filters, matches: result.rows.length, scope: "all_matching_source_rows_not_only_the_visible_page",
    source_dataset: metadata, rows: result.rows }, null, 2) + "\n";
}
