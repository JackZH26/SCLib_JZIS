import { afterEach, expect, it, vi } from "vitest";
import { API_BASE, ApiError, discoveryCalculationFile } from "@/lib/api";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("preserves original binary bytes through authenticated no-store GET", async () => {
  const bytes = new Uint8Array([0, 255, 13, 10, 192, 175]);
  const fetch = vi.fn().mockResolvedValue(new Response(bytes)); vi.stubGlobal("fetch", fetch);
  const signal = new AbortController().signal;
  expect(await discoveryCalculationFile("return/id", 2, bytes.length, signal)).toEqual(bytes);
  expect(fetch).toHaveBeenCalledWith(`${API_BASE}/research/discovery-calculations/returns/return%2Fid/files/2`, { credentials: "include", cache: "no-store", signal });
});

it("rejects truncated files and cancels oversized streams before exposing bytes", async () => {
  const cancel = vi.fn();
  const stream = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(new Uint8Array(5)); }, cancel });
  const fetch = vi.fn().mockResolvedValueOnce(new Response(new Uint8Array(3))).mockResolvedValueOnce(new Response(stream)); vi.stubGlobal("fetch", fetch);
  await expect(discoveryCalculationFile("truncated", 0, 4)).rejects.toBeInstanceOf(ApiError);
  await expect(discoveryCalculationFile("oversized", 0, 4)).rejects.toBeInstanceOf(ApiError);
  expect(cancel).toHaveBeenCalledTimes(1);
});

it("rejects invalid file selectors before network access", async () => {
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  for (const [ordinal, size] of [[-1, 1], [11, 1], [0, 0], [0, 8388609], [0.5, 1]]) {
    await expect(discoveryCalculationFile("invalid", ordinal, size)).rejects.toThrow("Invalid native file selector");
  }
  expect(fetch).not.toHaveBeenCalled();
});

it("retains access-loss status and never retries an interrupted download", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(new Response('{"detail":"held"}', { status: 403 })).mockRejectedValueOnce(new TypeError("interrupted")); vi.stubGlobal("fetch", fetch);
  await expect(discoveryCalculationFile("held", 0, 4)).rejects.toMatchObject({ status: 403 });
  await expect(discoveryCalculationFile("interrupted", 0, 4)).rejects.toMatchObject({ status: 0 });
  expect(fetch).toHaveBeenCalledTimes(2);
});
