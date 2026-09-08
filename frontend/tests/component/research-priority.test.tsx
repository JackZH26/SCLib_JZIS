import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ResearchPriorityBoard } from "@/components/ResearchPriorityBoard";
import { getRpsReleases, getRpsPage, getRpsDetail, rpsBundleDownloadUrl, verifyRpsCatalog, verifyRpsPage, verifyRpsDetail, PHYSICAL_DIMENSIONS, ACTION_RESOURCES, RPS_ACTION_CONTRACT, type RpsCatalog, type RpsPage, type RpsRelease, type RpsRow, type RpsDetail } from "@/lib/research-priority";
import { PUBLIC_API_BASE } from "@/lib/api";
import actualCatalog from "../fixtures/rps-catalog-http.json";
import actualPage from "../fixtures/rps-page-http.json";

vi.mock("@/lib/research-priority", async importOriginal => {
  const actual = await importOriginal<typeof import("@/lib/research-priority")>();
  return { ...actual, getRpsReleases: vi.fn(), getRpsPage: vi.fn(), getRpsDetail: vi.fn() };
});

const release: RpsRelease = {
  id: "test-release", manifest_sha256: "a".repeat(64), campaign_id: "test", campaign_version: "1",
  objective: "Synthetic test only", published_at: "2026-09-05T00:00:00+00:00", evidence_cutoff: "2026-09-01T00:00:00+00:00", total: 0,
  public_bundle: { status: "not_published", sha256: null, verifier_version: null },
};
function catalog(items: RpsRelease[] = [], unavailable: RpsCatalog["unavailable"] = []): RpsCatalog {
  return { schema_version: "rps-catalog/1.3", items, unavailable, approval_sha256: "e".repeat(64), catalog_revision: "f".repeat(64),
    status: items.length ? unavailable.length || items.some(item => item.public_bundle.status === "unavailable") ? "degraded" : "published"
      : unavailable.length ? "unavailable" : "not_published" };
}
const downloadableRelease = (): RpsRelease => ({ ...release, public_bundle: {
  status: "available", sha256: "7".repeat(64), verifier_version: "rps-public-verifier/1.0.0",
} });
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const page: RpsPage = {
  schema_version: "rps-page/1.2", release_id: release.id, manifest_sha256: release.manifest_sha256,
  policy_hash: "b".repeat(64), campaign: { id: "test", version: "1", objective: release.objective },
  evidence_cutoff: release.evidence_cutoff, items: [], total: 0, offset: 0, limit: 24, has_more: false,
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
  afterEach(() => vi.restoreAllMocks());

  it("truthfully distinguishes not-published from old heuristic scores", async () => {
    vi.mocked(getRpsReleases).mockResolvedValue(catalog());
    render(<ResearchPriorityBoard />);
    expect(await screen.findByText("No reviewed RPS release published yet")).toBeInTheDocument();
    expect(screen.getByText(/not a probability of superconductivity/)).toBeInTheDocument();
    expect(getRpsPage).not.toHaveBeenCalled();
  });

  it("consumes captured real synthetic HTTP catalog/page bindings and links only the selected catalog pins", async () => {
    // Verbatim guarded HTTP captures from test_capture_synthetic_catalog_and_page_wire_for_cross_stack_rehearsal.
    // The captured page requests group=all; the board deliberately keeps separate action groups.
    const checked = verifyRpsCatalog(actualCatalog), selected = checked.items.find(item => item.id === actualPage.release_id)!;
    expect(verifyRpsPage(actualPage as RpsPage, selected, 0, [], "all").items).toHaveLength(1);
    expect(() => verifyRpsPage(actualPage as RpsPage, selected, 0, [], "discovery")).toThrow();
    vi.mocked(getRpsReleases).mockResolvedValue(checked);
    vi.mocked(getRpsPage).mockReturnValue(new Promise(() => {}));
    render(<ResearchPriorityBoard />);
    await screen.findByRole("link", { name: "Download pinned public verification bundle" });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: selected.id } });
    const url = new URL(screen.getByRole("link", { name: "Download pinned public verification bundle" }).getAttribute("href")!);
    expect(url.searchParams.get("manifest_sha256")).toBe(selected.manifest_sha256);
    expect(url.searchParams.get("bundle_sha256")).toBe(selected.public_bundle.sha256);
    expect(url.pathname).toContain(`/${selected.id}/bundle`);
    expect(screen.getByText(/browser has not downloaded or independently verified/)).toBeVisible();
  });

  it("shows an outage, not an apparently successful empty release, and retries", async () => {
    vi.mocked(getRpsReleases).mockRejectedValueOnce(new Error("503"));
    vi.mocked(getRpsReleases).mockResolvedValueOnce(catalog());
    render(<ResearchPriorityBoard />);
    expect(await screen.findByRole("alert")).toHaveTextContent("No legacy score has been substituted");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("No reviewed RPS release published yet")).toBeInTheDocument();
  });

  it("hides a page with a different release digest", async () => {
    vi.mocked(getRpsReleases).mockResolvedValue(catalog([release]));
    vi.mocked(getRpsPage).mockResolvedValue({ ...page, manifest_sha256: "wrong" });
    render(<ResearchPriorityBoard />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Scores are hidden");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("loads a fixed release with separate action groups", async () => {
    vi.mocked(getRpsReleases).mockResolvedValue(catalog([release]));
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
    vi.mocked(getRpsReleases).mockResolvedValue(catalog([nonemptyRelease]));
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

  it("keeps a valid release visible in a degraded catalog without disguising failed releases as empty", async () => {
    vi.mocked(getRpsReleases).mockResolvedValue(catalog([release], [{ id: "failed-release", status: "unavailable", reason_code: "verification_failed" }]));
    vi.mocked(getRpsPage).mockResolvedValue(page);
    render(<ResearchPriorityBoard />);
    expect(await screen.findByRole("table")).toBeVisible();
    expect(screen.getByText(/Publication catalog partially available/)).toBeVisible();
    expect(screen.getByText("failed-release")).toBeVisible();
    expect(screen.queryByText("No reviewed RPS release published yet")).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /failed-release/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Download pinned/ })).not.toBeInTheDocument();
  });

  it("reports an all-failed inventory as unavailable with retry, not not-published", async () => {
    vi.mocked(getRpsReleases).mockResolvedValue(catalog([], [{ id: "failed-release", status: "unavailable", reason_code: "verification_failed" }]));
    render(<ResearchPriorityBoard />);
    expect(await screen.findByRole("alert")).toHaveTextContent("This is not an empty publication catalog");
    expect(screen.getByRole("button", { name: "Retry" })).toBeVisible();
    expect(screen.queryByText("No reviewed RPS release published yet")).not.toBeInTheDocument();
    expect(getRpsPage).not.toHaveBeenCalled();
  });

  it("renders a pinned application-origin download only for an available checked bundle", async () => {
    const available = downloadableRelease();
    vi.mocked(getRpsReleases).mockResolvedValue(catalog([available]));
    vi.mocked(getRpsPage).mockResolvedValue(page);
    render(<ResearchPriorityBoard />);
    const link = await screen.findByRole("link", { name: "Download pinned public verification bundle" });
    const url = new URL(link.getAttribute("href")!);
    expect(url.origin).toBe(new URL(PUBLIC_API_BASE).origin);
    expect(url.pathname).toBe(`${new URL(PUBLIC_API_BASE).pathname}/discovery/rps/releases/${release.id}/bundle`);
    expect(Object.fromEntries(url.searchParams)).toEqual({ manifest_sha256: release.manifest_sha256, bundle_sha256: available.public_bundle.sha256 });
    expect(screen.getByText(/browser has not downloaded or independently verified/)).toBeVisible();
    expect(screen.getByText(/Hash integrity and deterministic recomputation do not establish/)).toBeVisible();
    fireEvent.click(screen.getByText("Publication catalog snapshot"));
    expect(screen.getByText(/opaque server-snapshot identifiers/)).toBeVisible();
  });

  it("withholds a failed bundle while retaining the separately verified score release", async () => {
    const unavailable = { ...release, public_bundle: { ...release.public_bundle, status: "unavailable" as const } };
    vi.mocked(getRpsReleases).mockResolvedValue(catalog([unavailable]));
    vi.mocked(getRpsPage).mockResolvedValue(page);
    render(<ResearchPriorityBoard />);
    expect(await screen.findByRole("table")).toBeVisible();
    expect(screen.getByText(/Publication catalog partially available/)).toBeVisible();
    expect(screen.getByText(/public verification bundle is unavailable/)).toBeVisible();
    expect(screen.queryByRole("link", { name: /Download pinned/ })).not.toBeInTheDocument();
  });

  it("refuses malformed public bundle metadata before rendering scores or arbitrary backend links", async () => {
    const input = catalog([{ ...downloadableRelease(), total: 1 }]);
    Object.assign(input.items[0].public_bundle, { href: "https://attacker.invalid/private-download" });
    vi.mocked(getRpsReleases).mockResolvedValue(input);
    render(<ResearchPriorityBoard />);
    expect(await screen.findByRole("alert")).toHaveTextContent("catalog is inconsistent");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByText("4,400")).not.toBeInTheDocument();
    expect(getRpsPage).not.toHaveBeenCalled();
  });

  it("clears scores and download pins immediately during catalog refresh, then accepts the new manifest only", async () => {
    const first = { ...downloadableRelease(), total: 1 }, refreshed = deferred<RpsCatalog>();
    const second = { ...first, manifest_sha256: "8".repeat(64), public_bundle: { ...first.public_bundle, sha256: "9".repeat(64) } };
    vi.mocked(getRpsReleases).mockResolvedValueOnce(catalog([first])).mockReturnValueOnce(refreshed.promise);
    vi.mocked(getRpsPage).mockResolvedValueOnce({ ...page, total: 1, release_total: 1, items: [row] })
      .mockResolvedValueOnce({ ...page, manifest_sha256: second.manifest_sha256, total: 1, release_total: 1, items: [{ ...row, formula: "NEW" }] });
    render(<ResearchPriorityBoard />);
    expect(await screen.findByText("4,400")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Refresh releases" }));
    expect(screen.queryByText("4,400")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Download pinned/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/Manifest SHA-256:/)).not.toBeInTheDocument();
    await act(async () => { refreshed.resolve({ ...catalog([second]), catalog_revision: "0".repeat(64), approval_sha256: "1".repeat(64) }); });
    expect(await screen.findByRole("button", { name: "NEW · synthetic" })).toBeVisible();
    expect(new URL(screen.getByRole("link", { name: /Download pinned/ }).getAttribute("href")!).searchParams.get("bundle_sha256")).toBe("9".repeat(64));
  });

  it("ignores a late old catalog even when its transport ignores abort", async () => {
    const old = deferred<RpsCatalog>(), current = deferred<RpsCatalog>();
    vi.mocked(getRpsReleases).mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
    render(<ResearchPriorityBoard />);
    const oldSignal = vi.mocked(getRpsReleases).mock.calls[0][0];
    fireEvent.click(screen.getByRole("button", { name: "Refresh releases" }));
    expect(oldSignal?.aborted).toBe(true);
    await act(async () => { current.resolve(catalog()); });
    await act(async () => { old.resolve(catalog([downloadableRelease()])); });
    expect(screen.getByText("No reviewed RPS release published yet")).toBeVisible();
    expect(screen.queryByRole("link", { name: /Download pinned/ })).not.toBeInTheDocument();
    expect(getRpsPage).not.toHaveBeenCalled();
  });

  it("never lets a pending old page resurrect scores during a new approval-catalog check", async () => {
    const oldPage = deferred<RpsPage>(), current = deferred<RpsCatalog>();
    vi.mocked(getRpsReleases).mockResolvedValueOnce(catalog([{ ...release, total: 1 }])).mockReturnValueOnce(current.promise);
    vi.mocked(getRpsPage).mockReturnValue(oldPage.promise);
    render(<ResearchPriorityBoard />);
    await waitFor(() => expect(getRpsPage).toHaveBeenCalledOnce());
    const oldSignal = vi.mocked(getRpsPage).mock.calls[0][3];
    fireEvent.click(screen.getByRole("button", { name: "Refresh releases" }));
    expect(oldSignal?.aborted).toBe(true);
    await act(async () => { oldPage.resolve({ ...page, total: 1, release_total: 1, items: [row] }); });
    expect(screen.getByText("Loading a checked research release…")).toBeVisible();
    expect(screen.queryByText("4,400")).not.toBeInTheDocument();
    await act(async () => { current.reject(new Error("PRIVATE_PROVIDER_FAILURE")); });
    expect(screen.getByRole("alert")).toHaveTextContent("No legacy score has been substituted");
    expect(screen.queryByText(/PRIVATE_PROVIDER_FAILURE/)).not.toBeInTheDocument();
  });

  it("keeps late first-release scores out of a newer selected release", async () => {
    const first = { ...downloadableRelease(), total: 1 }, second = { ...first, id: "second-release", manifest_sha256: "8".repeat(64),
      public_bundle: { ...first.public_bundle, sha256: "9".repeat(64) } };
    const old = deferred<RpsPage>(), current = deferred<RpsPage>();
    vi.mocked(getRpsReleases).mockResolvedValue(catalog([first, second]));
    vi.mocked(getRpsPage).mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
    render(<ResearchPriorityBoard />);
    await waitFor(() => expect(getRpsPage).toHaveBeenCalledOnce());
    fireEvent.change(screen.getByRole("combobox"), { target: { value: second.id } });
    expect(vi.mocked(getRpsPage).mock.calls[0][3]?.aborted).toBe(true);
    await act(async () => { current.resolve({ ...page, release_id: second.id, manifest_sha256: second.manifest_sha256,
      total: 1, release_total: 1, items: [{ ...row, formula: "SECOND" }] }); });
    await act(async () => { old.resolve({ ...page, total: 1, release_total: 1, items: [row] }); });
    expect(screen.getByRole("button", { name: "SECOND · synthetic" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "TEST · synthetic" })).not.toBeInTheDocument();
    const url = new URL(screen.getByRole("link", { name: /Download pinned/ }).getAttribute("href")!);
    expect(url.pathname).toContain("second-release/bundle");
    expect(url.searchParams.get("manifest_sha256")).toBe(second.manifest_sha256);
  });

  it("does not display an old detail after a release refresh or retain scores on retry", async () => {
    const oldDetail = deferred<RpsDetail>();
    vi.mocked(getRpsReleases).mockResolvedValueOnce(catalog([{ ...release, total: 1 }])).mockRejectedValueOnce(new Error("503")).mockResolvedValueOnce(catalog());
    vi.mocked(getRpsPage).mockResolvedValue({ ...page, total: 1, release_total: 1, items: [row] });
    vi.mocked(getRpsDetail).mockReturnValue(oldDetail.promise);
    render(<ResearchPriorityBoard />);
    fireEvent.click(await screen.findByRole("button", { name: "TEST · synthetic" }));
    const signal = vi.mocked(getRpsDetail).mock.calls[0][2];
    fireEvent.click(screen.getByRole("button", { name: "Refresh releases" }));
    expect(signal?.aborted).toBe(true);
    await act(async () => { oldDetail.resolve(detail); });
    expect(await screen.findByRole("alert")).toHaveTextContent("No legacy score has been substituted");
    expect(screen.queryByText("Synthetic fixture source")).not.toBeInTheDocument();
    expect(screen.queryByText("4,400")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("No reviewed RPS release published yet")).toBeVisible();
  });
});

