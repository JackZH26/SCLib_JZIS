/** Source-scoped review DTOs. Admission never assigns scientific eligibility. */
export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type Body = { [key: string]: Json };
export type Authority = { scientific_acceptance: false; ml_training_eligible: false; canonical_identity_assigned: false; review_write_available: false; public_release: false };
export type ProposalRow = { local_id: string; review_status: "pending_review" | "quarantined"; issues: string[]; normalized: Body; payload: Body; source_path: string };
export type ProposalRun = { run_id: string; packet_sha256: string; bundle_sha256: string; work_id: string; title: string; created_at: string; worker_state: string; result_count: number; model: string; extraction_version: string | null };
export type ProposalQueue = { version: "materials-proposal-review/1"; items: ProposalRun[]; after: string | null; work_id: string | null; next_cursor: string | null; authority: Authority };
export type ProposalDetail = { version: "materials-proposal-review/1"; run: ProposalRun; after: string | null; results: ProposalRow[]; next_cursor: string | null; entities: Record<"samples" | "states" | "protocols" | "sample_relations" | "condition_supports", ProposalRow[]>; source_documents: Body[]; coverage: Body; validation: Body; training_exclusions: Body[]; authority: Authority };
export type ProposalEvidence = { version: "materials-proposal-review/1"; run_id: string; packet_sha256: string; result_id: string; after: number; total_count: number; scope_paths: string[]; items: { ordinal: number; path: string; block_id: string; block_sha256: string; document_id: string; locator: string; start_char: number; end_char: number; quote_sha256: string; quote: string }[]; next_cursor: number | null; authority: Authority };
export type ProposalExport = { version: "materials-proposal-export/1" | "materials-proposal-export/2" | "materials-proposal-export/4" | "materials-proposal-export/5"; scope: "complete_retained_run"; run: ProposalRun; authority: Authority; filename: string; bytes: number; sha256: string; counts: Record<string, number>; files: { name: string; bytes: number; sha256: string }[] };
export type ProjectorSourceQuote = { block_id: string; document_id: string; locator: string; block_sha256: string; quote_sha256: string; start_char: number; end_char: number; quote: string };
export type ProjectorReview = {
  version: "materials-projector-review-context/1"; graph_authorship: string; provider: string; model: string; reasoning: string;
  producer_interface: string; evidence_binding: string;
  terminal: { job_id: string; attempt_id: string; receipt_sha256: string; config_sha256: string; raw_output_sha256: string; state: string; outcome: string; error_code: string | null; diagnostic: Body | null };
  disposition: "draft_pending_review" | "unparsed_model_graph"; raw_result_objects: number | null; retained_result_rows: number;
  publication_version: string; coverage_sha256: string;
  findings_author: { kind: "assistant"; identity: string; thread_id: string } | null; findings_created_at: string | null; findings_sha256: string | null;
  findings: { id: string; kind: "entity" | "source_completeness"; path: string; code: string; note: string; source_quotes: ProjectorSourceQuote[] }[];
  source_completeness_findings: number; independent_review: false; paper_completed: false; scientific_acceptance: false; ml_training_eligible: false;
};
const VERSION = "materials-proposal-review/1";
const hash = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
const record = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === "string" && v.length <= 200000;
const integer = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const nullableText = (v: unknown) => v === null || text(v);
function keys(v: unknown, names: string[]): v is Record<string, unknown> { return record(v) && Object.keys(v).length === names.length && names.every(k => Object.hasOwn(v, k)); }
function json(v: unknown, depth = 0): v is Json {
  if (depth > 12) return false;
  if (v === null || typeof v === "boolean" || text(v)) return true;
  if (typeof v === "number") return Number.isFinite(v);
  if (Array.isArray(v)) return v.length <= 20000 && v.every(x => json(x, depth + 1));
  return record(v) && Object.keys(v).length <= 2000 && Object.values(v).every(x => json(x, depth + 1));
}
const body = (v: unknown): v is Body => record(v) && json(v);
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.length <= 20000 && v.every(text);
function authority(v: unknown): v is Authority { return keys(v, ["scientific_acceptance", "ml_training_eligible", "canonical_identity_assigned", "review_write_available", "public_release"]) && Object.values(v).every(x => x === false); }
function run(v: unknown): v is ProposalRun {
  return keys(v, ["run_id", "packet_sha256", "bundle_sha256", "work_id", "title", "created_at", "worker_state", "result_count", "model", "extraction_version"])
    && hash(v.run_id) && hash(v.packet_sha256) && hash(v.bundle_sha256) && text(v.work_id) && v.work_id.startsWith("arxiv:")
    && text(v.title) && text(v.created_at) && Number.isFinite(Date.parse(v.created_at))
    && ["succeeded", "quarantined", "failed"].includes(String(v.worker_state)) && integer(v.result_count) && text(v.model)
    && (v.extraction_version === null || /^materials-ner\/(?:[1-9]|10|11|12|13|14|15)$/.test(String(v.extraction_version)));
}
function row(v: unknown): v is ProposalRow {
  return keys(v, ["local_id", "review_status", "issues", "normalized", "payload", "source_path"])
    && text(v.local_id) && v.local_id.length > 0 && v.local_id.length <= 200 && ["pending_review", "quarantined"].includes(String(v.review_status))
    && strings(v.issues) && body(v.normalized) && body(v.payload) && v.payload.id === v.local_id && text(v.source_path) && /^\/[a-z_]+\/\d+$/.test(v.source_path);
}
function rows(v: unknown): v is ProposalRow[] { return Array.isArray(v) && v.length <= 2000 && v.every(row) && new Set(v.map(x => x.local_id)).size === v.length; }
export function proposalAccess(v: unknown): boolean { return keys(v, ["version", "can_read", "role", "authority"]) && v.version === VERSION && v.can_read === true && ["curator", "reviewer"].includes(String(v.role)) && authority(v.authority); }
export function proposalQueue(v: unknown): ProposalQueue | null {
  if (!keys(v, ["version", "items", "after", "work_id", "next_cursor", "authority"]) || v.version !== VERSION || !authority(v.authority)
    || !Array.isArray(v.items) || v.items.length > 25 || !v.items.every(run) || !nullableText(v.after) || !nullableText(v.work_id) || !nullableText(v.next_cursor)) return null;
  const items = v.items as ProposalRun[];
  if (items.some((x, i) => i > 0 && x.run_id <= items[i - 1].run_id) || v.after !== null && items.some(x => x.run_id <= String(v.after))
    || v.next_cursor !== null && (items.length === 0 || v.next_cursor !== items.at(-1)!.run_id)) return null;
  return v as unknown as ProposalQueue;
}
export function proposalDetail(v: unknown, expected: ProposalRun): ProposalDetail | null {
  if (!keys(v, ["version", "run", "after", "results", "next_cursor", "entities", "source_documents", "coverage", "validation", "training_exclusions", "authority"])
    || v.version !== VERSION || !authority(v.authority) || !run(v.run) || v.run.run_id !== expected.run_id || v.run.packet_sha256 !== expected.packet_sha256
    || v.run.bundle_sha256 !== expected.bundle_sha256 || v.run.work_id !== expected.work_id || !rows(v.results) || v.results.length > 25
    || !nullableText(v.after) || !nullableText(v.next_cursor) || !keys(v.entities, ["samples", "states", "protocols", "sample_relations", "condition_supports"])
    || !Object.values(v.entities).every(rows) || !Array.isArray(v.source_documents) || !v.source_documents.every(body)
    || !body(v.coverage) || !body(v.validation) || !Array.isArray(v.training_exclusions) || !v.training_exclusions.every(body)) return null;
  const dto = v as unknown as ProposalDetail;
  if (Object.hasOwn(dto.coverage, "projector_review") && !projectorReview(dto.coverage.projector_review, dto.run)) return null;
  if (dto.results.some((x, i) => i > 0 && x.local_id <= dto.results[i - 1].local_id)
    || dto.after !== null && dto.results.some(x => x.local_id <= dto.after!)
    || dto.next_cursor !== null && dto.next_cursor !== dto.results.at(-1)?.local_id) return null;
  for (const result of dto.results) {
    const p = result.payload;
    if (!dto.entities.samples.some(s => s.local_id === p.sample_id) || !dto.entities.states.some(s => s.local_id === p.state_id && s.payload.sample_id === p.sample_id)
      || !dto.entities.protocols.some(s => s.local_id === p.protocol_id)) return null;
  }
  return dto;
}
export function projectorReview(v: unknown, expected: ProposalRun): ProjectorReview | null {
  if (!keys(v, ["version", "graph_authorship", "provider", "model", "reasoning", "producer_interface", "evidence_binding", "terminal", "disposition", "raw_result_objects", "retained_result_rows", "publication_version", "coverage_sha256", "findings_author", "findings_created_at", "findings_sha256", "findings", "source_completeness_findings", "independent_review", "paper_completed", "scientific_acceptance", "ml_training_eligible"])
    || v.version !== "materials-projector-review-context/1" || !text(v.model) || v.model !== expected.model || v.graph_authorship !== v.model
    || ![v.provider, v.reasoning, v.producer_interface, v.evidence_binding].every(text)
    || !keys(v.terminal, ["job_id", "attempt_id", "receipt_sha256", "config_sha256", "raw_output_sha256", "state", "outcome", "error_code", "diagnostic"])
    || ![v.terminal.job_id, v.terminal.receipt_sha256, v.terminal.config_sha256, v.terminal.raw_output_sha256, v.coverage_sha256].every(hash)
    || !text(v.terminal.attempt_id) || !["succeeded", "quarantined"].includes(String(v.terminal.state))
    || !nullableText(v.terminal.error_code) || !(v.terminal.diagnostic === null || body(v.terminal.diagnostic))
    || !["draft_pending_review", "unparsed_model_graph"].includes(String(v.disposition))
    || !(v.raw_result_objects === null || integer(v.raw_result_objects)) || v.retained_result_rows !== expected.result_count
    || !text(v.publication_version) || !/^v[1-9]\d*$/.test(v.publication_version)
    || !Array.isArray(v.findings) || v.findings.length > 2000 || !integer(v.source_completeness_findings)
    || [v.independent_review, v.paper_completed, v.scientific_acceptance, v.ml_training_eligible].some(x => x !== false)) return null;
  if (v.disposition === "unparsed_model_graph") {
    if (v.retained_result_rows !== 0 || v.terminal.state !== "quarantined" || v.terminal.outcome !== "graph_not_validated") return null;
  } else if (v.terminal.outcome !== "graph_drafted_pending_semantic_review" || v.raw_result_objects !== v.retained_result_rows) return null;
  if (v.findings_author === null) {
    if (v.findings_created_at !== null || v.findings_sha256 !== null || v.findings.length) return null;
  } else if (!keys(v.findings_author, ["kind", "identity", "thread_id"]) || v.findings_author.kind !== "assistant"
    || !text(v.findings_author.identity) || !text(v.findings_author.thread_id) || !hash(v.findings_sha256)
    || !text(v.findings_created_at) || !Number.isFinite(Date.parse(v.findings_created_at))) return null;
  for (const item of v.findings) {
    if (!keys(item, ["id", "kind", "path", "code", "note", "source_quotes"]) || ![item.id, item.path, item.code, item.note].every(text)
      || !["entity", "source_completeness"].includes(String(item.kind)) || !Array.isArray(item.source_quotes) || !item.source_quotes.length
      || item.kind === "source_completeness" && item.path !== "/paper"
      || item.kind === "entity" && !/^\/(samples|states|protocols|results|sample_relations|condition_supports)\/(0|[1-9]\d*)$/.test(String(item.path))) return null;
    for (const q of item.source_quotes) {
      if (!keys(q, ["block_id", "document_id", "locator", "block_sha256", "quote_sha256", "start_char", "end_char", "quote"])
        || ![q.block_id, q.document_id, q.locator, q.quote].every(text) || !hash(q.block_sha256) || !hash(q.quote_sha256)
        || !integer(q.start_char) || !integer(q.end_char) || q.end_char <= q.start_char
        || Array.from(String(q.quote)).length !== q.end_char - q.start_char) return null;
    }
  }
  if (new Set(v.findings.map(x => x.id)).size !== v.findings.length
    || v.findings.filter(x => x.kind === "source_completeness").length !== v.source_completeness_findings) return null;
  return v as unknown as ProjectorReview;
}
export function proposalEvidence(v: unknown, expected: ProposalRun, resultId: string): ProposalEvidence | null {
  if (!keys(v, ["version", "run_id", "packet_sha256", "result_id", "after", "total_count", "scope_paths", "items", "next_cursor", "authority"])
    || v.version !== VERSION || !authority(v.authority) || v.run_id !== expected.run_id || v.packet_sha256 !== expected.packet_sha256 || v.result_id !== resultId
    || typeof v.after !== "number" || !Number.isInteger(v.after) || v.after < -1 || !integer(v.total_count) || !strings(v.scope_paths)
    || !Array.isArray(v.items) || v.items.length > 100 || !(v.next_cursor === null || integer(v.next_cursor))) return null;
  for (const x of v.items) {
    if (!keys(x, ["ordinal", "path", "block_id", "block_sha256", "document_id", "locator", "start_char", "end_char", "quote_sha256", "quote"])
      || !integer(x.ordinal) || !text(x.path) || !text(x.block_id) || !hash(x.block_sha256) || !text(x.document_id) || !text(x.locator)
      || !integer(x.start_char) || !integer(x.end_char) || x.end_char <= x.start_char || !hash(x.quote_sha256) || !text(x.quote)
      || Array.from(x.quote).length !== x.end_char - x.start_char) return null;
  }
  const dto = v as unknown as ProposalEvidence;
  if (dto.items.some((x, i) => x.ordinal <= dto.after || i > 0 && x.ordinal <= dto.items[i - 1].ordinal)
    || dto.next_cursor !== null && dto.next_cursor !== dto.items.at(-1)?.ordinal) return null;
  return dto;
}
export function displayValue(value: Json | undefined): string { return value === undefined || value === null ? "Not reported in this extraction" : typeof value === "string" ? value : JSON.stringify(value); }
export function proposalExport(v: unknown, expected: ProposalRun): ProposalExport | null {
  if (!keys(v, ["version", "scope", "run", "authority", "filename", "bytes", "sha256", "counts", "files"])
    || !["materials-proposal-export/1", "materials-proposal-export/2", "materials-proposal-export/4", "materials-proposal-export/5"].includes(String(v.version)) || v.scope !== "complete_retained_run" || !authority(v.authority) || !run(v.run)
    || v.run.run_id !== expected.run_id || v.run.packet_sha256 !== expected.packet_sha256 || v.run.bundle_sha256 !== expected.bundle_sha256 || v.run.work_id !== expected.work_id
    || v.filename !== `materials-review-${expected.run_id}.zip` || !integer(v.bytes) || v.bytes < 1 || v.bytes > 8388608 || !hash(v.sha256)
    || !keys(v.counts, ["samples", "states", "protocols", "sample_relations", "condition_supports", "results", "evidence", "result_evidence_references"])
    || !Object.values(v.counts).every(integer) || v.counts.results !== expected.result_count || v.run.result_count !== expected.result_count
    || Number(v.counts.evidence) > 20000 || Number(v.counts.result_evidence_references) > 200000
    || !Array.isArray(v.files)) return null;
  const names = v.version === "materials-proposal-export/4" || v.version === "materials-proposal-export/5" && v.files.some(f => record(f) && f.name === "raw-model-graph.json")
    ? ["README.txt", "graph.json", "manifest.json", "raw-model-graph.json", "results.csv"]
    : ["README.txt", "graph.json", "manifest.json", "results.csv"];
  if (v.files.length !== names.length) return null;
  let size = 0;
  for (const [i, f] of v.files.entries()) {
    if (!keys(f, ["name", "bytes", "sha256"]) || f.name !== names[i] || !integer(f.bytes) || !hash(f.sha256)) return null;
    size += f.bytes;
  }
  if (size > 16777216) return null;
  return v as unknown as ProposalExport;
}

