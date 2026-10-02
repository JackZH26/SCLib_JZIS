import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MaterialsPage from "@/app/materials/page";
import { MaterialTable } from "@/components/MaterialTable";
import { MaterialsFilters } from "@/components/MaterialsFilters";
import { listMaterials, type MaterialSummary, type MatchingScientificResult } from "@/lib/api";
import { materialFilterChips, materialRowTc, materialsHref, materialsParams } from "@/lib/materials-browser";
import { atomicItem, propertyEnvelope } from "../fixtures/property-evidence";
import { materialVisibility, sourceScopedMaterialVisibility } from "../fixtures/material-visibility";
import { materialAnomalyReview } from "../fixtures/scientific-anomalies";

vi.mock("@/lib/api", async importOriginal => ({ ...await importOriginal<typeof import("@/lib/api")>(), listMaterials: vi.fn() }));
function material(overrides: Partial<MaterialSummary> = {}): MaterialSummary {
  return { id: "synthetic", formula: "MgB2", family: "boride", tc_max: 9999, tc_ambient: 8888, arxiv_year: 1999, total_papers: 1, variant_count: 0, visibility: materialVisibility(), property_evidence: propertyEnvelope(atomicItem("tc_max", 39)), ...overrides } as MaterialSummary;
}
function matching(resultId: string, item?: ReturnType<typeof atomicItem>): MatchingScientificResult {
  return { result_id: resultId, record_index: 1, formula: "MgB2", family: "boride", tc_lower_bound_k: 23,
    pressure_semantics: { classifier_version: "pressure-policy/1.0.0", pressure_state: "reported", pressure_gpa: 140 }, result_classification: { knowledge_origin: "Observed" }, filter_policy_version: "scientific-filter/1.0.0", ...(item ? { tc_evidence: item } : {}) };
}

