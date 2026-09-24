import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TcTimeline } from "@/components/TcTimeline";
import { getMaterial, getTimeline, listSitemapResources, type TimelinePoint } from "@/lib/api";
import { materialVisibility } from "../fixtures/material-visibility";

vi.mock("next/dynamic", () => ({ default: () => function TestPlot({ data }: { data: unknown }) { return <pre aria-label="Timeline traces">{JSON.stringify(data)}</pre>; } }));

function point(material = "TEST"): TimelinePoint {
  return { material, family: null, tc_kelvin: 20, year: 2026, pressure_gpa: null, paper_id: null, is_theoretical: false, visibility: materialVisibility() };
}

describe("mutable visibility reads and timeline", () => {
  beforeEach(() => { vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null); });
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it.each([
    ["material detail", () => getMaterial("test")],
    ["timeline", () => getTimeline()],
    ["material sitemap", () => listSitemapResources("material")],
  ] as const)("%s bypasses the mutable Next data cache", async (_name, read) => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ points: [] }) });
    vi.stubGlobal("fetch", fetchMock);
    await read();
    const options = fetchMock.mock.calls[0][1];
    expect(options.cache).toBe("no-store");
    expect(options.next).toBeUndefined();
  });

  it("adds current governance status to each hover and labels origin as not approval", () => {
    render(<TcTimeline points={[point()]} coverage={null} />);
    expect(screen.getByLabelText("Timeline traces")).toHaveTextContent("Catalogue eligible — not scientific approval");
    expect(screen.getByText(/Markers describe reported result origin, not scientific approval/)).toBeInTheDocument();
    expect(screen.queryByText(/Archive or visibility-unverified points/)).not.toBeInTheDocument();
  });

  it("pending and missing policy remain explicitly Archive or unverified", () => {
    render(<TcTimeline points={[{ ...point(), visibility: materialVisibility("pending") }, { ...point("UNKNOWN"), visibility: undefined }]} coverage={null} />);
    expect(screen.getByLabelText("Timeline traces")).toHaveTextContent("Archive — review pending");
    expect(screen.getByLabelText("Timeline traces")).toHaveTextContent("Archive — visibility unverified");
    expect(screen.getByText(/Archive or visibility-unverified points/)).toBeInTheDocument();
  });

  it("does not plot explicitly quarantined data from an incompatible stale response", () => {
    render(<TcTimeline points={[point(), { ...point("RESTRICTED-TEST"), visibility: materialVisibility("quarantined") }]} coverage={null} />);
    expect(screen.getByLabelText("Timeline traces")).not.toHaveTextContent("RESTRICTED-TEST");
  });
});
