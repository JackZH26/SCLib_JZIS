/** Original native evidence plus explicitly synthetic interaction adapters. */
import captured from "../fixtures/ml-pilot-attestations-native.delivery20260924r1.wire.json";
import type { ReviewAction, ReviewControl, ReviewDocuments } from "@/lib/ml-pilot-reviews";
import { canonical, digest, sealRecord } from "./ml-pilot-wire";
export { canonical, digest, sha, changed } from "./ml-pilot-wire";
export const native = captured;
export const own = captured.participants.find(p => JSON.parse(p.preflight).own_review_record_count === 60)!;
export const coverageReply = (phase: "initial" | "complete" | "withdrawn" = "complete", p = own) =>
  (captured as unknown as { coverage: { phase: string; actor_user_id: string; raw: string }[] }).coverage
    .find(row => row.phase === phase && row.actor_user_id === p.actor_user_id)!.raw;
export const reference = (p = own) => ({ participant_id: p.upload.parameters.participant_id, participant_sha256: p.upload.parameters.participant_sha256, registration_sha256: p.upload.parameters.registration_sha256 });
export function controls(p = own, action: ReviewAction = "attest"): ReviewControl {
  const { dry_run: _dry, expected_intent_sha256: _expected, ...value } = action === "attest" ? p.upload.parameters : p.withdrawal_controls;
  return value as ReviewControl;
}
export function documents(p = own): ReviewDocuments { const { version: _version, parameters: _parameters, ...value } = p.upload; return value; }
export const recoveryFor = (p = own, action: ReviewAction = "attest") => {
  const v = JSON.parse(action === "attest" ? p.preview : p.withdrawal_preview).result;
  return { actorId: p.actor_user_id, requestKey: v.intent.request_key, intentSha256: v.intent_sha256 };
};
export function syntheticReply(c: ReviewControl, action: ReviewAction, committed: boolean, replayed = false, p = own) {
  const raw = action === "attest" ? (committed ? p.committed : p.preview) : (committed ? p.withdrawal_committed : p.withdrawal_preview);
  const v = JSON.parse(raw), r = v.result, { declaration_acknowledged: _ack, ...input } = c;
  Object.assign(r.intent, input); r.intent_sha256 = digest(r.intent); r.replayed = replayed;
  if (committed) { Object.assign(r.declaration, input, { intent_sha256: r.intent_sha256 }); sealRecord(r.declaration, ["basis"]); }
  return canonical(v);
}