describe("Materials browser scientific state and density", () => {
  beforeEach(() => vi.resetAllMocks());

  it("shows seven useful columns and keeps normal policy/completeness notices out of rows", () => {
    const review = materialAnomalyReview();
    review.needs_review = false; review.counts = { no_findings: 1, review_required: 0, format_invalid: 0, total_records: 1 };
    render(<MaterialTable rows={[material({ anomaly_review: review })]} />);
    expect(screen.getAllByRole("columnheader").map(cell => cell.textContent)).toEqual(["Formula", "Family", "Reported Tc (K)", "Conditions", "Source year", "Sources", "Evidence status"]);
    expect(screen.queryByText("Operational policy: no findings")).not.toBeInTheDocument();
    expect(screen.queryByText(/Catalogue eligible/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\d\/6/)).not.toBeInTheDocument();
    expect(screen.getByText("Locator available")).toBeInTheDocument();
    expect(screen.queryByText("9999")).not.toBeInTheDocument();
    expect(screen.queryByText("1999")).not.toBeInTheDocument();
  });

  it("shows the matching Tc, pressure, criterion and year from B without borrowing catalogue result A", () => {
    const a = atomicItem("tc_max", 200, { result_id: "A", state: { pressure_semantics: { classifier_version: "pressure-policy/1.0.0", pressure_state: "reported", pressure_gpa: 300 } }, conditions: { tc_criterion: "A-calculated" }, source: { paper_id: "paper:A", year: 2026 } });
    const b = atomicItem("tc_max", 23, { result_id: "B", state: { pressure_semantics: { classifier_version: "pressure-policy/1.0.0", pressure_state: "reported", pressure_gpa: 140 } }, conditions: { tc_criterion: "Resistive onset" }, source: { paper_id: "paper:B", year: 2024, source_locator: { table: "1" } }, origin: { knowledge_origin: "Observed" } });
    render(<MaterialTable rows={[material({ family: "cuprate", property_evidence: propertyEnvelope(a), matching_results: [matching("B", b)] })]} resultFiltersActive />);
    const row = screen.getByRole("rowheader", { name: "MgB2" }).closest("tr")!;
    expect(row).toHaveTextContent("23 K"); expect(row).toHaveTextContent("140 GPa"); expect(row).toHaveTextContent("Resistive onset"); expect(row).toHaveTextContent("2024"); expect(row).toHaveTextContent("Matched result");
    expect(row).not.toHaveTextContent("200 K"); expect(row).not.toHaveTextContent("300 GPa"); expect(row).not.toHaveTextContent("A-calculated"); expect(row).not.toHaveTextContent("2026"); expect(row).not.toHaveTextContent("Cuprate"); expect(row).toHaveTextContent("boride");
    fireEvent.click(within(row).getByRole("button", { name: "Evidence for MgB2" }));
    const dialog = screen.getByRole("dialog", { name: "MgB2" });
    const displayed = within(dialog).getByRole("heading", { name: "Matched Tc result" }).closest("section")!;
    expect(displayed).toHaveTextContent("paper:B"); expect(displayed).not.toHaveTextContent("paper:A");
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows readable core evidence first while retaining raw criterion and technical context", () => {
    const tc = atomicItem("tc_max", 39, { conditions: { tc_criterion: "zero_resistance", measurement_method: "Four-probe resistivity" }, state: { pressure_semantics: { classifier_version: "pressure-policy/1.0.0", pressure_state: "explicit_ambient" } } });
    render(<MaterialTable rows={[material({ property_evidence: propertyEnvelope(tc) })]} />);
    expect(screen.getByRole("table")).toHaveTextContent("Zero resistance");
    expect(screen.getByRole("table")).not.toHaveTextContent("zero_resistance");
    fireEvent.click(screen.getByRole("button", { name: "Evidence for MgB2" }));
    const dialog = screen.getByRole("dialog", { name: "MgB2" });
    const core = within(dialog).getByLabelText("Displayed Tc source and conditions");
    expect(core).toHaveTextContent("Explicit ambient"); expect(core).toHaveTextContent("Four-probe resistivity"); expect(core).toHaveTextContent("Zero resistance");
    expect(within(core).getByRole("link", { name: "arxiv:synthetic-test" })).toHaveAttribute("href", "/paper/arxiv%3Asynthetic-test");
    const identity = within(dialog).getByText("Result identity and missing context").closest("details")!;
    expect(identity).not.toHaveAttribute("open"); fireEvent.click(within(identity).getByText("Result identity and missing context")); expect(identity).toHaveAttribute("open");
    expect(identity).toHaveTextContent("zero_resistance"); expect(identity).toHaveTextContent(tc.result_id);
  });
  it("keeps missing match context scoped to its record instead of declaring a paper omission or borrowing another result", () => {
    const a = atomicItem("tc_max", 39, { result_id: "A", conditions: { tc_criterion: "zero_resistance", measurement_method: "Four-probe resistivity" }, source: { paper_id: "paper:A", year: 2026 } });
    const b = atomicItem("tc_max", 23, { result_id: "B", conditions: {}, source: { paper_id: "paper:B" } });
    render(<MaterialTable rows={[material({ property_evidence: propertyEnvelope(a), matching_results: [matching("B", b)] })]} resultFiltersActive />);
    const row = screen.getByRole("rowheader", { name: "MgB2" }).closest("tr")!;
    expect(row).toHaveTextContent("Criterion not supplied"); expect(row).toHaveTextContent("Not supplied");
    expect(row).not.toHaveTextContent("Criterion not reported"); expect(row).not.toHaveTextContent("2026"); expect(row).not.toHaveTextContent("Zero resistance");
    fireEvent.click(within(row).getByRole("button", { name: "Evidence for MgB2" }));
    const core = screen.getByLabelText("Displayed Tc source and conditions");
    for (const label of ["Source year", "Tc criterion", "Method"]) {
      expect(within(core).getByText(label).nextElementSibling).toHaveTextContent(/^Not supplied in this record$/);
    }
    expect(core).toHaveTextContent("paper:B"); expect(core).not.toHaveTextContent("paper:A"); expect(core).not.toHaveTextContent("Four-probe resistivity");
  });
  it("never displays a matching lower bound as an exact Tc or falls back to an unrelated selected value", () => {
    const row = material({ matching_results: [matching("unlocated-B")] });
    const display = materialRowTc(row, true);
    expect(display.item).toBeNull(); expect(display.usesMatch).toBe(true);
    render(<MaterialTable rows={[row]} resultFiltersActive />);
    const table = screen.getByRole("table");
    expect(table).not.toHaveTextContent("23 K"); expect(table).not.toHaveTextContent("39 K"); expect(table).toHaveTextContent("Source unavailable");
  });

  it.each([
    ["interval", null, { relation: "interval", value: null, lower: 20, upper: 30, uncertainty: null, approximate: false }, "20–30 K", "Reported interval"],
    ["lower bound", null, { relation: "ge", value: null, lower: 23, upper: null, uncertainty: null, approximate: false }, "≥ 23 K", "Reported lower bound"],
    ["uncertainty", 23, { relation: "exact", value: 23, lower: null, upper: null, uncertainty: 0.2, approximate: true }, "≈ 23 ± 0.2 K", "Uncertainty reported"],
  ] as const)("retains a sourced matching %s without turning its filter bound into a point", (_kind, value, quantity, label, kindLabel) => {
    const tc = atomicItem("tc_max", value, { result_id: "B", quantity: { status: "parsed", errors: [], unit: "K", ...quantity }, warnings: value === null ? ["no_compatible_point_value"] : ["reported_uncertainty_not_exact_precision"] });
    const row = material({ matching_results: [matching("B", tc)] });
    expect(materialRowTc(row, true).item).toEqual(tc);
    render(<MaterialTable rows={[row]} resultFiltersActive />);
    const table = screen.getByRole("table"); expect(table).toHaveTextContent(label); expect(table).toHaveTextContent(kindLabel); expect(table).not.toHaveTextContent("Source unavailable"); expect(table).not.toHaveTextContent("39 K");
    fireEvent.click(screen.getByRole("button", { name: "Evidence for MgB2" }));
    const core = screen.getByLabelText("Displayed Tc source and conditions"); expect(core).toHaveTextContent(`${quantity.relation} / parsed`);
  });

  it("withholds positive Tc from a matching outcome-conflict candidate even when only family was filtered", () => {
    const tc = atomicItem("tc_max", 23, { result_id: "B", warnings: ["outcome_does_not_support_positive_tc"] });
    const row = material({ matching_results: [matching("B", tc)] });
    expect(materialRowTc(row, true).item).toBeNull();
    render(<MaterialTable rows={[row]} resultFiltersActive />);
    expect(screen.getByRole("table")).not.toHaveTextContent("23 K"); expect(screen.getByRole("table")).toHaveTextContent("Source unavailable");
  });
  it("rejects an enriched match whose identity or anomaly gate is inconsistent", () => {
    const differentId = atomicItem("tc_max", 23, { result_id: "wrong-result" });
    expect(materialRowTc(material({ matching_results: [matching("B", differentId)] }), true).item).toBeNull();
    const held = atomicItem("tc_max", 23, { result_id: "B" }); held.anomaly_review!.status = "review_required"; held.anomaly_review!.review_required_properties = ["tc_max"];
    expect(materialRowTc(material({ matching_results: [matching("B", held)] }), true).item).toBeNull();
  });

  it("keeps unavailable classification distinct from a negative finding in optional columns", () => {
    render(<MaterialTable rows={[material()]} />);
    fireEvent.click(screen.getByText("Scientific columns")); fireEvent.click(screen.getByLabelText("Competing order"));
    expect(screen.getByRole("columnheader", { name: "Competing order" })).toBeInTheDocument();
    const row = screen.getByRole("rowheader", { name: "MgB2" }).closest("tr")!;
    expect(row).toHaveTextContent("Unknown"); expect(row).not.toHaveTextContent("Reported false");
    fireEvent.click(screen.getByLabelText("Competing order")); expect(screen.queryByRole("columnheader", { name: "Competing order" })).not.toBeInTheDocument();
  });

  it("shows real review holds while restricted materials stay absent", () => {
    render(<MaterialTable rows={[material({ visibility: materialVisibility("pending"), anomaly_review: materialAnomalyReview() }), material({ id: "partial", formula: "NbN", visibility: sourceScopedMaterialVisibility() }), material({ id: "secret", formula: "SECRET", visibility: materialVisibility("quarantined") })]} />);
    expect(screen.getByText("Archive: review pending")).toBeInTheDocument(); expect(screen.getByText("Review required")).toBeInTheDocument(); expect(screen.queryByText("SECRET")).not.toBeInTheDocument();
    expect(screen.getByText("1 excluded record")).toHaveAttribute("title", expect.stringContaining("2 of 3 retained records")); expect(screen.queryByText("Eligible sources only")).not.toBeInTheDocument();
  });

  it("keeps the full formula in an accessible link", () => {
    const formula = "Tl0.7Bi0.2Sr1.8Ba0.2Ca1.9Cu3Ox";
    render(<MaterialTable rows={[material({ formula })]} />);
    expect(screen.getByRole("link", { name: formula })).toHaveAttribute("title", formula);
    expect(screen.getByRole("link", { name: formula })).not.toHaveClass("truncate");
  });
});

