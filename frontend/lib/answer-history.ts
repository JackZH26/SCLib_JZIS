/** Historical receipt consistency is not scientific review or current source permission. */
import type { AskHistoryEntry, AskRequest, AskResponse, AskSource } from "@/lib/api";
import { knownEvidenceProvenance } from "@/lib/evidence-provenance";
import { knownInputBudget, knownPackingSummary } from "@/lib/evidence-packing";
import { knownScientificQuery, knownScientificLookup, knownScientificResults } from "@/lib/scientific-query";
import { knownScientificMixedResponse } from "@/lib/scientific-mixed";

export interface HistorySaveDisposition {
  version: "ask-history-save/1.0.0";
  status: "saved" | "not_saved" | "unknown" | "not_requested";
  history_id: string | null;
  receipt_sha256: string | null;
  reason_code: "guest_request" | "capture_unavailable" | "storage_unavailable" | "session_no_longer_authorized" | "commit_unconfirmed" | null;
}

export interface HistoryReceiptSummary {
  version: "ask-history-receipt-summary/1.0.0";
  status: "legacy_unpinned" | "recorded" | "unavailable";
  receipt_sha256: string | null;
}

type Row = Record<string, unknown>;
const row = (value: unknown): value is Row => value !== null && typeof value === "object" && !Array.isArray(value);
const keys = (value: unknown, fields: string[]): value is Row => row(value)
  && Object.keys(value).length === fields.length && fields.every(key => Object.hasOwn(value, key));
const uuid = (value: unknown): value is string => typeof value === "string"
  && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
const hash = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);

export function knownHistorySave(value: unknown): HistorySaveDisposition | null {
  if (!keys(value, ["version", "status", "history_id", "receipt_sha256", "reason_code"])
    || value.version !== "ask-history-save/1.0.0"
    || value.reason_code !== null && !["guest_request", "capture_unavailable", "storage_unavailable", "session_no_longer_authorized", "commit_unconfirmed"].includes(value.reason_code as string)) return null;
  if (value.status === "saved") {
    if (!uuid(value.history_id) || !hash(value.receipt_sha256) || value.reason_code !== null) return null;
  } else if (value.status === "unknown") {
    if (!uuid(value.history_id) || value.receipt_sha256 !== null || value.reason_code !== "commit_unconfirmed") return null;
  } else if (value.status === "not_saved" || value.status === "not_requested") {
    if (value.history_id !== null || value.receipt_sha256 !== null) return null;
    if (value.status === "not_requested" ? value.reason_code !== null && value.reason_code !== "guest_request"
      : !["capture_unavailable", "storage_unavailable", "session_no_longer_authorized"].includes(value.reason_code as string)) return null;
  } else return null;
  return value as unknown as HistorySaveDisposition;
}

export function knownHistorySummary(value: unknown): HistoryReceiptSummary | null {
  if (!keys(value, ["version", "status", "receipt_sha256"]) || value.version !== "ask-history-receipt-summary/1.0.0") return null;
  if (value.status === "recorded") {
    if (!hash(value.receipt_sha256)) return null;
  } else if (value.status === "legacy_unpinned" || value.status === "unavailable") {
    if (value.receipt_sha256 !== null) return null;
  } else return null;
  return value as unknown as HistoryReceiptSummary;
}

