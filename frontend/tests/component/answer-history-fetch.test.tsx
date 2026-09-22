import { afterEach, describe, expect, it, vi } from "vitest";
import { historyDetail } from "@/lib/api";

afterEach(() => vi.unstubAllGlobals());

describe("bounded owner-cookie history transport", () => {
  it("uses a no-store GET, cookies and the caller abort signal, without an API key", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ synthetic: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    const controller = new AbortController();
    expect(await historyDetail("id with/slash", controller.signal)).toEqual({ synthetic: true });
    const [url, options] = fetch.mock.calls[0];
    expect(url).toMatch(/\/history\/id%20with%2Fslash$/);
    expect(options.cache).toBe("no-store");
    expect(options.credentials).toBe("include");
    expect(options.signal).toBe(controller.signal);
    expect(options.method ?? "GET").toBe("GET");
    expect(options.headers.has("x-api-key")).toBe(false);
    expect(options.body).toBeUndefined();
  });

  it("cancels an oversized response before JSON decoding", async () => {
    const cancel = vi.fn();
    const stream = new ReadableStream({ start(controller) { controller.enqueue(new Uint8Array(3 * 1024 * 1024 + 1)); }, cancel });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(stream)));
    await expect(historyDetail("id")).rejects.toThrow("History detail unavailable.");
    expect(cancel).toHaveBeenCalledTimes(1);
  });

  it("does not trust a small content-length instead of actual bytes", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(" ".repeat(3 * 1024 * 1024 + 1), { headers: { "content-length": "1" } })));
    await expect(historyDetail("id")).rejects.toThrow("History detail unavailable.");
  });

  it.each(["not JSON PRIVATE_TEXT", new Uint8Array([0xff, 0xff])])("sanitizes malformed response bodies", async body => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body)));
    await expect(historyDetail("id")).rejects.toThrow(/^History detail unavailable\.$/);
  });

  it("retains an actual HTTP denial status for static UI handling", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "private" }), { status: 403 })));
    await expect(historyDetail("id")).rejects.toMatchObject({ status: 403 });
  });

  it("bounds excessively fragmented streams without an unbounded chunk inventory", async () => {
    const cancel = vi.fn();
    const stream = new ReadableStream({ pull(controller) { controller.enqueue(new Uint8Array([32])); }, cancel });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(stream)));
    await expect(historyDetail("id")).rejects.toThrow("History detail unavailable.");
    expect(cancel).toHaveBeenCalledTimes(1);
  });
});
