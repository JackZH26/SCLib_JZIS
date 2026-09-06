import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ResearchPriorityBoard } from "@/components/ResearchPriorityBoard";
import { getRpsReleases, getRpsPage, getRpsDetail, verifyRpsPage, verifyRpsDetail, PHYSICAL_DIMENSIONS, ACTION_RESOURCES, RPS_ACTION_CONTRACT, type RpsPage, type RpsRelease, type RpsRow, type RpsDetail } from "@/lib/research-priority";

vi.mock("@/lib/research-priority", async importOriginal => {
  const actual = await importOriginal<typeof import("@/lib/research-priority")>();
  return { ...actual, getRpsReleases: vi.fn(), getRpsPage: vi.fn(), getRpsDetail: vi.fn() };
});

const release: RpsRelease = {
  id: "test-release", manifest_sha256: "a".repeat(64), campaign_id: "test", campaign_version: "1",
  objective: "Synthetic test only", published_at: "2026-09-05", evidence_cutoff: "2026-09-01", total: 0,
};
const page: RpsPage = {
  schema_version: "rps-page/1.2", release_id: release.id, manifest_sha256: release.manifest_sha256,
  policy_hash: "b".repeat(64), campaign: { id: "test", version: "1", objective: "Synthetic test" },
  evidence_cutoff: "2026-09-01", items: [], total: 0, offset: 0, limit: 24, has_more: false,
  group: "discovery", release_total: 0,
};
const row: RpsRow = {
  id: "assessment-1", revision: 1, rank: 1, material_id: "material-1", state_id: "state-1", action_id: "action-1",
  formula: "TEST", family: "synthetic", state_summary: "Synthetic test state", action_summary: "Synthetic action", role: "new_candidate",
  action_template: { id: "template:test", version: "synthetic-1", sha256: "c".repeat(64), review_id: "synthetic-review" },
  dimensions: Object.fromEntries(PHYSICAL_DIMENSIONS.map(([key]) => [key, { status: "unknown", anchor: null, lower: 0, upper: 100, missing_reason: "Synthetic missing support", evidence_polarity: "unknown" }])),
  result: {
    eligibility: "eligible", reason_codes: [], rank_group: "discovery", policy_version: "RPS-v1.2",
    action_contract_version: RPS_ACTION_CONTRACT, action_requirements_hash: "d".repeat(64), execution_constraint_reasons: [],
    score_raw: 4375, score_display: 4400, score_upper: 8875,
    p_lower: 0, p_upper: 100, g_lower: 75, g_upper: 75, a_lower: 75, a_upper: 75, assessed_weight: 0,
    contributions: { baseline: 5500, physical: -2250, gain: 675, action: 450, rounding: 25,
      dimensions: Object.fromEntries(PHYSICAL_DIMENSIONS.map(([key]) => [key, -375])),
      dimension_reasons: Object.fromEntries(PHYSICAL_DIMENSIONS.map(([key]) => [key, "missing_support"])),
      dimension_explanations: Object.fromEntries(PHYSICAL_DIMENSIONS.map(([key]) => [key, {
        evidence_polarity: "unknown", reason_codes: ["missing_support"], anchor_contribution: null,
        uncertainty_discount: null, missing_support_contribution: -375,
      }])),
    },
  },
};
const detail: RpsDetail = {
  schema_version: "rps-detail/1.2", release_id: release.id, manifest_sha256: release.manifest_sha256,
  result: row.result,
  assessment: { id: row.id, revision: 1, material: { id: row.material_id }, state: { id: row.state_id }, action: { id: row.action_id },
    dimensions: Object.fromEntries(PHYSICAL_DIMENSIONS.map(([key]) => [key, { rationale: "Synthetic missing evidence", rule_id: `rule:${key}`, missing_reason: "Not computed", evidence_polarity: "unknown" }])),
    action_requirements: {
      schema_version: RPS_ACTION_CONTRACT, template_ref: { id: row.action_template.id, sha256: row.action_template.sha256 },
      template_review: { id: "synthetic-review", sha256: "e".repeat(64) },
      template: { version: "synthetic-1", title: "Synthetic only", action_kind: "calculation", scope: "Not a real template approval",
        prerequisite_completeness_rationale: "Synthetic review only", prerequisites: [{ key: "structure", description: "Synthetic structure prerequisite", dependency_kind: "structure", critical: true, allow_not_applicable: false }],
        resource_rules: Object.fromEntries(ACTION_RESOURCES.map(resource => [resource, resource === "cpu_core_hours" ? "required" : "not_applicable"])),
      },
      prerequisites: [{ key: "structure", status: "satisfied", rationale: "Synthetic input", evidence: [{ id: "source-1", sha256: "a".repeat(64) }], dependency_ids: ["structure-input"] }],
      dependencies: [{ id: "structure-input", kind: "structure", status: "available", rationale: "Synthetic available input", evidence: [{ id: "source-1", sha256: "a".repeat(64) }] }],
      resources: ACTION_RESOURCES.map(resource => ({ resource, applicability: resource === "cpu_core_hours" ? "required" : "not_applicable", rationale: "Synthetic applicability", evidence: [{ id: "source-1", sha256: "a".repeat(64) }] })),
    },
    outcomes: [{ observation: "positive", decision: "proceed" }, { observation: "negative", decision: "stop" }],
    costs: [{ resource: "cpu_core_hours", lower: 20, upper: 20, basis: "Synthetic estimate" }],
  },
  state: { pressure_status: "explicit_ambient", pressure_gpa: 0, phase: "test", sample_context: "Synthetic" },
  action: { kind: "calculation", action_requirements_hash: row.result.action_requirements_hash },
  evidence: [{ id: "source-1", sha256: "a".repeat(64), source: { title: "Synthetic fixture source", url: "https://example.org/test", source_version: "1", locator: "Table 1", validity: "accepted" } }],
};

