/** Synthetic response variants for UI transport/lifecycle tests; native capture remains immutable. */
import wire from "./discovery-calculations-native.synthetic.json";
import { expressionCanonical, expressionSha } from "@/lib/source-expressions";
import type { CalculationRequest } from "@/lib/discovery-calculations";
export async function syntheticCalculationPreview(request: CalculationRequest) {
  const preview = structuredClone(wire.preview);
  const payload = JSON.parse(preview.receipt_canonical_json), intent = JSON.parse(preview.preview_canonical_json);
  const requestText = expressionCanonical(request), requestSha = await expressionSha(requestText);
  intent.request_sha256 = requestSha; intent.design = request.design;
  const intentText = expressionCanonical(intent), intentSha = await expressionSha(intentText);
  Object.assign(payload, { request_json: requestText, request_sha256: requestSha, request_key: request.request_key, files: request.files, design_ref: request.design, design_revision_id: request.design.revision_id, preview_json: intentText, preview_sha256: intentSha });
  const receiptText = expressionCanonical(payload);
  return { ...preview, request_key: request.request_key, request_sha256: requestSha, request_canonical_json: requestText, preview_sha256: intentSha, preview_canonical_json: intentText, receipt_canonical_json: receiptText, receipt_sha256: await expressionSha(receiptText), design: request.design };
}
export async function syntheticCalculationSaved(request: CalculationRequest, replayed = false) {
  const { report: _report, report_canonical_json: _text, ...receipt } = await syntheticCalculationPreview(request);
  return { ...receipt, dry_run: false, private_ledger_written: true, replayed };
}
