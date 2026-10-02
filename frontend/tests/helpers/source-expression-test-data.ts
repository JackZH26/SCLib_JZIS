/** Small synthetic source and transaction rows; these are not source inspection or human review. */
import { EXPRESSION_FIELDS, EXPRESSION_REGISTRY_SHA, EXPRESSION_VERSION, PACKAGE_VERSION, expressionCanonical, expressionSha,
  prepareExpressionPackage, type ExpressionCapabilities, type ExpressionPackage, type ExpressionReceipt, type ExpressionRequest,
  type PreparedExpressionPackage, type SourceCapture, type SourceRevision } from "@/lib/source-expressions";

export const expressionActor = "00000000-0000-4000-8000-000000000101";
export const expressionGrant = "00000000-0000-4000-8000-000000000102";
const captureId = "00000000-0000-4000-8000-000000000103";
const receiptId = "00000000-0000-4000-8000-000000000104";
const revisionId = "00000000-0000-4000-8000-000000000105";
export const expressionCap: ExpressionCapabilities = { version: EXPRESSION_VERSION, package_version: PACKAGE_VERSION,
  actor_user_id: expressionActor, session_version: 2, can_import: true, curator_grant_id: expressionGrant, registry_sha256: EXPRESSION_REGISTRY_SHA,
  field_profiles: EXPRESSION_FIELDS, max_source_bytes: 131072, max_package_bytes: 131072, max_projection_bytes: 32768, max_expression_page_size: 8, max_expressions: 20, scope: "private_pending_source_expressions",
  scientific_acceptance: false, canonical_promotions: 0, public_content_release: false };