export type StoredAskResponse = Omit<AskResponse, "history" | "guest_remaining" | "remaining">;
export interface AnswerEvidenceItem {
  kind: "source" | "scientific_result";
  position: number;
  paper_id: string;
  chunk_id: string;
  content_sha256: string;
  member_record_sha256: string | null;
  chunk_revision_sha256: string | null;
  vector_sha256: string | null;
  source_snapshot_sha256: string | null;
  evidence_revision_id: string | null;
  evidence_record_sha256: string | null;
  parent_result_revision_id: string | null;
  parent_result_sha256: string | null;
  selection_input_sha256: string;
  selection_generation_pin_sha256: string | null;
  selection_grouping_sha256: string | null;
  has_evidence_pin: boolean;
}
export interface AnswerEvidenceBindings {
  version: "ask-answer-evidence/1.0.0";
  mode: "no_selected_evidence" | "generation_bound" | "snapshot_only";
  generation_id: string | null;
  activation_event_id: string | null;
  manifest_sha256: string | null;
  items: AnswerEvidenceItem[];
}
export interface AnswerEvidenceReceipt {
  version: "ask-answer-evidence/1.0.0";
  history_id: string;
  record_sha256: string;
  request_sha256: string;
  response_sha256: string;
  bindings_sha256: string;
  request: Required<AskRequest>;
  response: StoredAskResponse;
  bindings: AnswerEvidenceBindings;
}
export interface HistoryDetail {
  version: "ask-history-detail/1.0.0";
  entry: AskHistoryEntry;
  result_current_evidence: Record<string, unknown>;
  evidence: {
    status: "verified" | "legacy_unpinned" | "unavailable";
    binding_scope: "generation_members" | "legacy_snapshot" | "no_selected_evidence" | null;
    receipt: AnswerEvidenceReceipt | null;
    historical_integrity_verified: boolean;
    scientific_acceptance: false;
    ml_training_approved: false;
    public_release_authorized: false;
    currentness_revalidated: false;
    reason_codes: string[];
  };
}

const integer = (value: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): value is number => typeof value === "number"
  && Number.isSafeInteger(value) && value >= min && value <= max;
const text = (value: unknown, max: number, min = 0): value is string => typeof value === "string"
  && Array.from(value).length >= min && Array.from(value).length <= max;
const choice = (value: unknown, options: string[]) => typeof value === "string" && options.includes(value);
const strings = (value: unknown, max = 100, length = 8192): value is string[] => Array.isArray(value)
  && value.length <= max && value.every(item => text(item, length));
const nullableHash = (value: unknown) => value === null || hash(value);
const nullableUuid = (value: unknown) => value === null || uuid(value);

/** Resource validation before serializing or traversing nested metadata. */
function boundedJson(value: unknown, maxBytes: number): boolean {
  const pending: [unknown, number][] = [[value, 0]];
  let nodes = 0, characters = 0;
  while (pending.length) {
    const [item, depth] = pending.pop()!;
    if (++nodes > 100000 || depth > 32) return false;
    if (typeof item === "string") characters += item.length;
    else if (Array.isArray(item)) {
      if (item.length + pending.length + nodes > 100000) return false;
      for (const child of item) pending.push([child, depth + 1]);
    }
    else if (row(item)) {
      const fields = Object.keys(item);
      if (fields.length + pending.length + nodes > 100000) return false;
      for (const key of fields) { characters += key.length; pending.push([item[key], depth + 1]); }
    } else if (item !== null && typeof item !== "boolean" && (typeof item !== "number" || !Number.isFinite(item))) return false;
    if (characters > maxBytes || pending.length > 100000) return false;
  }
  try { return new TextEncoder().encode(JSON.stringify(value)).length <= maxBytes; } catch { return false; }
}

function equal(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  if (Array.isArray(left)) return Array.isArray(right) && left.length === right.length && left.every((item, index) => equal(item, right[index]));
  return row(left) && row(right) && Object.keys(left).length === Object.keys(right).length
    && Object.keys(left).every(key => Object.hasOwn(right, key) && equal(left[key], right[key]));
}

const RESPONSE_FIELDS = ["scientific_mixed", "evidence_packing", "input_budget", "retrieval_generation", "scientific_query",
  "scientific_lookup", "scientific_results", "answer", "sources", "tokens_used", "query_time_ms", "citation_valid",
  "citation_warnings", "support_policy_version", "citation_indices_valid", "lexical_support_checked", "scientific_support_status",
  "claim_assessments", "support_warnings", "support_coverage", "answer_mode", "assessment_scope"];
const SOURCE_FIELDS = ["index", "paper_id", "arxiv_id", "title", "authors_short", "year", "section", "snippet",
  "material_evidence", "source_visibility", "evidence_provenance", "packing_info"];
