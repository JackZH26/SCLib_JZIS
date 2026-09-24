import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, getTimeline, listMaterials, login, me } from "@/lib/api";

afterEach(() => vi.unstubAllGlobals());

function jsonResponse(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, headers: new Headers({ "x-request-id": "synthetic-response-check" }), json: async () => body };
}

describe("API response integrity", () => {
  it.each([getTimeline, () => listMaterials({}), () => login("synthetic@example.invalid", "synthetic-only")])(
    "rejects an interrupted 200 response without retrying or reporting success", async read => {
      const response = { ...jsonResponse(null), json: async () => { throw new TypeError("terminated at http://api:8000/private"); } };
      const fetcher = vi.fn().mockResolvedValue(response);
      vi.stubGlobal("fetch", fetcher);
      const error = await read().catch(error => error);
      expect(error).toBeInstanceOf(ApiError);
      expect(error.status).toBe(0);
      expect(error.requestId).toBe("synthetic-response-check");
      expect(error.message).toContain("incomplete or invalid");
      expect(error.message).not.toContain("api:8000");
      expect(fetcher).toHaveBeenCalledTimes(1);
    },
  );

  it("rejects a malformed JSON success response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('{"points":', { status: 200 })));
    await expect(getTimeline()).rejects.toBeInstanceOf(ApiError);
  });

  it.each([null, {}, [], { points: null }, { points: {} }, { points: [null] },
    { points: [{ material: "TEST", year: "2026", tc_kelvin: 20 }] },
    { points: [{ material: "TEST", year: 2026, tc_kelvin: null }] }])(
    "rejects a structurally unusable timeline instead of inventing an empty selection", async body => {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(body)));
      await expect(getTimeline()).rejects.toBeInstanceOf(ApiError);
    },
  );

  it("preserves a valid empty selection and its full-selection metadata", async () => {
    const response = { schema_version: "1", points: [], coverage: { total_points: 0 }, sampling: { is_sampled: false } };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(response)));
    expect(await getTimeline()).toBe(response);
  });

  it("preserves valid scientific points without coercing temperatures or identities", async () => {
    const response = { points: [{ material: "TEST", year: 2026, tc_kelvin: 0.00001, point_id: "opaque%2Fid" }] };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(response)));
    expect(await getTimeline()).toBe(response);
  });

  it("keeps authentication status and correlation when an error response is not JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("Not JSON", {
      status: 401, headers: { "x-request-id": "synthetic-unauthorized" },
    })));
    await expect(me()).rejects.toMatchObject({ status: 401, requestId: "synthetic-unauthorized" });
  });

  it("keeps retry guidance when a rate-limit response body is truncated", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ...jsonResponse(null, 429),
      headers: new Headers({ "retry-after": "15" }), json: async () => { throw new TypeError("terminated"); } }));
    await expect(getTimeline()).rejects.toMatchObject({ status: 429, retryAfterSec: 15 });
  });
});
