/** Ephemeral byte replay. A matching hash is not evidence of scientific support. */
import { boundedPilotOperation, pilotBytesHash, pilotHash, PILOT_FILE_LIMIT } from "./ml-pilot-participation";
import { parsePrivateDiscoveryJSON } from "./discovery-scientific";
import { importCanonical, importDigest } from "./scientific-imports";
import { parseReviewCoverage, REVIEW_FILES, validReviewRef, type ReviewBasis, type ReviewCoverage, type ReviewDocumentSet, type ReviewRef } from "./ml-pilot-reviews";

export const EVIDENCE_TYPE = "application/vnd.sclib.ml08-evidence-v1";
export const EVIDENCE_MAGIC = "SCLIB-ML08-EVIDENCE-1\n";
export const CANARY_LIMIT = 32 * 1024 * 1024;
export const CONTEXT_LIMIT = 64 * 1024 * 1024;
export const EVIDENCE_LIMIT = new TextEncoder().encode(EVIDENCE_MAGIC).length + 9 + 1024 * 1024 + 4 * PILOT_FILE_LIMIT + CANARY_LIMIT + CONTEXT_LIMIT;
type Obj = Record<string, unknown>;
export type EvidenceUpload = { body: Blob; inventorySha256: string; contextCount: number; contextBytes: number };
export type EvidenceSnapshot = { account: ReviewCoverage; contextCount: number; contextBytes: number; canarySha256: string; implementationSha256: string; inputSha256: string };
const object = (v: unknown): v is Obj => v !== null && typeof v === "object" && !Array.isArray(v);
const closed = (v: unknown, keys: string[]): v is Obj => object(v) && Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));
function requireValue(v: unknown): asserts v { if (!v) throw new Error("The exact canary and context bytes could not be verified."); }
const denied = ["scientific_acceptance", "scientific_pilot_accepted", "human_identity_verified", "scientific_reviewer_independence_verified", "source_permissions_verified",
  "actual_event_existence_verified", "external_review_chronology_verified", "public_release", "ml_training_approved", "run_authorization_granted",
  "source_document_bytes_retained", "external_digital_signature_verified", "current_collective_signoff_verified", "attestation_recorded"];

export async function prepareEvidence(ref: ReviewRef, basis: ReviewBasis, originals: ReviewDocumentSet, canary: File, contexts: File[], signal?: AbortSignal): Promise<EvidenceUpload> {
  requireValue(validReviewRef(ref) && pilotHash(basis.declared_canary_sha256) && closed(originals, [...REVIEW_FILES])
    && REVIEW_FILES.every(k => originals[k]?.size > 0 && originals[k].size <= PILOT_FILE_LIMIT && pilotHash(basis.input_pins[`${k}_file_sha256`]))
    && canary?.size > 0 && canary.size <= CANARY_LIMIT && contexts.length <= 6000);
  const sorted = [...contexts].sort((a, b) => a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
  requireValue(sorted.every((file, i) => /^[0-9a-f]{64}\.bin$/.test(file.name) && file.size > 0 && file.size <= PILOT_FILE_LIMIT && (!i || sorted[i - 1].name !== file.name)));
  const inventory = sorted.map(file => ({ sha256: file.name.slice(0, 64), size_bytes: file.size }));
  const contextBytes = inventory.reduce((sum, row) => sum + row.size_bytes, 0);
  requireValue(contextBytes <= CONTEXT_LIMIT);
  return boundedPilotOperation(async (active, interrupted) => {
    const bytes = new Uint8Array(await Promise.race([canary.arrayBuffer(), interrupted]));
    requireValue(!active.aborted && bytes.length === canary.size && await pilotBytesHash(bytes) === basis.declared_canary_sha256);
    const entries = REVIEW_FILES.map(k => ({ key: k, sha256: basis.input_pins[`${k}_file_sha256`], size_bytes: originals[k].size }));
    const metadata = new TextEncoder().encode(importCanonical({ version: "ml08-evidence-upload/1.0.0", parameters: ref,
      selection_sha256: basis.selection_sha256, review_log_sha256: basis.review_log_sha256,
      files: [...entries, { key: "canary", sha256: basis.declared_canary_sha256, size_bytes: canary.size }, ...inventory.map(row => ({ ...row, key: row.sha256 + ".bin" }))] }));
    requireValue(metadata.length > 0 && metadata.length <= 1024 * 1024);
    const body = new Blob([EVIDENCE_MAGIC, metadata.length.toString(16).padStart(8, "0") + "\n", metadata, ...REVIEW_FILES.map(k => originals[k]), canary, ...sorted], { type: EVIDENCE_TYPE });
    const inventorySha256 = await importDigest(inventory);
    requireValue(!active.aborted && body.size <= EVIDENCE_LIMIT);
    return { body, inventorySha256, contextCount: contexts.length, contextBytes };
  }, signal, 30000);
}

export function parseEvidenceSnapshot(raw: string, actorId: string, ref: ReviewRef, basis: ReviewBasis, uploaded: EvidenceUpload): EvidenceSnapshot {
  const value = parsePrivateDiscoveryJSON(raw, 128 * 1024).value;
  requireValue(importCanonical(value) === raw && closed(value, ["version", "scope", "training_execution", "actor_user_id", "participant_id", "participant_sha256", "registration_sha256",
    "evidence_input_sha256", "canary", "account_snapshot", "context_bytes_checked", "canary_replay_verified", ...denied])
    && value.version === "ml08-evidence-inspection/1.0.0" && value.scope === "private_authenticated_byte_integrity_not_scientific_acceptance"
    && value.actor_user_id === actorId && validReviewRef(ref) && value.participant_id === ref.participant_id && value.participant_sha256 === ref.participant_sha256
    && value.registration_sha256 === ref.registration_sha256 && denied.every(k => value[k] === false) && value.training_execution === "disabled"
    && value.context_bytes_checked === true && value.canary_replay_verified === true && pilotHash(value.evidence_input_sha256));
  const proof = value.canary;
  requireValue(closed(proof, ["version", "canary_version", "canary_sha256", "context_inventory_sha256", "context_file_count", "context_bytes_hashed",
    "context_bytes_embedded", "context_bytes_checked", "canary_replay_verified", "conclusion_documentary_gate_verified", "implementation_sha256"])
    && proof.version === "ml08-evidence-integrity/1.0.0" && proof.canary_version === "ml08-canary/1.2.0" && proof.canary_sha256 === basis.declared_canary_sha256
    && proof.context_inventory_sha256 === uploaded.inventorySha256 && proof.context_file_count === uploaded.contextCount && proof.context_bytes_hashed === uploaded.contextBytes
    && proof.context_bytes_embedded === false && proof.context_bytes_checked === true && proof.canary_replay_verified === true
    && proof.conclusion_documentary_gate_verified === true && pilotHash(proof.implementation_sha256));
  const account = parseReviewCoverage(importCanonical(value.account_snapshot), actorId, ref, basis);
  return { account, contextCount: uploaded.contextCount, contextBytes: uploaded.contextBytes, canarySha256: basis.declared_canary_sha256,
    implementationSha256: proof.implementation_sha256 as string, inputSha256: value.evidence_input_sha256 as string };
}