export const amendmentFields = ["quantity", "sample", "composition", "method", "criterion", "conditions", "source_role", "physical_identity"] as const;
export type AmendmentAnchor = { block_id: string; start_char: number; end_char: number; quote: string };
export type AmendmentSourceReview = { status: "pending_reassessment"; parent_terminal_sha256: string;
  findings_sha256: string | null; findings_author: { kind: "assistant"; identity: string; thread_id: string } | null;
  findings_created_at: string | null; findings: { id: string; kind: "entity" | "source_completeness"; path: string; code: string; note: string; anchors: AmendmentAnchor[] }[];
  paper_completed: false; independent_review: false };
export type AmendmentReview = { result_id: string; fields: Record<typeof amendmentFields[number], { disposition: string; note: string; anchors: AmendmentAnchor[] }>; holds: string[] };
export type AmendmentSummary = { id: string; parent_run_id: string; parent_packet_hash: string; created_at: string; author: Body; selected_result_ids: string[] };
export type AmendmentList = { version: "materials-proposal-amendment/1"; items: AmendmentSummary[]; authority: Authority };
export type AmendmentDetail = {
  amendment: Body & { amendment_id: string; parent_run_id: string; parent_packet_hash: string; work_id: string; author: Body;
    source_review?: AmendmentSourceReview;
    created_at: string; selected_result_ids: string[]; graph: Body & Record<"samples" | "states" | "protocols" | "results", Body[]>;
    bundle: Body & { blocks: (Body & { id: string; document_id: string; locator: string; text: string; sha256: string })[]; documents: Body[] };
    reviews: AmendmentReview[]; changes: (Body & { path: string; reason: string; anchors: AmendmentAnchor[] })[] };
  mapping: Body & { records: Body[] }; storage_hash: string; authority: Authority;
};
export type AmendmentSelection = { result: Body; sample: Body; state: Body; protocol: Body; review: AmendmentReview; mapping: Body };
export type AmendmentTarget = { id: string; event_id: string; state_id: string; sample_id: string; material_id: string; work_id: string; source_snapshot_id: string; interpretation_revision: number; source_record_hash: string; identity_status: "candidate_requires_independent_identity_review" };
export type AmendmentTargets = { version: "materials-amendment-targets/1"; parent_run_id: string; amendment_id: string; storage_hash: string; result_id: string; items: AmendmentTarget[]; authority: Authority };
export type ClaimSourceContext = { subject_sha256: string; result_row_sha256: string; target: Body; source_occurrences: { occurrence_id: string; source_revision_id: string; capture_id: string; bytes_sha256: string; binding_status: string; version_status: string; provider_revision: string | null; representation: string }[] };
const uuid = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/.test(v);
export function amendmentTargets(v: unknown, expected: AmendmentDetail, resultId: string): AmendmentTargets | null {
  if (!keys(v, ["version", "parent_run_id", "amendment_id", "storage_hash", "result_id", "items", "authority"])
    || v.version !== "materials-amendment-targets/1" || v.parent_run_id !== expected.amendment.parent_run_id
    || v.amendment_id !== expected.amendment.amendment_id || v.storage_hash !== expected.storage_hash || v.result_id !== resultId
    || !authority(v.authority) || !Array.isArray(v.items) || v.items.length > 10) return null;
  for (const x of v.items) {
    if (!keys(x, ["id", "event_id", "state_id", "sample_id", "material_id", "work_id", "source_snapshot_id", "interpretation_revision", "source_record_hash", "identity_status"])
      || ![x.id, x.event_id, x.state_id, x.sample_id, x.work_id, x.source_snapshot_id].every(uuid)
      || !text(x.material_id) || !x.material_id.length || !integer(x.interpretation_revision) || x.interpretation_revision < 1
      || !hash(x.source_record_hash) || x.identity_status !== "candidate_requires_independent_identity_review") return null;
  }
  if (new Set(v.items.map(x => x.id)).size !== v.items.length) return null;
  return v as AmendmentTargets;
}
export function claimSourceContext(v: unknown, expected: AmendmentTarget): ClaimSourceContext | null {
  if (!record(v) || !/^materials-result-review-context\/1\.[1-8]\.0$/.test(String(v.version))
    || !hash(v.subject_sha256) || !hash(v.result_row_sha256) || !body(v.target) || v.target.result_kind !== "claim"
    || v.target.result_id !== expected.id || v.target.event_id !== expected.event_id || v.target.state_id !== expected.state_id
    || v.target.sample_id !== expected.sample_id || v.target.material_id !== expected.material_id
    || v.review_write_available !== false || v.source_text_disclosed !== false
    || !keys(v.authority, ["scientific_accepted", "ml_training_approved", "public_release"]) || !Object.values(v.authority).every(x => x === false)
    || !Array.isArray(v.source_occurrences) || v.source_occurrences.length > 2000) return null;
  for (const x of v.source_occurrences) {
    if (!record(x) || ![x.occurrence_id, x.source_revision_id, x.capture_id].every(uuid) || !hash(x.bytes_sha256)
      || !["pending", "reviewed"].includes(String(x.binding_status)) || !["pinned", "unresolved"].includes(String(x.version_status))
      || !nullableText(x.provider_revision) || x.version_status === "pinned" && !text(x.provider_revision) || !text(x.representation)) return null;
  }
  if (new Set(v.source_occurrences.map(x => x.occurrence_id)).size !== v.source_occurrences.length) return null;
  return v as ClaimSourceContext;
}
const amendmentVersion = "materials-proposal-amendment/1";
const dispositions = ["supported", "corrected", "not_reported_in_reviewed_scope", "source_conflicted", "not_reviewed", "source_unavailable"];
const uniqueStrings = (v: unknown): v is string[] => strings(v) && new Set(v).size === v.length;
function amendmentAuthor(v: unknown): v is Body { return keys(v, ["kind", "identity", "thread_id"]) && v.kind === "assistant" && text(v.identity) && text(v.thread_id); }
export function proposalAmendments(v: unknown, expected: ProposalRun): AmendmentList | null {
  if (!keys(v, ["version", "items", "authority"]) || v.version !== amendmentVersion || !authority(v.authority)
    || !Array.isArray(v.items) || v.items.length > 100) return null;
  for (const x of v.items) {
    if (!keys(x, ["id", "parent_run_id", "parent_packet_hash", "created_at", "author", "selected_result_ids"]) || !hash(x.id)
      || x.parent_run_id !== expected.run_id || x.parent_packet_hash !== expected.packet_sha256 || !text(x.created_at)
      || !Number.isFinite(Date.parse(x.created_at)) || !amendmentAuthor(x.author) || !uniqueStrings(x.selected_result_ids)) return null;
  }
  if (new Set(v.items.map(x => x.id)).size !== v.items.length) return null;
  return v as AmendmentList;
}
function pointer(v: unknown, collection: string, rows: Body[]): Body | null {
  if (!text(v)) return null;
  const match = new RegExp(`^/graph/${collection}/(0|[1-9][0-9]*)$`).exec(v);
  return match ? rows[Number(match[1])] ?? null : null;
}
function sameJson(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v, i) => sameJson(v, b[i]));
  if (record(a) && record(b)) return Object.keys(a).length === Object.keys(b).length && Object.keys(a).every(k => Object.hasOwn(b, k) && sameJson(a[k], b[k]));
  return false;
}
/** Resolve within one immutable amendment, never by formula similarity or catalogue ID. */
export function amendmentSelection(detail: AmendmentDetail, resultId: string): AmendmentSelection | null {
  const a = detail.amendment, m = detail.mapping.records.find(r => r.source_result_id === resultId);
  const resultIndex = a.graph.results.findIndex(r => r.id === resultId), result = a.graph.results[resultIndex];
  const reviewIndex = a.reviews.findIndex(r => r.result_id === resultId), review = a.reviews[reviewIndex];
  if (!m || !result || !review || !a.selected_result_ids.includes(resultId)) return null;
  const sample = pointer(m.sample_pointer, "samples", a.graph.samples), state = pointer(m.state_pointer, "states", a.graph.states), protocol = pointer(m.protocol_pointer, "protocols", a.graph.protocols);
  if (!sample || !state || !protocol || sample.id !== result.sample_id || state.id !== result.state_id || state.sample_id !== sample.id || protocol.id !== result.protocol_id
    || m.source_sample_id !== sample.id || m.source_state_id !== state.id || m.source_protocol_id !== protocol.id
    || m.review_pointer !== `/reviews/${reviewIndex}` || m.source_evidence_pointer !== `/graph/results/${resultIndex}/evidence`) return null;
  return { result, sample, state, protocol, review, mapping: m };
}
export function proposalAmendment(v: unknown, expected: ProposalRun, summary: AmendmentSummary): AmendmentDetail | null {
  if (!keys(v, ["amendment", "mapping", "storage_hash", "authority"]) || !hash(v.storage_hash) || !authority(v.authority) || !body(v.amendment) || !body(v.mapping)) return null;
  const a = v.amendment, m = v.mapping;
  if (!keys(a, ["schema", "parent_run_id", "parent_packet_hash", "parent_graph_hash", "baseline_hash", "work_id", "author", "created_at", "bundle", "changes", "reviews", "graph", "validation", "affected_result_ids", "selected_result_ids", "unreviewed_result_ids", "independent_review", "scientific_acceptance", "ml_training_eligible", "canonical_writes", "source_scope", "amendment_id", ...(Object.hasOwn(a, "source_review") ? ["source_review"] : [])])
    || a.schema !== amendmentVersion || a.amendment_id !== summary.id || a.parent_run_id !== expected.run_id || a.parent_packet_hash !== expected.packet_sha256
    || summary.parent_run_id !== expected.run_id || summary.parent_packet_hash !== expected.packet_sha256 || a.work_id !== expected.work_id
    || !hash(a.parent_graph_hash) || !hash(a.baseline_hash) || !amendmentAuthor(a.author) || JSON.stringify(a.author) !== JSON.stringify(summary.author)
    || !text(a.created_at) || !Number.isFinite(Date.parse(a.created_at)) || !uniqueStrings(a.selected_result_ids)
    || !uniqueStrings(a.affected_result_ids) || !uniqueStrings(a.unreviewed_result_ids)
    || a.selected_result_ids.length !== summary.selected_result_ids.length || a.selected_result_ids.some(id => !summary.selected_result_ids.includes(id))
    || [a.independent_review, a.scientific_acceptance, a.ml_training_eligible, a.canonical_writes].some(x => x !== false)
    || !body(a.graph) || a.graph.work_id !== expected.work_id || !body(a.bundle) || a.bundle.work_id !== expected.work_id
    || !Array.isArray(a.bundle.blocks) || !Array.isArray(a.bundle.documents) || !a.bundle.documents.every(body)
    || !Array.isArray(a.reviews) || !Array.isArray(a.changes) || !body(a.validation) || !text(a.source_scope)
    || !keys(m, ["schema", "amendment_id", "records", "note"]) || !["materials-reviewed-tc-mapping/1", "materials-reviewed-result-mapping/1"].includes(String(m.schema)) || m.amendment_id !== a.amendment_id
    || !text(m.note) || !Array.isArray(m.records)) return null;
  if (!["materials-ner/13", "materials-ner/14", "materials-ner/15"].includes(String(a.graph.schema_version))
    || a.graph.schema_version === "materials-ner/14" && (a.validation.validator_version !== "materials-ner-validation/1.26.0"
      || a.validation.registry_version !== "materials-quantities/3.0.0" || m.schema !== "materials-reviewed-result-mapping/1")
    || a.graph.schema_version === "materials-ner/15" && (a.validation.validator_version !== "materials-ner-validation/1.29.0"
      || a.validation.registry_version !== "materials-quantities/4.0.0" || m.schema !== "materials-reviewed-result-mapping/1")) return null;
  for (const group of ["samples", "states", "protocols", "results"]) {
    const rows = a.graph[group];
    if (!Array.isArray(rows) || !rows.every(r => body(r) && text(r.id)) || new Set(rows.map(r => (r as Body).id)).size !== rows.length) return null;
  }
  const blocks = new Map<string, string>();
  for (const b of a.bundle.blocks) {
    if (!body(b) || !text(b.id) || !text(b.document_id) || !text(b.locator) || !text(b.text) || !hash(b.sha256)
      || blocks.has(b.id) || !a.bundle.documents.some(d => (d as Body).id === b.document_id)) return null;
    blocks.set(b.id, b.text);
  }
  const anchors = (value: unknown) => Array.isArray(value) && value.every(x => {
    if (!keys(x, ["block_id", "start_char", "end_char", "quote"]) || !text(x.block_id) || !integer(x.start_char) || !integer(x.end_char) || !text(x.quote)
      || x.end_char <= x.start_char || !blocks.has(x.block_id)) return false;
    // Python source offsets are Unicode code points; JS string.slice uses UTF-16 code units.
    const source = Array.from(blocks.get(x.block_id)!);
    return x.end_char <= source.length && source.slice(x.start_char, x.end_char).join("") === x.quote;
  });
  if (Object.hasOwn(a, "source_review")) {
    const source = a.source_review;
    if (!keys(source, ["status", "parent_terminal_sha256", "findings_sha256", "findings_author", "findings_created_at", "findings", "paper_completed", "independent_review"])
      || source.status !== "pending_reassessment" || !hash(source.parent_terminal_sha256) || source.paper_completed !== false || source.independent_review !== false
      || !Array.isArray(source.findings) || source.findings.length > 2000) return null;
    if (source.findings_author === null) {
      if (source.findings_sha256 !== null || source.findings_created_at !== null || source.findings.length) return null;
    } else if (!amendmentAuthor(source.findings_author) || !hash(source.findings_sha256) || !text(source.findings_created_at) || !Number.isFinite(Date.parse(source.findings_created_at))) return null;
    for (const f of source.findings) {
      if (!keys(f, ["id", "kind", "path", "code", "note", "anchors"]) || ![f.id, f.path, f.code, f.note].every(text)
        || !anchors(f.anchors) || !(f.anchors as unknown[]).length) return null;
      if (f.kind === "source_completeness") { if (f.path !== "/paper") return null; }
      else if (f.kind === "entity") {
        const parts = /^\/(samples|states|protocols|results|sample_relations|condition_supports)\/(0|[1-9]\d*)$/.exec(String(f.path));
        if (!parts || !Array.isArray(a.graph[parts[1]]) || !(a.graph[parts[1]] as Json[])[Number(parts[2])]) return null;
      } else return null;
    }
    if (new Set(source.findings.map(f => (f as Body).id)).size !== source.findings.length) return null;
  }
  for (const r of a.reviews) {
    if (!keys(r, ["result_id", "fields", "holds"]) || !text(r.result_id) || !keys(r.fields, [...amendmentFields]) || !strings(r.holds)) return null;
    for (const f of Object.values(r.fields)) {
      if (!keys(f, ["disposition", "note", "anchors"]) || !dispositions.includes(String(f.disposition)) || !text(f.note) || !anchors(f.anchors)) return null;
    }
  }
  for (const c of a.changes) {
    if (!keys(c, ["path", "before", "after", "reason", "anchors"]) || !text(c.path) || !text(c.reason) || !anchors(c.anchors)) return null;
  }
  for (const row of m.records) {
    if (!body(row) || row.parent_run_id !== expected.run_id || row.amendment_id !== a.amendment_id || row.target_table !== (m.schema === "materials-reviewed-result-mapping/1" ? null : "material_claims") || row.target_id !== null
      || !text(row.source_result_id) || !strings(row.holds) || [row.ready_for_canonical_insert, row.scientific_acceptance, row.ml_training_eligible].some(x => x !== false)) return null;
    if (m.schema === "materials-reviewed-result-mapping/1") {
      const graphRows = a.graph.results as Body[], index = graphRows.findIndex(r => r.id === row.source_result_id), result = graphRows[index];
      const normalized = record(a.validation.normalized) ? a.validation.normalized : {};
      const expectedNormalized = Object.fromEntries(Object.entries(normalized).filter(([key]) => key.startsWith(`/results/${index}/`)));
      if (!result || row.result_pointer !== `/graph/results/${index}` || row.quantity_kind !== result.quantity_kind
        || !sameJson(row.source_quantity, result.quantity) || !sameJson(row.dependencies, result.dependencies)
        || !sameJson(row.result_semantics, { version: a.graph.schema_version === "materials-ner/15" ? "materials-result-semantics/2" : "materials-result-semantics/1", definition: result.definition, qualifiers: result.qualifiers })
        || !sameJson(row.normalized, expectedNormalized) || !["pending_review", "quarantined"].includes(String(row.review_status))
        || !strings(row.validation_issues) || row.validation_issues.some(code => !(row.holds as string[]).includes(code))
        || !row.holds.includes("canonical_result_mapping_required")) return null;
    }
  }
  const selectedIds = a.selected_result_ids;
  for (const ids of [a.reviews.map(r => (r as Body).result_id), m.records.map(r => (r as Body).source_result_id)]) {
    if (ids.length !== selectedIds.length || new Set(ids).size !== ids.length || ids.some(id => !selectedIds.includes(String(id)))) return null;
  }
  const dto = v as unknown as AmendmentDetail;
  if (selectedIds.some(id => !amendmentSelection(dto, id))) return null;
  return dto;
}
