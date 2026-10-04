/** Synthetic closed-envelope test data, never represented as an executed SQL or scientific result. */
import { FEEDBACK_AUTHORITY, FEEDBACK_REQUEST_VERSION, FEEDBACK_VERSION, feedbackDesignPin, type FeedbackCapabilities, type FeedbackContext, type FeedbackEntry, type FeedbackPage, type FeedbackProjection, type FeedbackReceipt, type FeedbackRecovery, type FeedbackRequest } from "@/lib/discovery-feedback";
import type { DesignCapabilities, DesignDetail, DesignEntry } from "@/lib/discovery-designs";
import { expressionCanonical, expressionSha } from "@/lib/source-expressions";
import designWire from "./discovery-designs-native.synthetic.json";
import nativeWire from "./discovery-feedback-native.synthetic.json";

export const syntheticReceiptId = "aaaaaaaa-0000-4000-8000-000000000001";
export const syntheticChild = { design_id: "bbbbbbbb-0000-4000-8000-000000000001", revision_id: "bbbbbbbb-0000-4000-8000-000000000002", record_sha256: "b".repeat(64) };
export async function syntheticFeedbackWire() {
  const designCapabilities = structuredClone(designWire.capabilities) as DesignCapabilities;
  // A trusted parent prop for component isolation. Its ordinary design receipt is not a new native replay.
  const entry = structuredClone(designWire.detail.entries[0]) as DesignEntry;
  entry.baseline = { kind: "retained_result", material_id: "synthetic-design-host", record_index: 0, property_id: null, expected_context_sha256: "d".repeat(64) };
  entry.status = "proposed"; entry.is_head = true; entry.eligibility = { eligible: true, reason_codes: [] };
  entry.design.next_action = { ...entry.design.next_action, kind: "source_review", question: "Does an existing comparative record resolve the requested criterion?", outcomes: [{ observation: "The lexical criterion is supplied", decision: "continue" }, { observation: "The criterion remains unresolved", decision: "redirect" }] };
  const design = (await feedbackDesignPin(entry))!;
  const cap: FeedbackCapabilities = { ...FEEDBACK_AUTHORITY, version: FEEDBACK_VERSION, request_version: FEEDBACK_REQUEST_VERSION, actor_user_id: designCapabilities.actor_user_id, session_version: designCapabilities.session_version, curator_grant_id: designCapabilities.curator_grant_id, can_write: true, baseline_kinds: ["retained_result"], action_kinds: ["source_review"], decisions: ["continue", "stop", "redirect"], operations: ["return_evidence", "link_follow_up"], max_page_size: 8, max_operation_bytes: 32768 };
  const evidence = { kind: "retained_result" as const, material_id: "synthetic-comparative-material", record_index: 2, property_id: null, expected_context_sha256: "e".repeat(64) };
  const projection: FeedbackProjection = { kind: "retained_result", material_id: evidence.material_id, record_index: evidence.record_index, formula: "Synthetic comparator", source_snapshot_sha256: evidence.expected_context_sha256, physical_association: "unestablished", withheld_fields: [], record: { id: "synthetic-record-2", paper_id: "synthetic-paper", knowledge_origin: null, evidence_type: "primary_experimental", tc_kelvin: 23, tc_type: "onset", tc_definition: "Resistive transition", tc_criterion: "onset of resistive drop", criterion: "rho onset", measurement: "resistivity", measurement_method: "four-probe", method_statement: "Source-reported resistive criterion", pressure_gpa: null, pressure_status: "not_reported", pressure_kind: null, pressure_conditions: null, hc2_tesla: 65, hc2_tesla_unit: "T", hc2_conditions: "0 K, extrapolation model not supplied", hc2_direction: null, field_orientation: null, magnetic_field_orientation: null, scientific_values: null } };
  const projectionText = expressionCanonical(projection), projectionSha = await expressionSha(projectionText);
  const context: FeedbackContext = { ...FEEDBACK_AUTHORITY, version: FEEDBACK_VERSION, actor_user_id: cap.actor_user_id, session_version: cap.session_version, design, evidence, context_sha256: evidence.expected_context_sha256, projection, projection_canonical_json: projectionText, projection_sha256: projectionSha, eligibility: { eligible: true, reason_codes: [] } };
  const request: FeedbackRequest = { version: FEEDBACK_REQUEST_VERSION, request_key: "synthetic-return:original", operation: "return_evidence", payload: { design, evidence, findings: "The source retains a resistive onset alongside a separately scoped Hc2 field.", decision: "redirect", reason: "An exact criterion is available; sample relevance still needs evidence.", unknowns: ["Physical sample relation remains unestablished"] } };
  const preview = await syntheticFeedbackReceipt(request, cap, design, projectionSha);
  const commit = { ...preview, dry_run: false, pending_ledger_written: true };
  const recovery: FeedbackRecovery = { actorId: cap.actor_user_id, requestKey: request.request_key, requestSha: commit.request_sha256, previewSha: commit.preview_sha256, receiptSha: commit.receipt_sha256, receiptId: commit.receipt_id, design, operation: "return_evidence", feedback: null, child: null };
  const item: FeedbackEntry = { ...FEEDBACK_AUTHORITY, id: commit.feedback_id, record_sha256: commit.feedback_record_sha256, design, evidence, findings: request.payload.findings, decision: request.payload.decision, reason: request.payload.reason, unknowns: request.payload.unknowns, context_sha256: context.context_sha256, projection_sha256: projectionSha, projection, projection_canonical_json: projectionText, eligibility: { eligible: true, reason_codes: [] }, receipt: commit, follow_ups: [] };
  const page: FeedbackPage = { ...FEEDBACK_AUTHORITY, version: FEEDBACK_VERSION, actor_user_id: cap.actor_user_id, session_version: cap.session_version, design_id: design.design_id, offset: 0, limit: 8, total: 1, entries: [item] };
  return { designCapabilities, entry, cap, context, request, preview, commit, outcome: { ...commit, replayed: true }, recovery, page, item };
}
export async function syntheticFeedbackReceipt(request: FeedbackRequest, cap: FeedbackCapabilities, design: FeedbackContext["design"], projectionSha = "f".repeat(64)): Promise<FeedbackReceipt> {
  const actor = { actor_user_id: cap.actor_user_id, actor_grant_id: cap.curator_grant_id, actor_session_version: cap.session_version };
  const requestText = expressionCanonical(request), requestSha = await expressionSha(requestText);
  const returning = request.operation === "return_evidence", receiptId = returning ? syntheticReceiptId : "aaaaaaaa-0000-4000-8000-000000000002";
  const feedbackId = returning ? receiptId : request.payload.feedback.id;
  const preview = returning ? { version: FEEDBACK_VERSION, actor, request_sha256: requestSha, receipt_id: receiptId, feedback_id: feedbackId, design, context_sha256: request.payload.evidence.expected_context_sha256, projection_sha256: projectionSha }
    : { version: FEEDBACK_VERSION, actor, request_sha256: requestSha, receipt_id: receiptId, feedback_id: feedbackId, feedback_record_sha256: request.payload.feedback.record_sha256, child: request.payload.child };
  const previewText = expressionCanonical(preview), previewSha = await expressionSha(previewText);
  const flags = Object.fromEntries(Object.entries(FEEDBACK_AUTHORITY).filter(([key]) => key !== "scope"));
  const record = { id: receiptId, ...actor, operation: request.operation, request_key: request.request_key, request_json: requestText, payload: request.payload, request_sha256: requestSha, preview_json: previewText, preview_sha256: previewSha,
    ...(returning ? { design_ref: request.payload.design, design_revision_id: request.payload.design.revision_id, evidence: request.payload.evidence, findings: request.payload.findings, decision: request.payload.decision, reason: request.payload.reason, unknowns: request.payload.unknowns, context_sha256: request.payload.evidence.expected_context_sha256, projection_sha256: projectionSha }
      : { feedback_id: feedbackId, feedback_record_sha256: request.payload.feedback.record_sha256, child: request.payload.child, child_revision_id: request.payload.child.revision_id }), ...flags };
  const recordText = expressionCanonical(record), recordSha = await expressionSha(recordText);
  return { ...FEEDBACK_AUTHORITY, version: FEEDBACK_VERSION, receipt_id: receiptId, receipt_sha256: recordSha, operation: request.operation, design, feedback_id: feedbackId, feedback_record_sha256: returning ? recordSha : request.payload.feedback.record_sha256, child: returning ? null : request.payload.child, ...actor, request_key: request.request_key, request_sha256: requestSha, preview_sha256: previewSha, request_canonical_json: requestText, preview_canonical_json: previewText, receipt_canonical_json: recordText, replayed: false, dry_run: true, pending_ledger_written: false };
}

