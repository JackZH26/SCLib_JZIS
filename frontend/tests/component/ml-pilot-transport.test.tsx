import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import * as pilot from "@/lib/ml-pilot-participation";
import { http, inputFor, recoveryFor, sha } from "../helpers/ml-pilot-wire";

const json = { "Content-Type": "application/json" }, reg = JSON.parse(http.initial).registration;
const file = (bytes: Uint8Array): File => ({ size: bytes.byteLength, arrayBuffer: vi.fn(async () => new Uint8Array(bytes).buffer) }) as unknown as File;
const files = () => [file(Buffer.from(http.selection_base64, "base64")), file(Buffer.from(http.protocol_base64, "base64"))] as const;
beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); });
describe("bounded private pilot transport", () => {
  it("checks original raw bytes before upload, preserves both files, and sends no files on protective decisions or recovery", async () => {
    const fetcher = vi.fn().mockImplementation(async () => new Response("{}", { headers: json })); vi.stubGlobal("fetch", fetcher);
    const prepared = await pilot.preparePilotFiles(reg, ...files()), ref = recoveryFor("accept");
    expect(prepared).toEqual({ selection_base64: http.selection_base64, protocol_base64: http.protocol_base64,
      selection_file_sha256: reg.selection_file_sha256, protocol_file_sha256: reg.protocol_file_sha256, selection_sha256: reg.selection_sha256 });
    expect(fetcher).not.toHaveBeenCalled();
    await pilot.getPilotAccess(); await pilot.inspectPilot(http.query);
    await pilot.previewPilotDecision(inputFor("accept"), ref.actorId, prepared);
    await pilot.commitPilotDecision(inputFor("accept"), ref.actorId, prepared, ref.intentSha256);
    await pilot.previewPilotDecision(inputFor("withdraw"), ref.actorId, null); await pilot.recoverPilotDecision(ref);
    expect(fetcher.mock.calls.map(([url]) => url.slice(url.indexOf("/ml/pilots")))).toEqual([
      "/ml/pilots/participant-access", "/ml/pilots/inspect", "/ml/pilots/participation/accept", "/ml/pilots/participation/accept", "/ml/pilots/participation/decisions", "/ml/pilots/participation/outcome"]);
    for (const [, options] of fetcher.mock.calls) {
      expect(options).toMatchObject({ credentials: "include", cache: "no-store", redirect: "error" }); expect(options.headers.Authorization).toBeUndefined();
    }
    const upload = JSON.parse(fetcher.mock.calls[2][1].body), committed = JSON.parse(fetcher.mock.calls[3][1].body);
    expect(upload).toMatchObject({ version: "ml08-registration-upload/1.0.0", operation: "accept", ...prepared });
    expect(upload.parameters.decision).toBeUndefined(); expect(upload.parameters.dry_run).toBe(true); expect(upload.parameters.expected_intent_sha256).toBeNull();
    expect(committed.parameters).toEqual({ ...upload.parameters, dry_run: false, expected_intent_sha256: ref.intentSha256 });
    expect(fetcher.mock.calls[2][1].headers).toMatchObject({ "X-SCLib-Participant-Id": inputFor("accept").participant_id, "X-SCLib-Participant-Sha256": inputFor("accept").participant_sha256 });
    expect(JSON.parse(fetcher.mock.calls[4][1].body)).toEqual({ ...inputFor("withdraw"), dry_run: true, expected_intent_sha256: null });
    expect(JSON.parse(fetcher.mock.calls[5][1].body)).toEqual({ request_key: ref.requestKey, expected_intent_sha256: ref.intentSha256 });
  });
  it.each(["empty", "oversize", "changed", "length_mismatch", "bad_pin"])("refuses %s files before upload", async kind => {
    const [selection, protocol] = files(), changed = { ...reg }; const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    if (kind === "empty") Object.defineProperty(selection, "size", { value: 0 });
    if (kind === "oversize") Object.defineProperty(selection, "size", { value: pilot.PILOT_FILE_LIMIT + 1 });
    if (kind === "length_mismatch") Object.defineProperty(selection, "size", { value: 1 });
    if (kind === "changed") changed.selection_file_sha256 = "f".repeat(64);
    if (kind === "bad_pin") changed.protocol_file_sha256 = "bad";
    await expect(pilot.preparePilotFiles(changed, selection, protocol)).rejects.toThrow(); expect(fetcher).not.toHaveBeenCalled();
    if (["empty", "oversize", "bad_pin"].includes(kind)) expect(selection.arrayBuffer).not.toHaveBeenCalled();
  });
  it("accepts the exact two 8 MiB browser boundary without reserializing content", async () => {
    const bytes = new Uint8Array(pilot.PILOT_FILE_LIMIT).fill(32), pin = sha(Buffer.from(bytes));
    const value = await pilot.preparePilotFiles({ ...reg, selection_file_sha256: pin, protocol_file_sha256: pin }, file(bytes), file(bytes));
    expect(Buffer.from(value.selection_base64, "base64").equals(Buffer.from(bytes))).toBe(true); expect(value.protocol_base64).toBe(value.selection_base64);
  });
  it.each(["fetch", "stream", "file"])("bounds a stalled %s and frees cancellation hooks", async kind => {
    vi.useFakeTimers(); const canceled = vi.fn();
    const fetcher = vi.fn().mockImplementation(() => kind === "stream" ? Promise.resolve(new Response(new ReadableStream({ cancel: canceled }), { headers: json })) : new Promise(() => {}));
    vi.stubGlobal("fetch", fetcher);
    const pending = kind === "file" ? pilot.preparePilotFiles(reg, { size: 1, arrayBuffer: () => new Promise(() => {}) } as File, files()[1]) : pilot.getPilotAccess();
    const rejected = expect(pending).rejects.toBeInstanceOf(ApiError); await vi.advanceTimersByTimeAsync(kind === "file" ? 30001 : 65001); await rejected;
    expect(vi.getTimerCount()).toBe(0); expect(fetcher).toHaveBeenCalledTimes(kind === "file" ? 0 : 1);
    if (kind === "stream") expect(canceled).toHaveBeenCalledTimes(1);
  });
  it.each(["type", "missing_type", "length", "negative_length", "length_alias", "utf8", "truncated_utf8", "actual_bytes", "parts", "empty_body", "401", "403", "404", "409", "503"])("rejects %s without retries or error-body leakage", async kind => {
    const canceled = vi.fn(); let response: Response;
    if (["parts", "actual_bytes", "utf8", "truncated_utf8"].includes(kind)) response = new Response(new ReadableStream({ start(c) {
      if (kind === "parts") for (let i = 0; i < 4097; i++) c.enqueue(new Uint8Array([32]));
      else c.enqueue(kind === "actual_bytes" ? new Uint8Array(4097) : new Uint8Array(kind === "utf8" ? [255] : [0xe2, 0x82]));
      if (kind === "truncated_utf8") c.close();
    }, cancel: canceled }), { headers: json });
    else response = new Response(kind === "empty_body" ? null : "PRIVATE_CANARY", { status: /^\d+$/.test(kind) ? Number(kind) : 200,
      headers: { ...(kind === "missing_type" ? {} : { "Content-Type": kind === "type" ? "text/html" : "application/json" }),
        ...(["length", "negative_length", "length_alias"].includes(kind) ? { "Content-Length": kind === "length" ? "99999999" : kind === "negative_length" ? "-1" : "1e3" } : {}) } });
    const fetcher = vi.fn().mockResolvedValue(response); vi.stubGlobal("fetch", fetcher);
    await expect(pilot.getPilotAccess()).rejects.toThrow(/Private pilot/); expect(fetcher).toHaveBeenCalledTimes(1);
    if (["parts", "actual_bytes", "utf8"].includes(kind)) expect(canceled).toHaveBeenCalledTimes(1);
  });
  it("honors pre-abort and midstream cancellation without a write or retry", async () => {
    const c = new AbortController(), canceled = vi.fn(), fetcher = vi.fn().mockResolvedValue(new Response(new ReadableStream({ cancel: canceled }), { headers: json }));
    vi.stubGlobal("fetch", fetcher); c.abort(); await expect(pilot.getPilotAccess(c.signal)).rejects.toThrow(); expect(fetcher).not.toHaveBeenCalled();
    const next = new AbortController(), pending = pilot.getPilotAccess(next.signal), rejected = expect(pending).rejects.toThrow();
    await Promise.resolve(); await Promise.resolve(); next.abort(); await rejected; expect(canceled).toHaveBeenCalledTimes(1); expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("rejects invalid references and unsupported decision controls before fetch", async () => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    expect(() => pilot.inspectPilot({ ...http.query, registration_id: "https://evil.invalid" })).toThrow();
    expect(() => pilot.recoverPilotDecision({ ...recoveryFor("decline"), requestKey: "../" })).toThrow();
    await expect(pilot.previewPilotDecision({ ...inputFor("decline"), reason_code: "x".repeat(161) }, http.participant_id, null)).rejects.toThrow();
    await expect(pilot.previewPilotDecision(inputFor("accept"), http.participant_id, null)).rejects.toThrow();
    expect(fetcher).not.toHaveBeenCalled();
  });
});
