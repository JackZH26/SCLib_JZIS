import { afterEach, describe, expect, it, vi } from "vitest";
import { listMaterials } from "@/lib/api";
import { materialsParams } from "@/lib/materials-browser";

afterEach(() => vi.unstubAllGlobals());

function stubMaterialResponse() {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, status: 200, headers: new Headers(), json: async () => ({ total: 0, results: [], limit: 100, offset: 200 }) });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

describe("Materials formula query URL transport", () => {
  it("sends one normalized q parameter without splitting its literal punctuation or dropping scientific filters", async () => {
    const fetcher = stubMaterialResponse();
    await listMaterials(materialsParams({ q: "  Ｂｉ₂Ｔｅ₃_%&+  ", family: "conventional,hydride", tc_min: "20", pressure_max: "150", knowledge_origin: "Observed", page: "2", per_page: "100" }));
    expect(fetcher).toHaveBeenCalledTimes(1);
    const [input, init] = fetcher.mock.calls[0];
    const url = new URL(String(input));
    expect(url.pathname).toMatch(/\/materials$/);
    expect(url.searchParams.getAll("q")).toEqual(["Bi2Te3_%&+"]);
    expect(url.searchParams.get("family")).toBe("conventional,hydride");
    expect(url.searchParams.get("tc_min")).toBe("20");
    expect(url.searchParams.get("pressure_max")).toBe("150");
    expect(url.searchParams.get("knowledge_origin")).toBe("Observed");
    expect(url.searchParams.get("experimental_only")).toBe("true");
    expect(url.searchParams.get("offset")).toBe("200");
    expect(url.searchParams.get("limit")).toBe("100");
    expect(init?.method ?? "GET").toBe("GET");
    expect(init?.body).toBeUndefined();
  });

  it("does not add q to old URLs or whitespace-only queries", async () => {
    const fetcher = stubMaterialResponse();
    await listMaterials(materialsParams({ family: "conventional" }));
    await listMaterials(materialsParams({ q: " \u00a0 ", family: "conventional" }));
    expect(fetcher).toHaveBeenCalledTimes(2);
    for (const [input] of fetcher.mock.calls) {
      const url = new URL(String(input));
      expect(url.searchParams.has("q")).toBe(false);
      expect(url.searchParams.get("family")).toBe("conventional");
    }
  });
});