/** A synthetic detail envelope around actual native child proof and its unchanged source projection. */
export function nativeFeedbackWithChildDetail() {
  const designCapabilities = { ...structuredClone(designWire.capabilities), actor_user_id: nativeWire.capabilities.actor_user_id, session_version: nativeWire.capabilities.session_version, curator_grant_id: nativeWire.capabilities.curator_grant_id } as DesignCapabilities;
  const entry = structuredClone(nativeWire.parent.entries[0]) as DesignEntry;
  const cap = structuredClone(nativeWire.capabilities) as FeedbackCapabilities, context = structuredClone(nativeWire.context) as FeedbackContext;
  const commit = structuredClone(nativeWire.commit) as FeedbackReceipt;
  const recovery: FeedbackRecovery = { actorId: cap.actor_user_id, requestKey: commit.request_key, requestSha: commit.request_sha256, previewSha: commit.preview_sha256, receiptSha: commit.receipt_sha256, receiptId: commit.receipt_id, design: context.design, operation: "return_evidence", feedback: null, child: null };
  const childEntry: DesignEntry = { ...structuredClone(entry), id: nativeWire.child_commit.receipt_id, record_sha256: nativeWire.child_commit.receipt_sha256, design_id: nativeWire.child_commit.design_id, revision: 1, operation: "propose", status: "proposed", is_head: true, design: structuredClone(nativeWire.child_request.payload.design) as DesignEntry["design"], parent: structuredClone(nativeWire.child_request.payload.parent), predecessor: null, receipt: structuredClone(nativeWire.child_commit) as DesignEntry["receipt"] };
  const childDetail: DesignDetail = { ...structuredClone(nativeWire.parent) as DesignDetail, design_id: childEntry.design_id, revision_total: 1, entries: [childEntry] };
  return { designCapabilities, entry, cap, context, request: structuredClone(nativeWire.request) as Extract<FeedbackRequest, { operation: "return_evidence" }>, preview: structuredClone(nativeWire.preview) as FeedbackReceipt, commit, outcome: structuredClone(nativeWire.outcome) as FeedbackReceipt, recovery, page: structuredClone(nativeWire.page) as FeedbackPage, item: structuredClone(nativeWire.page.entries[0]) as FeedbackEntry, childDetail };
}
