import rawBatch from "@/public/research-pilots/materials-source-followup-2026-10-02.json";

type Row = Record<string, unknown>;
const isRow = (value: unknown): value is Row => value != null && typeof value === "object" && !Array.isArray(value);
const FLAGS = ["formal_human_review", "formal_scientific_review", "scientific_acceptance", "ml_training_approved", "database_changed", "sample_identity_established", "phase_identity_established", "public_release_completed_at_preparation", "rights_to_original_fulltext_redistribution_established"];
const ORIGINAL_SHA = "af823526b7c2764c75c116c2d42e48fde3746feac8e5d6635fecaa34f7a41615";
export const sourceFollowupDownloadPath = `${process.env.NEXT_PUBLIC_BASE_PATH || ""}/research-pilots/materials-source-followup-2026-10-02.json`;

export interface SourceFollowupEntry {
  id: string; source_group: string; field: string; value: unknown;
  source_subject: Row; source_window: Row; source_role: string;
  sources: Row[]; field_locators: Row[]; limitations: string[]; inspection_status: string;
  belongs_to_remaining29_plan: boolean; selected_result_association: "unestablished";
}
export interface SourceFollowupBatch {
  version: "materials-source-followup/1.0.0"; prepared_at_utc: string; original_batch_sha256: string;
  planned_task_records: 29; planned_tasks_with_source_expressions: 26; planned_source_unavailable: 3;
  additional_pt_task_records: 5; total_records: 34; expression_metadata_records: 31;
  entries: SourceFollowupEntry[];
}
const groups: Record<string, { label: string; scope: string }> = {
  ysc: { label: "YScH₁₀ · calculation report", scope: "Official abstract metadata; detailed electron–phonon settings remain unavailable in the inspected source." },
  lasm: { label: "La₀.₄Sm₀.₆O₀.₅F₀.₅BiS₂ · preparation and probes", scope: "Database rows, preparation recommendations and separate pressure measurements retain their individual scopes." },
  sn_in: { label: "Sn₀.₉₅₅In₀.₀₄₅Te · composition and spectroscopy", scope: "The source supplies local x and probe interpretations; pairing claims retain their author-reported role." },
  sr_ni: { label: "SrFe₁.₈₄Ni₀.₁₆As₂ · source composition and curves", scope: "Nominal composition, curve definitions, model estimates and series protocols remain separate." },
  bapb: { label: "BaPb₀.₇₂Bi₀.₂₈O₃ · optical report", scope: "Optical conditions and author interpretations remain tied to the source's composition and figures." },
  motm: { label: "MoSr₂TmCu₂O₈ · Tm member", scope: "The Tm member's magnetic order and superconducting transition are distinct reports; neighboring members' fields are not transferred." },
  fese_cif: { label: "FeSe · independent COD crystallography", scope: "Independent historical CIF metadata. This source reference does not release a held catalogue record or establish a superconducting sample association." },
  pt_extra: { label: "Pt substituted BaFe₂As₂ · growth and specific heat", scope: "Growth conditions and heat-capacity analysis, with printed-unit conflicts and BCS/volume assumptions preserved." },
};

export function sourceFollowupHref(value: unknown): string | null {
  if (typeof value !== "string" || value.length > 2000) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password && !url.port
      && ["arxiv.org", "journals.aps.org", "doi.org", "www.crystallography.net", "mdr.nims.go.jp"].includes(url.hostname) ? url.href : null;
  } catch { return null; }
}
/** A fixed-snapshot contract: no arbitrary extra keys, altered values or conditions can enter the exported batch. */
function matchesSnapshot(value: unknown, expected: unknown, depth = 0): boolean {
  if (depth > 24) return false;
  if (expected === null || typeof expected !== "object") return value === expected
    && (typeof value !== "number" || Number.isFinite(value)) && (typeof value !== "string" || value.length <= 4000);
  if (Array.isArray(expected)) return Array.isArray(value) && value.length === expected.length && value.length <= 128
    && value.every((entry, index) => matchesSnapshot(entry, expected[index], depth + 1));
  if (!isRow(value) || !isRow(expected)) return false;
  const keys = Object.keys(expected);
  return keys.length <= 64 && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key) && matchesSnapshot(value[key], expected[key], depth + 1));
}
/** Source-byte and scientific checks are separate; this function only accepts the bundled, inspected finite projection. */
export function loadSourceFollowupBatch(value: unknown = rawBatch): SourceFollowupBatch | null {
  if (!isRow(value) || value.version !== "materials-source-followup/1.0.0" || value.original_batch_sha256 !== ORIGINAL_SHA
    || value.planned_task_records !== 29 || value.planned_tasks_with_source_expressions !== 26 || value.planned_source_unavailable !== 3
    || value.additional_pt_task_records !== 5 || value.total_records !== 34 || value.expression_metadata_records !== 31
    || value.canonical_promotions !== 0 || value.selected_result_association !== "unestablished" || FLAGS.some(flag => value[flag] !== false)
    || value.manuscript_fulltext_or_private_context_in_public_target_metadata !== false || !matchesSnapshot(value, rawBatch)
    || !Array.isArray(value.entries) || value.entries.length !== 34) return null;
  const entries = value.entries as Row[];
  if (new Set(entries.map(entry => entry.id)).size !== 34 || entries.filter(entry => entry.value !== null).length !== 31
    || entries.filter(entry => entry.belongs_to_remaining29_plan === true).length !== 29
    || entries.filter(entry => entry.inspection_status === "source_unavailable").length !== 3
    || entries.some(entry => !groups[String(entry.source_group)] || FLAGS.some(flag => entry[flag] !== false) || entry.canonical_promotions !== 0
      || entry.selected_result_association !== "unestablished" || !isRow(entry.source_subject) || !isRow(entry.source_window)
      || !Array.isArray(entry.sources) || entry.sources.some(source => !isRow(source) || !sourceFollowupHref(source.source_url)))) return null;
  return JSON.parse(JSON.stringify(value)) as SourceFollowupBatch;
}
export function groupSourceFollowup(batch: SourceFollowupBatch) {
  return Object.entries(groups).map(([id, { label, scope }]) => ({ id, label, scope, entries: batch.entries.filter(entry => entry.source_group === id) }));
}
export function downloadSourceFollowupGroup(groupId: string): boolean {
  const batch = loadSourceFollowupBatch(), group = batch && groupSourceFollowup(batch).find(entry => entry.id === groupId);
  if (!batch || !group || !group.entries.length) return false;
  const window = { version: "material-source-followup-window/1.0.0", original_batch_sha256: batch.original_batch_sha256,
    source_group: group.id, task_records: group.entries.length, expression_metadata_records: group.entries.filter(entry => entry.value !== null).length,
    entries: group.entries, selected_result_association: "unestablished", scientific_acceptance: false, canonical_promotions: 0 };
  const url = URL.createObjectURL(new Blob([JSON.stringify(window, null, 2) + "\n"], { type: "application/json;charset=utf-8" }));
  let link: HTMLAnchorElement | null = null;
  try {
    link = document.createElement("a"); link.href = url; link.download = `source-followup-${group.id}.json`;
    document.body.appendChild(link); link.click(); return true;
  } finally { link?.remove(); setTimeout(() => URL.revokeObjectURL(url), 0); }
}
