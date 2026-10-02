/** Closed private source-fragment intake. No URL fetch, source execution or scientific approval. */
export const EXPRESSION_VERSION = "source-expression-intake/2.0.0";
export const PACKAGE_VERSION = "source-expression-package/2.0.0";
export const EXPRESSION_REGISTRY_SHA = "96aebf58ceffad643c5aa156697f6aff064fe7a43fcfd3b27c9ade53bac5535a";
export const MAX_PACKAGE_BYTES = 1024 * 1024;
export const MAX_FRAGMENT_BYTES = 131072;
export const MAX_PACKAGE_METADATA_BYTES = 131072;
export const MAX_PROJECTION_BYTES = 32768;
export const EXPRESSION_PAGE_SIZE = 8;
export const EXPRESSION_FIELDS: Record<string, string | null> = {
  tc_kelvin: "K", pressure_gpa: "GPa", measurement_temperature_k: "K", magnetic_field_t: "T", hc2_tesla: "T",
  lambda_london_nm: "nm", lambda_eph: "1", omega_log_k: "K", mu_star: "1", lattice_a: "angstrom", lattice_b: "angstrom", lattice_c: "angstrom",
  method_statement: null, sample_form_statement: null, structure_statement: null, classification_statement: null,
};
const ROLES = ["source_reported", "source_fitted", "source_model_estimate", "source_proposed"];
const CONDITION_FIELDS = ["pressure_gpa", "measurement_temperature_k", "magnetic_field_t", "method_statement", "criterion_statement", "window_statement"];
const CONDITION_ROLES = ["reported_result_condition", "study_extent", "synthesis_condition", "fit_window"];
type Row = Record<string, unknown>;
export type ExpressionSpan = { start: number; end: number; sha256: string };
export type SourceMetadata = {
  source_id: string; url: string; kind: string; content_kind: string; revision: string | null; revision_status: string;
  original_parent_sha256: string | null; parent_hash_status: string; rights_status: string; currentness: string; captured_at: string;
};
export type ExpressionLocator = { page: number | null; slide: number | null; table: string | null; row: number | null; column: number | null; section: string | null; member: string | null };
export type ExpressionRequest = {
  field_id: string; subject: { formula_spans: ExpressionSpan[]; sample_label_spans: ExpressionSpan[] };
  window: { id: string; label_spans: ExpressionSpan[] }; source_role: string; knowledge_origin: string;
  origin_basis: { statement: string | null; spans: ExpressionSpan[] }; model_spans: ExpressionSpan[]; value_spans: ExpressionSpan[]; unit_spans: ExpressionSpan[];
  conditions: { field_id: string; role: string; value_spans: ExpressionSpan[]; unit_spans: ExpressionSpan[] }[];
  locator: ExpressionLocator; predecessor: { revision_id: string; record_sha256: string; revision_number: number } | null;
};
export type ExpressionPackage = { version: string; source: SourceMetadata; source_text_base64: string; source_content_sha256: string; expressions: ExpressionRequest[] };
export type SourceQuantity = { raw_value: string; raw_unit: string | null; value: number | null; unit: string | null; uncertainty: number | null;
  uncertainty_interpretation: string | null; approximate: boolean; relation: string; status: string; unit_basis: string };
export type SourceStatement = { raw_value: string; status: "source_statement" };
export type SourceValue = SourceQuantity | SourceStatement;
export type ExpressionProjection = {
  source_id: string; field_id: string; subject: { formula: string; sample_label: string | null; formula_scope: string };
  window: { id: string; raw_label: string | null }; source_role: string; model: string | null; expression_key: string;
  knowledge_origin: string; origin_basis: { statement: string | null; retained_text: string | null; verification: string };
  value: SourceValue; conditions: { field_id: string; role: string; value: SourceValue }[]; locator: ExpressionLocator;
  status: "pending"; selected_result_association: "unestablished"; sample_identity_established: false; phase_identity_established: false;
  scientific_acceptance: false; canonical_promotions: 0; missingness_scope: string;
};
export type LocalExpression = { expressionKey: string; entrySha: string; field: string; formula: string; sampleLabel: string | null; formulaScope: string;
  window: string | null; windowId: string; model: string | null; role: string; origin: string; originStatement: string | null; originText: string | null;
  rawValue: string; rawUnit: string | null; conditions: { field: string; role: string; rawValue: string; rawUnit: string | null }[]; locator: ExpressionLocator };
export type PreparedExpressionPackage = { package: ExpressionPackage; packageSha: string; requestSha: string; fileSha: string; fileBytes: number;
  fileName: string; retainedBytes: number; localExpressions: LocalExpression[] };
export type ExpressionCapabilities = { version: string; package_version: string; actor_user_id: string; session_version: number; can_import: boolean;
  curator_grant_id: string | null; registry_sha256: string; field_profiles: Record<string, string | null>; max_source_bytes: number; max_expressions: number;
  max_package_bytes: number; max_projection_bytes: number; max_expression_page_size: number; scope: string; scientific_acceptance: false; canonical_promotions: 0; public_content_release: false };
export type ExpressionManifest = { entry_index: number; expression_key: string; entry_sha256: string; projection_sha256: string;
  predecessor_id: string | null; predecessor_sha256: string | null; revision_number: number };
