import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MaterialsPage from "@/app/materials/page";
import { MaterialsFilters } from "@/components/MaterialsFilters";
import { listMaterials, type MaterialSummary, type MatchingScientificResult } from "@/lib/api";
import { materialFilterChips, materialResultFiltersActive, materialRowTc, materialsHref, materialsParams, materialsQueryErrors } from "@/lib/materials-browser";
import { atomicItem, propertyEnvelope } from "../fixtures/property-evidence";
import { materialVisibility } from "../fixtures/material-visibility";

// These synthetic responses exercise presentation and request admission only.
// They do not prove database formula matching or physical sample identity.
vi.mock("@/lib/api", async importOriginal => ({ ...await importOriginal<typeof import("@/lib/api")>(), listMaterials: vi.fn() }));

function materialWithAlternative(): MaterialSummary {
  const selected = atomicItem("tc_max", 39, { result_id: "selected-A", source: { paper_id: "paper:A", year: 2020 }, conditions: { tc_criterion: "onset" } });
  const alternative = atomicItem("tc_max", 23, { result_id: "matched-B", source: { paper_id: "paper:B", year: 2024 }, conditions: { tc_criterion: "zero_resistance" }, state: { pressure_semantics: { classifier_version: "pressure-policy/1.0.0", pressure_state: "reported", pressure_gpa: 140 } } });
  const match: MatchingScientificResult = {
    result_id: "matched-B", record_index: 1, formula: "NbN", family: "conventional", tc_lower_bound_k: 23,
    pressure_semantics: { classifier_version: "pressure-policy/1.0.0", pressure_state: "reported", pressure_gpa: 140 },
    result_classification: { knowledge_origin: "Computed" }, filter_policy_version: "scientific-filter/1.0.0", tc_evidence: alternative,
  };
  return {
    id: "synthetic-formula-lookup", formula: "NbN", family: "conventional", tc_max: 9999,
    arxiv_year: 1999, total_papers: 2, variant_count: 0, visibility: materialVisibility(),
    property_evidence: propertyEnvelope(selected), matching_results: [match],
  } as MaterialSummary;
}

