import rawBatch from "@/public/research-pilots/materials-pressure-table-sources-2026-10-02.json";
import biSubject from "@/public/research-pilots/materials-pressure-table-bitecl-2026-10-02.json";
import moColumn2 from "@/public/research-pilots/materials-pressure-table-mo-column-2-2026-10-02.json";
import moColumn3 from "@/public/research-pilots/materials-pressure-table-mo-column-3-2026-10-02.json";

type Row = Record<string, unknown>;
export interface SourceQuantity {
  raw_value: string; raw_unit?: string | null; value?: number | null; unit?: string | null;
  status: "parsed" | "unit_requires_review" | "source_statement";
}
export interface PressureTableEntry {
  id: string; source_subject_id: string; source_id: string; expression_key: string; field_id: string;
  subject: { formula: string; sample_label: string | null };
  window: { id: string; raw_label: string }; value: SourceQuantity;
  conditions: { field_id: string; role: string; value: SourceQuantity }[];
  locator: { page: number; table: string | null; row: number | null; column: number | null; section: string; member: string };
  field_spans: Row; status: "pending"; selected_result_association: "unestablished";
}
export interface PressureTableSource {
  id: string; paper_id: string; source_url: string; source_revision: string; captured_at_utc: string;
  parent_pdf_sha256: string; source_content_sha256: string; prepared_package_file_sha256: string;
  pdf_internal_date_raw?: string; official_arxiv_v1_submission_date: string;
}
export interface PressureTableBatch {
  version: "materials-pressure-table-sources/1.0.0"; prepared_on: string;
  expression_count: 18; source_case_count: 2; source_subject_count: 3;
  entries: PressureTableEntry[]; sources: PressureTableSource[];
  source_label_conflict: { caption_and_main_text_pressure_raw: string; inset_legend_pressure_raw: string; resolved: false };
}
const flags = ["sample_identity_established", "phase_identity_established", "scientific_acceptance", "ml_training_approved", "formal_human_review", "formal_scientific_review", "database_changed"];
const isRow = (value: unknown): value is Row => value !== null && typeof value === "object" && !Array.isArray(value);
const subjects: Record<string, { file: string; metadata: unknown }> = {
  bitecl: { file: "materials-pressure-table-bitecl-2026-10-02.json", metadata: biSubject },
  mo_nominal_column_2: { file: "materials-pressure-table-mo-column-2-2026-10-02.json", metadata: moColumn2 },
  mo_nominal_column_3: { file: "materials-pressure-table-mo-column-3-2026-10-02.json", metadata: moColumn3 },
};

export const pressureTableDownloadPath = `${process.env.NEXT_PUBLIC_BASE_PATH || ""}/research-pilots/materials-pressure-table-sources-2026-10-02.json`;
export function pressureTableSourceHref(value: unknown, page?: number): string | null {
  if (typeof value !== "string" || value.length > 2000) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.hostname !== "arxiv.org" || url.username || url.password || url.port
      || !/^\/pdf\/(1501\.06203|1603\.02892)$/.test(url.pathname)) return null;
    if (page !== undefined) {
      if (!Number.isSafeInteger(page) || page < 1 || page > 30) return null;
      url.hash = `page=${page}`;
    }
    return url.href;
  } catch { return null; }
}
function matchesSnapshot(value: unknown, expected: unknown, depth = 0): boolean {
  if (depth > 24) return false;
  if (expected === null || typeof expected !== "object") return value === expected
    && (typeof value !== "number" || Number.isFinite(value)) && (typeof value !== "string" || value.length <= 4000);
  if (Array.isArray(expected)) return Array.isArray(value) && value.length === expected.length && value.length <= 128
    && value.every((entry, index) => matchesSnapshot(entry, expected[index], depth + 1));
  if (!isRow(value) || !isRow(expected)) return false;
  const keys = Object.keys(expected);
  return keys.length <= 64 && Object.keys(value).length === keys.length
    && keys.every(key => Object.hasOwn(value, key) && matchesSnapshot(value[key], expected[key], depth + 1));
}
/** This finite metadata snapshot grants no sample association, scientific acceptance or source redistribution rights. */
export function loadPressureTableBatch(value: unknown = rawBatch): PressureTableBatch | null {
  if (!isRow(value) || value.version !== "materials-pressure-table-sources/1.0.0" || value.expression_count !== 18
    || value.source_case_count !== 2 || value.source_subject_count !== 3 || value.canonical_promotions !== 0
    || value.status !== "pending" || value.selected_result_association !== "unestablished" || flags.some(flag => value[flag] !== false)
    || value.counts_are_independent_experiments !== false || value.original_fulltext_or_private_context_included !== false
    || value.rights_to_original_fulltext_redistribution_established !== false || !matchesSnapshot(value, rawBatch)
    || !Array.isArray(value.entries) || value.entries.length !== 18 || !Array.isArray(value.sources) || value.sources.length !== 2) return null;
  if (value.entries.some(entry => !isRow(entry) || entry.status !== "pending" || entry.canonical_promotions !== 0
    || entry.selected_result_association !== "unestablished" || flags.some(flag => entry[flag] !== false))
    || value.sources.some(source => !isRow(source) || !pressureTableSourceHref(source.source_url))
    || new Set(value.entries.map(entry => (entry as Row).expression_key)).size !== 18) return null;
  return JSON.parse(JSON.stringify(value)) as PressureTableBatch;
}
export function pressureTableSubjectEntries(batch: PressureTableBatch, subjectId: string): PressureTableEntry[] {
  return batch.entries.filter(entry => entry.source_subject_id === subjectId);
}
/** A readable static subject resource preserves the whole batch's scientific identity and authority boundary. */
export function loadPressureTableSubject(subjectId: string, value: unknown = subjects[subjectId]?.metadata): Row | null {
  const batch = loadPressureTableBatch();
  if (!batch || !Object.hasOwn(subjects, subjectId)) return null;
  const entries = pressureTableSubjectEntries(batch, subjectId);
  if (entries.length !== 6) return null;
  const sourceIds = new Set(entries.map(entry => entry.source_id));
  const expected = { version: "material-pressure-table-subject/1.0.0",
    original_batch_sha256: "788144f67d439d0a5051e3b5144c988311e5423ccfa56402beb5566744ebe284",
    source_subject_id: subjectId, expression_count: entries.length,
    entries, sources: batch.sources.filter(source => sourceIds.has(source.id)),
    ...(subjectId === "bitecl" ? { source_label_conflict: batch.source_label_conflict } : {}),
    status: "pending", selected_result_association: "unestablished", scientific_acceptance: false, canonical_promotions: 0,
    sample_identity_established: false, phase_identity_established: false, ml_training_approved: false,
    formal_human_review: false, formal_scientific_review: false, database_changed: false,
    original_fulltext_or_private_context_included: false, counts_are_independent_experiments: false,
    rights_to_original_fulltext_redistribution_established: false };
  return matchesSnapshot(value, expected) && matchesSnapshot(value, subjects[subjectId].metadata)
    ? JSON.parse(JSON.stringify(value)) as Row : null;
}
export function pressureTableSubjectPath(subjectId: string): string | null {
  return loadPressureTableSubject(subjectId)
    ? `${process.env.NEXT_PUBLIC_BASE_PATH || ""}/research-pilots/${subjects[subjectId].file}` : null;
}
