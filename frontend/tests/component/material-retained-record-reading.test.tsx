import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import MaterialDetailPage from "@/app/materials/[id]/page";
import { RetainedHc2, RetainedTcCriteria } from "@/components/RetainedRecordScientificFields";
import { retainedHc2, retainedRecordText, retainedTcCriteria } from "@/lib/material-retained-record";
import { getMaterial, getMaterialEnrichment, getMaterialHydrideParameters, type MaterialDetail } from "@/lib/api";
import { materialVisibility } from "../fixtures/material-visibility";

vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, getMaterial: vi.fn(), getMaterialEnrichment: vi.fn(), getMaterialHydrideParameters: vi.fn() };
});
vi.mock("@/components/BookmarkButton", () => ({ BookmarkButton: () => <span>Save control</span> }));
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(getMaterialEnrichment).mockImplementation(() => new Promise(() => {}));
  vi.mocked(getMaterialHydrideParameters).mockResolvedValue([]);
});
afterEach(cleanup);

describe("retained Tc and Hc2 field reading", () => {
  it("keeps coarse type and distinct criterion aliases beside one another", () => {
    const record = { tc_type: "onset", tc_definition: "diamagnetic", tc_criterion: "90% of normal-state resistivity", criterion: "Heat-capacity midpoint" };
    expect(retainedTcCriteria(record).map(item => item.key)).toEqual(["tc_type", "tc_definition", "tc_criterion", "criterion"]);
    render(<RetainedTcCriteria record={record} />);
    // All lexical fields are retained; the browser chooses no winning criterion.
    expect(document.body).toHaveTextContent("Retained Tc type: onset");
    expect(document.body).toHaveTextContent("Reported criterion: 90% of normal-state resistivity");
    expect(document.body).toHaveTextContent("Criterion alias: Heat-capacity midpoint");
    expect(screen.getAllByRole("definition")).toHaveLength(4);
  });

  it("does not infer a criterion from a method, selected result, or missing aliases", () => {
    render(<RetainedTcCriteria record={{ tc_type: "unknown", tc_criterion: null, measurement: "resistivity", tc_conditions: "onset in other window" }} />);
    expect(screen.getByText("Criterion not supplied")).toBeInTheDocument();
    expect(screen.queryByText("onset in other window")).not.toBeInTheDocument();
    expect(retainedRecordText({ toString: () => "onset" })).toBeNull();
    expect(retainedRecordText("zero\nresistance")).toBeNull();
    expect(retainedRecordText("x".repeat(501))).toBeNull();
  });

  it("preserves the Hc2 number without rounding and distinguishes the API field unit", () => {
    render(<RetainedHc2 record={{ hc2_tesla: 5.123456789, hc2_conditions: "fit at 5 K", hc2_direction: "ab" }} />);
    expect(screen.getByText("5.123456789 T")).toBeInTheDocument();
    const summary = screen.getByText("Hc2 field context", { selector: "summary" });
    expect(summary.closest("details")).not.toHaveAttribute("open");
    fireEvent.click(summary);
    expect(screen.getByText(/This field unit does not establish the source's printed unit/)).toBeInTheDocument();
    expect(screen.getByText("Source unit token not supplied.")).toBeInTheDocument();
    expect(screen.getByText("fit at 5 K")).toBeInTheDocument();
    expect(screen.getByText("ab")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("Hc2(0)");
    expect(document.body.textContent).not.toContain("direct measurement");
  });

  it("shows raw unit-qualified Hc2 as stored, without relabeling mT as T", () => {
    expect(retainedHc2({ hc2_tesla: 650, hc2_tesla_unit: "mT" })).toMatchObject({ value: "650", displayUnit: null, representation: "source_token" });
    render(<RetainedHc2 record={{ hc2_tesla: "6.50(2) mT", hc2_tesla_unit: "mT" }} />);
    expect(screen.getByText("6.50(2) mT")).toBeInTheDocument();
    expect(screen.queryByText("6.50(2) mT T")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Hc2 field context", { selector: "summary" }));
    expect(screen.getByText("Stored input unit:")).toBeInTheDocument();
    expect(screen.getByText("mT")).toBeInTheDocument();
    expect(retainedHc2({ hc2_tesla: 650, hc2_tesla_unit: "unknown" })?.displayUnit).toBeNull();
    expect(retainedHc2({ hc2_tesla: 650, hc2_tesla_unit: { value: "T" } })).toMatchObject({ displayUnit: null, unitMetadataUnresolved: true });
  });

  it("prefers preserved proposal input and refuses a forged normalized fallback", () => {
    const record = { hc2_tesla: 999, scientific_values: { hc2_tesla: { raw_value: "< 65 mT", raw_unit: "mT", value: 999, status: "parsed" } } };
    expect(retainedHc2(record)).toMatchObject({ value: "< 65 mT", displayUnit: null, representation: "source_token" });
    expect(retainedHc2({ hc2_tesla: 999, scientific_values: { hc2_tesla: { value: 999, status: "parsed" } } })).toBeNull();
    expect(retainedHc2({ hc2_tesla: Infinity })).toBeNull();
    expect(retainedHc2({ hc2_tesla: false })).toBeNull();
    expect(retainedHc2({ hc2_tesla: { value: 65 } })).toBeNull();
  });

  it("retains zero and does not borrow missing Hc2 context from Tc or a material headline", () => {
    const source = { hc2_tesla: 0, tc_conditions: "250 K crystallography", tc_type: "onset" };
    expect(retainedHc2(source)).toMatchObject({ value: "0", displayUnit: "T", context: [] });
    render(<RetainedHc2 record={source} />);
    fireEvent.click(screen.getByText("Hc2 field context", { selector: "summary" }));
    expect(screen.getByText("Hc2 conditions and direction not supplied.")).toBeInTheDocument();
    expect(screen.queryByText("250 K crystallography")).not.toBeInTheDocument();
  });

  it("reads per-row criteria and Hc2 in the real material detail table without merging equal Tc", async () => {
    const record = (overrides: Record<string, unknown>) => ({ tc_kelvin: 23, paper_id: "arxiv:0912.2752", measurement: "resistivity", visibility: materialVisibility(), ...overrides });
    const mat = { id: "synthetic", formula: "TEST", family: null, subfamily: null, visibility: materialVisibility(), records: [
      record({ tc_type: "onset", tc_criterion: "90% of normal-state resistivity", hc2_tesla: 65, hc2_conditions: "GL fit" }),
      record({ tc_type: "zero_resistance", hc2_tesla: 5.123456789 }),
    ], variants: [], disputed: false, retracted: false, total_papers: 1, arxiv_year: 2026, property_evidence: undefined, hc2_tesla: 999 } as unknown as MaterialDetail;
    vi.mocked(getMaterial).mockResolvedValue(mat);
    render(await MaterialDetailPage({ params: Promise.resolve({ id: mat.id }) }));
    const region = within(screen.getByRole("region", { name: "Scrollable retained evidence" }));
    expect(region.getAllByRole("row")).toHaveLength(3);
    expect(region.getByRole("columnheader", { name: "Retained Hc2" })).toBeInTheDocument();
    expect(region.getByText("onset")).toBeInTheDocument();
    expect(region.getByText("zero_resistance")).toBeInTheDocument();
    expect(region.getByText("90% of normal-state resistivity")).toBeInTheDocument();
    expect(region.getByText("65 T")).toBeInTheDocument();
    expect(region.getByText("5.123456789 T")).toBeInTheDocument();
    expect(region.queryByText("999 T")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]/);
  });

  it("preserves the existing restricted-record exclusion in the real detail table", async () => {
    const mat = { id: "synthetic", formula: "TEST", family: null, subfamily: null, visibility: materialVisibility(), records: [
      { tc_kelvin: 23, tc_type: "onset", hc2_tesla: 65, paper_id: "arxiv:0912.2752", visibility: materialVisibility() },
      { tc_kelvin: 23, tc_type: "restricted-criterion", hc2_tesla: 999, paper_id: "arxiv:restricted", visibility: materialVisibility("quarantined") },
    ], variants: [], disputed: false, retracted: false, total_papers: 1 } as unknown as MaterialDetail;
    vi.mocked(getMaterial).mockResolvedValue(mat);
    render(await MaterialDetailPage({ params: Promise.resolve({ id: mat.id }) }));
    const region = within(screen.getByRole("region", { name: "Scrollable retained evidence" }));
    expect(region.getAllByRole("row")).toHaveLength(2);
    expect(region.getByText("65 T")).toBeInTheDocument();
    expect(region.queryByText("restricted-criterion")).not.toBeInTheDocument();
    expect(region.queryByText("999 T")).not.toBeInTheDocument();
  });

  it("omits an entirely unavailable Hc2 column without borrowing a headline or restricted value", async () => {
    const mat = { id: "synthetic", formula: "TEST", family: null, subfamily: null, visibility: materialVisibility(), hc2_tesla: 999, records: [
      { tc_kelvin: 23, tc_type: "onset", paper_id: "arxiv:0912.2752", visibility: materialVisibility() },
      { tc_kelvin: 20, tc_type: "midpoint", hc2_tesla: 999, scientific_values: { hc2_tesla: { value: 999 } }, paper_id: "arxiv:0912.2752", visibility: materialVisibility() },
      { tc_kelvin: 23, hc2_tesla: 999, paper_id: "arxiv:restricted", visibility: materialVisibility("quarantined") },
    ], variants: [], disputed: false, retracted: false, total_papers: 1 } as unknown as MaterialDetail;
    vi.mocked(getMaterial).mockResolvedValue(mat);
    render(await MaterialDetailPage({ params: Promise.resolve({ id: mat.id }) }));
    const region = within(screen.getByRole("region", { name: "Scrollable retained evidence" }));
    expect(region.getAllByRole("row")).toHaveLength(3);
    expect(region.queryByRole("columnheader", { name: "Retained Hc2" })).not.toBeInTheDocument();
    expect(region.queryByText("Hc2 field context")).not.toBeInTheDocument();
    expect(region.getByText("onset")).toBeInTheDocument();
    expect(region.getByText("midpoint")).toBeInTheDocument();
    expect(region.queryByText("999 T")).not.toBeInTheDocument();
  });
});
