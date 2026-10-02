import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, sourceExpressionCapabilities, sourceExpressionCommit, sourceExpressionDetail, sourceExpressionOutcome } from "@/lib/api";
import { syntheticPackage } from "../helpers/source-expression-test-data";

beforeEach(() => { vi.stubGlobal("crypto", webcrypto); });
afterEach(() => { vi.unstubAllGlobals(); });
describe("Source-expression bounded private API transport", () => {
  it("preserves exact fragment base64 in one explicit POST and recovers only by an explicit credentialed GET", async () => {
    const pkg = await syntheticPackage(), body = { request_key: "test-intake:transport", package: pkg }, previewSha = "a".repeat(64);
    const fetch = vi.fn().mockResolvedValueOnce(new Response('{"detail":"temporarily unavailable"}', { status: 503 })).mockResolvedValueOnce(new Response('{"receipt":"synthetic outcome only"}'));
    vi.stubGlobal("fetch", fetch); await expect(sourceExpressionCommit(body, previewSha)).rejects.toBeInstanceOf(ApiError); expect(fetch).toHaveBeenCalledOnce();
    const init = fetch.mock.calls[0][1]; expect(init.credentials).toBe("include"); expect(init.cache).toBe("no-store"); expect(init.method).toBe("POST");
    expect(JSON.parse(init.body).package.source_text_base64).toBe(pkg.source_text_base64); expect(JSON.parse(init.body).expected_preview_sha256).toBe(previewSha);
    await sourceExpressionOutcome(body.request_key, "b".repeat(64)); expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls[1][0]).toContain("/imports/outcome?request_key=test-intake%3Atransport&expected_request_sha256="); expect(fetch.mock.calls[1][1].method ?? "GET").toBe("GET");
  });
  it("bounds capability and exact-detail responses before exposing hydrated metadata", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(new Response(" ".repeat(16385))).mockResolvedValueOnce(new Response(" ".repeat(2 * 1024 * 1024 + 1))); vi.stubGlobal("fetch", fetch);
    await expect(sourceExpressionCapabilities()).rejects.toMatchObject({ status: 0 }); await expect(sourceExpressionDetail("00000000-0000-4000-8000-000000000105")).rejects.toMatchObject({ status: 0 }); expect(fetch).toHaveBeenCalledTimes(2);
  });
});