function source(value: unknown): value is AskSource {
  return keys(value, SOURCE_FIELDS) && integer(value.index, 1, 20) && text(value.paper_id, 100, 1)
    && (value.arxiv_id === null || text(value.arxiv_id, 300)) && text(value.title, 20000) && text(value.authors_short, 20000)
    && (value.year === null || integer(value.year, 0, 9999)) && (value.section === null || text(value.section, 2048))
    && text(value.snippet, 8192) && Array.isArray(value.material_evidence) && value.material_evidence.every(row)
    && row(value.source_visibility) && row(value.evidence_provenance)
    && (Object.keys(value.evidence_provenance).length === 0 || knownEvidenceProvenance(value.evidence_provenance) !== null);
}
function generation(value: unknown): boolean {
  if (!keys(value, ["version", "mode", "generation_id", "activation_event_id", "manifest_sha256"]) || value.version !== "index-read/1.0.0") return false;
  return value.mode === "generation_snapshot" ? uuid(value.generation_id) && uuid(value.activation_event_id) && hash(value.manifest_sha256)
    : value.mode === "legacy_lexical_only" && [value.generation_id, value.activation_event_id, value.manifest_sha256].every(item => item === null);
}
function claim(value: unknown): boolean {
  return keys(value, ["claim_id", "text", "cited_indices", "status", "reason_codes", "evidence", "quantities"])
    && text(value.claim_id, 200, 1) && text(value.text, 100000) && Array.isArray(value.cited_indices)
    && value.cited_indices.length <= 100 && value.cited_indices.every(item => integer(item, 1))
    && choice(value.status, ["supported", "contradicted", "undetermined", "not_checked"]) && strings(value.reason_codes)
    && Array.isArray(value.evidence) && value.evidence.length <= 100 && value.evidence.every(item =>
      keys(item, ["source_index", "paper_id", "excerpt"]) && integer(item.source_index, 1) && text(item.paper_id, 100, 1) && text(item.excerpt, 100000))
    && (row(value.quantities) || Array.isArray(value.quantities) && value.quantities.every(row));
}
function storedResponse(value: unknown, rawQuery: string): value is StoredAskResponse {
  if (!keys(value, RESPONSE_FIELDS) || !text(value.answer, 1024 * 1024) || !Array.isArray(value.sources)
    || value.sources.length > 20 || !value.sources.every(source) || value.sources.some((item, index) => item.index !== index + 1)
    || value.tokens_used !== null && !integer(value.tokens_used) || !integer(value.query_time_ms)
    || ["citation_valid", "citation_indices_valid", "lexical_support_checked"].some(key => typeof value[key] !== "boolean")
    || !strings(value.citation_warnings) || !strings(value.support_warnings) || !text(value.support_policy_version, 160, 1)
    || !choice(value.scientific_support_status, ["supported", "contradicted", "undetermined", "not_checked"])
    || !choice(value.answer_mode, ["synthesis", "limited_synthesis", "extractive_fallback", "abstention"])
    || !choice(value.assessment_scope, ["generated_draft", "none"]) || !row(value.support_coverage)
    || !Array.isArray(value.claim_assessments) || value.claim_assessments.length > 100 || !value.claim_assessments.every(claim)
    || !generation(value.retrieval_generation)) return false;
  const query = value.scientific_query === null ? null : knownScientificQuery(value.scientific_query, rawQuery);
  const lookup = knownScientificLookup(value.scientific_lookup);
  if (value.scientific_query !== null && !query || !lookup || !Array.isArray(value.scientific_results)) return false;
  if (query ? knownScientificResults(value.scientific_results, lookup, value.retrieval_generation, query) === null
    : lookup.status !== "not_requested" || value.scientific_results.length !== 0) return false;
  const packing = knownPackingSummary(value.evidence_packing, value.sources), budget = knownInputBudget(value.input_budget);
  if (!packing || !budget || packing.status === "packed" && budget.payload_bytes !== null && packing.payload_bytes !== budget.payload_bytes) return false;
  return knownScientificMixedResponse(value, rawQuery) !== null;
}

