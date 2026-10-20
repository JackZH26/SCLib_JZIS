import { describe, it, expect, vi } from "vitest";
import { chartPosition, createTimelineScene, type TimelineSceneInput } from "@/lib/timeline-webgpu";
import { timelineSvg } from "@/lib/timeline-export";
import type { TimelineDisplayCluster } from "@/lib/timeline-display";

const input: TimelineSceneInput = { width: 1000, height: 500, clusters: [], xRange: [1900, 2030], yRange: [0, 300], logarithmic: false };

describe("Three-dimensional timeline scientific coordinates", () => {
  it("preserves exact coordinate overlap and does not perturb nearby values", () => {
    const first = chartPosition({ year: 2000, tc_kelvin: 10 }, input);
    expect(chartPosition({ year: 2000, tc_kelvin: 10 }, input)).toEqual(first);
    expect(chartPosition({ year: 2000, tc_kelvin: 10.0001 }, input)?.y).not.toEqual(first?.y);
  });
  it("rejects points outside a chosen view without changing the original records", () => {
    const point = { year: 2000, tc_kelvin: 90 };
    expect(chartPosition(point, { ...input, yRange: [0, 1] })).toBeNull();
    expect(point.tc_kelvin).toBe(90);
    expect(chartPosition(point, input)).not.toBeNull();
  });
  it("retains sub-kelvin scale and excludes nonpositive values from logarithmic rendering", () => {
    const logarithmic = { ...input, logarithmic: true, yRange: [-6, 3] as [number, number] };
    expect(chartPosition({ year: 2000, tc_kelvin: .000001 }, logarithmic)).not.toBeNull();
    expect(chartPosition({ year: 2000, tc_kelvin: 0 }, logarithmic)).toBeNull();
    expect(chartPosition({ year: 2000, tc_kelvin: -1 }, logarithmic)).toBeNull();
  });
  it("never probes a WebGL context when no WebGPU adapter is available", async () => {
    const context = vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    await expect(createTimelineScene(document.createElement("canvas"), input, () => {}, () => {})).rejects.toThrow("WebGPU unavailable");
    expect(context).not.toHaveBeenCalled();
    context.mockRestore();
  });
  it.each(["null adapter", "rejected adapter"])("handles %s without re-entering renderer initialization", async mode => {
    const requestAdapter = mode === "null adapter" ? vi.fn().mockResolvedValue(null) : vi.fn().mockRejectedValue(new Error("Adapter rejected"));
    vi.stubGlobal("navigator", { gpu: { requestAdapter } });
    const context = vi.spyOn(HTMLCanvasElement.prototype, "getContext");
    try {
      await expect(createTimelineScene(document.createElement("canvas"), input, () => {}, () => {})).rejects.toThrow(/adapter/i);
      expect(requestAdapter).toHaveBeenCalledTimes(1);
      expect(context).not.toHaveBeenCalled();
    } finally {
      context.mockRestore();
      vi.unstubAllGlobals();
    }
  });
  it("exports a labelled front view with source filters and escaped metadata", () => {
    const svg = timelineSvg({ clusters: [], xRange: [1900, 2030], yRange: [0, 300], logarithmic: false, receivedCount: 72, sourceUrl: 'https://example.test/timeline?family=cuprate&label=<script>"' });
    const document = new DOMParser().parseFromString(svg, "image/svg+xml");
    expect(document.querySelector("parsererror")).toBeNull();
    expect(document.querySelector("script")).toBeNull();
    expect(document.querySelector("desc")?.textContent).toContain("72 received results; 0 visible coordinate clusters");
    expect(document.querySelector("desc")?.textContent).toContain("family=cuprate&label=<script>");
  });
  it("exports logarithmic sub-kelvin records while disclosing out-of-view omissions", () => {
    const cluster: TimelineDisplayCluster = { id: "subkelvin", year: 2000, tc_kelvin: .000001, members: [], sourceCount: 0, family: "elemental", origin: "Observed" };
    const svg = timelineSvg({ clusters: [cluster, { ...cluster, id: "zero", tc_kelvin: 0 }], xRange: [1900, 2030], yRange: [-6, 3], logarithmic: true, receivedCount: 2, sourceUrl: "https://example.test/timeline" });
    const document = new DOMParser().parseFromString(svg, "image/svg+xml");
    expect(document.querySelectorAll("g[transform]")).toHaveLength(1);
    expect(document.querySelector("desc")?.textContent).toContain("2 received results; 1 visible coordinate clusters");
    expect(svg).not.toMatch(/NaN|Infinity/);
    expect(svg).toContain("Out-of-view records remain in the website table");
  });
});
