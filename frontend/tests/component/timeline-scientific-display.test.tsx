import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TcTimeline } from "@/components/TcTimeline";
import { formulaToHtml } from "@/components/FormulaDisplay";
import { clusterTimelinePoints, escapePlotlyHtml, formatTimelineTc, timelineRenderBudget } from "@/lib/timeline-display";
import type { TimelinePoint, TimelineRecordSummary, TimelineSampling } from "@/lib/api";
import { materialVisibility } from "../fixtures/material-visibility";

vi.mock("next/dynamic", () => ({ default: () => function TestPlot({ data, layout }: { data: unknown; layout: unknown }) { return <pre aria-label="Timeline traces">{JSON.stringify({ data, layout })}</pre>; } }));

function point(id = "a", patch: Partial<TimelinePoint> = {}): TimelinePoint {
  return { point_id: `point:${id}`, material_id: `material:${id}`, material: `TEST-${id}`, family: "elemental", tc_kelvin: 0.03, year: 2026, pressure_gpa: null, paper_id: `doi:${id}`, is_theoretical: false, knowledge_origin: "Observed", classification_status: "resolved", source_role: "primary", classifier_version: "result-classifier/1.0.0", visibility: materialVisibility(), result_metadata: { result_id: `result:${id}`, result_revision: "r1", identity_basis: "legacy_occurrence_digest", year_basis: "legacy_record_year_unspecified", source_date: "2026-08-31", source_date_basis: "publication_date", tc_criterion: "zero_resistance", state: { sample_id: id }, source_locator: { figure: "2a" }, occurrence_count: 1, review_status: "legacy_unreviewed" }, ...patch };
}

const sampling: TimelineSampling = { policy_version: "timeline-sampling/1.0.0", method: "deterministic_stratified", requested_max_points: 10, total_points: 120, selected_points: 10, returned_points: 1, is_sampled: true, strata_total: 12, strata_represented: 10, rare_groups_omitted: 2, display_only: true };
const summary: TimelineRecordSummary = { scope: "full_filtered_unsampled", total_points: 120, total_materials: 45, source_count: 30, max_tc_kelvin: 200, min_tc_kelvin: 0.002, by_family: { elemental: 120 }, by_origin: { Observed: 120 }, by_year_basis: { legacy_record_year_unspecified: 120 }, by_pressure_state: { unknown: 120 }, record_candidates: [] };

describe("scientific Timeline display helpers", () => {
  it("preserves 0.03 K and sub-mK values rather than rounding them to zero", () => {
    expect(formatTimelineTc(0.03)).toBe("0.03 K (30 mK)");
    expect(formatTimelineTc(0.000001)).toBe("0.000001 K (0.001 mK)");
  });
  it("does not collapse nearby values into display buckets", () => {
    expect(clusterTimelinePoints([point("a"), point("b", { tc_kelvin: 0.031 })])).toHaveLength(2);
  });
  it("exact overlaps preserve different sources, states, criteria, and duplicated inputs", () => {
    const members = [point("b"), point("a"), point("a")];
    const [cluster] = clusterTimelinePoints(members);
    expect(cluster.members).toHaveLength(3);
    expect(cluster.sourceCount).toBe(2);
    expect(cluster.members.map(member => member.paper_id)).toEqual(["doi:a", "doi:a", "doi:b"]);
    expect(cluster.members[0].result_metadata?.state).toEqual({ sample_id: "a" });
  });
  it("cluster/member and render-budget selection is permutation invariant", () => {
    const points = [point("b"), point("a"), point("c", { year: 2025 }), point("d", { tc_kelvin: 10 })];
    const first = clusterTimelinePoints(points);
    const reversed = clusterTimelinePoints([...points].reverse());
    expect(first).toEqual(reversed);
    expect(timelineRenderBudget(first, "svg", 2)).toEqual(timelineRenderBudget(reversed, "svg", 2));
    expect(timelineRenderBudget(first, "webgl", 2)).toHaveLength(3);
  });
  it("escapes source HTML for Plotly and formula subscripts", () => {
    expect(escapePlotlyHtml('<img src=x onerror="bad">')).toBe("&lt;img src=x onerror=&quot;bad&quot;&gt;");
    expect(formulaToHtml("H2<script>x</script>")).toBe("H<sub>2</sub>&lt;script&gt;x&lt;/script&gt;");
  });
  it("does not interpret an unversioned origin flag as an observation", () => {
    expect(clusterTimelinePoints([point("a", { classifier_version: undefined })])[0].origin).toBe("Unknown / conflict");
  });
});

