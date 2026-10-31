import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MaterialsVNext, MaterialsVNextResults } from "@/components/MaterialsVNext";
import MaterialDetailPage from "@/app/materials/[id]/page";
import { getMaterial, getMaterialsDataset, listAdmittedTcResults, PUBLIC_API_BASE } from "@/lib/api";
import { admittedTcLabel, type AdmittedTcPage, type AdmittedTcResult } from "@/lib/materials-vnext";

vi.mock("@/lib/api", async importOriginal => ({ ...await importOriginal<typeof import("@/lib/api")>(), listAdmittedTcResults: vi.fn(), getMaterial: vi.fn(), getMaterialsDataset: vi.fn() }));
const result = (overrides: Partial<AdmittedTcResult> = {}): AdmittedTcResult => ({
  id: "claim-1", material_id: "source:sample", formula: "FeSe", compositions: [{ formula: "FeSe", basis: "nominal" }],
  sample_label: "S1", sample_form: "thin film", substrate: "SrTiO3", value_kelvin: 23,
  value_lower_kelvin: null, value_upper_kelvin: null, value_relation: "exact",
  quantity: { raw: "23 K", unit: "K", approximate: false }, criterion: "onset", method: "resistivity",
  method_raw: null, measurement_context: "in zero field", pressure_regime: "unknown", pressure_gpa: null, pressure_raw: null,
  paper_id: "arxiv:2301.04984", paper_title: "Synthetic read-contract fixture", source_url: "https://arxiv.org/pdf/2301.04984v2",
  source_versions: ["v2"], evidence: [{ locator: "pdf_page:3", page: 3, quote_sha256: "a".repeat(64), field_paths: ["tc"] }],
  validity_status: "pending", review: { quality_status: "model_source_checked", per_record_checked: true, independent_expert_review: false, complete_paper: false },
  ...overrides,
});
const page = (items = [result()]): AdmittedTcPage => ({ items, total: items.length, paper_count: 1, material_count: 1, limit: 50, offset: 0, dataset: "materials-production90/1", count_scope: "Matching reported results" });
beforeEach(() => { vi.resetAllMocks(); vi.mocked(getMaterialsDataset).mockRejectedValue(new Error("not prepared")); });
afterEach(() => { cleanup(); vi.unstubAllEnvs(); });

it("retains equal Tc results with different samples and criteria, with English evidence and pressure labels", () => {
  render(<MaterialsVNextResults data={page([result(), result({ id: "claim-2", sample_label: "S2", criterion: "zero_resistance" })])} />);
  expect(screen.getAllByRole("row")).toHaveLength(3);
  expect(screen.getAllByRole("link", { name: "FeSe" })[0]).toHaveAttribute("href", "/materials/source%3Asample");
  expect(screen.getAllByText("23 K")).toHaveLength(4); // displayed value and preserved raw token per result
  expect(screen.getByText("Onset")).toBeInTheDocument();
  expect(screen.getByText("Zero resistance")).toBeInTheDocument();
  expect(screen.getByText("S2")).toBeInTheDocument();
  expect(screen.getAllByText("Pressure not reported")).toHaveLength(2);
  expect(screen.queryByText("Ambient pressure")).not.toBeInTheDocument();
  expect(screen.getAllByRole("link", { name: "Read source, page 3" })[0]).toHaveAttribute("href", "https://arxiv.org/pdf/2301.04984v2#page=3");
  expect(document.body).toHaveTextContent("Source version: v2");
  expect(document.body).toHaveTextContent("Independent domain review is pending");
  expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]/);
});

it.each([
  ["KNi$_2$S$_2$", 2],
  ["PrFeAsO$_{0.60}$F$_{0.12}$", 2],
  ["Bi$_2$Sr$_2$CuO$_{6+\\delta}$", 3],
])("renders reported TeX subscripts for %s while preserving the raw composition", (formula, subscripts) => {
  const data = page([result({ formula, compositions: [{ formula, basis: "unresolved" }] })]);
  const { container } = render(<MaterialsVNextResults data={data} />);
  const materialLink = container.querySelector('a[href="/materials/source%3Asample"]')!;
  expect(materialLink).toHaveAccessibleName(formula);
  expect(materialLink).not.toHaveTextContent(/[$_\\]/);
  expect(materialLink.querySelectorAll(".msupsub")).toHaveLength(subscripts);
  expect(materialLink.querySelector(".katex-error")).toBeNull();
  expect(screen.getByText(formula, { selector: "code" })).toBeInTheDocument();
  expect(data.items[0].formula).toBe(formula);
  expect(document.body).toHaveTextContent("Reported composition:");
});