export type ExpressionReceipt = {
  version: string; receipt_id: string; receipt_sha256: string; actor_user_id: string; actor_grant_id: string; actor_session_version: number;
  request_key: string; request_sha256: string; preview_sha256: string; capture_id: string; package_sha256: string;
  package_canonical_json: string; request_canonical_json: string; preview_canonical_json: string; receipt_canonical_json: string;
  expression_count: number; expression_manifest: ExpressionManifest[]; count_scope: string; replayed: boolean; dry_run: boolean; pending_ledger_written: boolean;
  status: "pending"; scientific_acceptance: false; canonical_promotions: 0; selected_result_association: "unestablished"; public_content_release: false;
};
export type ExpressionRecovery = { actorId: string; requestKey: string; requestSha: string; packageSha: string; previewSha: string;
  manifestCanonical: string; packageCanonical: string };
export type SourceCapture = { id: string; record_sha256: string; source: SourceMetadata; source_metadata_canonical_json: string;
  source_content_sha256: string; metadata_sha256: string; retained_utf8_bytes: number; fragment_integrity: string; parent_integrity: string;
  publication_revision_verified: false; rights_verified: false; publication_currentness_verified: false; latest_retained_capture_for_source: boolean; public_content_release: false };
export type SourceRevision = { id: string; record_sha256: string; expression_key: string; revision_canonical_json: string; entry_index: number;
  source_entry_sha256: string; import_receipt_id: string; import_receipt_sha256: string; import_receipt: ExpressionReceipt | null; revision_number: number; predecessor_id: string | null;
  predecessor_sha256: string | null; projection_sha256: string; projection_canonical_json: string; projection: ExpressionProjection; source_entry: ExpressionRequest;
  is_expression_head: boolean; capture: SourceCapture };
export type ExpressionPage = { version: string; total: number; offset: number; limit: number; count_scope: string; expressions: SourceRevision[]; scientific_acceptance: false; canonical_promotions: 0 };
export type CapturePage = { version: string; total: number; offset: number; limit: number; count_scope: string; captures: SourceCapture[] };
export type ExpressionFilters = { field?: string; sourceId?: string; currentness?: string };
export type ExpressionImportRequest = { request_key: string; package: ExpressionPackage };

