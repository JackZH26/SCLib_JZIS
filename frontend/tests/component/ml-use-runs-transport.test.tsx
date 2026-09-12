import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import * as runs from "@/lib/ml-use-runs";
import { http, recoveryFor } from "../helpers/ml-run-wire";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); });
const json = { "Content-Type": "application/json" };
describe("private run transport", () => {
  it("uses only fixed routes, session cookies, no-store and redirect refusal; recovery omits inputs", async () => {
    const fetcher = vi.fn().mockImplementation(async () => new Response("{}", { headers: json })); vi.stubGlobal("fetch", fetcher);
    const plan = recoveryFor("plan"), decision = recoveryFor("approve");
    await runs.getRunAccess("plan"); await runs.getRunAccess("decision"); await runs.inspectRunContext(http.submission_query);
    await runs.inspectRunPlan(http.plan_query); await runs.previewRun("plan", http.plan_input);
    await runs.commitRun("decision", http.approve_input as runs.RunDecisionInput, decision.intentSha256);
    await runs.recoverRun(plan); await runs.recoverRun(decision); await runs.checkRun(http.plan_query);
    expect(fetcher.mock.calls.map(([url]) => url.slice(url.indexOf("/ml/use/runs")))).toEqual([
      "/ml/use/runs/requester-access", "/ml/use/runs/approver-access", "/ml/use/runs/context", "/ml/use/runs/inspect",
      "/ml/use/runs/plans", "/ml/use/runs/decisions", "/ml/use/runs/plans/outcome", "/ml/use/runs/decisions/outcome", "/ml/use/runs/check"]);
    fetcher.mock.calls.forEach(([, options], n) => {
      expect(options).toMatchObject({ method: n < 2 ? "GET" : "POST", credentials: "include", cache: "no-store", redirect: "error" });
      expect(options.headers.Authorization).toBeUndefined(); expect(options.signal.aborted).toBe(true);
    });
    expect(JSON.parse(fetcher.mock.calls[6][1].body)).toEqual({ request_key: plan.requestKey, expected_intent_sha256: plan.intentSha256 });
    expect(JSON.parse(fetcher.mock.calls[7][1].body)).toEqual({ request_key: decision.requestKey, expected_intent_sha256: decision.intentSha256 });
    expect(JSON.parse(fetcher.mock.calls[4][1].body).dry_run).toBe(true);
    expect(JSON.parse(fetcher.mock.calls[5][1].body)).toEqual({ ...http.approve_input, dry_run: false, expected_intent_sha256: decision.intentSha256 });
  });
  it.each(["type", "missing_type", "length", "negative_length", "length_alias", "utf8", "truncated_utf8", "actual_bytes", "parts", "empty_body", "401", "403", "404", "409", "503"])("rejects %s without source/error-body disclosure or retry", async name => {
    let response: Response, canceled = vi.fn();
    if (["parts", "actual_bytes", "utf8", "truncated_utf8"].includes(name)) {
      response = new Response(new ReadableStream({ start(c) {
        if (name === "parts") for (let i = 0; i < 4097; i++) c.enqueue(new Uint8Array([32]));
        else c.enqueue(name === "actual_bytes" ? new Uint8Array(4097).fill(32) : new Uint8Array(name === "utf8" ? [255] : [0xe2, 0x82]));
        if (name === "truncated_utf8") c.close();
      }, cancel: canceled }), { headers: json });
    } else response = new Response(name === "empty_body" ? null : "PRIVATE_CANARY", { status: /^\d+$/.test(name) ? Number(name) : 200,
      headers: { ...(name === "missing_type" ? {} : { "Content-Type": name === "type" ? "text/html" : "application/json" }),
        ...(["length", "negative_length", "length_alias"].includes(name) ? { "Content-Length": name === "length" ? "99999999" : name === "negative_length" ? "-1" : "1e3" } : {}) } });
    const fetcher = vi.fn().mockResolvedValue(response); vi.stubGlobal("fetch", fetcher);
    await expect(runs.getRunAccess("plan")).rejects.toBeInstanceOf(ApiError);
    expect(fetcher).toHaveBeenCalledTimes(1);
    if (["parts", "actual_bytes", "utf8"].includes(name)) expect(canceled).toHaveBeenCalledTimes(1);
  });
  it("decodes split UTF-8 chunks and preserves exact raw body bytes", async () => {
    const raw = '{"notice":"µ"}', bytes = new TextEncoder().encode(raw);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(new ReadableStream({ start(c) {
      for (const b of bytes) c.enqueue(new Uint8Array([b])); c.close();
    } }), { headers: json })));
    expect(await runs.getRunAccess("plan")).toBe(raw);
  });
  it.each(["fetch", "stream", "readiness"])("actually bounds a hung %s with no retries", async name => {
    vi.useFakeTimers(); const canceled = vi.fn();
    const fetcher = vi.fn().mockImplementation(() => name === "stream"
      ? Promise.resolve(new Response(new ReadableStream({ cancel: canceled }), { headers: json })) : new Promise(() => {}));
    vi.stubGlobal("fetch", fetcher);
    const promise = name === "readiness" ? runs.checkRun(http.plan_query) : runs.getRunAccess("plan");
    const rejected = expect(promise).rejects.toBeInstanceOf(ApiError);
    await vi.advanceTimersByTimeAsync(name === "readiness" ? 95001 : 30001); await rejected;
    expect(fetcher).toHaveBeenCalledTimes(1); expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
    if (name === "stream") expect(canceled).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });
  it("honors pre-abort and caller cancellation of a stalled stream", async () => {
    const c = new AbortController(), canceled = vi.fn();
    const fetcher = vi.fn().mockResolvedValue(new Response(new ReadableStream({ cancel: canceled }), { headers: json })); vi.stubGlobal("fetch", fetcher);
    c.abort(); await expect(runs.getRunAccess("plan", c.signal)).rejects.toThrow(); expect(fetcher).not.toHaveBeenCalled();
    const next = new AbortController(); const promise = runs.checkRun(http.plan_query, next.signal), rejected = expect(promise).rejects.toBeInstanceOf(ApiError);
    await Promise.resolve(); await Promise.resolve(); next.abort(); await rejected;
    expect(fetcher).toHaveBeenCalledTimes(1); expect(canceled).toHaveBeenCalledTimes(1);
  });
  it("rejects oversized input and invalid opaque references before fetch", async () => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    await expect(runs.previewRun("plan", { ...http.plan_input, request_key: "x".repeat(9000) })).rejects.toThrow();
    expect(() => runs.inspectRunPlan({ ...http.plan_query, plan_id: "https://evil.invalid" })).toThrow();
    expect(() => runs.commitRun("plan", http.plan_input, "bad")).toThrow();
    expect(() => runs.recoverRun({ ...recoveryFor("plan"), requestKey: "../../" })).toThrow();
    expect(fetcher).not.toHaveBeenCalled();
  });
});