it("uses the reported formula renderer in the material heading", async () => {
  vi.mocked(listAdmittedTcResults).mockResolvedValue(page([result({ formula: "KNi$_2$S$_2$" })]));
  render(await MaterialsVNext({ searchParams: {}, materialId: "source:sample" }));
  const heading = screen.getByRole("heading", { level: 1 });
  expect(heading).not.toHaveTextContent(/[$_]/);
  expect(heading.querySelectorAll(".msupsub")).toHaveLength(2);
});

it.each([
  ["unspecified", "R(Tc)=0.5 R(10 K)", "Criterion not classified"],
  ["midpoint", "R(Tc)=0.5 R(10 K)", "Midpoint"],
  ["unspecified", null, "Not specified"],
])("preserves the reported criterion with an English label for %s", (criterion, criterion_raw, label) => {
  render(<MaterialsVNextResults data={page([result({ criterion: criterion!, criterion_raw })])} />);
  expect(screen.getByText(label!)).toBeInTheDocument();
  if (criterion_raw) {
    expect(screen.getByText(criterion_raw)).toBeInTheDocument();
    expect(document.body).toHaveTextContent("Reported criterion:");
  } else {
    expect(document.body).not.toHaveTextContent("Reported criterion:");
  }
  expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]/);
});

it.each([
  ["lt", null, 0.5, "< 0.5 K"], ["le", null, 0.5, "≤ 0.5 K"],
  ["gt", 4, null, "> 4 K"], ["ge", 4, null, "≥ 4 K"], ["interval", 4, 6, "4–6 K"],
])("preserves the %s relation without inventing a midpoint", (relation, lower, upper, expected) => {
  expect(admittedTcLabel(result({ value_relation: relation as string, value_kelvin: null,
    value_lower_kelvin: lower as number | null, value_upper_kelvin: upper as number | null }))).toBe(expected);
});

it("does not label every result in a passing batch as individually checked", () => {
  render(<MaterialsVNextResults data={page([result({ review: { quality_status: "batch_sampled", per_record_checked: false, independent_expert_review: false, complete_paper: false } })])} />);
  expect(screen.getByText("Batch sample passed")).toBeInTheDocument();
  expect(screen.queryByText("Model source checked")).not.toBeInTheDocument();
  expect(document.body).toHaveTextContent("it has not been checked individually");
});

it("explains individual admission in English without claiming the original batch passed", async () => {
  vi.mocked(listAdmittedTcResults).mockResolvedValue(page([result({ review: {
    quality_status: "model_source_checked", per_record_checked: true,
    admission_route: "individual_source_check", batch_qualified: false,
    independent_expert_review: false, complete_paper: false,
  } })]));
  render(await MaterialsVNext({ searchParams: {} }));
  expect(document.body).toHaveTextContent("or an individual check against the original paper");
  expect(screen.getByText("Model source checked")).toBeInTheDocument();
  expect(screen.queryByText("Batch sample passed")).not.toBeInTheDocument();
  expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]/);
});

it.each([{ pressure: "ambient" }, { criterion: "made_up" }, { page: "-1" }, { page: "abc" }, { q: ["FeSe", "MgB2"] }, { ambient_sc: "true" }])("rejects invalid filters before fetching: %j", async searchParams => {
  render(await MaterialsVNext({ searchParams }));
  expect(screen.getByRole("alert")).toHaveTextContent("Invalid filters");
  expect(listAdmittedTcResults).not.toHaveBeenCalled();
});

it("passes valid filters to the canonical reader and preserves a preview base path", async () => {
  vi.stubEnv("NEXT_PUBLIC_BASE_PATH", "/preview");
  vi.mocked(listAdmittedTcResults).mockResolvedValue(page());
  render(await MaterialsVNext({ searchParams: { q: "FeSe", pressure: "unknown", criterion: "onset", page: "2" } }));
  expect(listAdmittedTcResults).toHaveBeenCalledWith({ q: "FeSe", pressure: "unknown", criterion: "onset", offset: 100, limit: 50 });
  expect(screen.getByRole("button", { name: "Apply filters" }).closest("form")).toHaveAttribute("action", "/preview/materials");
  expect(screen.getByRole("link", { name: "Previous" })).toHaveAttribute("href", "/materials?page=1&q=FeSe&pressure=unknown&criterion=onset");
});