const HASH = /^[a-f0-9]{64}$/;
const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const SOURCE_KEYS = "source_id url kind content_kind revision revision_status original_parent_sha256 parent_hash_status rights_status currentness captured_at";
const ENTRY_KEYS = "field_id subject window source_role knowledge_origin origin_basis model_spans value_spans unit_spans conditions locator predecessor";
const LOCATOR_KEYS = "page slide table row column section member";
function row(value: unknown): value is Row { return typeof value === "object" && value !== null && !Array.isArray(value); }
function closed(value: unknown, keys: string): value is Row { return row(value) && Object.keys(value).length === keys.split(" ").length && keys.split(" ").every(key => Object.hasOwn(value, key)); }
function safe(value: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= min && value <= max; }
function hash(value: unknown): value is string { return typeof value === "string" && HASH.test(value); }
function uuid(value: unknown): value is string { return typeof value === "string" && UUID.test(value); }
function text(value: unknown, max = 160, nullable = false): value is string | null { return nullable && value === null || typeof value === "string" && value === value.trim() && Array.from(value).length > 0 && Array.from(value).length <= max && !/[\u0000-\u001f]/.test(value) && wellFormed(value); }
function wellFormed(value: string) { return !Array.from(value).some(char => char.length === 1 && char.charCodeAt(0) >= 0xd800 && char.charCodeAt(0) <= 0xdfff); }
function rawText(value: unknown, max: number, nullable = false): boolean { return nullable && value === null || typeof value === "string" && Array.from(value).length <= max && value.length > 0 && !value.includes("\0") && wellFormed(value); }
function includes(values: string[], value: unknown): value is string { return typeof value === "string" && values.includes(value); }
export class ExpressionPackageError extends Error {}
function expect(ok: unknown, message = "The package does not match the supported source-expression format."): asserts ok { if (!ok) throw new ExpressionPackageError(message); }
export function expressionSourceHref(value: unknown): string | null {
  if (!text(value, 2048)) return null;
  try { const url = new URL(value as string); return url.protocol === "https:" && url.hostname.includes(".") && !url.username && !url.password && !url.hash && (!url.port || url.port === "443") ? value as string : null; } catch { return null; }
}
export async function expressionSha(value: string | Uint8Array): Promise<string> {
  const bytes = typeof value === "string" ? new TextEncoder().encode(value) : value;
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes as BufferSource)), byte => byte.toString(16).padStart(2, "0")).join("");
}
/** Package metadata contains integers and source strings. Scientific scalars remain original strings. */
export function expressionCanonical(value: unknown): string {
  if (value === null || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "string") { expect(wellFormed(value)); return JSON.stringify(value); }
  if (typeof value === "number") { expect(Number.isSafeInteger(value)); return JSON.stringify(value); }
  if (Array.isArray(value)) return `[${value.map(expressionCanonical).join(",")}]`;
  expect(row(value)); return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${expressionCanonical(value[key])}`).join(",")}}`;
}
function equal(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  if (Array.isArray(left) && Array.isArray(right)) return left.length === right.length && left.every((value, i) => equal(value, right[i]));
  if (row(left) && row(right)) return Object.keys(left).length === Object.keys(right).length && Object.keys(left).every(key => Object.hasOwn(right, key) && equal(left[key], right[key]));
  return false;
}
/** Detect duplicate keys before JSON.parse can discard them. Never evaluate input text. */
export function parseExpressionJson(source: string, integerOnly = true): unknown {
  let at = 0, nodes = 0;
  const whitespace = () => { while (/\s/.test(source[at] ?? "") && at < source.length) { expect(/[ \t\r\n]/.test(source[at])); at++; } };
  function string(): string {
    const start = at++; let escaped = false;
    while (at < source.length) { const char = source[at++]; if (!escaped && char === '"') { const result = JSON.parse(source.slice(start, at)) as string; expect(wellFormed(result)); return result; } if (!escaped && char === "\\") escaped = true; else escaped = false; }
    throw new ExpressionPackageError("The JSON file is incomplete.");
  }
  function value(depth: number): unknown {
    expect(depth <= 20 && ++nodes <= 40000, "The JSON structure exceeds the supported bounds."); whitespace();
    if (source[at] === '"') return string();
    if (source[at] === "{") { at++; whitespace(); const result: Row = Object.create(null), keys = new Set<string>(); if (source[at] === "}") { at++; return result; }
      while (at < source.length) { whitespace(); expect(source[at] === '"'); const key = string(); expect(!keys.has(key), "Duplicate JSON keys are not supported."); keys.add(key); whitespace(); expect(source[at++] === ":"); result[key] = value(depth + 1); whitespace(); const end = source[at++]; if (end === "}") return result; expect(end === ","); } }
    if (source[at] === "[") { at++; whitespace(); const result: unknown[] = []; if (source[at] === "]") { at++; return result; }
      while (at < source.length) { result.push(value(depth + 1)); whitespace(); const end = source[at++]; if (end === "]") return result; expect(end === ","); } }
    for (const [literal, result] of [["true", true], ["false", false], ["null", null]] as const) if (source.slice(at, at + literal.length) === literal) { at += literal.length; return result; }
    const match = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/.exec(source.slice(at)); expect(match); at += match[0].length; const number = Number(match[0]); expect(Number.isFinite(number) && (!integerOnly || Number.isSafeInteger(number) && /^-?(?:0|[1-9]\d*)$/.test(match[0])), "JSON metadata numbers must be finite integers."); return number;
  }
  const result = value(0); whitespace(); expect(at === source.length); return result;
}
function metadata(value: unknown): value is SourceMetadata {
  if (!closed(value, SOURCE_KEYS) || !text(value.source_id) || !/^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,159}$/.test(value.source_id as string) || !expressionSourceHref(value.url)) return false;
  if (!includes(["primary_paper", "conference_presentation", "supplement", "crystal_reference"], value.kind) || !includes(["plain_text", "xml_text"], value.content_kind)) return false;
  if (!includes(["declared", "unresolved"], value.revision_status) || !includes(["declared", "unresolved"], value.parent_hash_status) || (value.revision === null) !== (value.revision_status === "unresolved") || (value.original_parent_sha256 === null) !== (value.parent_hash_status === "unresolved")) return false;
  return text(value.revision, 160, true) && (value.original_parent_sha256 === null || hash(value.original_parent_sha256)) && includes(["unresolved", "declared_private_inspection", "restricted"], value.rights_status) && includes(["unresolved", "declared_current", "historical"], value.currentness) && text(value.captured_at, 40) && /(?:Z|[+-]\d{2}:?\d{2})$/.test(value.captured_at as string) && Number.isFinite(Date.parse(value.captured_at as string));
}
function locator(value: unknown): value is ExpressionLocator { return closed(value, LOCATOR_KEYS) && ["page", "slide", "row", "column"].every(key => value[key] === null || safe(value[key], 1, 100000)) && ["table", "section", "member"].every(key => text(value[key], 200, true)); }
function spanShape(value: unknown, optional = false, limit = 2048): value is ExpressionSpan[] {
  if (!Array.isArray(value) || value.length < (optional ? 0 : 1) || value.length > 8) return false;
  let end = -1, length = 0;
  return value.every(span => { if (!closed(span, "start end sha256") || !safe(span.start) || !safe(span.end, 1) || span.start < end || span.end <= span.start || span.end - span.start > limit || !hash(span.sha256)) return false; end = span.end; length += span.end - span.start; return length <= limit; });
}
function entryShape(value: unknown): value is ExpressionRequest {
  if (!closed(value, ENTRY_KEYS) || typeof value.field_id !== "string" || !Object.hasOwn(EXPRESSION_FIELDS, value.field_id) || !includes(ROLES, value.source_role) || !includes(["Observed", "Computed", "unknown"], value.knowledge_origin)) return false;
  if (!closed(value.subject, "formula_spans sample_label_spans") || !spanShape(value.subject.formula_spans, false, 200) || !spanShape(value.subject.sample_label_spans, true, 200) || !closed(value.window, "id label_spans") || !text(value.window.id) || !spanShape(value.window.label_spans, true, 500)) return false;
  if (!closed(value.origin_basis, "statement spans") || !text(value.origin_basis.statement, 500, true) || !spanShape(value.origin_basis.spans, true, 1000) || !spanShape(value.model_spans, true, 500) || !spanShape(value.value_spans, false, 1200) || value.value_spans.length !== 1 || !spanShape(value.unit_spans, true, 40) || value.unit_spans.length > 1) return false;
  if (EXPRESSION_FIELDS[value.field_id as string] === null && value.unit_spans.length) return false;
  if (!Array.isArray(value.conditions) || value.conditions.length > 8 || !value.conditions.every(item => closed(item, "field_id role value_spans unit_spans") && includes(CONDITION_FIELDS, item.field_id) && includes(CONDITION_ROLES, item.role) && spanShape(item.value_spans, false, 1200) && item.value_spans.length === 1 && spanShape(item.unit_spans, true, 40) && item.unit_spans.length <= 1 && (EXPRESSION_FIELDS[item.field_id as string] != null || item.unit_spans.length === 0))) return false;
  return locator(value.locator) && (value.predecessor === null || closed(value.predecessor, "revision_id record_sha256 revision_number") && uuid(value.predecessor.revision_id) && hash(value.predecessor.record_sha256) && safe(value.predecessor.revision_number, 1, 10000));
}
async function joined(chars: string[], spans: ExpressionSpan[]) { const parts: string[] = []; for (const span of spans) { expect(span.end <= chars.length); const part = chars.slice(span.start, span.end).join(""); expect(await expressionSha(part) === span.sha256, "A source span does not match its declared hash."); parts.push(part); } return parts.join(""); }
function retainedPackage(value: ExpressionPackage) { const { source_text_base64: _privateFragment, ...retained } = value; return retained; }
export async function prepareExpressionPackage(bytes: Uint8Array, fileName = "source-package.json"): Promise<PreparedExpressionPackage> {
  expect(bytes.length > 0 && bytes.length <= MAX_PACKAGE_BYTES, "Choose a source-package JSON file of at most 1 MiB.");
  const decoded = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes); const value = parseExpressionJson(decoded);
  expect(closed(value, "version source source_text_base64 source_content_sha256 expressions") && value.version === PACKAGE_VERSION && metadata(value.source) && hash(value.source_content_sha256) && typeof value.source_text_base64 === "string" && value.source_text_base64.length <= 4 * Math.ceil(MAX_FRAGMENT_BYTES / 3) && Array.isArray(value.expressions) && value.expressions.length >= 1 && value.expressions.length <= 20 && value.expressions.every(entryShape));
  const pkg = value as unknown as ExpressionPackage; let binary: string;
  try { binary = atob(pkg.source_text_base64); } catch { throw new ExpressionPackageError("The retained fragment must use canonical UTF-8 base64."); }
  expect(binary.length > 0 && binary.length <= MAX_FRAGMENT_BYTES && btoa(binary) === pkg.source_text_base64, "The retained fragment must use canonical UTF-8 base64.");
  const sourceBytes = Uint8Array.from(binary, character => character.charCodeAt(0)); const sourceText = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(sourceBytes);
  expect(!sourceText.includes("\0") && await expressionSha(sourceBytes) === pkg.source_content_sha256, "The retained fragment does not match its declared SHA256.");
  const chars = Array.from(sourceText); const localExpressions: LocalExpression[] = [];
  for (const entry of pkg.expressions) {
    const formula = await joined(chars, entry.subject.formula_spans), sampleLabel = await joined(chars, entry.subject.sample_label_spans) || null;
    const formulaScope = entry.subject.formula_spans.length === 1 ? "retained_formula_span" : "declared_formula_span_assembly";
    const window = await joined(chars, entry.window.label_spans) || null, model = await joined(chars, entry.model_spans) || null;
    const expressionKey = await expressionSha(expressionCanonical({ source_id: pkg.source.source_id, field_id: entry.field_id, subject: { formula, sample_label: sampleLabel, formula_scope: formulaScope }, window: { id: entry.window.id, raw_label: window }, source_role: entry.source_role, model }));
    const conditions = []; for (const item of entry.conditions) conditions.push({ field: item.field_id, role: item.role, rawValue: await joined(chars, item.value_spans), rawUnit: await joined(chars, item.unit_spans) || null });
    localExpressions.push({ expressionKey, entrySha: await expressionSha(expressionCanonical(entry)), field: entry.field_id, formula, sampleLabel, formulaScope, window, windowId: entry.window.id, model, role: entry.source_role, origin: entry.knowledge_origin,
      originStatement: entry.origin_basis.statement, originText: await joined(chars, entry.origin_basis.spans) || null, rawValue: await joined(chars, entry.value_spans), rawUnit: await joined(chars, entry.unit_spans) || null, conditions, locator: entry.locator });
  }
  expect(new Set(localExpressions.map(entry => entry.expressionKey)).size === localExpressions.length, "Each expression needs a distinct source, subject, window, role or model identity.");
  const canonical = expressionCanonical(retainedPackage(pkg)); expect(new TextEncoder().encode(canonical).length <= MAX_PACKAGE_METADATA_BYTES, "The package metadata exceeds the supported 128 KiB bound.");
  const packageSha = await expressionSha(canonical), requestSha = await expressionSha(expressionCanonical({ version: EXPRESSION_VERSION, package_sha256: packageSha }));
  return { package: pkg, packageSha, requestSha, fileSha: await expressionSha(bytes), fileBytes: bytes.length, fileName, retainedBytes: sourceBytes.length, localExpressions };
}
export function knownExpressionCapabilities(value: unknown, actorId: string): ExpressionCapabilities | null {
  return closed(value, "version package_version actor_user_id session_version can_import curator_grant_id registry_sha256 field_profiles max_source_bytes max_package_bytes max_projection_bytes max_expression_page_size max_expressions scope scientific_acceptance canonical_promotions public_content_release") && value.version === EXPRESSION_VERSION && value.package_version === PACKAGE_VERSION && uuid(value.actor_user_id) && value.actor_user_id === actorId && safe(value.session_version) && typeof value.can_import === "boolean" && (value.can_import ? uuid(value.curator_grant_id) : value.curator_grant_id === null) && value.registry_sha256 === EXPRESSION_REGISTRY_SHA && equal(value.field_profiles, EXPRESSION_FIELDS) && value.max_source_bytes === MAX_FRAGMENT_BYTES && value.max_package_bytes === MAX_PACKAGE_METADATA_BYTES && value.max_projection_bytes === MAX_PROJECTION_BYTES && value.max_expression_page_size === EXPRESSION_PAGE_SIZE && value.max_expressions === 20 && value.scope === "private_pending_source_expressions" && value.scientific_acceptance === false && value.canonical_promotions === 0 && value.public_content_release === false ? value as unknown as ExpressionCapabilities : null;
}

