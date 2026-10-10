import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MaterialReports } from "@/components/MaterialReports";
import { getMaterialReports } from "@/lib/api";
import { curveGroup, reportQuantity, type MaterialReportPoint, type MaterialReports as Reports } from "@/lib/material-reports";

vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(), getMaterialReports: vi.fn() }));
beforeEach(() => vi.resetAllMocks());
afterEach(cleanup);
const q = { status: "parsed", relation: "exact", value: 240, lower: null, upper: null, unit: "K" };
const point = { point_id: "p1", work_id: null, paper_id: "arxiv:synthetic", title: "Synthetic source report", sample_label: "S1",
  sample_form: "powder", path_direction: "loading", series_id: "scan", tc_definition: "onset", tc: q,
  pressure: { ...q, value: 150, unit: "GPa" }, pressure_role: "measurement_pressure", source_locator: { page: 3 }, properties: [],
  knowledge_origin: "Observed", source_role: "primary", method: "resistivity", sc_outcome: "positive_reported" } as unknown as MaterialReportPoint;
const data = { version: "material-reports/3.0", material_id: "m", total_points: 1, offset: 0, limit: 50, has_more: false,
  report_groups: [{ group_id: "g", work_id: null, points: [point] }], support_counts: { source_ids: 1, verified_unique_works: 0 },
  scientific_acceptance: false } as Reports;

it("loads source evidence only on user expansion", async () => {
  vi.mocked(getMaterialReports).mockResolvedValue(data);
  render(<MaterialReports materialId="m" />);
  expect(getMaterialReports).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: /Papers and results/ }));
  expect(await screen.findByText("Synthetic source report")).toBeVisible();
  expect(screen.getByText("150 GPa")).toBeVisible();
  expect(screen.getByText("240 K")).toBeVisible();
  expect(screen.getByText(/Work identity unresolved/)).toBeVisible();
  expect(screen.getByRole("button", { name: /Papers and results/ })).toHaveAttribute("aria-expanded", "true");
});

it("keeps a negative outcome and minimum tested temperature without Tc=0", async () => {
  vi.mocked(getMaterialReports).mockResolvedValue({ ...data, report_groups: [{ ...data.report_groups[0], points: [{ ...point, sc_outcome: "not_detected", minimum_test_temperature: { ...q, value: 2 } }] }] });
  render(<MaterialReports materialId="m" initiallyOpen />);
  expect(await screen.findByText("Not detected")).toBeVisible();
  expect(screen.getByText("Minimum tested T: 2 K")).toBeVisible();
  expect(screen.queryByText("0 K")).toBeNull();
});

it("preserves multiple criteria in one source instead of averaging", async () => {
  vi.mocked(getMaterialReports).mockResolvedValue({ ...data, total_points: 2, report_groups: [{ ...data.report_groups[0], points: [point, { ...point, point_id: "p2", tc: { ...q, value: 232 }, tc_definition: "zero_resistance" }] }] });
  render(<MaterialReports materialId="m" initiallyOpen />);
  expect(await screen.findByText("232 K")).toBeVisible();
  expect(screen.getByText("240 K")).toBeVisible();
  expect(screen.getByText("zero resistance")).toBeVisible();
});