it("renders an English empty state and a separate load failure", async () => {
  vi.mocked(listAdmittedTcResults).mockResolvedValue(page([]));
  render(await MaterialsVNext({ searchParams: {} }));
  expect(screen.getByRole("status")).toHaveTextContent("No reported results match these filters");
  cleanup();
  vi.mocked(listAdmittedTcResults).mockRejectedValue(new Error("unavailable"));
  render(await MaterialsVNext({ searchParams: {} }));
  expect(screen.getByRole("alert")).toHaveTextContent("Reported results could not be loaded");
});

it("resets form values with URL filters after a client-side Clear navigation", async () => {
  vi.mocked(listAdmittedTcResults).mockResolvedValue(page());
  const view = render(await MaterialsVNext({ searchParams: { pressure: "nonambient", q: "FeSe" } }));
  expect(screen.getByRole("textbox")).toHaveValue("FeSe");
  expect(screen.getByDisplayValue("Reported nonambient")).toHaveValue("nonambient");
  view.rerender(await MaterialsVNext({ searchParams: {} }));
  expect(screen.getByRole("textbox")).toHaveValue("");
  expect(screen.getByDisplayValue("All pressures")).toHaveValue("");
});

it("opens the real material detail route with canonical results and keeps filtering within that material", async () => {
  vi.stubEnv("MATERIALS_VNEXT_ENABLED", "true");
  vi.mocked(listAdmittedTcResults).mockResolvedValue({ ...page(), total: 60 });
  render(await MaterialDetailPage({ params: Promise.resolve({ id: "source%3Asample" }), searchParams: Promise.resolve({ criterion: "onset" }) }));
  expect(getMaterial).not.toHaveBeenCalled();
  expect(listAdmittedTcResults).toHaveBeenCalledWith({ material_id: "source:sample", q: "", pressure: "", criterion: "onset", offset: 0, limit: 50 });
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("FeSe");
  expect(screen.getByRole("link", { name: "Browse all materials" })).toHaveAttribute("href", "/materials");
  expect(screen.getByRole("link", { name: "Clear", exact: true })).toHaveAttribute("href", "/materials/source%3Asample");
  expect(screen.getByRole("link", { name: "Next", exact: true })).toHaveAttribute("href", "/materials/source%3Asample?page=1&criterion=onset");
  expect(screen.getByRole("button", { name: "Apply filters" }).closest("form")).toHaveAttribute("action", "/materials/source%3Asample");
  expect(getMaterialsDataset).not.toHaveBeenCalled();
});

it("offers versioned full dataset downloads with English scope and training guidance", async () => {
  vi.mocked(listAdmittedTcResults).mockResolvedValue(page());
  vi.mocked(getMaterialsDataset).mockResolvedValue({ version: "a".repeat(64), created_at: "2026-10-28T10:57:52Z", paper_count: 850,
    files: { results: { rows: 1739, columns: 43, sha256: "b".repeat(64) }, evidence: { rows: 5105, columns: 8, sha256: "c".repeat(64) }, training: { rows: 1680, columns: 28, sha256: "d".repeat(64) } },
    source_scope: "Selected source assertions; no complete-paper recall claim.",
    training_policy: "Primary experimental scalar Tc; no midpoint is imputed.",
    grouping_policy: "Use the supplied split; unseen-composition performance is not established.",
  });
  render(await MaterialsVNext({ searchParams: { q: "FeSe" } }));
  for (const [label, kind] of [["Results CSV", "results"], ["Evidence CSV", "evidence"], ["Training CSV", "training"]]) {
    expect(screen.getByRole("link", { name: label })).toHaveAttribute("href", `${PUBLIC_API_BASE}/materials/dataset/${"a".repeat(64)}/${kind}`);
  }
  expect(document.body).toHaveTextContent("1,739 results from 850 papers");
  expect(document.body).toHaveTextContent("Page filters do not change these downloads");
  expect(document.body).toHaveTextContent("Use only feature columns as model inputs");
  expect(document.body).toHaveTextContent("Oct 28, 2026");
  expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]/);
});

it("keeps result browsing available while a stale download snapshot is being refreshed", async () => {
  vi.mocked(listAdmittedTcResults).mockResolvedValue(page());
  render(await MaterialsVNext({ searchParams: {} }));
  expect(document.body).toHaveTextContent("Downloads will be available after the latest dataset update is prepared");
  expect(screen.queryByRole("link", { name: "Training CSV" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "FeSe" })).toBeInTheDocument();
});