const ITEM_FIELDS = ["kind", "position", "paper_id", "chunk_id", "content_sha256", "member_record_sha256", "chunk_revision_sha256",
  "vector_sha256", "source_snapshot_sha256", "evidence_revision_id", "evidence_record_sha256", "parent_result_revision_id",
  "parent_result_sha256", "selection_input_sha256", "selection_generation_pin_sha256", "selection_grouping_sha256", "has_evidence_pin"];
function bindingItem(value: unknown): value is AnswerEvidenceItem {
  return keys(value, ITEM_FIELDS) && choice(value.kind, ["source", "scientific_result"]) && integer(value.position, 1, 20)
    && text(value.paper_id, 100, 1) && text(value.chunk_id, 200, 1) && hash(value.content_sha256) && hash(value.selection_input_sha256)
    && ["member_record_sha256", "chunk_revision_sha256", "vector_sha256", "source_snapshot_sha256", "evidence_record_sha256",
      "parent_result_sha256", "selection_generation_pin_sha256", "selection_grouping_sha256"].every(key => nullableHash(value[key]))
    && nullableUuid(value.evidence_revision_id) && nullableUuid(value.parent_result_revision_id)
    && (value.evidence_revision_id === null) === (value.evidence_record_sha256 === null)
    && (value.parent_result_revision_id === null) === (value.parent_result_sha256 === null)
    && (value.parent_result_revision_id === null || value.evidence_revision_id !== null)
    && typeof value.has_evidence_pin === "boolean" && (value.has_evidence_pin || value.evidence_revision_id === null);
}

/** SQL digests are checked server-side; here we check shape and exact displayed references, not PostgreSQL hash spelling. */
export function knownAnswerReceipt(value: unknown): AnswerEvidenceReceipt | null {
  if (!boundedJson(value, 1024 * 1024) || !keys(value, ["version", "history_id", "record_sha256", "request_sha256", "response_sha256", "bindings_sha256", "request", "response", "bindings"])
    || value.version !== "ask-answer-evidence/1.0.0" || !uuid(value.history_id)
    || ![value.record_sha256, value.request_sha256, value.response_sha256, value.bindings_sha256].every(hash)
    || !keys(value.request, ["question", "max_sources", "language"]) || !text(value.request.question, 2000, 3)
    || !value.request.question.trim() || !integer(value.request.max_sources, 1, 20)
    || !choice(value.request.language, ["auto", "en", "zh"]) || !storedResponse(value.response, value.request.question)) return null;
  const b = value.bindings, response = value.response;
  if (!keys(b, ["version", "mode", "generation_id", "activation_event_id", "manifest_sha256", "items"])
    || b.version !== "ask-answer-evidence/1.0.0" || !nullableUuid(b.generation_id) || !nullableUuid(b.activation_event_id)
    || !nullableHash(b.manifest_sha256) || !Array.isArray(b.items) || b.items.length > value.request.max_sources || !b.items.every(bindingItem)) return null;
  const generated = b.generation_id !== null;
  if (generated !== (b.activation_event_id !== null) || generated !== (b.manifest_sha256 !== null)
    || b.mode !== (!b.items.length ? "no_selected_evidence" : generated ? "generation_bound" : "snapshot_only")
    || !["generation_id", "activation_event_id", "manifest_sha256"].every(key => b[key] === (response.retrieval_generation as unknown as Row)[key])
    || new Set(b.items.map(item => item.chunk_id)).size !== b.items.length) return null;
  const sources = b.items.filter(item => item.kind === "source"), results = b.items.filter(item => item.kind === "scientific_result");
  if (sources.length !== response.sources.length || results.length !== response.scientific_results!.length
    || !equal(b.items, [...sources, ...results]) || [sources, results].some(items => items.some((item, index) => item.position !== index + 1))) return null;
  for (const item of b.items) {
    const pins = [item.member_record_sha256, item.chunk_revision_sha256, item.vector_sha256, item.source_snapshot_sha256, item.selection_generation_pin_sha256];
    if (generated ? pins.some(pin => pin === null) || item.evidence_revision_id === null || !item.has_evidence_pin
      || item.chunk_id !== `ig62_${String(b.generation_id).replaceAll("-", "")}_${item.chunk_revision_sha256}`
      : pins.some(pin => pin !== null) || item.kind === "scientific_result") return null;
    if (item.kind === "scientific_result" && item.parent_result_revision_id === null) return null;
  }
  const evidenceFields = ["content_sha256", "evidence_revision_id", "evidence_record_sha256", "parent_result_revision_id", "parent_result_sha256"] as const;
  for (const [index, item] of sources.entries()) {
    const source = response.sources[index], packing = source.packing_info, evidence = source.evidence_provenance;
    if (source.index !== item.position || source.paper_id !== item.paper_id || !packing || packing.chunk_id !== item.chunk_id
      || packing.position !== item.position || packing.source_snapshot_sha256 !== item.source_snapshot_sha256
      || (item.has_evidence_pin ? !evidence || evidenceFields.some(key => evidence[key] !== item[key])
        : !!evidence && Object.keys(evidence).length > 0)) return null;
  }
  for (const [index, item] of results.entries()) {
    const binding = response.scientific_results![index].binding;
    if (binding.vector_id !== item.chunk_id || binding.paper_id !== item.paper_id || evidenceFields.some(key => binding[key] !== item[key])) return null;
  }
  return value as unknown as AnswerEvidenceReceipt;
}

