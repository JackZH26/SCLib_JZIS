import { describe, it, expect, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import * as timelineEngine from "@/lib/timeline-webgpu";
import Timeline3D from "@/components/Timeline3D";
import { chartPosition, createTimelineScene, type TimelineSceneInput } from "@/lib/timeline-webgpu";
import { timelineSvg } from "@/lib/timeline-export";
import type { TimelineDisplayCluster } from "@/lib/timeline-display";
import { nearbyTimelineTargets } from "@/lib/timeline-display";
import { timelineFamilyColour, timelineMarkerDiameter } from "@/lib/timeline-style";

const input: TimelineSceneInput = { width: 1000, height: 500, clusters: [], xRange: [1900, 2030], yRange: [0, 300], logarithmic: false };

describe("Three-dimensional timeline scientific coordinates", () => {
  it("preserves exact coordinate overlap and does not perturb nearby values", () => {
    const first = chartPosition({ year: 2000, tc_kelvin: 10 }, input);
    expect(chartPosition({ year: 2000, tc_kelvin: 10 }, input)).toEqual(first);
    expect(chartPosition({ year: 2000, tc_kelvin: 10.0001 }, input)?.y).not.toEqual(first?.y);
  });
  it("keeps naturally overlapping Tc markers individually selectable, ordered by screen distance", () => {
    const first: TimelineDisplayCluster = { id: "first", year: 2000, tc_kelvin: 100, members: [], sourceCount: 0, family: "cuprate", origin: "Observed" };
    const second = { ...first, id: "second", tc_kelvin: 100.2, family: "hydride" };
    const a = chartPosition(first, input)!, b = chartPosition(second, input)!;
    expect(Math.abs(a.y - b.y)).toBeLessThan(timelineMarkerDiameter(1));
    const targets = [{ ...b, cluster: second }, { ...a, cluster: first }];
    expect(nearbyTimelineTargets(targets, a.x, a.y)).toEqual([first, second]);
    expect(nearbyTimelineTargets(targets, b.x, b.y)).toEqual([second, first]);
    expect(nearbyTimelineTargets(targets, a.x + 30, a.y)).toEqual([]);
    expect([first.tc_kelvin, second.tc_kelvin]).toEqual([100, 100.2]);
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
  it("exports close values at distinct overlapping positions with the same family colours as the chart", () => {
    const a: TimelineDisplayCluster = { id: "a", year: 2000, tc_kelvin: 100, members: [], sourceCount: 0, family: "cuprate", origin: "Observed" };
    const b = { ...a, id: "b", family: "hydride", tc_kelvin: 100.2 };
    const svg = timelineSvg({ clusters: [a, b], xRange: [1900, 2030], yRange: [0, 300], logarithmic: false, receivedCount: 2, sourceUrl: "https://example.test/timeline" });
    const doc = new DOMParser().parseFromString(svg, "image/svg+xml");
    const marks = [...doc.querySelectorAll("g[transform]")];
    expect(marks).toHaveLength(2);
    expect(marks[0].getAttribute("transform")).not.toEqual(marks[1].getAttribute("transform"));
    expect(marks.map(mark => mark.getAttribute("stroke"))).toEqual([timelineFamilyColour(a.family), timelineFamilyColour(b.family)]);
    expect(marks.map(mark => mark.querySelector("title")?.textContent)).toEqual([expect.stringContaining("100 K"), expect.stringContaining("100.2 K")]);
  });
  it("pins the clicked overlap without a queued hover replacing it, and switches members explicitly", async () => {
    const clusters: TimelineDisplayCluster[] = [100, 100.2].map((tc, i) => ({
      id: String(i), year: 2000, tc_kelvin: tc, sourceCount: 0, family: "cuprate", origin: "Observed",
      members: [{ material: `SYNTHETIC-${i}`, tc_kelvin: tc, year: 2000, family: "cuprate", pressure_gpa: null, paper_id: null, is_theoretical: false }],
    }));
    const frames = new Map<number, FrameRequestCallback>();
    let frameId = 0;
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => { frames.set(++frameId, callback); return frameId; });
    vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
    vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
    const onReady = vi.fn(), onSelect = vi.fn();
    const engine = { perspective: vi.fn(), zoom: vi.fn(), rotate: vi.fn(), pan: vi.fn(), dispose: vi.fn(), pick: vi.fn(() => [clusters[1], clusters[0]]) };
    const create = vi.spyOn(timelineEngine, "createTimelineScene").mockResolvedValue(engine);
    const view = render(<Timeline3D clusters={clusters} xRange={input.xRange} yRange={input.yRange} logarithmic={false} onError={vi.fn()} onReady={onReady} onSelect={onSelect} />);
    try {
      await waitFor(() => expect(onReady).toHaveBeenCalled());
      const canvas = screen.getByLabelText(/Three-dimensional reported Tc chart/);
      fireEvent(canvas, Object.assign(new Event("pointermove", { bubbles: true }), { pointerType: "mouse", clientX: 10, clientY: 10 }));
      expect(frames.size).toBe(1);
      fireEvent.click(canvas, { clientX: 10, clientY: 10 });
      expect(frames.size).toBe(0);
      act(() => { frames.forEach(callback => callback(0)); });
      expect(screen.getByLabelText("Selected result details")).toHaveTextContent("SYNTHETIC-1");
      expect(onSelect).toHaveBeenLastCalledWith("1");
      fireEvent.change(screen.getByRole("combobox", { name: "Nearby markers (2)" }), { target: { value: "0" } });
      expect(screen.getByLabelText("Selected result details")).toHaveTextContent("SYNTHETIC-0");
      expect(onSelect).toHaveBeenLastCalledWith("0");
    } finally {
      view.unmount(); create.mockRestore(); vi.unstubAllGlobals();
    }
  });
});
