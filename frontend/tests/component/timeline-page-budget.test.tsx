import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ getTimeline: vi.fn(), chart: vi.fn() }));
vi.mock("@/lib/api", () => ({ getTimeline: mocks.getTimeline }));
vi.mock("@/components/TcTimeline", () => ({ TcTimeline: mocks.chart }));
import TimelinePage from "@/app/timeline/page";

describe("timeline initial display budget", () => {
  const response = {
    points: [], coverage: { total_points: 15000, year_min: 1911, year_max: 2026 },
    sampling: { total_points: 15000, returned_points: 2000, is_sampled: true },
    record_summary: { scope: "full_filtered_unsampled", record_candidates: [] },
  };
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getTimeline.mockResolvedValue(response);
    mocks.chart.mockReturnValue(null);
  });

  it.each([undefined, "unbounded", "100000000", "Expanded"])(
    "bounds initial delivery for display=%s while retaining full-selection metadata", async display => {
      render(await TimelinePage({ searchParams: Promise.resolve({ display }) }));
      expect(mocks.getTimeline).toHaveBeenCalledWith(expect.objectContaining({ maxPoints: 2000, compact: true }));
      expect(mocks.chart.mock.calls[0][0]).toEqual({
        points: response.points, coverage: response.coverage,
        sampling: response.sampling, recordSummary: response.record_summary,
      });
      expect(screen.getByRole("link", { name: "Up to 2,000 results" })).toHaveAttribute("aria-pressed", "true");
      expect(screen.getByText(/Coverage counts and reported record summaries use the full eligible selection/)).toBeVisible();
    },
  );

  it("expands only on explicit choice and preserves scientific filters in both display links", async () => {
    render(await TimelinePage({ searchParams: Promise.resolve({
      display: "expanded", family: "iron_based", experimental_only: "true", only_aps: "true",
    }) }));
    expect(mocks.getTimeline).toHaveBeenCalledWith({
      family: "iron_based", experimentalOnly: true, onlyAps: true, maxPoints: 10000, compact: true,
    });
    expect(screen.getByRole("link", { name: "Up to 2,000 results" })).toHaveAttribute(
      "href", "/timeline?family=iron_based&experimental_only=true&only_aps=true",
    );
    expect(screen.getByRole("link", { name: "Up to 10,000 results" })).toHaveAttribute(
      "href", "/timeline?family=iron_based&experimental_only=true&only_aps=true&display=expanded",
    );
    expect(screen.getByRole("link", { name: "Observed only" })).toHaveAttribute(
      "href", "/timeline?family=iron_based&only_aps=true&display=expanded",
    );
  });
});