export async function syntheticPackage(raw = "94.5 ± 0.3", unit = "K"): Promise<ExpressionPackage> {
  const sourceText = `🌿 LaH10 | ambient | ${raw} | ${unit} | computed | example fit`;
  const chars = Array.from(sourceText);
  async function spans(part: string) {
    if (!part) return [];
    const utf16 = sourceText.indexOf(part), start = Array.from(sourceText.slice(0, utf16)).length;
    return [{ start, end: start + Array.from(part).length, sha256: await expressionSha(part) }];
  }
  const entry: ExpressionRequest = { field_id: "tc_kelvin", subject: { formula_spans: await spans("LaH10"), sample_label_spans: [] },
    window: { id: "conference-slide-6", label_spans: await spans("ambient") }, source_role: "source_reported", knowledge_origin: "Computed",
    origin_basis: { statement: "Synthetic declared computation context", spans: await spans("computed") }, model_spans: await spans("example fit"),
    value_spans: await spans(raw), unit_spans: await spans(unit), conditions: [{ field_id: "window_statement", role: "fit_window", value_spans: await spans("ambient"), unit_spans: [] }],
    locator: { page: null, slide: 6, table: null, row: 1, column: 2, section: null, member: null }, predecessor: null };
  // Keep the fixture codepoint-aware so a regression to UTF-16 offsets has real consequences.
  if (chars.length === sourceText.length) throw new Error("Synthetic test source must exercise non-BMP offsets");
  const bytes = new TextEncoder().encode(sourceText);
  return { version: PACKAGE_VERSION, source: { source_id: "test-conference", url: "https://example.com/source.pdf", kind: "conference_presentation", content_kind: "plain_text",
    revision: "slide-capture-1", revision_status: "declared", original_parent_sha256: await expressionSha("synthetic parent bytes"), parent_hash_status: "declared", rights_status: "declared_private_inspection", currentness: "historical", captured_at: "2026-10-02T00:00:00Z" },
    source_text_base64: btoa(Array.from(bytes, byte => String.fromCharCode(byte)).join("")), source_content_sha256: await expressionSha(bytes), expressions: [entry] };
}
export async function preparedSynthetic(raw?: string, unit?: string) { const pkg = await syntheticPackage(raw, unit); return prepareExpressionPackage(new TextEncoder().encode(JSON.stringify(pkg, null, 2))); }
export async function syntheticReceipt(prepared: PreparedExpressionPackage, key: string, dryRun = true): Promise<ExpressionReceipt> {
  const manifest = prepared.localExpressions.map((entry, index) => ({ entry_index: index, expression_key: entry.expressionKey, entry_sha256: entry.entrySha,
    projection_sha256: "1".repeat(64), predecessor_id: null, predecessor_sha256: null, revision_number: 1 }));
  const { source_text_base64: _private, ...retained } = prepared.package;
  const requestCanonical = expressionCanonical({ version: EXPRESSION_VERSION, package_sha256: prepared.packageSha });
  const previewCanonical = expressionCanonical({ version: EXPRESSION_VERSION, request_key: key, request_sha256: prepared.requestSha,
    actor: { actor_user_id: expressionActor, actor_grant_id: expressionGrant, actor_session_version: 2 }, manifest });
  const packageCanonical = expressionCanonical(retained), previewSha = await expressionSha(previewCanonical);
  const body = { id: receiptId, actor_user_id: expressionActor, actor_grant_id: expressionGrant, actor_session_version: 2, request_key: key,
    request_sha256: prepared.requestSha, preview_sha256: previewSha, capture_id: captureId, package_json: packageCanonical, package_sha256: prepared.packageSha,
    expression_count: manifest.length, expression_manifest: manifest };
  const receiptCanonical = expressionCanonical(body);
  return { version: EXPRESSION_VERSION, receipt_id: receiptId, receipt_sha256: await expressionSha(receiptCanonical), actor_user_id: expressionActor,
    actor_grant_id: expressionGrant, actor_session_version: 2, request_key: key, request_sha256: prepared.requestSha, preview_sha256: previewSha, capture_id: captureId,
    package_sha256: prepared.packageSha, package_canonical_json: packageCanonical, request_canonical_json: requestCanonical,
    preview_canonical_json: previewCanonical, receipt_canonical_json: receiptCanonical, expression_count: manifest.length, expression_manifest: manifest,
    count_scope: "source_expression_revisions_not_independent_experiments", replayed: false, dry_run: dryRun, pending_ledger_written: !dryRun,
    status: "pending", scientific_acceptance: false, canonical_promotions: 0, selected_result_association: "unestablished", public_content_release: false };
}
export async function syntheticRevision(): Promise<SourceRevision & { version: string }> {
  const prepared = await preparedSynthetic(), entry = prepared.package.expressions[0], local = prepared.localExpressions[0];
  const projection = { source_id: prepared.package.source.source_id, field_id: "tc_kelvin", subject: { formula: "LaH10", sample_label: null, formula_scope: "retained_formula_span" },
    window: { id: entry.window.id, raw_label: "ambient" }, source_role: entry.source_role, model: "example fit", expression_key: local.expressionKey,
    knowledge_origin: "Computed", origin_basis: { statement: entry.origin_basis.statement, retained_text: "computed", verification: "declared_inspection_basis" },
    value: { raw_value: local.rawValue, raw_unit: "K", value: 94.5, unit: "K", uncertainty: 0.3, uncertainty_interpretation: "unspecified", approximate: false, relation: "exact", status: "parsed", unit_basis: "source_printed" },
    conditions: [{ field_id: "window_statement", role: "fit_window", value: { raw_value: "ambient", status: "source_statement" } }], locator: entry.locator,
    status: "pending", selected_result_association: "unestablished", sample_identity_established: false, phase_identity_established: false,
    scientific_acceptance: false, canonical_promotions: 0, missingness_scope: "not_supplied_in_retained_expression_is_not_source_absence" } as SourceRevision["projection"];
  // Python emits floats as 94.5 and 0.3; preserve those exact strings rather than use the integer canonicalizer.
  const projectionCanonical = JSON.stringify(projection, (_key, value) => value), projectionSha = await expressionSha(projectionCanonical);
  const receipt = await syntheticReceipt(prepared, "test-intake:detail", false);
  receipt.expression_manifest[0].projection_sha256 = projectionSha;
  const previewBody = JSON.parse(receipt.preview_canonical_json); previewBody.manifest = receipt.expression_manifest;
  receipt.preview_canonical_json = expressionCanonical(previewBody); receipt.preview_sha256 = await expressionSha(receipt.preview_canonical_json);
  const receiptBody = JSON.parse(receipt.receipt_canonical_json); receiptBody.preview_sha256 = receipt.preview_sha256; receiptBody.expression_manifest = receipt.expression_manifest;
  receipt.receipt_canonical_json = expressionCanonical(receiptBody); receipt.receipt_sha256 = await expressionSha(receipt.receipt_canonical_json);
  const capture: SourceCapture = { id: captureId, record_sha256: await expressionSha("synthetic capture record"), source: prepared.package.source,
    source_metadata_canonical_json: expressionCanonical(prepared.package.source), source_content_sha256: prepared.package.source_content_sha256,
    metadata_sha256: await expressionSha(expressionCanonical(prepared.package.source)), retained_utf8_bytes: prepared.retainedBytes,
    fragment_integrity: "server_verified_retained_bytes", parent_integrity: "declared_not_verified", publication_revision_verified: false, rights_verified: false,
    publication_currentness_verified: false, latest_retained_capture_for_source: true, public_content_release: false };
  const body = { id: revisionId, actor_user_id: expressionActor, actor_grant_id: expressionGrant, actor_session_version: 2, import_receipt_id: receiptId, import_receipt_sha256: receipt.receipt_sha256,
    capture_id: captureId, entry_index: 0, entry_sha256: local.entrySha, expression_key: local.expressionKey, field_id: "tc_kelvin", revision_number: 1,
    predecessor_id: null, predecessor_sha256: null, projection_json: projectionCanonical, projection_sha256: projectionSha };
  const revisionCanonical = expressionCanonical(body);
  return { version: EXPRESSION_VERSION, id: revisionId, record_sha256: await expressionSha(revisionCanonical), expression_key: local.expressionKey,
    revision_canonical_json: revisionCanonical, entry_index: 0, source_entry_sha256: local.entrySha, import_receipt_id: receiptId, import_receipt_sha256: receipt.receipt_sha256, import_receipt: receipt,
    revision_number: 1, predecessor_id: null, predecessor_sha256: null, projection_sha256: projectionSha, projection_canonical_json: projectionCanonical,
    projection, source_entry: entry, is_expression_head: true, capture };
}
export function emptyExpressionPage() { return { version: EXPRESSION_VERSION, total: 0, offset: 0, limit: 8,
  count_scope: "current_pending_expression_heads_not_experiments_or_verified_properties", expressions: [], scientific_acceptance: false, canonical_promotions: 0 }; }
export function emptyCapturePage() { return { version: EXPRESSION_VERSION, total: 0, offset: 0, limit: 25, count_scope: "retained_source_fragments_not_publications_or_experiments", captures: [] }; }