export function knownHistoryDetail(value: unknown, expectedId: string): HistoryDetail | null {
  if (!uuid(expectedId) || !boundedJson(value, 3 * 1024 * 1024) || !keys(value, ["version", "entry", "evidence", "result_current_evidence"])
    || value.version !== "ask-history-detail/1.0.0" || !row(value.result_current_evidence)) return null;
  const entry = value.entry, evidence = value.evidence;
  if (!keys(entry, ["id", "question", "answer", "sources", "current_evidence", "receipt", "tokens_used", "latency_ms", "language", "created_at"])
    || entry.id !== expectedId || !text(entry.question, 100000) || !text(entry.answer, 1024 * 1024)
    || !Array.isArray(entry.sources) || entry.sources.length > 50 || !entry.sources.every(row) || !row(entry.current_evidence)
    || !knownHistorySummary(entry.receipt) || entry.tokens_used !== null && !integer(entry.tokens_used) || !integer(entry.latency_ms)
    || entry.language !== null && !text(entry.language, 10) || !text(entry.created_at, 40) || !Number.isFinite(Date.parse(entry.created_at))) return null;
  if (!keys(evidence, ["status", "binding_scope", "receipt", "historical_integrity_verified", "scientific_acceptance", "ml_training_approved", "public_release_authorized", "currentness_revalidated", "reason_codes"])
    || [evidence.scientific_acceptance, evidence.ml_training_approved, evidence.public_release_authorized, evidence.currentness_revalidated].some(flag => flag !== false)) return null;
  const summary = knownHistorySummary(entry.receipt)!;
  if (evidence.status === "verified") {
    const receipt = knownAnswerReceipt(evidence.receipt);
    if (!receipt || receipt.history_id !== entry.id || receipt.record_sha256 !== summary.receipt_sha256
      || summary.status !== "recorded" || evidence.historical_integrity_verified !== true || !equal(evidence.reason_codes, [])
      || evidence.binding_scope !== ({ generation_bound: "generation_members", snapshot_only: "legacy_snapshot", no_selected_evidence: "no_selected_evidence" }[receipt.bindings.mode])
      || receipt.request.question !== entry.question || receipt.request.language !== entry.language
      || receipt.response.answer !== entry.answer || receipt.response.tokens_used !== entry.tokens_used
      || receipt.response.query_time_ms !== entry.latency_ms || !equal(receipt.response.sources, entry.sources)) return null;
  } else {
    if (!choice(evidence.status, ["legacy_unpinned", "unavailable"]) || evidence.binding_scope !== null || evidence.receipt !== null
      || evidence.historical_integrity_verified !== false || !equal(evidence.reason_codes, [evidence.status === "legacy_unpinned" ? "legacy_receipt_not_recorded" : "receipt_unavailable"])
      || evidence.status === "legacy_unpinned" && summary.status !== "legacy_unpinned") return null;
  }
  return value as unknown as HistoryDetail;
}
