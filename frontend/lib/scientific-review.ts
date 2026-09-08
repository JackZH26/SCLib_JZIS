/** Strict display admission only; never scientific acceptance or source rights. */
type ObjectValue = Record<string, unknown>;
export type ResearchRole = "curator" | "reviewer" | "publisher";
export interface ReviewCapabilities {
  version: "scientific-review-capabilities/1.0.0";
  roles: ResearchRole[];
  can_read: boolean;
  review_write_available: false;
}
export interface ReviewQueueItem {
  property_id: string;
  event_id: string;
  event_revision: number;
  material_id: string;
  formula: string;
  property_key: string;
  unit: string;
  knowledge_origin: string;
  review_status: string;
  validity_status: string;
}
export interface ReviewQueue {
  version: "scientific-review-queue/1.0.0";
  items: ReviewQueueItem[];
  next_cursor: string | null;
  has_more: boolean;
  total_count: null;
  count_basis: string;
}
export interface ReviewDossier {
  version: "scientific-result-dossier/1.0.0";
  descriptor_sha256: string;
  target: { property_id: string; event_id: string; event_revision: number };
  material: { id: string; formula: string };
  result: { property_key: string; registry_version: string; component_key: string; relation: string;
    value: number | null; lower: number | null; upper: number | null; unit: string };
  event: { event_type: string; knowledge_origin: string; review_status: string; validity_status: string };
  state: { id: string; resolution: string; pressure_status: string; pressure_gpa: number | null;
    temperature_role: string; temperature_k: number | null };
  structure: { id: string; structure_kind: string; artifact_id: string | null } | null;
  run: { id: string; run_kind: string; status: string } | null;
  sources: { artifact_id: string; kind: string; access: string; hash_status: string; bytes_sha256: string | null;
    evidence_link_ids: string[]; locators: ({ line: number; start_byte: number; end_byte: number }
      | { scope: "locator_not_disclosed" })[] }[];
  inventory: { row_count: number; artifact_count: number; sha256: string };
  warnings: string[];
  impact: { version: "scientific-result-impact/1.0.0"; scope: string[]; unsupported_scopes: string[];
    complete_for_scope: true; counts: Record<string, number>;
    items: { table: string; row_id: string; relation: string; via_table: string; via_id: string }[] };
  authority: { scientific_accepted: false; ml_training_approved: false; public_release: false; review_write_available: false };
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const HASH = /^[0-9a-f]{64}$/;
const CODE = /^[a-z][a-z0-9_]{0,119}$/;
const origins = ["Observed", "Computed", "Inferred", "AI-Proposed", "unknown"];
const reviews = ["pending", "approved", "rejected"];
const validities = ["pending", "accepted", "disputed", "retracted", "excluded"];
const COUNT_BASIS = "Canonical non-Tc, non-RPS properties; review status belongs to each parent event. This page is not a reviewed-result total.";
// Frozen rv2/1 quantities exposed by this endpoint, not ML admission profiles.
const PROPERTY_UNITS: Record<string, string> = {
  formation_energy_per_atom: "eV/atom", energy_above_hull: "eV/atom", band_gap: "eV",
  dos_at_fermi: "states/eV/formula_unit", electron_phonon_lambda: "1", omega_log: "K",
  phonon_min_frequency: "THz", superfluid_stiffness: "K",
};
const record = (value: unknown): value is ObjectValue => value !== null && typeof value === "object" && !Array.isArray(value);
function keys(value: unknown, names: string[]): value is ObjectValue {
  return record(value) && Object.keys(value).length === names.length && names.every(name => Object.hasOwn(value, name));
}
function text(value: unknown, max = 200): value is string {
  return typeof value === "string" && value.length <= max * 2 && value.trim().length > 0
    && !/[\u0000-\u001f\u007f]/.test(value) && Array.from(value).length <= max;
}
const uuid = (value: unknown): value is string => typeof value === "string" && UUID.test(value);
const hash = (value: unknown): value is string => typeof value === "string" && HASH.test(value);
const code = (value: unknown): value is string => typeof value === "string" && CODE.test(value);
const choice = (value: unknown, options: string[]) => typeof value === "string" && options.includes(value);
const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const integer = (value: unknown, max: number, min = 0): value is number => finite(value) && Number.isSafeInteger(value) && value >= min && value <= max;
const nullableNumber = (value: unknown) => value === null || finite(value);
function list(value: unknown, max: number, check: (item: unknown) => boolean): value is unknown[] {
  return Array.isArray(value) && value.length <= max && value.every(check);
}
function uniqueList(value: unknown, max: number, check: (item: unknown) => boolean): value is unknown[] {
  return list(value, max, check) && new Set(value).size === value.length;
}
function status(value: ObjectValue) {
  return choice(value.knowledge_origin, origins) && choice(value.review_status, reviews) && choice(value.validity_status, validities);
}
export function knownReviewCapabilities(value: unknown): ReviewCapabilities | null {
  if (!keys(value, ["version", "roles", "can_read", "review_write_available"])
    || value.version !== "scientific-review-capabilities/1.0.0" || value.review_write_available !== false
    || !uniqueList(value.roles, 3, role => choice(role, ["curator", "reviewer", "publisher"]))
    || typeof value.can_read !== "boolean"
    || value.can_read !== value.roles.some(role => role === "curator" || role === "reviewer")) return null;
  return value as unknown as ReviewCapabilities;
}
function queueItem(value: unknown): value is ReviewQueueItem {
  return keys(value, ["property_id", "event_id", "event_revision", "material_id", "formula", "property_key", "unit",
    "knowledge_origin", "review_status", "validity_status"])
    && uuid(value.property_id) && uuid(value.event_id) && integer(value.event_revision, 2147483647, 1)
    && text(value.material_id, 100) && text(value.formula, 512) && code(value.property_key)
    && Object.hasOwn(PROPERTY_UNITS, value.property_key) && value.unit === PROPERTY_UNITS[value.property_key] && status(value);
}
export function knownReviewQueue(value: unknown): ReviewQueue | null {
  if (!keys(value, ["version", "items", "next_cursor", "has_more", "total_count", "count_basis"])
    || value.version !== "scientific-review-queue/1.0.0" || !list(value.items, 50, queueItem)
    || new Set(value.items.map(item => (item as ReviewQueueItem).property_id)).size !== value.items.length
    || value.items.some((item, index, items) => index > 0 && (item as ReviewQueueItem).property_id <= (items[index - 1] as ReviewQueueItem).property_id)
    || value.total_count !== null || value.count_basis !== COUNT_BASIS || typeof value.has_more !== "boolean"
    || (value.has_more ? !uuid(value.next_cursor) || value.items.length === 0
      || value.next_cursor !== (value.items.at(-1) as ReviewQueueItem).property_id : value.next_cursor !== null)) return null;
  return value as unknown as ReviewQueue;
}
function quantity(value: ObjectValue) {
  if (![value.value, value.lower, value.upper].every(nullableNumber)) return false;
  switch (value.relation) {
    case "exact": return finite(value.value) && value.lower === null && value.upper === null;
    case "lt": case "le": return finite(value.upper) && value.value === null && value.lower === null;
    case "gt": case "ge": return finite(value.lower) && value.value === null && value.upper === null;
    case "interval": return finite(value.lower) && finite(value.upper) && value.value === null && value.lower <= value.upper;
    case "unreported": return value.value === null && value.lower === null && value.upper === null;
    default: return false;
  }
}
function source(value: unknown) {
  if (!keys(value, ["artifact_id", "kind", "access", "hash_status", "bytes_sha256", "evidence_link_ids", "locators"])
    || !uuid(value.artifact_id)
    || !choice(value.kind, ["literature_locator", "structure", "run_manifest", "policy", "review", "dataset", "other"])
    || !choice(value.access, ["public", "metadata_only", "restricted", "unknown"])
    || !(value.hash_status === "verified" ? hash(value.bytes_sha256)
      : choice(value.hash_status, ["unavailable", "not_applicable"]) && value.bytes_sha256 === null)
    || !uniqueList(value.evidence_link_ids, 200, uuid) || !list(value.locators, 200, item =>
      keys(item, ["scope"]) ? item.scope === "locator_not_disclosed"
        : keys(item, ["line", "start_byte", "end_byte"]) && integer(item.line, 1_000_000, 1)
          && integer(item.start_byte, 64 * 1024 * 1024) && integer(item.end_byte, 64 * 1024 * 1024)
          && item.end_byte >= item.start_byte)
    || value.evidence_link_ids.length !== value.locators.length) return false;
  return true;
}
function impact(value: unknown) {
  if (!keys(value, ["version", "scope", "unsupported_scopes", "complete_for_scope", "counts", "items"])
    || value.version !== "scientific-result-impact/1.0.0" || value.complete_for_scope !== true
    || !uniqueList(value.scope, 32, code) || !uniqueList(value.unsupported_scopes, 32, code)
    || !record(value.counts) || Object.keys(value.counts).length > 64
    || !Object.entries(value.counts).every(([key, count]) => code(key) && integer(count, 4000))
    || !list(value.items, 4000, item => keys(item, ["table", "row_id", "relation", "via_table", "via_id"])
      && code(item.table) && text(item.row_id, 200) && code(item.relation) && code(item.via_table) && text(item.via_id, 200))) return false;
  const items = value.items as ReviewDossier["impact"]["items"];
  const counts = value.counts as Record<string, number>;
  const nodes = new Map<string, Set<string>>();
  const relations = new Set<string>();
  for (const item of items) {
    if (!Object.hasOwn(counts, item.table)) return false;
    const ids = nodes.get(item.table) ?? new Set<string>();
    ids.add(item.row_id); nodes.set(item.table, ids);
    relations.add(JSON.stringify([item.table, item.row_id, item.relation, item.via_table, item.via_id]));
  }
  return relations.size === items.length && counts.total_relations === items.length
    && counts.total_nodes === Array.from(nodes.values()).reduce((sum, ids) => sum + ids.size, 0)
    && counts.total_nodes <= 2000
    && Object.entries(counts).every(([table, count]) => ["total_nodes", "total_relations"].includes(table) || count === (nodes.get(table)?.size ?? 0));
}
export function knownReviewDossier(value: unknown, expected: ReviewQueueItem): ReviewDossier | null {
  if (!queueItem(expected) || !keys(value, ["version", "descriptor_sha256", "target", "material", "result", "event", "state", "structure", "run",
    "sources", "inventory", "warnings", "impact", "authority"])
    || value.version !== "scientific-result-dossier/1.0.0" || !hash(value.descriptor_sha256)
    || !keys(value.target, ["property_id", "event_id", "event_revision"])
    || value.target.property_id !== expected.property_id || value.target.event_id !== expected.event_id
    || value.target.event_revision !== expected.event_revision
    || !keys(value.material, ["id", "formula"]) || value.material.id !== expected.material_id || value.material.formula !== expected.formula
    || !keys(value.result, ["property_key", "registry_version", "component_key", "relation", "value", "lower", "upper", "unit"])
    || value.result.property_key !== expected.property_key || value.result.unit !== expected.unit
    || value.result.registry_version !== "rv2/1" || !text(value.result.component_key, 120) || !quantity(value.result)
    || !["formation_energy_per_atom", "phonon_min_frequency"].includes(expected.property_key)
      && [value.result.value, value.result.lower, value.result.upper].some(number => finite(number) && number < 0)
    || !keys(value.event, ["event_type", "knowledge_origin", "review_status", "validity_status"])
    || !choice(value.event.event_type, ["measurement", "calculation", "extraction", "curation", "prediction", "priority_assessment"])
    || !status(value.event) || value.event.knowledge_origin !== expected.knowledge_origin
    || value.event.review_status !== expected.review_status || value.event.validity_status !== expected.validity_status
    || !keys(value.state, ["id", "resolution", "pressure_status", "pressure_gpa", "temperature_role", "temperature_k"])
    || !uuid(value.state.id) || !choice(value.state.resolution, ["resolved", "source_scoped", "unresolved"])
    || !(value.state.pressure_status === "explicit_ambient" ? value.state.pressure_gpa === 0
      : value.state.pressure_status === "reported" ? finite(value.state.pressure_gpa) && value.state.pressure_gpa >= 0
        : choice(value.state.pressure_status, ["not_reported", "ambiguous"]) && value.state.pressure_gpa === null)
    || !choice(value.state.temperature_role, ["measurement", "synthesis", "simulation", "unknown"])
    || !(value.state.temperature_k === null || finite(value.state.temperature_k) && value.state.temperature_k >= 0)
    || value.state.temperature_role === "unknown" && value.state.temperature_k !== null
    || !(value.structure === null || keys(value.structure, ["id", "structure_kind", "artifact_id"]) && uuid(value.structure.id)
      && choice(value.structure.structure_kind, ["coordinates", "prototype", "literature_description", "unresolved"])
      && (value.structure.artifact_id === null || uuid(value.structure.artifact_id))
      && (value.structure.structure_kind !== "coordinates" || value.structure.artifact_id !== null))
    || !(value.run === null || keys(value.run, ["id", "run_kind", "status"]) && uuid(value.run.id)
      && choice(value.run.run_kind, ["extraction", "composition_features", "structure_matching", "dft", "dfpt", "ml_prediction", "priority_assessment", "curation"])
      && choice(value.run.status, ["planned", "running", "completed", "failed", "cancelled"]))
    || !list(value.sources, 200, source)
    || new Set(value.sources.map(item => (item as { artifact_id: string }).artifact_id)).size !== value.sources.length
    || !keys(value.inventory, ["row_count", "artifact_count", "sha256"])
    || !integer(value.inventory.row_count, 1000, 1) || !integer(value.inventory.artifact_count, 200) || !hash(value.inventory.sha256)
    || value.inventory.artifact_count !== value.sources.length || value.inventory.row_count < value.inventory.artifact_count
    || !uniqueList(value.warnings, 100, code) || !impact(value.impact)
    || !keys(value.authority, ["scientific_accepted", "ml_training_approved", "public_release", "review_write_available"])
    || Object.values(value.authority).some(flag => flag !== false)) return null;
  return value as unknown as ReviewDossier;
}

export function reviewNumber(value: number): string {
  return new Intl.NumberFormat("en", { maximumSignificantDigits: 10 }).format(value);
}
export function reviewQuantity(result: ReviewDossier["result"]): string {
  const format = (value: number | null) => value === null ? "Not reported" : reviewNumber(value);
  const signs: Record<string, string> = { lt: "<", le: "≤", gt: ">", ge: "≥" };
  if (result.relation === "unreported") return "Not reported";
  if (result.relation === "interval") return `${format(result.lower)}–${format(result.upper)} ${result.unit}`;
  if (result.relation === "exact") return `${format(result.value)} ${result.unit}`;
  return `${signs[result.relation]} ${format(["lt", "le"].includes(result.relation) ? result.upper : result.lower)} ${result.unit}`;
}
