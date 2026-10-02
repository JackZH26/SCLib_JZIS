/** Synthetic authenticated DTO envelopes around the actual fixed source projections.
 * These are test actors and fidelity notes, never a human/scientific review receipt.
 */
import { PROPERTY_SNAPSHOTS, SOURCE_PROPERTY_REGISTRY, SOURCE_PROPERTY_VERSION, propertyDigest, propertyImportRequestSha,
  sourcePropertyManifest, sourcePropertyProjection, type PropertyCapabilities, type PropertyDetail, type PropertyImportReceipt,
  type PropertyNote, type PropertyObservation, type PropertyReviewRequest } from "@/lib/source-properties";
export const actorId = "00000000-0000-4000-8000-000000000001";
export const otherId = "00000000-0000-4000-8000-000000000002";
export const grantId = "00000000-0000-4000-8000-000000000003";
export const uuid = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
export const access: PropertyCapabilities = { version: SOURCE_PROPERTY_VERSION, actor_user_id: actorId, session_version: 1, can_import: true, can_append_source_note: true,
  grants: { curator: grantId, reviewer: grantId }, registry_sha256: SOURCE_PROPERTY_REGISTRY, canonical_promotions: 0, scientific_acceptance: false, scope: "private_pending_source_expressions" };
export const copy = <T,>(v: T): T => structuredClone(v);
export function observation(index = 0, batchIndex = 0): PropertyObservation {
  const batch = PROPERTY_SNAPSHOTS[batchIndex], manifest = sourcePropertyManifest(batch.sha256)[index];
  return { id: uuid(index + 10 + batchIndex * 20), record_sha256: "a".repeat(64), revision_number: 1, source_json_sha256: batch.sha256,
    original_batch_sha256: batch.original_sha256, registry_sha256: SOURCE_PROPERTY_REGISTRY,
    projection_sha256: manifest.projection_sha256, projection: sourcePropertyProjection(manifest.source_entry_id)! };
}
export const detail = (index = 0, batchIndex = 0): PropertyDetail => ({ ...observation(index, batchIndex), source_notes: [], source_notes_total: 0, source_notes_truncated: false });
export const page = () => ({ version: SOURCE_PROPERTY_VERSION, total: 1, offset: 0, limit: 25,
  count_scope: "pending_source_task_observations_not_independent_experiments", observations: [observation()], canonical_promotions: 0, scientific_acceptance: false });
export async function importReceipt(key: string, dryRun = true, replayed = false, sourceSha: string = PROPERTY_SNAPSHOTS[0].sha256, caps = access): Promise<PropertyImportReceipt> {
  const batch = PROPERTY_SNAPSHOTS.find(item => item.sha256 === sourceSha)!, requestHash = await propertyImportRequestSha(sourceSha), manifest = sourcePropertyManifest(sourceSha);
  const preview = await propertyDigest({ version: SOURCE_PROPERTY_VERSION, request_key: key, request_sha256: requestHash,
    actor: { actor_user_id: caps.actor_user_id, actor_grant_id: caps.grants.curator, actor_session_version: caps.session_version }, summary: batch.summary, observation_manifest: manifest });
  return { version: SOURCE_PROPERTY_VERSION, receipt_id: uuid(99), receipt_sha256: "b".repeat(64), actor_user_id: caps.actor_user_id, actor_session_version: caps.session_version, actor_grant_id: caps.grants.curator!,
    request_sha256: requestHash, preview_sha256: preview, source_json_sha256: sourceSha, original_batch_sha256: batch.original_sha256, batch_id: batch.id, summary: copy(batch.summary),
    observation_manifest: manifest, status: "pending", scientific_acceptance: false, canonical_promotions: 0, selected_result_association: "unestablished", replayed,
    ...(!replayed ? { dry_run: dryRun } : {}), pending_ledger_written: replayed || !dryRun };
}
export async function noteReceipt(request: PropertyReviewRequest, dryRun = true, caps = access, reviewNumber = 1): Promise<PropertyNote> {
  const { request_key: _key, expected_previous_review_id: _id, expected_previous_review_sha256: parentHash, ...body } = request, requestHash = await propertyDigest(request);
  return { version: SOURCE_PROPERTY_VERSION, review_id: uuid(200 + reviewNumber), review_sha256: "c".repeat(64), actor_user_id: caps.actor_user_id, actor_session_version: caps.session_version, actor_grant_id: caps.grants.reviewer!,
    source_note_sha256: await propertyDigest(body), observation_id: request.observation_id, request_sha256: requestHash,
    preview_sha256: await propertyDigest({ version: SOURCE_PROPERTY_VERSION, actor: { actor_user_id: caps.actor_user_id, actor_grant_id: caps.grants.reviewer, actor_session_version: caps.session_version }, request_sha256: requestHash,
      observation_sha256: request.observation_sha256, previous_review_sha256: parentHash }), review_number: reviewNumber, source_note: body,
    status: "pending", scientific_acceptance: false, canonical_promotions: 0, selected_result_association: "unestablished", replayed: false, dry_run: dryRun, pending_ledger_written: !dryRun };
}
export function requestNote(current = detail()): PropertyReviewRequest {
  const head = current.source_notes[0];
  return { request_key: "test-source-note:one", observation_id: current.id, observation_sha256: current.record_sha256,
    expected_previous_review_id: head?.review_id ?? null, expected_previous_review_sha256: head?.review_sha256 ?? null,
    scope: "source_expression_fidelity_note", action: "requires_clarification", checks: ["source_expression"], note: "Test-only source inspection note.", source_inspection_attested: true };
}