async function canonicalProof(source: unknown, sha: unknown, max = 524288): Promise<unknown> {
  expect(typeof source === "string" && new TextEncoder().encode(source).length <= max && hash(sha));
  expect(await expressionSha(source) === sha); return parseExpressionJson(source, false);
}
function retainedShape(value: unknown): value is Omit<ExpressionPackage, "source_text_base64"> {
  return closed(value, "version source source_content_sha256 expressions") && value.version === PACKAGE_VERSION && metadata(value.source) && hash(value.source_content_sha256) && Array.isArray(value.expressions) && value.expressions.length >= 1 && value.expressions.length <= 20 && value.expressions.every(entryShape);
}
function manifestShape(value: unknown): value is ExpressionManifest[] {
  return Array.isArray(value) && value.length >= 1 && value.length <= 20 && value.every((entry, index) => closed(entry, "entry_index expression_key entry_sha256 projection_sha256 predecessor_id predecessor_sha256 revision_number") && entry.entry_index === index && hash(entry.expression_key) && hash(entry.entry_sha256) && hash(entry.projection_sha256) && safe(entry.revision_number, 1, 10001) && (entry.revision_number === 1 ? entry.predecessor_id === null && entry.predecessor_sha256 === null : uuid(entry.predecessor_id) && hash(entry.predecessor_sha256))) && new Set(value.map(entry => entry.expression_key)).size === value.length;
}
const RECEIPT_KEYS = "version receipt_id receipt_sha256 actor_user_id actor_grant_id actor_session_version request_key request_sha256 preview_sha256 capture_id package_sha256 package_canonical_json request_canonical_json preview_canonical_json receipt_canonical_json expression_count expression_manifest count_scope replayed dry_run pending_ledger_written status scientific_acceptance canonical_promotions selected_result_association public_content_release";
async function receiptProof(value: unknown): Promise<ExpressionReceipt | null> {
  try {
    expect(closed(value, RECEIPT_KEYS) && value.version === EXPRESSION_VERSION && uuid(value.receipt_id) && hash(value.receipt_sha256) && uuid(value.actor_user_id) && uuid(value.actor_grant_id) && safe(value.actor_session_version) && text(value.request_key) && /^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$/.test(value.request_key as string) && hash(value.request_sha256) && hash(value.preview_sha256) && uuid(value.capture_id) && hash(value.package_sha256) && manifestShape(value.expression_manifest) && value.expression_count === value.expression_manifest.length && value.count_scope === "source_expression_revisions_not_independent_experiments" && typeof value.replayed === "boolean" && typeof value.dry_run === "boolean" && value.pending_ledger_written === !value.dry_run && (!value.replayed || !value.dry_run) && value.status === "pending" && value.scientific_acceptance === false && value.canonical_promotions === 0 && value.selected_result_association === "unestablished" && value.public_content_release === false);
    const receipt = value as unknown as ExpressionReceipt;
    const pkg = await canonicalProof(receipt.package_canonical_json, receipt.package_sha256, 131072); expect(retainedShape(pkg) && pkg.expressions.length === receipt.expression_count);
    const request = await canonicalProof(receipt.request_canonical_json, receipt.request_sha256, 4096); expect(equal(request, { version: EXPRESSION_VERSION, package_sha256: receipt.package_sha256 }));
    const actor = { actor_user_id: receipt.actor_user_id, actor_grant_id: receipt.actor_grant_id, actor_session_version: receipt.actor_session_version };
    const preview = await canonicalProof(receipt.preview_canonical_json, receipt.preview_sha256, 32768);
    expect(equal(preview, { version: EXPRESSION_VERSION, request_key: receipt.request_key, request_sha256: receipt.request_sha256, actor, manifest: receipt.expression_manifest }));
    const body = await canonicalProof(receipt.receipt_canonical_json, receipt.receipt_sha256);
    expect(equal(body, { id: receipt.receipt_id, ...actor, request_key: receipt.request_key, request_sha256: receipt.request_sha256, preview_sha256: receipt.preview_sha256, capture_id: receipt.capture_id, package_json: receipt.package_canonical_json, package_sha256: receipt.package_sha256, expression_count: receipt.expression_count, expression_manifest: receipt.expression_manifest }));
    for (const [index, entry] of pkg.expressions.entries()) {
      const pin = receipt.expression_manifest[index]; expect(pin.entry_sha256 === await expressionSha(expressionCanonical(entry)));
      expect(entry.predecessor === null ? pin.revision_number === 1 && pin.predecessor_id === null && pin.predecessor_sha256 === null : pin.revision_number === entry.predecessor.revision_number + 1 && pin.predecessor_id === entry.predecessor.revision_id && pin.predecessor_sha256 === entry.predecessor.record_sha256);
    }
    return receipt;
  } catch { return null; }
}
export async function knownExpressionReceipt(value: unknown, cap: ExpressionCapabilities, ref: ExpressionRecovery, stage: "preview" | "commit" | "outcome", prepared: PreparedExpressionPackage | null = null): Promise<ExpressionReceipt | null> {
  const receipt = await receiptProof(value); if (!receipt || receipt.actor_user_id !== cap.actor_user_id || receipt.actor_user_id !== ref.actorId || receipt.request_key !== ref.requestKey || receipt.request_sha256 !== ref.requestSha || receipt.package_sha256 !== ref.packageSha || receipt.package_canonical_json !== ref.packageCanonical) return null;
  if (stage !== "preview" && (!hash(ref.previewSha) || receipt.preview_sha256 !== ref.previewSha || expressionCanonical(receipt.expression_manifest) !== ref.manifestCanonical || receipt.dry_run)) return null;
  if (stage === "preview" && !receipt.replayed && !receipt.dry_run || stage === "outcome" && !receipt.replayed) return null;
  if (!receipt.replayed && (receipt.actor_session_version !== cap.session_version || receipt.actor_grant_id !== cap.curator_grant_id)) return null;
  if (prepared && (prepared.localExpressions.length !== receipt.expression_count || receipt.expression_manifest.some((pin, index) => pin.expression_key !== prepared.localExpressions[index].expressionKey || pin.entry_sha256 !== prepared.localExpressions[index].entrySha))) return null;
  return receipt;
}
export function expressionRecovery(prepared: PreparedExpressionPackage, cap: ExpressionCapabilities, requestKey: string): ExpressionRecovery {
  return { actorId: cap.actor_user_id, requestKey, requestSha: prepared.requestSha, packageSha: prepared.packageSha, previewSha: "", manifestCanonical: "", packageCanonical: expressionCanonical(retainedPackage(prepared.package)) };
}
function sourceValue(value: unknown, field: string): value is SourceValue {
  if (EXPRESSION_FIELDS[field] == null) return closed(value, "raw_value status") && rawText(value.raw_value, 1200) && value.status === "source_statement";
  if (!closed(value, "raw_value raw_unit value unit uncertainty uncertainty_interpretation approximate relation status unit_basis") || !rawText(value.raw_value, 1200) || !rawText(value.raw_unit, 1200, true) || typeof value.approximate !== "boolean") return false;
  if (value.status === "parsed") return value.raw_unit !== null && typeof value.value === "number" && Number.isFinite(value.value) && value.unit === EXPRESSION_FIELDS[field] && (value.uncertainty === null && value.uncertainty_interpretation === null || typeof value.uncertainty === "number" && Number.isFinite(value.uncertainty) && value.uncertainty >= 0 && value.uncertainty_interpretation === "unspecified") && value.relation === "exact" && value.unit_basis === "source_printed";
  return includes(["value_requires_review", "unit_not_supplied", "unit_requires_review"], value.status) && value.value === null && value.unit === null && value.uncertainty === null && value.uncertainty_interpretation === null && value.relation === "unresolved" && value.unit_basis === "unresolved" && (value.status !== "unit_not_supplied" || value.raw_unit === null);
}
function projectionShape(value: unknown): value is ExpressionProjection {
  return closed(value, "source_id field_id subject window source_role model expression_key knowledge_origin origin_basis value conditions locator status selected_result_association sample_identity_established phase_identity_established scientific_acceptance canonical_promotions missingness_scope") && text(value.source_id) && typeof value.field_id === "string" && Object.hasOwn(EXPRESSION_FIELDS, value.field_id) && closed(value.subject, "formula sample_label formula_scope") && rawText(value.subject.formula, 200) && rawText(value.subject.sample_label, 200, true) && includes(["retained_formula_span", "declared_formula_span_assembly"], value.subject.formula_scope) && closed(value.window, "id raw_label") && text(value.window.id) && rawText(value.window.raw_label, 500, true) && includes(ROLES, value.source_role) && rawText(value.model, 500, true) && hash(value.expression_key) && includes(["Observed", "Computed", "unknown"], value.knowledge_origin) && closed(value.origin_basis, "statement retained_text verification") && text(value.origin_basis.statement, 500, true) && rawText(value.origin_basis.retained_text, 1000, true) && value.origin_basis.verification === "declared_inspection_basis" && sourceValue(value.value, value.field_id) && Array.isArray(value.conditions) && value.conditions.length <= 8 && value.conditions.every(condition => closed(condition, "field_id role value") && includes(CONDITION_FIELDS, condition.field_id) && includes(CONDITION_ROLES, condition.role) && sourceValue(condition.value, condition.field_id as string)) && locator(value.locator) && value.status === "pending" && value.selected_result_association === "unestablished" && value.sample_identity_established === false && value.phase_identity_established === false && value.scientific_acceptance === false && value.canonical_promotions === 0 && value.missingness_scope === "not_supplied_in_retained_expression_is_not_source_absence";
}
async function rawBinding(raw: string | null, spans: ExpressionSpan[]): Promise<boolean> {
  if (spans.length === 0) return raw === null;
  if (raw === null) return false;
  const chars = Array.from(raw); if (chars.length !== spans.reduce((sum, span) => sum + span.end - span.start, 0)) return false;
  let offset = 0; for (const span of spans) { const length = span.end - span.start; if (await expressionSha(chars.slice(offset, offset + length).join("")) !== span.sha256) return false; offset += length; } return true;
}
async function projectionBinding(projection: ExpressionProjection, entry: ExpressionRequest, source: SourceMetadata): Promise<boolean> {
  if (projection.source_id !== source.source_id || projection.field_id !== entry.field_id || projection.source_role !== entry.source_role || projection.knowledge_origin !== entry.knowledge_origin || projection.window.id !== entry.window.id || projection.origin_basis.statement !== entry.origin_basis.statement || !equal(projection.locator, entry.locator) || projection.conditions.length !== entry.conditions.length || projection.subject.formula_scope !== (entry.subject.formula_spans.length === 1 ? "retained_formula_span" : "declared_formula_span_assembly")) return false;
  if (!await rawBinding(projection.subject.formula, entry.subject.formula_spans) || !await rawBinding(projection.subject.sample_label, entry.subject.sample_label_spans) || !await rawBinding(projection.window.raw_label, entry.window.label_spans) || !await rawBinding(projection.model, entry.model_spans) || !await rawBinding(projection.origin_basis.retained_text, entry.origin_basis.spans) || !await rawBinding(projection.value.raw_value, entry.value_spans)) return false;
  // An inline printed unit can exist inside value_spans. An explicit unit span must match exactly.
  if (entry.unit_spans.length && (!("raw_unit" in projection.value) || !await rawBinding(projection.value.raw_unit, entry.unit_spans))) return false;
  for (const [index, condition] of projection.conditions.entries()) { const input = entry.conditions[index]; if (condition.field_id !== input.field_id || condition.role !== input.role || !await rawBinding(condition.value.raw_value, input.value_spans) || input.unit_spans.length && (!("raw_unit" in condition.value) || !await rawBinding(condition.value.raw_unit, input.unit_spans))) return false; }
  const identity = { source_id: source.source_id, field_id: projection.field_id, subject: projection.subject, window: projection.window, source_role: projection.source_role, model: projection.model };
  return projection.expression_key === await expressionSha(expressionCanonical(identity));
}
const CAPTURE_KEYS = "id record_sha256 source source_metadata_canonical_json source_content_sha256 metadata_sha256 retained_utf8_bytes fragment_integrity parent_integrity publication_revision_verified rights_verified publication_currentness_verified latest_retained_capture_for_source public_content_release";
export async function knownSourceCapture(value: unknown, detailId?: string, original?: SourceCapture): Promise<SourceCapture | null> {
  try { expect(closed(value, detailId ? `version ${CAPTURE_KEYS}` : CAPTURE_KEYS) && (!detailId || value.version === EXPRESSION_VERSION && value.id === detailId) && uuid(value.id) && hash(value.record_sha256) && metadata(value.source) && hash(value.source_content_sha256) && hash(value.metadata_sha256) && safe(value.retained_utf8_bytes, 1, MAX_FRAGMENT_BYTES) && value.fragment_integrity === "server_verified_retained_bytes" && value.parent_integrity === "declared_not_verified" && value.publication_revision_verified === false && value.rights_verified === false && value.publication_currentness_verified === false && typeof value.latest_retained_capture_for_source === "boolean" && value.public_content_release === false);
    expect(equal(await canonicalProof(value.source_metadata_canonical_json, value.metadata_sha256, 8192), value.source));
    if (original) expect(value.id === original.id && value.record_sha256 === original.record_sha256 && value.source_content_sha256 === original.source_content_sha256 && value.metadata_sha256 === original.metadata_sha256 && value.source_metadata_canonical_json === original.source_metadata_canonical_json && value.retained_utf8_bytes === original.retained_utf8_bytes);
    return value as unknown as SourceCapture;
  } catch { return null; }
}
const REVISION_KEYS = "id record_sha256 expression_key revision_canonical_json entry_index source_entry_sha256 import_receipt_id import_receipt_sha256 import_receipt revision_number predecessor_id predecessor_sha256 projection_sha256 projection_canonical_json projection source_entry is_expression_head capture";
export async function knownSourceRevision(value: unknown, detailId?: string, expectedRecordSha?: string): Promise<SourceRevision | null> {
  try {
    expect(closed(value, detailId ? `version ${REVISION_KEYS}` : REVISION_KEYS) && (!detailId || value.version === EXPRESSION_VERSION && value.id === detailId) && uuid(value.id) && hash(value.record_sha256) && (!expectedRecordSha || value.record_sha256 === expectedRecordSha) && hash(value.expression_key) && safe(value.entry_index, 0, 19) && hash(value.source_entry_sha256) && uuid(value.import_receipt_id) && hash(value.import_receipt_sha256) && safe(value.revision_number, 1, 10001) && (value.revision_number === 1 ? value.predecessor_id === null && value.predecessor_sha256 === null : uuid(value.predecessor_id) && hash(value.predecessor_sha256)) && hash(value.projection_sha256) && projectionShape(value.projection) && entryShape(value.source_entry) && typeof value.is_expression_head === "boolean");
    const revision = value as unknown as SourceRevision, capture = await knownSourceCapture(revision.capture); expect(capture);
    expect(equal(await canonicalProof(revision.projection_canonical_json, revision.projection_sha256, 32768), revision.projection));
    const body = await canonicalProof(revision.revision_canonical_json, revision.record_sha256, 65536);
    expect(closed(body, "id actor_user_id actor_grant_id actor_session_version import_receipt_id import_receipt_sha256 capture_id entry_index entry_sha256 expression_key field_id revision_number predecessor_id predecessor_sha256 projection_json projection_sha256") && uuid(body.actor_user_id) && uuid(body.actor_grant_id) && safe(body.actor_session_version));
    expect(equal(body, { id: revision.id, actor_user_id: body.actor_user_id, actor_grant_id: body.actor_grant_id, actor_session_version: body.actor_session_version, import_receipt_id: revision.import_receipt_id, import_receipt_sha256: revision.import_receipt_sha256, capture_id: capture.id, entry_index: revision.entry_index, entry_sha256: revision.source_entry_sha256, expression_key: revision.expression_key, field_id: revision.projection.field_id, revision_number: revision.revision_number, predecessor_id: revision.predecessor_id, predecessor_sha256: revision.predecessor_sha256, projection_json: revision.projection_canonical_json, projection_sha256: revision.projection_sha256 }));
    expect(revision.expression_key === revision.projection.expression_key && revision.source_entry_sha256 === await expressionSha(expressionCanonical(revision.source_entry)) && await projectionBinding(revision.projection, revision.source_entry, capture.source));
    expect(revision.source_entry.predecessor === null ? revision.revision_number === 1 : revision.source_entry.predecessor.revision_id === revision.predecessor_id && revision.source_entry.predecessor.record_sha256 === revision.predecessor_sha256 && revision.source_entry.predecessor.revision_number + 1 === revision.revision_number);
    if (detailId) {
      const receipt = await receiptProof(revision.import_receipt); expect(receipt && !receipt.dry_run && receipt.receipt_id === revision.import_receipt_id && receipt.receipt_sha256 === revision.import_receipt_sha256 && receipt.capture_id === capture.id && receipt.actor_user_id === body.actor_user_id && receipt.actor_grant_id === body.actor_grant_id && receipt.actor_session_version === body.actor_session_version);
      const pkg = parseExpressionJson(receipt.package_canonical_json) as Omit<ExpressionPackage, "source_text_base64">;
      const pin = receipt.expression_manifest[revision.entry_index]; expect(pin && pin.expression_key === revision.expression_key && pin.entry_sha256 === revision.source_entry_sha256 && pin.projection_sha256 === revision.projection_sha256 && pin.predecessor_id === revision.predecessor_id && pin.predecessor_sha256 === revision.predecessor_sha256 && pin.revision_number === revision.revision_number && equal(pkg.expressions[revision.entry_index], revision.source_entry) && equal(pkg.source, capture.source) && pkg.source_content_sha256 === capture.source_content_sha256);
    } else expect(revision.import_receipt === null);
    return revision;
  } catch { return null; }
}
export async function knownExpressionPage(value: unknown, offset: number, limit: number, filters: ExpressionFilters = {}): Promise<ExpressionPage | null> {
  if (!safe(offset, 0, 10000) || !safe(limit, 1, EXPRESSION_PAGE_SIZE) || !closed(value, "version total offset limit count_scope expressions scientific_acceptance canonical_promotions") || value.version !== EXPRESSION_VERSION || !safe(value.total) || value.offset !== offset || value.limit !== limit || value.count_scope !== "current_pending_expression_heads_not_experiments_or_verified_properties" || value.scientific_acceptance !== false || value.canonical_promotions !== 0 || !Array.isArray(value.expressions) || value.expressions.length > limit || value.expressions.length !== Math.min(limit, Math.max(0, value.total - offset))) return null;
  const items = await Promise.all(value.expressions.map(item => knownSourceRevision(item)));
  if (items.some(item => !item || !item.is_expression_head || filters.field && item.projection.field_id !== filters.field || filters.sourceId && item.capture.source.source_id !== filters.sourceId || filters.currentness && item.capture.source.currentness !== filters.currentness) || new Set(items.map(item => item?.expression_key)).size !== items.length) return null;
  return value as unknown as ExpressionPage;
}
export async function knownCapturePage(value: unknown, offset: number, limit: number, currentness?: string): Promise<CapturePage | null> {
  if (!safe(offset, 0, 10000) || !safe(limit, 1, 50) || !closed(value, "version total offset limit count_scope captures") || value.version !== EXPRESSION_VERSION || !safe(value.total) || value.offset !== offset || value.limit !== limit || value.count_scope !== "retained_source_fragments_not_publications_or_experiments" || !Array.isArray(value.captures) || value.captures.length > limit || value.captures.length !== Math.min(limit, Math.max(0, value.total - offset))) return null;
  const items = await Promise.all(value.captures.map(item => knownSourceCapture(item))); if (items.some(item => !item || currentness && item.source.currentness !== currentness) || new Set(items.map(item => item?.id)).size !== items.length) return null;
  return value as unknown as CapturePage;
}
export function expressionFieldLabel(field: string): string {
  return ({ tc_kelvin: "Reported Tc", pressure_gpa: "Pressure", measurement_temperature_k: "Measurement temperature", magnetic_field_t: "Magnetic field", hc2_tesla: "Upper critical field", lambda_london_nm: "London penetration depth", lambda_eph: "Electron–phonon coupling λ", omega_log_k: "Logarithmic phonon frequency", mu_star: "Coulomb pseudopotential μ*", lattice_a: "Lattice a", lattice_b: "Lattice b", lattice_c: "Lattice c", method_statement: "Method", sample_form_statement: "Sample form", structure_statement: "Structure statement", classification_statement: "Classification statement", criterion_statement: "Criterion", window_statement: "Source window" } as Record<string, string>)[field] ?? field;
}
export function sourceValueLabel(value: SourceValue): string {
  if (!("raw_unit" in value) || !value.raw_unit || value.raw_value.trim().endsWith(value.raw_unit)) return value.raw_value;
  return `${value.raw_value} ${value.raw_unit}`;
}