describe("ResearchPriorityBoard", () => {
  beforeEach(() => vi.resetAllMocks());

  it("truthfully distinguishes not-published from old heuristic scores", async () => {
    vi.mocked(getRpsReleases).mockResolvedValue({ schema_version: "rps-catalog/1.2", status: "not_published", items: [] });
    render(<ResearchPriorityBoard />);
    expect(await screen.findByText("No reviewed RPS release published yet")).toBeInTheDocument();
    expect(screen.getByText(/not a probability of superconductivity/)).toBeInTheDocument();
    expect(getRpsPage).not.toHaveBeenCalled();
  });

  it("shows an outage, not an apparently successful empty release, and retries", async () => {
    vi.mocked(getRpsReleases).mockRejectedValueOnce(new Error("503"));
    vi.mocked(getRpsReleases).mockResolvedValueOnce({ schema_version: "rps-catalog/1.2", status: "not_published", items: [] });
    render(<ResearchPriorityBoard />);
    expect(await screen.findByRole("alert")).toHaveTextContent("No legacy score has been substituted");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("No reviewed RPS release published yet")).toBeInTheDocument();
  });

  it("hides a page with a different release digest", async () => {
    vi.mocked(getRpsReleases).mockResolvedValue({ schema_version: "rps-catalog/1.2", status: "published", items: [release] });
    vi.mocked(getRpsPage).mockResolvedValue({ ...page, manifest_sha256: "wrong" });
    render(<ResearchPriorityBoard />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Scores are hidden");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("loads a fixed release with separate action groups", async () => {
    vi.mocked(getRpsReleases).mockResolvedValue({ schema_version: "rps-catalog/1.2", status: "published", items: [release] });
    vi.mocked(getRpsPage).mockResolvedValue(page);
    render(<ResearchPriorityBoard />);
    await waitFor(() => expect(screen.getByRole("table")).toBeInTheDocument());
    vi.mocked(getRpsPage).mockResolvedValue({ ...page, group: "unranked" });
    fireEvent.click(screen.getByRole("button", { name: "Unranked / references" }));
    await waitFor(() => expect(screen.getByRole("table")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Unranked / references" })).toHaveAttribute("aria-pressed", "true");
  });

  it("rejects mixed-release pagination rather than merging it", () => {
    expect(() => verifyRpsPage({ ...page, release_id: "other" }, release, 0)).toThrow();
    expect(() => verifyRpsPage({ ...page, offset: 24 }, release, 0)).toThrow();
    expect(() => verifyRpsPage({ ...page, has_more: true }, release, 0)).toThrow();
  });

  it("renders a real-shaped score row, unknowns and lazy traceable detail", async () => {
    const nonemptyRelease = { ...release, total: 1 };
    vi.mocked(getRpsReleases).mockResolvedValue({ schema_version: "rps-catalog/1.2", status: "published", items: [nonemptyRelease] });
    vi.mocked(getRpsPage).mockResolvedValue({ ...page, total: 1, release_total: 1, items: [row] });
    vi.mocked(getRpsDetail).mockResolvedValue(detail);
    render(<ResearchPriorityBoard />);
    expect(await screen.findByText("4,400")).toBeInTheDocument();
    expect(screen.getAllByText("Unknown")).toHaveLength(6);
    expect(getRpsDetail).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "TEST · synthetic" }));
    expect(await screen.findByRole("link", { name: "Synthetic fixture source" })).toHaveAttribute("href", "https://example.org/test");
    expect(screen.getByText(/Unknown dimensions lower conservative priority/)).toBeInTheDocument();
    expect(screen.getByText("Reviewed action contract")).toBeInTheDocument();
    expect(screen.getByText(/Template: template:test/)).toHaveTextContent("version synthetic-1");
    expect(screen.getByText("All resource declarations")).toBeInTheDocument();
    expect(screen.getByText(/gpu_hours: not applicable/)).toBeInTheDocument();
    expect(screen.getAllByText("Missing support — not adverse evidence")).toHaveLength(6);
  });

  it("rejects another assessment from the same release", () => {
    expect(() => verifyRpsDetail({ ...detail, assessment: { ...detail.assessment, id: "other-row" } }, release, row)).toThrow(/identity/);
    expect(() => verifyRpsDetail({ ...detail, result: { ...detail.result, score_display: 9950 } }, release, row)).toThrow(/mismatch/);
  });

  it("rejects duplicate rows across pages and noneligible public scores", () => {
    const one = { ...page, total: 1, release_total: 1, items: [row] };
    expect(() => verifyRpsPage(one, { ...release, total: 1 }, 0, [row])).toThrow(/Duplicate/);
    expect(() => verifyRpsPage({ ...one, items: [{ ...row, result: { ...row.result, eligibility: "pending" } }] }, { ...release, total: 1 }, 0)).toThrow(/Invalid public/);
  });

  it("fails closed for old action contracts and changed template or resource detail", () => {
    const one = { ...page, total: 1, release_total: 1, items: [row] };
    expect(() => verifyRpsPage({ ...one, items: [{ ...row, result: { ...row.result, action_contract_version: "old" as typeof RPS_ACTION_CONTRACT } }] }, { ...release, total: 1 }, 0)).toThrow(/Missing reviewed/);
    expect(() => verifyRpsDetail({ ...detail, action: { ...detail.action, action_requirements_hash: "f".repeat(64) } }, release, row)).toThrow(/mismatch/);
    const wrongTemplate = structuredClone(detail);
    wrongTemplate.assessment.action_requirements.template.version = "synthetic-2";
    expect(() => verifyRpsDetail(wrongTemplate, release, row)).toThrow(/contract mismatch/);
    const missingResource = structuredClone(detail);
    missingResource.assessment.action_requirements.resources.pop();
    expect(() => verifyRpsDetail(missingResource, release, row)).toThrow(/contract mismatch/);
  });
});
