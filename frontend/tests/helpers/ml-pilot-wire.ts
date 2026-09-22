/** Test-only transport adapters; resealed replies are not fresh SQL evidence. */
import { createHash } from "node:crypto";
import captured from "../fixtures/ml-pilot-participant-native.delivery20260922r4.wire.json";
import type { PilotChoice, PilotInput } from "@/lib/ml-pilot-participation";
export const http = captured;
export const sha = (value: string | Buffer) => createHash("sha256").update(value).digest("hex");
export const canonical = (v: any): string => {
  if (typeof v === "number" && !Number.isSafeInteger(v)) throw new Error("Noninteger test envelope");
  if (Array.isArray(v)) return "[" + v.map(canonical).join(",") + "]";
  if (v !== null && typeof v === "object") return "{" + Object.keys(v).sort().map(k => JSON.stringify(k) + ":" + canonical(v[k])).join(",") + "}";
  return JSON.stringify(v);
};
export const digest = (v: unknown) => sha(canonical(v));
export const changed = (raw: string, mutate: (v: any) => void) => { const v = JSON.parse(raw); mutate(v); return canonical(v); };
export const wire = (name: string): string => { const v = (http as Record<string, unknown>)[name]; if (typeof v !== "string") throw new Error(name); return v; };
export const inputFor = (name: PilotChoice) => http[(name + "_input") as "accept_input"] as PilotInput;
export const recoveryFor = (name: PilotChoice) => {
  const r = JSON.parse(wire(name + "_preview")).result;
  return { actorId: r.intent.actor_user_id, requestKey: r.intent.request_key, intentSha256: r.intent_sha256 };
};
export function sealRecord(v: any, decoded: string[] = []) {
  v.record_sha256 = digest(Object.fromEntries(Object.entries(v).filter(([k]) => !["created_at", "record_sha256", ...decoded].includes(k))));
}
export function syntheticReply(input: PilotInput, committed: boolean, replayed = false) {
  const v = JSON.parse(wire(input.decision + (committed ? "_committed" : "_preview"))), r = v.result;
  Object.assign(r.intent, input); r.intent_sha256 = digest(r.intent); r.replayed = replayed;
  if (committed) { Object.assign(r.decision, input, { intent_sha256: r.intent_sha256 }); sealRecord(r.decision); }
  return canonical(v);
}