describe("Materials filters and URL compatibility", () => {
  beforeEach(() => vi.resetAllMocks());
  it("parses old observed-only URLs and rejects invalid page/size/numeric values", () => {
    expect(materialsParams({ family: "hydride,cuprate", tc_min: "20", pressure_max: "0", experimental_only: "true", page: "3", per_page: "100" })).toMatchObject({ family: "hydride,cuprate", tc_min: 20, pressure_max: 0, experimental_only: true, offset: 300, limit: 100 });
    expect(materialsParams({ tc_min: "NaN", pressure_max: "-1", page: "Infinity", per_page: "999", sort: "unsafe" })).toMatchObject({ tc_min: undefined, pressure_max: undefined, offset: 0, limit: 50, sort: "tc_max" });
  });
  it("does not broaden malformed scientific filters into an unfiltered query", async () => {
    render(await MaterialsPage({ searchParams: Promise.resolve({ tc_min: "NaN", pressure_max: "-1" }) }));
    expect(vi.mocked(listMaterials)).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Tc minimum must be a finite, nonnegative number");
    expect(screen.getByRole("alert")).toHaveTextContent("Pressure maximum must be a finite, nonnegative number");
  });
  it("preserves active filters in removal/paging URLs while resetting pagination", () => {
    const query = { family: "hydride", tc_min: "20", pressure_max: "2", experimental_only: "true", has_competing_order: "false", page: "9", per_page: "100" };
    const href = materialsHref(query, ["has_competing_order"]);
    expect(href).toBe("/materials?family=hydride&tc_min=20&pressure_max=2&experimental_only=true&per_page=100");
    expect(materialFilterChips(query)).toContainEqual({ key: "has_competing_order", label: "Competing order: Qualified false" });
  });
  it("removes the legacy observed-only flag when a user chooses computed results", () => {
    const { container } = render(<MaterialsFilters query={{ experimental_only: "true" }} pageSize={50} />);
    expect(screen.getByLabelText("Result origin")).toHaveValue("Observed"); expect(container.querySelector('input[name="experimental_only"]')).toHaveValue("true");
    fireEvent.change(screen.getByLabelText("Result origin"), { target: { value: "Computed" } });
    expect(container.querySelector('input[name="experimental_only"]')).toBeNull();
    expect(screen.getByLabelText("Result origin")).toHaveValue("Computed");
  });
  it("retains collapsed advanced controls in GET submission and marks active filters in English", () => {
    const { container } = render(<MaterialsFilters query={{ pairing_symmetry: "d-wave", has_competing_order: "false", min_tier: "T2", custom: "preserve-me", page: "5" }} pageSize={100} />);
    expect(screen.getByText("3 active")).toBeInTheDocument();
    const form = container.querySelector("form")!; const submitted = new FormData(form);
    expect(submitted.get("pairing_symmetry")).toBe("d-wave"); expect(submitted.get("has_competing_order")).toBe("false"); expect(submitted.get("min_tier")).toBe("T2"); expect(submitted.get("custom")).toBe("preserve-me"); expect(submitted.has("page")).toBe(false);
    expect(container.textContent).not.toMatch(/\p{Script=Han}/u);
  });
  it("requests same-result filters and keeps short intro and pagination filters", async () => {
    vi.mocked(listMaterials).mockResolvedValue({ total: 105, results: [material()], limit: 50, offset: 0, sort_basis: "current_projected_catalogue" });
    render(await MaterialsPage({ searchParams: Promise.resolve({ family: "hydride", tc_min: "20", pressure_max: "2", knowledge_origin: "Computed", has_competing_order: "false", page: "0" }) }));
    expect(vi.mocked(listMaterials)).toHaveBeenCalledWith(expect.objectContaining({ family: "hydride", tc_min: 20, pressure_max: 2, knowledge_origin: "Computed", has_competing_order: false }));
    expect(screen.getByText("Explore reported superconducting properties, measurement conditions, and their sources.").textContent!.split(/\s+/).length).toBeLessThanOrEqual(20);
    const pagination = screen.getByRole("navigation", { name: "Pagination" });
    expect(within(pagination).getByRole("link", { name: "51-100" }).getAttribute("href")).toContain("knowledge_origin=Computed");
    expect(within(pagination).getByRole("link", { name: "51-100" }).getAttribute("href")).toContain("has_competing_order=false");
  });
});
