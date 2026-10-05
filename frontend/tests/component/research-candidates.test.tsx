import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { groupResearchCandidates, readCompleteCandidateRelease, ResearchCandidateBoard } from "@/components/ResearchCandidateBoard";
import { getRpsDetail, getRpsPage, getRpsReleases, type RpsCatalog, type RpsPage, type RpsRelease, type RpsRow } from "@/lib/research-priority";
import catalogCapture from "../fixtures/rps-catalog-http.json";
import pageCapture from "../fixtures/rps-page-http.json";

vi.mock("@/lib/research-priority", async importOriginal => ({
  ...await importOriginal<typeof import("@/lib/research-priority")>(),
  getRpsReleases: vi.fn(), getRpsPage: vi.fn(), getRpsDetail: vi.fn(),
}));

// The captured guarded HTTP shape and every derived row here are synthetic tests only.
const originalPage = pageCapture as RpsPage;
const originalRelease = catalogCapture.items.find(item => item.id === originalPage.release_id) as RpsRelease;
function makeRow(id: string, materialId: string, score: number | null = 4400, role = "new_candidate"): RpsRow {
  const row = structuredClone(originalPage.items[0]);
  return { ...row, id, material_id: materialId, state_id: `state:${id}`, action_id: `action:${id}`, formula: materialId,
    state_summary: `Test state ${id}`, action_summary: `Test action ${id}`, role,
    result: { ...row.result, score_display: score, eligibility: score === null ? "pending" : "eligible",
      rank_group: role === "mechanism_anchor" ? "mechanism" : "discovery" } };
}
function releaseFor(rows: RpsRow[], id = originalRelease.id): RpsRelease { return { ...originalRelease, id, total: rows.length }; }
function catalog(items: RpsRelease[] = []): RpsCatalog {
  return { ...structuredClone(catalogCapture) as RpsCatalog, items, unavailable: [], status: items.length ? "published" : "not_published" };
}
function pageFor(rows: RpsRow[], release = releaseFor(rows), offset = 0): RpsPage {
  return { ...originalPage, release_id: release.id, manifest_sha256: release.manifest_sha256, items: rows.slice(offset, offset + 24),
    total: rows.length, release_total: rows.length, offset, has_more: offset + 24 < rows.length };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(yes => { resolve = yes; });
  return { promise, resolve };
}
async function select(release: RpsRelease) {
  await screen.findByRole("option", { name: `${release.id} · ${release.campaign_id}` });
  fireEvent.change(screen.getByRole("combobox", { name: "Published release" }), { target: { value: release.id } });
}
describe("published research candidates", () => {
  beforeEach(() => vi.resetAllMocks());

  it("shows a truthful empty catalogue and never loads candidate data", async () => {
    vi.mocked(getRpsReleases).mockResolvedValue(catalog()); render(<ResearchCandidateBoard />);
    expect(await screen.findByText("No research candidate release published yet")).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Published release" })).toBeDisabled();
    expect(getRpsPage).not.toHaveBeenCalled();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("can render one compact empty line without disabled filters, while retaining distinct errors", async () => {
    vi.mocked(getRpsReleases).mockResolvedValueOnce(catalog());
    const view = render(<ResearchCandidateBoard compactEmpty />);
    expect(await screen.findByText("No published research-priority assessments. Structure proposals below remain unranked.")).toBeVisible();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument(); view.unmount();
    vi.mocked(getRpsReleases).mockRejectedValueOnce(new Error("503")); render(<ResearchCandidateBoard compactEmpty />);
    expect(await screen.findByRole("alert")).toHaveTextContent("not an empty release");
    expect(screen.queryByText(/Structure proposals below remain unranked/)).not.toBeInTheDocument();
  });

  it("requires explicit release selection and supports one material with one action", async () => {
    const release = originalRelease;
    vi.mocked(getRpsReleases).mockResolvedValue(catalog([release]));
    vi.mocked(getRpsPage).mockResolvedValue(originalPage);
    render(<ResearchCandidateBoard />);
    await screen.findByText("Choose a release to compare research candidates within one campaign.");
    expect(screen.getByRole("combobox", { name: "Published release" })).toHaveValue("");
    expect(getRpsPage).not.toHaveBeenCalled(); await select(release);
    expect(await screen.findByRole("button", { name: "TEST" })).toBeVisible();
    expect(getRpsPage).toHaveBeenCalledWith(release.id, 0, "all", expect.any(AbortSignal));
    expect(screen.getByRole("table").querySelectorAll("tbody > tr")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Download pinned public verification bundle" })).toHaveAttribute("href", expect.stringContaining(`manifest_sha256=${release.manifest_sha256}`));
  });

  it("groups by ID, keeps same-formula identities separate, sorts highest-action scores, and puts missing scores last", () => {
    const rows = [makeRow("a", "first", 4400), makeRow("b", "second", 7100), makeRow("c", "first", 7500), makeRow("d", "missing", null), makeRow("e", "tied", 7100)];
    rows[0].formula = rows[2].formula = rows[1].formula = "SAME";
    const unchanged = structuredClone(rows), grouped = groupResearchCandidates(rows, "discovery");
    expect(grouped.map(item => item.materialId)).toEqual(["first", "second", "tied", "missing"]);
    expect(grouped[0].primary).toMatchObject({ id: "c", state_id: "state:c", action_id: "action:c" });
    expect(grouped[0].actions.map(item => item.id)).toEqual(["c", "a"]);
    expect(rows).toEqual(unchanged);
  });

  it("keeps all actions and role-specific scores, expands locally and returns focus on Close", async () => {
    const rows = [makeRow("low", "Candidate", 4400), makeRow("high", "Candidate", 7100), makeRow("pending", "Pending", null), makeRow("mechanism", "Candidate", 9000, "mechanism_anchor"), makeRow("control", "Control", null, "reference_anchor")];
    const release = releaseFor(rows);
    vi.mocked(getRpsReleases).mockResolvedValue(catalog([release])); vi.mocked(getRpsPage).mockResolvedValue(pageFor(rows));
    render(<ResearchCandidateBoard />); await select(release);
    const trigger = await screen.findByRole("button", { name: "Candidate" });
    const main = screen.getByRole("table");
    expect(main.querySelectorAll("tbody > tr")).toHaveLength(2);
    expect(within(main).getByText("7,100")).toBeVisible();
    expect(within(main).getByText("Test state high")).toBeVisible();
    expect(within(main).queryByText("9,000")).not.toBeInTheDocument();
    fireEvent.click(trigger); expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByText("Test action low")).toBeVisible();
    expect(screen.getByText("4,400")).toBeVisible(); expect(getRpsDetail).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Close", exact: true })); expect(trigger).toHaveFocus();
    fireEvent.change(screen.getByRole("combobox", { name: "Research role" }), { target: { value: "mechanism" } });
    expect(screen.getByText("9,000")).toBeVisible(); expect(screen.queryByText("7,100")).not.toBeInTheDocument();
    expect(getRpsPage).toHaveBeenCalledTimes(1);
  });

  it("waits for every page before grouping alternatives, then uses the later-page action", async () => {
    const rows = Array.from({ length: 25 }, (_, i) => makeRow(`a${i}`, i === 24 ? "m0" : `m${i}`, i === 24 ? 8000 : 4400));
    const release = releaseFor(rows), later = deferred<RpsPage>();
    vi.mocked(getRpsReleases).mockResolvedValue(catalog([release]));
    vi.mocked(getRpsPage).mockResolvedValueOnce(pageFor(rows)).mockReturnValueOnce(later.promise);
    render(<ResearchCandidateBoard />); await select(release);
    await waitFor(() => expect(getRpsPage).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    await act(async () => later.resolve(pageFor(rows, release, 24)));
    const table = await screen.findByRole("table"); expect(table.querySelectorAll("tbody > tr")).toHaveLength(24);
    expect(within(table).getByText("8,000")).toBeVisible();
    expect(within(table).getByText("Test state a24")).toBeVisible();
  });

  it("discards a partial ranking if a later page changes policy or fails", async () => {
    const rows = Array.from({ length: 25 }, (_, i) => makeRow(`a${i}`, `m${i}`)), release = releaseFor(rows);
    vi.mocked(getRpsReleases).mockResolvedValue(catalog([release]));
    vi.mocked(getRpsPage).mockResolvedValueOnce(pageFor(rows)).mockResolvedValueOnce({ ...pageFor(rows, release, 24), policy_hash: "b".repeat(64) });
    render(<ResearchCandidateBoard />); await select(release);
    expect(await screen.findByRole("alert")).toHaveTextContent("partial candidate ranking is not shown");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("rejects repeated IDs, conflicting identities and missing pages without inventing values", async () => {
    const rows = [makeRow("a", "same"), makeRow("b", "same")], release = releaseFor(rows);
    vi.mocked(getRpsPage).mockResolvedValue({ ...pageFor(rows), items: [rows[0], rows[0]] });
    await expect(readCompleteCandidateRelease(release, new AbortController().signal)).rejects.toThrow(/Duplicate/);
    rows[1].family = "different"; vi.mocked(getRpsPage).mockResolvedValue(pageFor(rows));
    await expect(readCompleteCandidateRelease(release, new AbortController().signal)).rejects.toThrow(/identity/);
    vi.mocked(getRpsPage).mockResolvedValue({ ...pageFor(rows), items: [], has_more: true });
    await expect(readCompleteCandidateRelease(release, new AbortController().signal)).rejects.toThrow(/Incomplete/);
    await expect(readCompleteCandidateRelease({ ...release, total: 1001 }, new AbortController().signal)).rejects.toThrow(/size/);
  });

  it("does not merge a late response from an earlier selection and clears rows on refresh", async () => {
    const oldRows = [makeRow("old", "Old")], newRows = [makeRow("new", "New")];
    const oldRelease = releaseFor(oldRows, "old-release"), newRelease = releaseFor(newRows, "new-release"), pending = deferred<RpsPage>();
    vi.mocked(getRpsReleases).mockResolvedValue(catalog([oldRelease, newRelease]));
    vi.mocked(getRpsPage).mockReturnValueOnce(pending.promise).mockResolvedValueOnce(pageFor(newRows, newRelease));
    render(<ResearchCandidateBoard />); await select(oldRelease); await select(newRelease);
    expect(await screen.findByRole("button", { name: "New" })).toBeVisible();
    await act(async () => pending.resolve(pageFor(oldRows, oldRelease)));
    expect(screen.queryByRole("button", { name: "Old" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh releases" }));
    await screen.findByText("Choose a release to compare research candidates within one campaign.");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Published release" })).toHaveValue("");
  });

  it("distinguishes an unavailable publication service from an empty catalogue", async () => {
    vi.mocked(getRpsReleases).mockRejectedValue(new Error("503")); render(<ResearchCandidateBoard />);
    expect(await screen.findByRole("alert")).toHaveTextContent("not an empty release");
    expect(screen.queryByText("No research candidate release published yet")).not.toBeInTheDocument();
  });
});
