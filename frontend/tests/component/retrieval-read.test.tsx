import { describe, expect, it } from "vitest";
import { knownRetrievalRead, sameRetrievalRead } from "@/lib/retrieval-read";

const content = {
  version: "index-read/2.0.0", mode: "content_snapshot",
  content_id: "11111111-1111-4111-8111-111111111111", build_id: "22222222-2222-4222-8222-222222222222",
  activation_event_id: "33333333-3333-4333-8333-333333333333", manifest_sha256: "a".repeat(64),
  policy_artifact_sha256: "b".repeat(64), profile: {
    version: "sclib-index-profile/1.0.0", provider: "google-vertex-ai", model: "text-embedding-005",
    output_dimensionality: 768, document_task: "RETRIEVAL_DOCUMENT", query_task: "RETRIEVAL_QUERY",
  },
};
const legacy = { version: "index-read/1.0.0", mode: "generation_snapshot",
  generation_id: content.content_id, activation_event_id: content.activation_event_id, manifest_sha256: content.manifest_sha256 };

describe("versioned retrieval read identity", () => {
  it("keeps legacy fields and explicit v2 content identity distinct", () => {
    expect(knownRetrievalRead(legacy)).toEqual(legacy);
    expect(knownRetrievalRead(content)).toEqual(content);
    expect(knownRetrievalRead({ version: "index-read/1.0.0", mode: "legacy_lexical_only",
      generation_id: null, activation_event_id: null, manifest_sha256: null })).not.toBeNull();
    expect(sameRetrievalRead(content, legacy)).toBe(false);
    expect(sameRetrievalRead(content, structuredClone(content))).toBe(true);
  });
  it.each([
    { generation_id: content.content_id }, { resource: {} }, { scientific_acceptance: true },
    { mode: "generation_snapshot" }, { content_id: null }, { build_id: "bad" },
    { activation_event_id: "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA" }, { manifest_sha256: "A".repeat(64) },
  ])("rejects incomplete, mixed, or authority-bearing fields %j", change => {
    expect(knownRetrievalRead({ ...content, ...change })).toBeNull();
  });
  it.each([{ model: "other-model" }, { output_dimensionality: 1536 }, { query_task: "RETRIEVAL_DOCUMENT" },
    { provider: "other-provider" }, { distance: "cosine" }])("requires the exact embedding space %j", change => {
    expect(knownRetrievalRead({ ...content, profile: { ...content.profile, ...change } })).toBeNull();
  });
  it("does not alias the validated object or its nested profile", () => {
    const input = structuredClone(content), parsed = knownRetrievalRead(input);
    input.profile.model = "changed";
    expect(parsed?.version === "index-read/2.0.0" && parsed.profile.model).toBe("text-embedding-005");
    expect(Object.isFrozen(parsed)).toBe(true);
  });
  it("includes event, build, content and policy in equality", () => {
    for (const change of [{ content_id: content.build_id }, { build_id: content.content_id },
      { activation_event_id: content.build_id }, { manifest_sha256: "c".repeat(64) }, { policy_artifact_sha256: "c".repeat(64) }]) {
      expect(sameRetrievalRead(content, { ...content, ...change })).toBe(false);
    }
  });
});
