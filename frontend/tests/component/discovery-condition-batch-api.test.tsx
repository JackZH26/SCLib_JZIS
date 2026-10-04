import { afterEach, expect, it, vi } from "vitest";
import { API_BASE, ApiError, discoveryConditionBatchManifest, discoveryConditionBatchCommit, discoveryConditionBatchOutcome } from "@/lib/api";
import { CONDITION_BATCH_REQUEST_VERSION } from "@/lib/discovery-condition-batches";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it("exports exact bounded UTF-8 bytes through a private no-store GET", async () => {
  const text = '{"label":"Researcher text: μ*","batch_saved":false}', fetch = vi.fn().mockResolvedValue(new Response(text, { headers: { "content-type": "application/json" } }));
  vi.stubGlobal("fetch", fetch);
  expect(await discoveryConditionBatchManifest("batch/id")).toBe(text);
  expect(fetch).toHaveBeenCalledWith(`${API_BASE}/research/discovery-condition-batches/batches/batch%2Fid/manifest`, expect.objectContaining({ cache: "no-store", credentials: "include" }));
});
it("preserves a received BOM so canonical proof checks can reject it without rewriting bytes", async () => {
  const bytes = new Uint8Array([0xef, 0xbb, 0xbf, 0x7b, 0x7d]); vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(bytes)));
  expect(await discoveryConditionBatchManifest("bom")).toBe("\ufeff{}");
});
it("refuses an oversized export before JSON hydration and rejects invalid UTF-8", async () => {
  const cancel = vi.fn(), bytes = new Uint8Array(4194304 + 129);
  const stream = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(bytes); }, cancel });
  const fetch = vi.fn().mockResolvedValueOnce(new Response(stream)).mockResolvedValueOnce(new Response(new Uint8Array([0xc0, 0xaf]))); vi.stubGlobal("fetch", fetch);
  await expect(discoveryConditionBatchManifest("bounded")).rejects.toBeInstanceOf(ApiError); expect(cancel).toHaveBeenCalledTimes(1);
  await expect(discoveryConditionBatchManifest("bad-utf8")).rejects.toBeInstanceOf(ApiError);
});
it("preserves authorization status on failed exports", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('{"detail":"held"}', { status: 403 })));
  await expect(discoveryConditionBatchManifest("held")).rejects.toMatchObject({ status: 403 });
});
it("sends one explicit commit and only GET for original outcome recovery", async () => {
  const fetch = vi.fn().mockRejectedValueOnce(new Error("Synthetic transport interruption")).mockResolvedValueOnce(new Response("{}")); vi.stubGlobal("fetch", fetch);
  const request = { version: CONDITION_BATCH_REQUEST_VERSION, request_key: "test-original", operation: "propose_candidate_child" as const, payload: { batch: { id: "00000000-0000-0000-0000-000000000001", record_sha256: "a".repeat(64), manifest_sha256: "b".repeat(64) }, candidate_sha256: "c".repeat(64) } };
  await expect(discoveryConditionBatchCommit(request, "d".repeat(64))).rejects.toMatchObject({ status: 0 });
  expect(fetch).toHaveBeenCalledTimes(1); expect(fetch.mock.calls[0][1]).toMatchObject({ method: "POST", credentials: "include", cache: "no-store", body: JSON.stringify({ request, expected_preview_sha256: "d".repeat(64) }) });
  await discoveryConditionBatchOutcome(request.request_key, "e".repeat(64));
  expect(fetch).toHaveBeenCalledTimes(2); expect(fetch.mock.calls[1][0]).toContain("request_key=test-original&expected_request_sha256=" + "e".repeat(64)); expect(fetch.mock.calls[1][1].method).toBeUndefined();
});