describe("Materials formula lookup and retained scientific state", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(listMaterials).mockResolvedValue({ total: 0, results: [], limit: 50, offset: 0, sort_basis: "current_projected_catalogue" });
  });

  it("submits one formula field with existing filters through the same GET form", () => {
    const { container } = render(<MaterialsFilters query={{ q: "NbN", family: "conventional,hydride", tc_min: "20", pressure_max: "150", knowledge_origin: "Computed", page: "9", custom: "preserved" }} pageSize={100} />);
    const input = screen.getByLabelText("Formula contains");
    expect(input).toHaveAttribute("name", "q");
    expect(input).toHaveAttribute("type", "search");
    expect(input).toHaveAttribute("placeholder", "e.g. NbN or BiTeCl");
    expect(input).toHaveAttribute("maxlength", "400");
    expect(input).toHaveValue("NbN");
    expect(container.querySelectorAll("form")).toHaveLength(1);
    const form = input.closest("form")!;
    expect(form).toHaveAttribute("method", "get");
    expect(form).toHaveAttribute("action", "/materials");
    expect(container.querySelectorAll('[name="q"]')).toHaveLength(1);
    expect(form.querySelector('input[type="hidden"][name="q"]')).toBeNull();
    const submitted = new FormData(form);
    expect(submitted.getAll("q")).toEqual(["NbN"]);
    expect(submitted.get("family")).toBe("conventional,hydride");
    expect(submitted.get("tc_min")).toBe("20");
    expect(submitted.get("pressure_max")).toBe("150");
    expect(submitted.get("knowledge_origin")).toBe("Computed");
    expect(submitted.get("per_page")).toBe("100");
    expect(submitted.get("custom")).toBe("preserved");
    expect(submitted.has("page")).toBe(false);
    expect(screen.getByRole("link", { name: "Clear filters" })).toHaveAttribute("href", "/materials");
  });

  it("normalizes query typography without losing composition punctuation or scientific filters", () => {
    const params = materialsParams({ q: "  Ｂｉ₂Ｔｅ₃_%&+  ", family: "conventional", tc_min: "20", pressure_max: "150", knowledge_origin: "Observed", page: "2", per_page: "100" });
    expect(params).toMatchObject({ q: "Bi2Te3_%&+", family: "conventional", tc_min: 20, pressure_max: 150, knowledge_origin: "Observed", experimental_only: true, offset: 200, limit: 100 });
    expect(materialsParams({ q: " FeSe1-xSx " }).q).toBe("FeSe1-xSx");
    expect(materialsParams({ q: " \u00a0 " }).q).toBeUndefined();
  });

  it.each(["\uFEFF", "\uFEFFNbN", "NbN\uFEFF"])("preserves literal U+FEFF instead of silently broadening the query", async q => {
    expect(materialsQueryErrors({ q })).toEqual([]);
    expect(materialsParams({ q }).q).toBe(q);
    expect(materialFilterChips({ q })).toEqual([{ key: "q", label: `Formula: ${q}` }]);
    render(await MaterialsPage({ searchParams: Promise.resolve({ q }) }));
    expect(vi.mocked(listMaterials)).toHaveBeenCalledWith(expect.objectContaining({ q }));
  });

  it.each([
    { q: ["NbN", "CrB2"], family: "conventional", tc_min: "20" },
    { q: "NbN", tc_min: ["20", "200"] },
  ])("blocks repeated filter values while retaining a removable form state", async raw => {
    render(await MaterialsPage({ searchParams: Promise.resolve(raw) }));
    expect(vi.mocked(listMaterials)).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Each material filter must have one value");
    expect(screen.getByLabelText("Formula contains")).toHaveValue("NbN");
    expect(screen.getByRole("link", { name: "Clear filters" })).toHaveAttribute("href", "/materials");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it.each(["true", "false"])("shows a literal formula chip instead of a boolean classification", q => {
    expect(materialFilterChips({ q })).toEqual([{ key: "q", label: `Formula: ${q}` }]);
    expect(materialsParams({ q }).q).toBe(q);
  });

  it("removes only the formula chip and resets paging while preserving other constraints", () => {
    const query = { q: "NbN", family: "conventional", tc_min: "20", pressure_max: "150", knowledge_origin: "Observed", experimental_only: "true", page: "9", per_page: "100", sort: "tc_max" };
    const chip = materialFilterChips(query).find(item => item.key === "q");
    expect(chip).toEqual({ key: "q", label: "Formula: NbN" });
    render(<MaterialsFilters query={query} pageSize={100} />);
    const removed = new URL(screen.getByRole("link", { name: "Remove Formula: NbN" }).getAttribute("href")!, "http://synthetic.test");
    expect(removed.pathname).toBe("/materials");
    expect(removed.searchParams.has("q")).toBe(false);
    expect(removed.searchParams.has("page")).toBe(false);
    expect(removed.searchParams.get("family")).toBe("conventional");
    expect(removed.searchParams.get("tc_min")).toBe("20");
    expect(removed.searchParams.get("pressure_max")).toBe("150");
    expect(removed.searchParams.get("knowledge_origin")).toBe("Observed");
    expect(removed.searchParams.get("experimental_only")).toBe("true");
    expect(removed.searchParams.get("per_page")).toBe("100");
    const retained = new URL(materialsHref(query, ["pressure_max"]), "http://synthetic.test");
    expect(retained.searchParams.get("q")).toBe("NbN");
    expect(retained.searchParams.has("page")).toBe(false);
  });

  it("passes the normalized formula to the Page API call and retains it during pagination", async () => {
    vi.mocked(listMaterials).mockResolvedValue({ total: 105, results: [materialWithAlternative()], limit: 50, offset: 0, sort_basis: "current_projected_catalogue" });
    render(await MaterialsPage({ searchParams: Promise.resolve({ q: " ＮｂＮ ", family: "conventional", tc_min: "20", pressure_max: "150", knowledge_origin: "Computed" }) }));
    expect(vi.mocked(listMaterials)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(listMaterials)).toHaveBeenCalledWith(expect.objectContaining({ q: "NbN", family: "conventional", tc_min: 20, pressure_max: 150, knowledge_origin: "Computed" }));
    const next = new URL(within(screen.getByRole("navigation", { name: "Pagination" })).getByRole("link", { name: "51-100" }).getAttribute("href")!, "http://synthetic.test");
    expect(next.searchParams.get("q")?.normalize("NFKC").trim()).toBe("NbN");
    expect(next.searchParams.get("family")).toBe("conventional");
    expect(next.searchParams.get("tc_min")).toBe("20");
    expect(next.searchParams.get("pressure_max")).toBe("150");
    expect(next.searchParams.get("knowledge_origin")).toBe("Computed");
  });

  it("keeps a formula-only query from selecting another Tc result", async () => {
    const row = materialWithAlternative();
    expect(materialResultFiltersActive({ q: "NbN" })).toBe(false);
    expect(materialRowTc(row, materialResultFiltersActive({ q: "NbN" })).item?.result_id).toBe("selected-A");
    expect(materialResultFiltersActive({ q: "NbN", tc_min: "20" })).toBe(true);
    vi.mocked(listMaterials).mockResolvedValue({ total: 1, results: [row], limit: 50, offset: 0 });
    render(await MaterialsPage({ searchParams: Promise.resolve({ q: "NbN" }) }));
    const rendered = screen.getByRole("rowheader", { name: "NbN" }).closest("tr")!;
    expect(rendered).toHaveTextContent("39 K");
    expect(rendered).toHaveTextContent("2020");
    expect(rendered).not.toHaveTextContent("23 K");
    expect(rendered).not.toHaveTextContent("140 GPa");
    expect(rendered).not.toHaveTextContent("2024");
    expect(rendered).not.toHaveTextContent("Matched result");
  });

  it.each([
    ["embedded C0", "Nb\u0000N"],
    ["trimmed C0", "\tNbN\t"],
    ["DEL", "Nb\u007fN"],
    ["C1", "Nb\u0085N"],
    ["raw overlength despite trimming", " ".repeat(200) + "NbN"],
    ["raw codepoint overlength", "🧪".repeat(201)],
    ["normalized codepoint overlength", "ﬃ".repeat(67)],
    ["normalized overlength despite trimming", " ".repeat(66) + "ﬃ".repeat(45)],
  ])("blocks %s query before any Page API request", async (_label, q) => {
    expect(materialsQueryErrors({ q })).not.toEqual([]);
    render(await MaterialsPage({ searchParams: Promise.resolve({ q, family: "conventional", tc_min: "20" }) }));
    expect(vi.mocked(listMaterials)).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/Formula/i);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it.each([
    ["200 non-BMP codepoints", "🧪".repeat(200), "🧪".repeat(200)],
    ["200 normalized codepoints", "ﬃ".repeat(66) + "Nb", "ffi".repeat(66) + "Nb"],
  ])("accepts %s rather than applying a UTF-16 length limit", async (_label, q, expected) => {
    expect(materialsQueryErrors({ q })).toEqual([]);
    render(await MaterialsPage({ searchParams: Promise.resolve({ q }) }));
    expect(vi.mocked(listMaterials)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(listMaterials)).toHaveBeenCalledWith(expect.objectContaining({ q: expected }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