it("reports unavailable data and allows retry", async () => {
  vi.mocked(getMaterialReports).mockRejectedValueOnce(new Error("failure")).mockResolvedValueOnce(data);
  render(<MaterialReports materialId="m" initiallyOpen />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Source reports are unavailable");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText("Synthetic source report")).toBeVisible();
});

it("discards a response after the panel is collapsed", async () => {
  let resolve!: (v: Reports) => void;
  vi.mocked(getMaterialReports).mockImplementation(() => new Promise(r => { resolve = r; }));
  render(<MaterialReports materialId="m" initiallyOpen />);
  await waitFor(() => expect(getMaterialReports).toHaveBeenCalled());
  fireEvent.click(screen.getByRole("button", { name: /Papers and results/ }));
  resolve(data);
  expect(screen.queryByText("Synthetic source report")).toBeNull();
  expect(vi.mocked(getMaterialReports).mock.calls[0][2]?.aborted).toBe(true);
});

it("renders interval and bound quantities without midpoints", () => {
  expect(reportQuantity({ ...q, relation: "interval", value: null, lower: 80, upper: 95 })).toBe("80–95 K");
  expect(reportQuantity({ ...q, relation: "lt", value: null, upper: 2 })).toBe("< 2 K");
  expect(reportQuantity({ ...q, status: "unreported" })).toBe("Not reported");
  expect(reportQuantity({ ...q, status: "unresolved" })).toBe("Value needs review");
  expect(reportQuantity({ ...q, status: "extraction_failed" })).toBe("Extraction failed");
  expect(reportQuantity({ ...q, status: "source_unavailable" })).toBe("Source unavailable");
});

it("never joins unknown samples, different works or pressure paths in curves", () => {
  expect(curveGroup(point)).toBeNull();
  expect(curveGroup({ ...point, work_id: "w1" })).toBeNull();
  const known = { ...point, work_id: "w1", fixed_conditions_sha256: "verified-context-fixture" };
  expect(curveGroup(known)).not.toBeNull();
  expect(curveGroup(known)).not.toEqual(curveGroup({ ...known, path_direction: "unloading" }));
  expect(curveGroup(known)).not.toEqual(curveGroup({ ...known, work_id: "w2" }));
  expect(curveGroup(known)).not.toEqual(curveGroup({ ...known, source_role: "cited" }));
  expect(curveGroup(known)).not.toEqual(curveGroup({ ...known, replicate_label: "R2" }));
  expect(curveGroup(known)).not.toEqual(curveGroup({ ...known, fixed_conditions_sha256: "different-field" }));
  expect(curveGroup({ ...known, pressure_role: "unknown" })).toBeNull();
  expect(curveGroup(known)).not.toEqual(curveGroup({ ...known, pressure_role: "calculation_pressure" }));
});

it("labels calculation pressure and preserves synthesis pressure as a separate condition", async () => {
  vi.mocked(getMaterialReports).mockResolvedValue({ ...data, report_groups: [{ ...data.report_groups[0], points: [{
    ...point, knowledge_origin: "Computed", pressure_role: "calculation_pressure", pressure: { ...q, value: 170, unit: "GPa" },
    conditions: [
      { key: "calculation_pressure", status: "reported", quantity: { ...q, value: 170, unit: "GPa" } },
      { key: "synthesis_pressure", status: "reported", quantity: { ...q, value: 100, unit: "GPa" } },
    ],
  }] }] });
  render(<MaterialReports materialId="m" initiallyOpen />);
  expect(await screen.findByText("170 GPa")).toBeVisible();
  expect(screen.getByText("Calculation pressure")).toBeVisible();
  fireEvent.click(screen.getByText("Locator and properties"));
  expect(screen.getByText("synthesis pressure: 100 GPa")).toBeInTheDocument();
  expect(screen.queryByText("calculation pressure: 170 GPa")).toBeNull();
});

it("identifies private candidates and distinguishes explicit ambient pressure from missing pressure", async () => {
  const snapshot = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
  vi.mocked(getMaterialReports).mockResolvedValue({ ...data, total_points: 2, report_groups: [{ ...data.report_groups[0], points: [
    { ...point, pressure_semantics: "explicit_ambient", properties: [{ key: "pairing_symmetry", quantity: q, unit: "", value_raw: "reported d wave", knowledge_origin: "Computed", source_role: "cited" }] },
    { ...point, point_id: "p2", pressure: { ...q, status: "unreported" } },
  ] }] });
  render(<MaterialReports materialId="m" snapshotId={snapshot} initiallyOpen />);
  expect(await screen.findByText(/Candidate extraction preview/)).toBeVisible();
  expect(screen.getByText("Ambient (reported)")).toBeVisible();
  expect(screen.getByText("Not reported")).toBeVisible();
  expect(getMaterialReports).toHaveBeenCalledWith("m", 0, expect.any(AbortSignal), snapshot);
  const details = screen.getAllByText("Locator and properties")[0];
  fireEvent.click(details);
  expect(screen.getByText(/reported d wave/)).toBeInTheDocument();
  expect(screen.getByText(/Computed · cited/)).toBeInTheDocument();
});