describe("Reported Tc Timeline accessible UI", () => {
  beforeEach(() => { vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null); });
  afterEach(() => { vi.restoreAllMocks(); window.history.replaceState(null, "", "/"); });

  it("offers every overlapping result through a keyboard-accessible selector", () => {
    render(<TcTimeline points={[point("b"), point("a"), point("c", { tc_kelvin: 10 })]} coverage={null} />);
    fireEvent.change(screen.getByLabelText("Overlap group"), { target: { value: "[2026,0.03]" } });
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).getByText("doi:a")).toBeInTheDocument();
    expect(within(table).getByText("doi:b")).toBeInTheDocument();
    expect(within(table).queryByText("doi:c")).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: /2 results · 2 linked sources/ })).toBeInTheDocument();
    expect(screen.getByText(/cluster counts refer to this received selection/)).toBeInTheDocument();
    expect(screen.getByLabelText("Timeline traces")).toHaveTextContent("2 received results");
  });
  it("paginates all received records, including all members of a large overlap", () => {
    render(<TcTimeline points={Array.from({ length: 26 }, (_, index) => point(String(index).padStart(2, "0")))} coverage={null} />);
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(26);
    fireEvent.click(screen.getByRole("button", { name: "Next results" }));
    expect(within(table).getAllByRole("row")).toHaveLength(2);
    expect(within(table).getByText("doi:25")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next results" })).toBeDisabled();
  });
  it("opens an anchor's table page, with real material and source links", () => {
    window.history.replaceState(null, "", "/timeline#timeline-result-point%3A25");
    render(<TcTimeline points={Array.from({ length: 26 }, (_, index) => point(String(index).padStart(2, "0")))} coverage={null} />);
    expect(screen.getByRole("link", { name: "doi:25" })).toHaveAttribute("href", "/paper/doi%3A25");
    expect(screen.getByRole("link", { name: "TEST-25" })).toHaveAttribute("href", "/materials/material%3A25");
    expect(screen.getByRole("link", { name: "Link to result result:25" })).toHaveAttribute("href", "#timeline-result-point%3A25");
  });
  it("shows all chronology, state, criterion and review caveats without inventing approval", () => {
    const input = point();
    input.result_metadata = { ...input.result_metadata, identity_conflict: true, identity_warnings: ["conflicting_occurrences"], chronology_warnings: ["year_date_conflict"] };
    render(<TcTimeline points={[input]} coverage={null} />);
    expect(screen.getByText("legacy record year unspecified")).toBeInTheDocument();
    expect(screen.getByText(/Source date: 2026-08-31/)).toBeInTheDocument();
    expect(screen.getByText(/Criterion: zero_resistance/)).toBeInTheDocument();
    expect(screen.getByText(/Identity warning: conflicting occurrences/)).toBeInTheDocument();
    expect(screen.getByText(/Chronology warning: year date conflict/)).toBeInTheDocument();
    expect(screen.getByText(/Legacy result · unreviewed/)).toBeInTheDocument();
    expect(screen.getByText(/"sample_id": "a"/)).toBeInTheDocument();
  });
  it("shows server sampling limits and server unsampled extrema separately", () => {
    render(<TcTimeline points={[point()]} coverage={null} sampling={sampling} recordSummary={summary} />);
    const full = screen.getByLabelText("Full filtered unsampled summary");
    expect(full).toHaveTextContent("120 reported results · 45 materials · 30 linked sources");
    expect(full).toHaveTextContent("0.002 K (2 mK) – 200 K");
    expect(screen.getByText(/1 returned results from 120/)).toBeInTheDocument();
    expect(screen.getByText(/omitted rare groups: 2/)).toBeInTheDocument();
    expect(screen.getByText(/not a statistically representative sample/)).toBeInTheDocument();
  });
  it("does not compute an unsampled summary from the returned sample", () => {
    render(<TcTimeline points={[point()]} coverage={null} />);
    expect(screen.getByText(/Full filtered, unsampled summary unavailable/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Full filtered unsampled summary")).not.toBeInTheDocument();
  });
  it("withholds an incompatible summary containing a quarantined record candidate", () => {
    render(<TcTimeline points={[point()]} coverage={null} sampling={sampling} recordSummary={{ ...summary, record_candidates: [point("restricted", { visibility: materialVisibility("quarantined") })] }} />);
    expect(screen.queryByLabelText("Full filtered unsampled summary")).not.toBeInTheDocument();
    expect(screen.queryByText(/doi:restricted/)).not.toBeInTheDocument();
    expect(screen.getByText(/Full filtered, unsampled summary unavailable/)).toBeInTheDocument();
  });
  it("discloses the SVG render budget and retains all 3,001 records in table navigation", () => {
    render(<TcTimeline points={Array.from({ length: 3001 }, (_, index) => point(String(index), { tc_kelvin: index + 1 }))} coverage={null} />);
    expect(screen.getByText(/showing the first 3,000 of 3,001 coordinate clusters/)).toBeInTheDocument();
    expect(screen.getByText(/All 3,001 received results are available here/)).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 121")).toBeInTheDocument();
  });
  it("keeps low-T values exact and provides logarithmic and low-temperature views", () => {
    render(<TcTimeline points={[point()]} coverage={null} />);
    expect(within(screen.getByRole("table")).getByText("0.03 K (30 mK)")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Temperature view"), { target: { value: "log" } });
    expect(screen.getByLabelText("Timeline traces")).toHaveTextContent('"type":"log"');
    fireEvent.change(screen.getByLabelText("Temperature view"), { target: { value: "low" } });
    expect(screen.getByText(/chart is zoomed to 0–1 K/)).toBeInTheDocument();
    expect(screen.getByLabelText("Timeline traces")).toHaveTextContent('"range":[0,1]');
  });
  it("escapes malicious source strings in Plotly traces and uses non-color origin symbols", () => {
    render(<TcTimeline points={[point("a", { material: "<script>unsafe</script>", paper_id: "doi:<b>unsafe</b>" }), point("b", { tc_kelvin: 10, knowledge_origin: "Computed" })]} coverage={null} />);
    const plot = screen.getByLabelText("Timeline traces");
    expect(plot).toHaveTextContent("&lt;script&gt;unsafe&lt;/script&gt;");
    expect(plot).not.toHaveTextContent("<script>unsafe</script>");
    expect(plot).toHaveTextContent('"circle-open"');
    expect(screen.getByLabelText("Result origin symbol legend")).toHaveTextContent("● Observed");
  });
});
