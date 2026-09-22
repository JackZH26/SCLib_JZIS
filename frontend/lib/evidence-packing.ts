/** Operational display guards, never evidence/root/permission adjudication. */
import type { EvidencePackingSelection, EvidencePackingSummary, RagInputBudgetReport } from "@/lib/api";
import { knownEvidenceProvenance } from "@/lib/evidence-provenance";

type Row = Record<string, unknown>;
const row = (value: unknown): value is Row => value !== null && typeof value === "object" && !Array.isArray(value);
function keys(value: unknown, expected: string[]): value is Row {
  return row(value) && Object.keys(value).length === expected.length && expected.every(key => Object.hasOwn(value, key));
}
const oneOf = (value: unknown, choices: string[]) => typeof value === "string" && choices.includes(value);
const integer = (value: unknown, min: number, max: number): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= min && value <= max;
const nullableInteger = (value: unknown, min: number, max: number) => value === null || integer(value, min, max);
const hash = (value: unknown) => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
const bounded = (value: unknown, max: number): value is string => typeof value === "string" && !!value.trim() && Array.from(value).length <= max && !/[\u0000-\u001f\u007f]/.test(value);

export function knownPackingSelection(value: unknown): EvidencePackingSelection | null {
  if (!keys(value, ["version", "position", "chunk_id", "source_group_id", "source_snapshot_sha256", "diversity_group_id", "source_group_basis", "group_basis", "role_hint", "selection_reason", "scientific_acceptance"])
    || value.version !== "evidence-pack-item/1.0.0" || !integer(value.position, 1, 20) || !bounded(value.chunk_id, 200)
    || typeof value.source_group_id !== "string" || !/^src:[0-9a-f]{64}$/.test(value.source_group_id)
    || typeof value.diversity_group_id !== "string" || !/^div:[0-9a-f]{64}$/.test(value.diversity_group_id)
    || !oneOf(value.source_group_basis, ["source_snapshot", "legacy_paper"])
    || !oneOf(value.group_basis, ["accepted_work_mapping", "source_snapshot", "legacy_paper"])
    || !oneOf(value.role_hint, ["methods", "results", "table", "other"])
    || !oneOf(value.selection_reason, ["source_diversity", "source_coverage", "complementary_role"])
    || value.scientific_acceptance !== false) return null;
  if (value.source_group_basis === "source_snapshot" ? !hash(value.source_snapshot_sha256) : value.source_snapshot_sha256 !== null) return null;
  if (value.group_basis !== "accepted_work_mapping" && value.group_basis !== value.source_group_basis
    || value.selection_reason === "complementary_role" && (value.source_group_basis === "legacy_paper" || value.role_hint === "other")) return null;
  return value as unknown as EvidencePackingSelection;
}

export function knownInputBudget(value: unknown): RagInputBudgetReport | null {
  if (!keys(value, ["status", "model", "profile", "request_sha256", "payload_bytes", "byte_limit", "input_tokens", "max_input_tokens", "count_method", "generation_started", "scientific_acceptance"])
    || !oneOf(value.status, ["not_requested", "counted", "rejected", "unavailable"])
    || value.model !== null && (typeof value.model !== "string" || !/^gemini-[A-Za-z0-9][A-Za-z0-9._-]{0,119}$/.test(value.model))
    || value.profile !== "sclib-gemini-text-rag/1.0.0" || value.request_sha256 !== null && !hash(value.request_sha256)
    || !nullableInteger(value.payload_bytes, 1, Number.MAX_SAFE_INTEGER) || !integer(value.byte_limit, 1, 1048576)
    || !nullableInteger(value.input_tokens, 1, 2147483647) || !nullableInteger(value.max_input_tokens, 1, 131072)
    || value.count_method !== "provider_count_tokens" || value.generation_started !== null && typeof value.generation_started !== "boolean"
    || value.scientific_acceptance !== false) return null;
  if (value.status === "not_requested" && [value.model, value.request_sha256, value.payload_bytes,
    value.input_tokens, value.max_input_tokens, value.generation_started].some(field => field !== null)
    || value.status === "counted" && value.generation_started !== true
    || value.status === "rejected" && value.generation_started) return null;
  if ((value.status === "counted" || value.generation_started)
    && (value.model === null || value.request_sha256 === null || !integer(value.payload_bytes, 1, value.byte_limit)
      || !integer(value.input_tokens, 1, 2147483647) || !integer(value.max_input_tokens, 1, 131072)
      || value.input_tokens > value.max_input_tokens)) return null;
  return value as unknown as RagInputBudgetReport;
}

export type PackingSource = { index?: unknown; paper_id?: unknown; packing_info?: unknown; evidence_provenance?: unknown };

