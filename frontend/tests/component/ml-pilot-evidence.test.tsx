import { webcrypto } from "node:crypto";
import { Blob as NodeBlob, File as NodeFile } from "node:buffer";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EVIDENCE_LIMIT, EVIDENCE_TYPE, parseEvidenceSnapshot, prepareEvidence } from "@/lib/ml-pilot-evidence";
import { REVIEW_EVIDENCE_LIMIT, sendReviewEvidence } from "@/lib/ml-pilot-reviews";
import { evidenceBasis as basis, evidenceFiles, evidenceNative as native, evidenceParts } from "../helpers/ml-evidence-wire";
import { canonical, changed, sha } from "../helpers/ml-review-wire";

beforeEach(() => { vi.stubGlobal("crypto", webcrypto); vi.stubGlobal("Blob", NodeBlob); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function prepared() { const f = evidenceFiles(NodeFile as unknown as typeof File); return prepareEvidence(native.reference, basis, f.originals, f.canary, f.contexts); }
describe("actual native canary byte inspection", () => {
  it("assembles the exact native frame without serializing originals or context into JSON", async () => {
    const value = await prepared(); expect(value.body.type).toBe(EVIDENCE_TYPE); expect(EVIDENCE_LIMIT).toBe(REVIEW_EVIDENCE_LIMIT);
    expect(Buffer.from(await value.body.arrayBuffer())).toEqual(evidenceParts().raw);
    expect(value.contextCount).toBe(0); expect(value.contextBytes).toBe(0);
    expect(value.inventorySha256).toBe(sha("[]"));
  });
  it.each(["initial", "complete"] as const)("verifies original %s byte proof without upgrading scientific authority", async name => {
    const value = parseEvidenceSnapshot(native[name], native.actor_user_id, native.reference, basis, await prepared());
    expect(value.account.account_declarations_complete).toBe(name === "complete");
    expect(value.contextCount).toBe(0); expect(value.contextBytes).toBe(0);
    expect(value.canarySha256).toBe(basis.declared_canary_sha256);
  });
  it.each(["flag", "permission", "write", "actor", "reference", "canary", "version", "inventory", "count", "bytes", "embedded", "replay", "proof", "snapshot", "extra"])("rejects misleading proof: %s", async name => {
    const raw = changed(native.complete, v => {
      if (name === "flag") v.scientific_acceptance = true;
      if (name === "permission") v.source_permissions_verified = true;
      if (name === "write") v.attestation_recorded = true;
      if (name === "actor") v.actor_user_id = "00000000-0000-4000-8000-999999999999";
      if (name === "reference") v.participant_sha256 = "f".repeat(64);
      if (name === "canary") v.canary.canary_sha256 = "f".repeat(64);
      if (name === "version") v.canary.canary_version = "ml08-canary/1.1.0";
      if (name === "inventory") v.canary.context_inventory_sha256 = "f".repeat(64);
      if (name === "count") v.canary.context_file_count = true;
      if (name === "bytes") v.canary.context_bytes_hashed = 1;
      if (name === "embedded") v.canary.context_bytes_embedded = true;
      if (name === "replay") v.canary_replay_verified = false;
      if (name === "proof") v.canary.implementation_sha256 = "old";
      if (name === "snapshot") v.account_snapshot.input_pins.reviews_file_sha256 = "f".repeat(64);
      if (name === "extra") v.source_text = "PRIVATE_CANARY";
    });
    const upload = await prepared(); expect(() => parseEvidenceSnapshot(raw, native.actor_user_id, native.reference, basis, upload)).toThrow();
  });
  it.each(["canary_hash", "canary_size", "context_name", "duplicate", "context_size", "total", "original", "cancel"])("refuses invalid input before upload: %s", async name => {
    const f = evidenceFiles(NodeFile as unknown as typeof File), c = new AbortController();
    if (name === "canary_hash") f.canary = new NodeFile(["altered"], "canary.json") as unknown as File;
    if (name === "canary_size") Object.defineProperty(f.canary, "size", { value: 32 * 1024 * 1024 + 1 });
    if (["context_name", "duplicate", "context_size", "total"].includes(name)) {
      const one = new NodeFile(["synthetic"], name === "context_name" ? "source.txt" : "a".repeat(64) + ".bin") as unknown as File;
      f.contexts = [one]; if (name === "duplicate") f.contexts.push(one);
      if (name === "context_size") Object.defineProperty(one, "size", { value: 8 * 1024 * 1024 + 1 });
      if (name === "total") f.contexts = Array.from({ length: 9 }, (_, i) => {
        const file = new NodeFile(["synthetic"], String(i).repeat(64) + ".bin"); Object.defineProperty(file, "size", { value: 8 * 1024 * 1024 }); return file as unknown as File;
      });
    }
    if (name === "original") Object.defineProperty(f.originals.reviews, "size", { value: 0 });
    if (name === "cancel") c.abort();
    await expect(prepareEvidence(native.reference, basis, f.originals, f.canary, f.contexts, c.signal)).rejects.toThrow();
  });
  it("sends only a bounded binary body to the fixed credentialed no-store endpoint", async () => {
    const upload = await prepared(), fetcher = vi.fn(async () => new Response(native.complete, { headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetcher); expect(await sendReviewEvidence(native.reference, upload.body)).toBe(native.complete);
    const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/ml\/pilots\/review-attestations\/evidence$/); expect(init.body).toBe(upload.body);
    expect(init).toMatchObject({ method: "POST", credentials: "include", cache: "no-store", redirect: "error" });
    expect(init.headers).toMatchObject({ "Content-Type": EVIDENCE_TYPE, "X-SCLib-Participant-Id": native.reference.participant_id });
  });
  it.each(["type", "oversized", "response", "denied"])("enforces bounded transport on %s", async name => {
    const upload = await prepared();
    if (name === "type") upload.body = new NodeBlob(["{}"]) as unknown as Blob;
    if (name === "oversized") Object.defineProperty(upload.body, "size", { value: EVIDENCE_LIMIT + 1 });
    const fetcher = vi.fn(async () => name === "denied" ? new Response("PRIVATE_CANARY", { status: 403 }) : new Response("x".repeat(128 * 1024 + 1), { headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetcher); await expect(sendReviewEvidence(native.reference, upload.body)).rejects.toThrow();
    if (["type", "oversized"].includes(name)) expect(fetcher).not.toHaveBeenCalled();
  });
  it("retains unmodified native replies and exact selected source pins", () => {
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-pilot-evidence-native.delivery20260921r2.wire.json")))).toBe("f52b65f81710bafacd24017459d323aa6f926755f75493442512428345df9714");
    expect(sha(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-pilot-evidence-native.batch75.wire.json")))).toBe("f8128d35236754dac5164721bb34becc0431751fcc79fac2236fa23f6aa1edd8");
    expect(native.source_pins).toHaveLength(598);
    expect(native.capture_test_path).toBe("api/tests/test_ml_pilot_evidence.py");
    expect(native.fixture_notice).toContain("synthetic accounts and events only");
    for (const row of native.source_pins) expect(sha(readFileSync(resolve(process.cwd(), "..", row.path))), row.path).toBe(row.sha256);
    expect(canonical(JSON.parse(native.complete))).toBe(native.complete);
  });
});