describe("closed RPS catalog and download wire contract", () => {
  it("accepts exactly the coherent four catalog outcomes and isolates the retained read snapshot", () => {
    const failed: RpsCatalog["unavailable"] = [{ id: "failed", status: "unavailable", reason_code: "verification_failed" }];
    for (const value of [catalog(), catalog([release]), catalog([release], failed), catalog([], failed)]) {
      expect(verifyRpsCatalog(value)).toEqual(value);
    }
    const input = catalog([downloadableRelease()]), retained = verifyRpsCatalog(input);
    input.items[0].public_bundle.sha256 = "0".repeat(64);
    expect(retained.items[0].public_bundle.sha256).toBe("7".repeat(64));
  });

  it.each([null, false, [], {}, { ...catalog(), schema_version: "rps-catalog/1.2" },
    { ...catalog(), status: ["not_published"] }, { ...catalog(), approval_sha256: true },
    { ...catalog(), catalog_revision: "F".repeat(64) }, { ...catalog(), catalog_revision: "short" },
    { ...catalog(), href: "https://attacker.invalid" }, { ...catalog(), unavailable: [{ id: "failed", status: "unavailable", reason_code: "raw_private_error" }] },
    { ...catalog(), items: [release, release] },
    { ...catalog([release]), unavailable: [{ id: release.id, status: "unavailable", reason_code: "verification_failed" }], status: "degraded" },
  ])("rejects malformed, duplicate or incompatible catalog %j", value => {
    expect(() => verifyRpsCatalog(value)).toThrow();
  });

  it.each(["published", "degraded", "unavailable"])("does not relabel empty success as %s", status => {
    expect(() => verifyRpsCatalog({ ...catalog(), status })).toThrow();
  });

  it.each([{ status: "available", sha256: null, verifier_version: "rps-public-verifier/1.0.0" },
    { status: "available", sha256: "7".repeat(64), verifier_version: "future-verifier" },
    { status: ["available"], sha256: "7".repeat(64), verifier_version: "rps-public-verifier/1.0.0" },
    { status: "unavailable", sha256: "7".repeat(64), verifier_version: null },
    { status: "not_published", sha256: null, verifier_version: "rps-public-verifier/1.0.0" },
    { ...downloadableRelease().public_bundle, href: "javascript:alert(1)" }])("rejects incoherent public bundle %j", public_bundle => {
    const bad = { ...downloadableRelease(), public_bundle };
    expect(() => verifyRpsCatalog({ ...catalog([release]), items: [bad] })).toThrow();
    expect(rpsBundleDownloadUrl(bad as RpsRelease)).toBeNull();
  });

  it.each([{ total: true }, { total: NaN }, { total: -1 }, { total: 10001 }, { id: "../other" }, { id: ".." }, { id: "." },
    { objective: {} }, { objective: "a".repeat(4001) }, { published_at: "2026-02-30T00:00:00Z" },
    { published_at: "2026-09-05T24:00:00Z" }, { published_at: "2026-09-05" }, { evidence_cutoff: "2027-01-01T00:00:00Z" },
    { published_at: "2026-09-05T00:00:00.000001Z", evidence_cutoff: "2026-09-05T00:00:00.000002Z" },
    { manifest_sha256: "A".repeat(64) }])("rejects unsafe or malformed release fields %j", patch => {
    expect(() => verifyRpsCatalog({ ...catalog([release]), items: [{ ...release, ...patch }] })).toThrow();
  });

  it("requires degraded status for failed bundle publication and for a failed release", () => {
    const input = catalog([{ ...release, public_bundle: { ...release.public_bundle, status: "unavailable" } }]);
    expect(verifyRpsCatalog(input).status).toBe("degraded");
    expect(() => verifyRpsCatalog({ ...input, status: "published" })).toThrow();
    const allFailed = catalog([], [{ id: "failed", status: "unavailable", reason_code: "verification_failed" }]);
    expect(() => verifyRpsCatalog({ ...allFailed, status: "not_published" })).toThrow();
  });

  it("enforces the configured-release catalog bound before accepting an oversized inventory", () => {
    expect(() => verifyRpsCatalog(catalog(Array.from({ length: 129 }, (_, index) => ({ ...release, id: `release-${index}` }))))).toThrow();
  });

  it("binds the page's campaign and cutoff to the selected catalog entry", () => {
    expect(() => verifyRpsPage({ ...page, campaign: { ...page.campaign, objective: "different" } }, release, 0)).toThrow();
    expect(() => verifyRpsPage({ ...page, evidence_cutoff: "2027-01-01T00:00:00Z" }, release, 0)).toThrow();
    expect(() => verifyRpsPage({ ...page, policy_hash: "invalid" }, release, 0)).toThrow();
  });

  it("encodes a release identifier without accepting a backend URL or extra query parameters", () => {
    const input = { ...downloadableRelease(), id: "release:2026-1" };
    const url = new URL(rpsBundleDownloadUrl(input)!);
    expect(url.pathname).toContain("/release%3A2026-1/bundle");
    expect([...url.searchParams.keys()]).toEqual(["manifest_sha256", "bundle_sha256"]);
    expect(rpsBundleDownloadUrl({ ...input, href: "https://attacker.invalid" } as RpsRelease)).toBeNull();
  });

  it("validates the real client response before returning and forwards cancellation without credentials", async () => {
    const actual = await vi.importActual<typeof import("@/lib/research-priority")>("@/lib/research-priority");
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(JSON.stringify(catalog()), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...catalog(), catalog_revision: false }), { status: 200 }));
    const controller = new AbortController();
    expect((await actual.getRpsReleases(controller.signal)).status).toBe("not_published");
    expect(fetch.mock.calls[0][1]).toMatchObject({ credentials: "omit", cache: "no-store" });
    expect(fetch.mock.calls[0][1]?.signal).toBeInstanceOf(AbortSignal);
    await expect(actual.getRpsReleases()).rejects.toThrow(/inconsistent/);
    fetch.mockRestore();
  });
});