/** Validate declared source-snapshot grouping; this cannot establish a root or Work mapping. */
export function knownPackingInventory(sources: PackingSource[]): EvidencePackingSelection[] | null {
  if (sources.length > 20) return null;
  const items: EvidencePackingSelection[] = [];
  const groups = new Map<string, { paper: string; snapshot: string | null; diversity: string; basis: string; count: number }>();
  const sourceKeys = new Map<string, string>(), diversityBases = new Map<string, string>();
  const chunks = new Set<string>(), diversity = new Set<string>();
  for (const [position, source] of sources.entries()) {
    const item = knownPackingSelection(source.packing_info);
    if (!item || !bounded(source.paper_id, 100) || source.index !== position + 1 || item.position !== source.index || chunks.has(item.chunk_id)) return null;
    const existing = groups.get(item.source_group_id);
    const expectedReason = !diversity.has(item.diversity_group_id) ? "source_diversity" : !existing ? "source_coverage" : "complementary_role";
    if (item.selection_reason !== expectedReason) return null;
    if (item.selection_reason === "complementary_role" && (knownEvidenceProvenance(source.evidence_provenance)?.chunk_kind !== "original_passage"
      || items.some(other => other.source_group_id === item.source_group_id && other.role_hint === item.role_hint))) return null;
    if (existing && (existing.paper !== source.paper_id || existing.snapshot !== item.source_snapshot_sha256
      || existing.diversity !== item.diversity_group_id || existing.basis !== item.group_basis)) return null;
    const sourceKey = JSON.stringify([source.paper_id, item.source_snapshot_sha256]);
    if (sourceKeys.has(sourceKey) && sourceKeys.get(sourceKey) !== item.source_group_id
      || diversityBases.has(item.diversity_group_id) && diversityBases.get(item.diversity_group_id) !== item.group_basis) return null;
    const count = (existing?.count ?? 0) + 1;
    if (count > (item.source_group_basis === "legacy_paper" ? 1 : 3)) return null;
    groups.set(item.source_group_id, { paper: source.paper_id, snapshot: item.source_snapshot_sha256, diversity: item.diversity_group_id, basis: item.group_basis, count });
    sourceKeys.set(sourceKey, item.source_group_id);
    diversityBases.set(item.diversity_group_id, item.group_basis);
    diversity.add(item.diversity_group_id);
    chunks.add(item.chunk_id);
    items.push(item);
  }
  for (const item of items) {
    if (item.group_basis !== "accepted_work_mapping" && items.some(other => other.diversity_group_id === item.diversity_group_id && other.source_group_id !== item.source_group_id)
      || item.group_basis === "accepted_work_mapping" && items.filter(other => other.diversity_group_id === item.diversity_group_id).length > 3) return null;
  }
  return items;
}

const exclusions = ["payload_budget", "base_payload_budget", "chunk_limit", "source_limit", "work_limit", "duplicate_content", "role_already_represented", "not_complementary_original"];
const reasons = ["packing_not_requested", "no_admitted_candidates", "base_payload_budget_exceeded", "payload_budget_excluded", "selection_limits_applied", "duplicate_content_removed", "complementarity_not_established", "packing_unavailable", "selected_context_withheld"];

export function knownPackingSummary(value: unknown, sources: PackingSource[]): EvidencePackingSummary | null {
  if (!keys(value, ["version", "status", "candidate_count", "selected_count", "source_group_count", "diversity_group_count", "payload_bytes", "byte_budget", "byte_count_method", "max_chunks", "max_per_source", "max_per_work", "reason_counts", "reason_codes", "independent_support_count", "independence_status", "scientific_acceptance"])
    || value.version !== "evidence-packing/1.0.0" || !oneOf(value.status, ["not_requested", "packed", "empty", "base_budget_exceeded", "withheld", "unavailable"])
    || !integer(value.candidate_count, 0, 300) || !integer(value.selected_count, 0, 20)
    || !integer(value.source_group_count, 0, 20) || !integer(value.diversity_group_count, 0, 20)
    || !nullableInteger(value.payload_bytes, 0, 67108864) || !nullableInteger(value.byte_budget, 1, 16777216)
    || value.byte_count_method !== "utf8-full-payload/1" || !integer(value.max_chunks, 1, 20)
    || !integer(value.max_per_source, 1, 3) || !integer(value.max_per_work, 1, 3)
    || !row(value.reason_counts) || Object.entries(value.reason_counts).some(([key, count]) => !exclusions.includes(key) || !integer(count, 1, 300))
    || !Array.isArray(value.reason_codes) || value.reason_codes.length > 9 || value.reason_codes.some(item => !oneOf(item, reasons))
    || new Set(value.reason_codes).size !== value.reason_codes.length || value.independent_support_count !== null
    || value.independence_status !== "independence_not_established" || value.scientific_acceptance !== false) return null;
  if (!(value.diversity_group_count <= value.source_group_count && value.source_group_count <= value.selected_count
    && value.selected_count <= value.candidate_count && value.selected_count <= value.max_chunks)) return null;
  if (["not_requested", "withheld", "unavailable"].includes(value.status as string)) {
    if (value.selected_count !== 0 || value.source_group_count !== 0 || value.diversity_group_count !== 0
      || value.payload_bytes !== null || Object.keys(value.reason_counts).length) return null;
    if (value.status === "not_requested" ? value.candidate_count !== 0 || value.byte_budget !== null
      || sources.some(source => source.packing_info !== null && source.packing_info !== undefined) : sources.length > 0) return null;
  } else {
    if (!integer(value.payload_bytes, 0, 67108864) || !integer(value.byte_budget, 1, 16777216)
      || Object.values(value.reason_counts).reduce<number>((total, count) => total + (count as number), 0) !== value.candidate_count - value.selected_count) return null;
    if (value.status === "base_budget_exceeded" ? value.selected_count !== 0 || value.payload_bytes <= value.byte_budget
      : value.payload_bytes > value.byte_budget || (value.selected_count > 0) !== (value.status === "packed")) return null;
    const items = knownPackingInventory(sources);
    if (!items || items.length !== value.selected_count || new Set(items.map(item => item.source_group_id)).size !== value.source_group_count
      || new Set(items.map(item => item.diversity_group_id)).size !== value.diversity_group_count
      || items.some(item => items.filter(other => other.source_group_id === item.source_group_id).length > (value.max_per_source as number)
        || item.group_basis === "accepted_work_mapping" && items.filter(other => other.diversity_group_id === item.diversity_group_id).length > (value.max_per_work as number))) return null;
  }
  return value as unknown as EvidencePackingSummary;
}
