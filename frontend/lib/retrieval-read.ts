import type { ContentRetrieval, RetrievalGeneration, RetrievalReadIdentity } from "@/lib/api";

type Row = Record<string, unknown>;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const SHA = /^[0-9a-f]{64}$/;
function row(value: unknown): value is Row {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function keys(value: unknown, names: string[]): value is Row {
  return row(value) && Object.keys(value).length === names.length && names.every(name => Object.hasOwn(value, name));
}
const uuid = (value: unknown): value is string => typeof value === "string" && UUID.test(value);
const sha = (value: unknown): value is string => typeof value === "string" && SHA.test(value);

/** Structural parsing never grants source rights or scientific acceptance. */
export function knownRetrievalRead(value: unknown): RetrievalReadIdentity | null {
  if (!row(value)) return null;
  if (value.version === "index-read/1.0.0") {
    if (!keys(value, ["version", "mode", "generation_id", "activation_event_id", "manifest_sha256"])) return null;
    if (value.mode === "legacy_lexical_only") {
      if (value.generation_id !== null || value.activation_event_id !== null || value.manifest_sha256 !== null) return null;
    } else if (value.mode !== "generation_snapshot" || !uuid(value.generation_id)
      || !uuid(value.activation_event_id) || !sha(value.manifest_sha256)) return null;
    return Object.freeze({ ...value }) as unknown as RetrievalGeneration;
  }
  if (value.version !== "index-read/2.0.0" || !keys(value, ["version", "mode", "content_id", "build_id",
    "activation_event_id", "manifest_sha256", "policy_artifact_sha256", "profile"])) return null;
  if (value.mode !== "content_snapshot" || !uuid(value.content_id) || !uuid(value.build_id)
    || !uuid(value.activation_event_id) || !sha(value.manifest_sha256) || !sha(value.policy_artifact_sha256)) return null;
  const p = value.profile;
  if (!keys(p, ["version", "provider", "model", "output_dimensionality", "document_task", "query_task"])
    || p.version !== "sclib-index-profile/1.0.0" || p.provider !== "google-vertex-ai"
    || p.model !== "text-embedding-005" || p.output_dimensionality !== 768
    || p.document_task !== "RETRIEVAL_DOCUMENT" || p.query_task !== "RETRIEVAL_QUERY") return null;
  return Object.freeze({ ...value, profile: Object.freeze({ ...p }) }) as unknown as ContentRetrieval;
}

export function sameRetrievalRead(left: unknown, right: unknown): boolean {
  const a = knownRetrievalRead(left), b = knownRetrievalRead(right);
  if (!a || !b || a.version !== b.version || a.mode !== b.mode) return false;
  if (a.version === "index-read/1.0.0" && b.version === "index-read/1.0.0") {
    return a.generation_id === b.generation_id && a.activation_event_id === b.activation_event_id
      && a.manifest_sha256 === b.manifest_sha256;
  }
  if (a.version === "index-read/2.0.0" && b.version === "index-read/2.0.0") {
    return a.content_id === b.content_id && a.build_id === b.build_id
      && a.activation_event_id === b.activation_event_id && a.manifest_sha256 === b.manifest_sha256
      && a.policy_artifact_sha256 === b.policy_artifact_sha256;
  }
  return false;
}
