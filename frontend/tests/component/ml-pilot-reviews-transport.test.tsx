import { webcrypto } from "node:crypto";
import { File as NodeFile } from "node:buffer";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as review from "@/lib/ml-pilot-reviews";
import { controls, documents, own, recoveryFor, reference } from "../helpers/ml-review-wire";
const json = { "Content-Type": "application/json" };
const files = (): review.ReviewDocumentSet => Object.fromEntries(review.REVIEW_FILES.map(k => [k, new NodeFile([Buffer.from(own.upload[`${k}_base64`], "base64")], k)])) as unknown as review.ReviewDocumentSet;
beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); });
describe("bounded review declaration transport", () => {
  it("sends joint coverage only as four original read-only files with the exact own binding", async () => {
    const fetcher = vi.fn(async () => new Response("{}", { headers: json })); vi.stubGlobal("fetch", fetcher);
    await review.checkReviewCoverage(reference(), documents());
    const [url, options] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/ml\/pilots\/review-attestations\/coverage$/);
    expect(options).toMatchObject({ method: "POST", credentials: "include", cache: "no-store", redirect: "error",
      headers: { "X-SCLib-Participant-Id": reference().participant_id, "X-SCLib-Participant-Sha256": reference().participant_sha256 } });
    expect(JSON.parse(options.body as string)).toEqual({ version: "ml08-review-upload/1.0.0", ...documents(), parameters: reference() });
    expect(options.body).not.toContain("dry_run"); expect(options.body).not.toContain("request_key");
  });
  it("rejects an invalid coverage binding or extra document/control input before fetch", () => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    expect(() => review.checkReviewCoverage({ ...reference(), participant_sha256: "bad" }, documents())).toThrow();
    expect(() => review.checkReviewCoverage(reference(), { ...documents(), committed: true } as review.ReviewDocuments)).toThrow();
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("preserves four original files and never uploads sources on withdrawal, inspection or recovery", async () => {
    const fetcher = vi.fn(async () => new Response("{}", { headers: json })); vi.stubGlobal("fetch", fetcher);
    const d = await review.prepareReviewDocuments(files()); expect(d).toEqual(documents()); expect(fetcher).not.toHaveBeenCalled();
    await review.getReviewWording(); await review.inspectReview(reference()); await review.checkReviewDocuments(reference(), d);
    await review.previewReview("attest", controls(), d); await review.commitReview("attest", controls(), d, recoveryFor().intentSha256);
    await review.previewReview("withdraw", controls(own, "withdraw"), null); await review.recoverReview(recoveryFor());
    const calls = fetcher.mock.calls as unknown as [string, RequestInit][];
    expect(calls.map(([u]) => u.slice(u.indexOf("/ml/pilots")))).toEqual(["/ml/pilots/review-attestations/declaration", "/ml/pilots/review-attestations/inspect", "/ml/pilots/review-preflight",
      "/ml/pilots/review-attestations", "/ml/pilots/review-attestations", "/ml/pilots/review-attestations/withdraw", "/ml/pilots/review-attestations/outcome"]);
    for (const [, options] of calls) expect(options).toMatchObject({ credentials: "include", cache: "no-store", redirect: "error" });
    expect(JSON.parse(calls[2][1].body as string)).toEqual({ version: "ml08-review-upload/1.0.0", ...d, parameters: reference() });
    const preview = JSON.parse(calls[3][1].body as string), commit = JSON.parse(calls[4][1].body as string);
    expect(preview).toEqual({ version: "ml08-review-attestation-upload/1.0.0", ...d, parameters: { ...controls(), dry_run: true, expected_intent_sha256: null } });
    expect(commit.parameters).toEqual({ ...preview.parameters, dry_run: false, expected_intent_sha256: recoveryFor().intentSha256 });
    expect(calls[3][1].headers).toMatchObject({ "X-SCLib-Participant-Id": reference().participant_id, "X-SCLib-Participant-Sha256": reference().participant_sha256 });
    expect(JSON.parse(calls[5][1].body as string)).toEqual({ ...controls(own, "withdraw"), dry_run: true, expected_intent_sha256: null });
    expect(JSON.parse(calls[6][1].body as string)).toEqual({ request_key: recoveryFor().requestKey, expected_intent_sha256: recoveryFor().intentSha256 });
  });
  it.each(["missing", "empty", "oversize", "length", "json", "duplicate", "utf8", "selection_hash", "review_hash"])("refuses invalid local %s before upload", async kind => {
    const set = files(), fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    if (kind === "missing") Reflect.deleteProperty(set, "protocol");
    if (kind === "empty") set.reviews = new NodeFile([], "empty") as unknown as File;
    if (kind === "oversize") Object.defineProperty(set.protocol, "size", { value: 8 * 1024 * 1024 + 1 });
    if (kind === "length") Object.defineProperty(set.protocol, "size", { value: 1 });
    if (["json", "duplicate", "utf8"].includes(kind)) set.selection = new NodeFile([kind === "utf8" ? new Uint8Array([255]) : kind === "json" ? "[]" : '{"schema_version":1,"schema_version":2}'], "bad") as unknown as File;
    if (kind === "selection_hash" || kind === "review_hash") { const v = JSON.parse(Buffer.from(own.upload.conclusion_base64, "base64").toString());
      v[kind === "selection_hash" ? "selection_sha256" : "review_log_sha256"] = "bad"; set.conclusion = new NodeFile([JSON.stringify(v)], "bad") as unknown as File; }
    await expect(review.prepareReviewDocuments(set)).rejects.toThrow(); expect(fetcher).not.toHaveBeenCalled();
  });
  it.each(["fetch", "stream", "file"])("bounds stalled %s and cleans cancellation hooks", async kind => {
    vi.useFakeTimers(); const cancel = vi.fn(); vi.stubGlobal("fetch", vi.fn(() => kind === "stream" ? Promise.resolve(new Response(new ReadableStream({ cancel }), { headers: json })) : new Promise(() => {})));
    const set = files(); set.selection = { size: 1, arrayBuffer: () => new Promise(() => {}) } as File;
    const pending = kind === "file" ? review.prepareReviewDocuments(set) : review.getReviewWording(), rejected = expect(pending).rejects.toThrow();
    await vi.advanceTimersByTimeAsync(kind === "file" ? 30001 : 65001); await rejected; expect(vi.getTimerCount()).toBe(0);
    if (kind === "stream") expect(cancel).toHaveBeenCalledTimes(1);
  });
  it.each(["type", "length", "utf8", "bytes", "parts", "401", "403", "404", "409", "503"])("rejects %s without exposing a private error body or retrying", async kind => {
    const status = /^\d+$/.test(kind) ? Number(kind) : 200;
    const body = ["bytes", "parts"].includes(kind) ? new ReadableStream<Uint8Array>({ start(c) { if (kind === "bytes") c.enqueue(new Uint8Array(128 * 1024 + 1)); else for (let i = 0; i < 4097; i++) c.enqueue(new Uint8Array([32])); c.close(); } })
      : kind === "utf8" ? new Uint8Array([255]) : "PRIVATE_CANARY";
    const fetcher = vi.fn(async () => new Response(body, { status, headers: { "Content-Type": kind === "type" ? "text/html" : "application/json", ...(kind === "length" ? { "Content-Length": "1e9" } : {}) } })); vi.stubGlobal("fetch", fetcher);
    await expect(review.getReviewWording()).rejects.toThrow(/Private review/); expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("refuses missing/false consent, unsupported controls and pre-abort without sending a write", async () => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    for (const value of [false, 1, "true", undefined]) await expect(review.previewReview("attest", { ...controls(), declaration_acknowledged: value } as unknown as review.ReviewControl, documents())).rejects.toThrow();
    await expect(review.previewReview("withdraw", controls(), null)).rejects.toThrow();
    await expect(review.previewReview("withdraw", controls(own, "withdraw"), documents())).rejects.toThrow();
    const c = new AbortController(); c.abort(); await expect(review.getReviewWording(c.signal)).rejects.toThrow(); expect(fetcher).not.toHaveBeenCalled();
  });
});
