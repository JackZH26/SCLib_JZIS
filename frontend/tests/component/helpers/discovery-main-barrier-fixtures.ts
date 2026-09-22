import { parsePrivateDiscoveryJSON, type MainBarrier } from "@/lib/discovery-scientific";
import type { SelectionRequestV2 } from "@/lib/discovery-selection";
import { hash, requestFixture, wires } from "./discovery-selection-fixtures";

// Synthetic client-only v2 adapters. These are not native HTTP captures or
// scientific/publication approvals. Historical v1 files remain byte-identical.
const canonical = (value: any): string => Array.isArray(value) ? `[${value.map(canonical).join(",")}]`
  : value !== null && typeof value === "object" ? `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${canonical(value[k])}`).join(",")}}`
    : JSON.stringify(value);
export function barrierRequest(barrier: MainBarrier = { status: "not_declared" }): SelectionRequestV2 {
  const original = requestFixture();
  return { ...original, choices: original.choices.map(c => ({ ...c, main_barrier: structuredClone(barrier) })) };
}
export function syntheticV2Prepared(key: string, barrier: MainBarrier = { status: "not_declared" }) {
  const envelope = JSON.parse(wires.preparedWire), payload = JSON.parse(envelope.payload_json);
  const campaign = parsePrivateDiscoveryJSON(envelope.payload_json, 4 * 1024 * 1024, ["campaign"]).spans.get("campaign")!;
  payload.version = "discovery-scientific-projection/2.0.0";
  payload.selection.version = "discovery-scientific-selection/2.0.0";
  for (const row of payload.rows) row.main_barrier = structuredClone(barrier);
  for (const choice of payload.selection.representatives) choice.main_barrier = structuredClone(barrier);
  const selection = canonical(payload.selection);
  envelope.selection_sha256 = payload.selection_sha256 = hash(selection);
  envelope.payload_json = JSON.stringify(payload).replace(JSON.stringify(payload.selection), selection).replace(JSON.stringify(payload.campaign), campaign);
  envelope.payload_sha256 = hash(envelope.payload_json); envelope.request_key = key;
  const originalCommand = JSON.parse(envelope.commit_json);
  const command = { ...originalCommand, selection: payload.selection, expected_selection_sha256: envelope.selection_sha256,
    expected_payload_sha256: envelope.payload_sha256, request_key: key };
  const encode = (v: Record<string, unknown>) => `{${Object.keys(v).sort().map(k => `${JSON.stringify(k)}:${k === "selection" ? selection
    : k === "public_bundle" ? wires.sourceWire : JSON.stringify(v[k])}`).join(",")}}`;
  envelope.preview_json = encode({ ...command, dry_run: true }); envelope.commit_json = encode({ ...command, dry_run: false });
  envelope.preview_sha256 = hash(envelope.preview_json); envelope.commit_sha256 = hash(envelope.commit_json);
  const request = { ...command, operation: "register", version: "discovery-projection-governance/1.0.0" };
  for (const field of ["dry_run", "request_key", "expected_payload_sha256"]) delete request[field];
  envelope.request_sha256 = hash(encode(request));
  return JSON.stringify(envelope);
}
export function syntheticV2Registration(raw: string, preparedRaw = syntheticV2Prepared(requestFixture().request_key)) {
  const receipt = JSON.parse(raw), prepared = JSON.parse(preparedRaw);
  for (const key of ["request_sha256", "payload_sha256", "selection_sha256"]) receipt.result[key] = prepared[key];
  return JSON.stringify(receipt);
}
