/** Test-only adapters. Resealed responses below are synthetic, not new SQL evidence. */
import { createHash } from "node:crypto";
import native from "../fixtures/ml-use-runs-native.delivery20260924r1.wire.json";
export const http = native;
export const reviewText = "SYNTHETIC independent run-budget review record. Not a real human review, scientific pilot or source licence.";
export const canonical = (v: any): string => {
  if (typeof v === "number" && !Number.isSafeInteger(v)) throw new Error("Noninteger test envelope");
  if (Array.isArray(v)) return "[" + v.map(canonical).join(",") + "]";
  if (v !== null && typeof v === "object") return "{" + Object.keys(v).sort().map(k => JSON.stringify(k) + ":" + canonical(v[k])).join(",") + "}";
  return JSON.stringify(v);
};
export const sha = (v: string | Buffer) => createHash("sha256").update(v).digest("hex");
export const digest = (v: unknown) => sha(canonical(v));
export const changed = (raw: string, mutate: (v: any) => void) => { const v = JSON.parse(raw); mutate(v); return canonical(v); };
export const wire = (name: string): string => { const v = (http as Record<string, unknown>)[name]; if (typeof v !== "string") throw new Error(name); return v; };
export const inputFor = (name: "plan" | "approve" | "deny" | "revoke") => http[(name + "_input") as "plan_input"];
export const recoveryFor = (name: "plan" | "approve" | "deny" | "revoke") => {
  const r = JSON.parse(wire(name + "_preview")).result;
  return { kind: name === "plan" ? "plan" as const : "decision" as const, actorId: r.intent.actor_user_id,
    requestKey: r.intent.request_key, intentSha256: r.intent_sha256 };
};
export function sealRecord(record: any) {
  const { created_at: _created, record_sha256: _pin, ...body } = record;
  record.record_sha256 = digest(body);
}
export function syntheticReply(kind: "plan" | "decision", input: object, committed: boolean, replayed = false): string {
  const name = kind === "plan" ? "plan" : (input as { decision: string }).decision;
  const v = JSON.parse(wire(name + (committed ? "_committed" : "_preview"))), r = v.result;
  const { evidence_text: _privateText, ...metadata } = input as Record<string, unknown>;
  Object.assign(r.intent, metadata); r.intent_sha256 = digest(r.intent); r.replayed = replayed;
  if (committed) { Object.assign(r[kind], metadata, { intent_sha256: r.intent_sha256 }); sealRecord(r[kind]); }
  return canonical(v);
}
