import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DiscoveryFeed } from "@/components/DiscoveryFeed";
import {
  ApiError, getDiscoveryCandidate, getDiscoveryCandidates, verifyDiscoveryDetail, verifyDiscoveryPage,
  type DiscoveryCandidate, type DiscoveryCandidatePage, type DiscoveryCandidateSummary, type DiscoveryVersion,
} from "@/lib/api";

vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, getDiscoveryCandidate: vi.fn(), getDiscoveryCandidates: vi.fn() };
});

const version = "discovery-v1-aaaaaaaaaaaaaaaa";
const candidate: DiscoveryCandidateSummary = {
  candidate_id: "lead-1", formula: "TEST", branch: "synthetic fixture", lane_id: null,
  prototype_family: null, candidate_layer: null, condition_class: null,
  evidence_level: "E1", checker_status: "pending", public_confidence: "Legacy lead",
  evidence_quality_score: null, experiment_readiness: null, record_role: "exploratory_candidate",
  claim_level: null, next_action: null, discovery_score: null,
};
const page: DiscoveryCandidatePage = {
  schema_version: "1", data_version: version, source_status: "ready", last_successful_at: "2026-09-05T00:00:00Z", source_error: null,
  items: [candidate], total: 2, offset: 0, limit: 24, has_more: true, record_role: null,
};

function show(initialPage = page) {
  return render(<DiscoveryFeed initialPage={initialPage} roleCounts={{ exploratory_candidate: 2 }} totalCandidates={2} />);
}

describe("legacy Discovery version contract", () => {
  beforeEach(() => vi.resetAllMocks());

  it("labels the legacy literature stage as a report, without changing the stage code", () => {
    const item = { ...candidate, evidence_level: "literature-confirmed" };
    show({ ...page, items: [item] });
    expect(screen.getByText("Literature-reported")).toBeInTheDocument();
    expect(screen.queryByText("Literature-confirmed")).not.toBeInTheDocument();
    expect(item.evidence_level).toBe("literature-confirmed");
  });

  it("verifies stable IDs, roles, totals and version before adding rows", () => {
    expect(() => verifyDiscoveryPage(page, version, 0, [], null, 2)).not.toThrow();
    expect(() => verifyDiscoveryPage({ ...page, data_version: "other" }, version, 0)).toThrow();
    expect(() => verifyDiscoveryPage({ ...page, total: 3 }, version, 0, [], null, 2)).toThrow();
    expect(() => verifyDiscoveryPage({ ...page, record_role: "negative_control" }, version, 0)).toThrow();
    expect(() => verifyDiscoveryPage(page, version, 0, [candidate])).toThrow();
    expect(() => verifyDiscoveryPage({ ...page, items: [{ ...candidate, discovery_score: Infinity }] }, version, 0)).toThrow();
  });

  it("pins load-more requests and never appends another version", async () => {
    vi.mocked(getDiscoveryCandidates).mockResolvedValue({ ...page, data_version: "other", offset: 1, has_more: false, items: [{ ...candidate, candidate_id: "lead-2" }] });
    show();
    fireEvent.click(screen.getByRole("button", { name: "Load 1 more" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("mixed-version records have been cleared");
    expect(getDiscoveryCandidates).toHaveBeenCalledWith({ offset: 1, limit: 24, recordRole: null, dataVersion: version });
    expect(screen.queryByText("Legacy lead")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload latest feed" })).toBeInTheDocument();
  });

  it("clears the old list on an API version conflict instead of retrying its offset", async () => {
    vi.mocked(getDiscoveryCandidates).mockRejectedValue(new ApiError(409, { detail: { code: "discovery_version_conflict" } }, "Version conflict"));
    show();
    fireEvent.click(screen.getByRole("button", { name: "Load 1 more" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Reload the latest feed");
    expect(screen.queryByRole("button", { name: "Load 1 more" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All · 2" })).toBeDisabled();
  });

  it("binds role filters to the initial version and does not reinterpret negative controls", async () => {
    vi.mocked(getDiscoveryCandidates).mockResolvedValue({ ...page, record_role: "exploratory_candidate" });
    show();
    fireEvent.click(screen.getByRole("button", { name: "Active Exploratory Candidates · 2" }));
    await waitFor(() => expect(getDiscoveryCandidates).toHaveBeenCalledWith({ limit: 24, recordRole: "exploratory_candidate", dataVersion: version }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("pins lazy detail to the same version and rejects another revision", async () => {
    vi.mocked(getDiscoveryCandidate).mockResolvedValue({ ...candidate, data_version: "other", source_status: "ready" } as DiscoveryCandidate & DiscoveryVersion);
    const view = show();
    expect(getDiscoveryCandidate).not.toHaveBeenCalled();
    const details = view.container.querySelector("details")!;
    details.open = true;
    fireEvent(details, new Event("toggle"));
    await waitFor(() => expect(getDiscoveryCandidate).toHaveBeenCalledWith("lead-1", version));
    expect(await screen.findByRole("alert")).toHaveTextContent("mixed-version records have been cleared");
    expect(screen.queryByText("Legacy lead")).not.toBeInTheDocument();
  });

  it("rejects a detail for another candidate even within one version", () => {
    const detail = { ...candidate, data_version: version, source_status: "ready" } as DiscoveryCandidate & DiscoveryVersion;
    expect(() => verifyDiscoveryDetail(detail, version, "other-id")).toThrow();
    expect(() => verifyDiscoveryDetail(detail, version, candidate.candidate_id)).not.toThrow();
  });

  it("shows the last-good state without disguising it as a fresh successful update", () => {
    show({ ...page, source_status: "stale", source_error: "invalid_update" });
    expect(screen.getByRole("status")).toHaveTextContent("The latest feed update could not be validated");
    expect(screen.getByRole("status")).toHaveTextContent("2026-09-05T00:00:00Z");
    expect(screen.getByText("Legacy lead")).toBeInTheDocument();
  });
});
