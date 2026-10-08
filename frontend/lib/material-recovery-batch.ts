import type { MaterialEnrichmentReport } from "./api";

export interface MaterialRecoveryBatch {
  version: "materials-recovery-batch-seed/1.0.0";
  seed_id: string;
  seed_sha256: string;
  material_id: string;
  formula: string;
  status: "checked";
  summary: string;
  unknowns: string[];
  pending_candidates_in_batch: number;
  retained_result_refs: { paper_id: string; result_id: string; record_sha256: string }[];
  observations: Array<{
    id: string; field: string; label: string; value: string;
    knowledge_origin: "Observed" | "Computed";
    scope: string; source_content_inspected: true;
    inspection_actor: "AI-assisted source check";
    sample_association_status: "pending";
    source: { paper_id: string; source_revision: string; source_url: string;
      capture_sha256: string; content_sha256: string;
      locator: { page: number; section: string };
      span: { char_start: number; char_end: number; text_sha256: string };
      source_status: "unknown" };
  }>;
  scientific_acceptance: false;
  human_reviewed: false;
  database_changed: false;
}
const object = (v: unknown): Record<string, unknown> | null => typeof v === "object" && v !== null && !Array.isArray(v) ? v as Record<string, unknown> : null;
const sha = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const text = (v: unknown, max = 1000) => typeof v === "string" && v.trim().length > 0 && v.length <= max;
const count = (v: unknown) => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;

/** API provenance guard. The server binds every occurrence to the current raw record. */
export function verifiedRecoveryBatch(report: MaterialEnrichmentReport, materialId: string): MaterialRecoveryBatch | null {
  const v = object(report.source_recovery_batch);
  if (!v || v.version !== "materials-recovery-batch-seed/1.0.0" || v.material_id !== materialId
    || !text(v.formula, 500) || !text(v.seed_id, 100) || !sha(v.seed_sha256) || v.status !== "checked"
    || !text(v.summary) || !count(v.pending_candidates_in_batch)
    || v.scientific_acceptance !== false || v.human_reviewed !== false || v.database_changed !== false
    || !Array.isArray(v.unknowns) || v.unknowns.length > 12 || !v.unknowns.every(x => text(x))
    || !Array.isArray(v.retained_result_refs) || v.retained_result_refs.length < 1 || v.retained_result_refs.length > 32
    || !v.retained_result_refs.every(x => { const r = object(x); return r && text(r.paper_id, 100) && text(r.result_id, 150) && sha(r.record_sha256); })
    || !Array.isArray(v.observations) || v.observations.length < 1 || v.observations.length > 12) return null;
  const ids = new Set<string>();
  for (const item of v.observations) {
    const o = object(item), s = object(o?.source), l = object(s?.locator), span = object(s?.span);
    if (!o || !s || !l || !span || !text(o.id, 150) || ids.has(o.id as string)
      || !text(o.field, 100) || !text(o.label, 160) || !text(o.value, 500) || !text(o.scope)
      || !["Observed", "Computed"].includes(o.knowledge_origin as string)
      || o.source_content_inspected !== true || o.sample_association_status !== "pending"
      || o.inspection_actor !== "AI-assisted source check" || s.source_status !== "unknown"
      || !text(s.paper_id, 100) || !text(s.source_revision, 100)
      || typeof s.source_url !== "string" || !/^https:\/\/arxiv\.org\/pdf\/\d{4}\.\d{4,5}v\d+$/.test(s.source_url)
      || !sha(s.capture_sha256) || !sha(s.content_sha256)
      || !count(l.page) || (l.page as number) < 1 || !text(l.section)
      || !count(span.char_start) || !count(span.char_end) || (span.char_end as number) <= (span.char_start as number)
      || !sha(span.text_sha256)) return null;
    ids.add(o.id as string);
  }
  const checked = v as unknown as MaterialRecoveryBatch;
  // Export the approved metadata shape, not arbitrary extra API context.
  return {
    version: checked.version, seed_id: checked.seed_id, seed_sha256: checked.seed_sha256,
    material_id: checked.material_id, formula: checked.formula, status: checked.status,
    summary: checked.summary, unknowns: [...checked.unknowns],
    pending_candidates_in_batch: checked.pending_candidates_in_batch,
    scientific_acceptance: false, human_reviewed: false, database_changed: false,
    retained_result_refs: checked.retained_result_refs.map(r => ({ paper_id: r.paper_id, result_id: r.result_id, record_sha256: r.record_sha256 })),
    observations: checked.observations.map(o => ({
      id: o.id, field: o.field, label: o.label, value: o.value, scope: o.scope,
      knowledge_origin: o.knowledge_origin, source_content_inspected: true,
      inspection_actor: "AI-assisted source check", sample_association_status: "pending",
      source: { paper_id: o.source.paper_id, source_revision: o.source.source_revision,
        source_url: o.source.source_url, capture_sha256: o.source.capture_sha256,
        content_sha256: o.source.content_sha256, source_status: "unknown",
        locator: { page: o.source.locator.page, section: o.source.locator.section },
        span: { char_start: o.source.span.char_start, char_end: o.source.span.char_end, text_sha256: o.source.span.text_sha256 } },
    })),
  };
}
