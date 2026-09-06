import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MaterialDetailPage, { generateMetadata } from "@/app/materials/[id]/page";
import { BookmarksPanel } from "@/components/dashboard/BookmarksPanel";
import { ApiError, getMaterial, getMaterialHydrideParameters, listMaterialBookmarks, listPaperBookmarks, type MaterialDetail } from "@/lib/api";
import { atomicItem, propertyEnvelope } from "../fixtures/property-evidence";
import { anomalyAssessment, materialAnomalyReview, rawArchive } from "../fixtures/scientific-anomalies";

vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, getMaterial: vi.fn(), getMaterialHydrideParameters: vi.fn(), listMaterialBookmarks: vi.fn(), listPaperBookmarks: vi.fn() };
});
vi.mock("@/components/BookmarkButton", () => ({ BookmarkButton: () => <span>Save control</span> }));

function material(): MaterialDetail {
  return {
    id: "synthetic", formula: "TEST", family: null, subfamily: null,
    tc_max: 9999, tc_ambient: 8888, tc_max_origin: "Observed", tc_max_experimental: 7777, tc_max_theoretical: 6666,
    total_papers: 1, arxiv_year: 2026, records: [], variants: [], mp_id: null, mp_alternate_ids: [],
    structure_phase: "unsupported-phase", crystal_structure: "unsupported-structure", pairing_symmetry: "unsupported-pairing",
    hc2_tesla: 100, hc2_conditions: "Old A: Along c at 5 K", disputed: true, retracted: true,
  } as unknown as MaterialDetail;
}

describe("atomic evidence across material surfaces", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(getMaterialHydrideParameters).mockResolvedValue([]);
    vi.mocked(listPaperBookmarks).mockResolvedValue({ total: 0, results: [] });
  });

  it("hides unsupported headlines, header structure and variant values in page and SEO", async () => {
    const mat = material();
    mat.variants = [{ id: "variant", formula: "TEST-variant", tc_max: 5555, tc_ambient: 4444, total_papers: 1, doping_level: 0.123, pressure_type: null }];
    vi.mocked(getMaterial).mockResolvedValue(mat);
    const metadata = await generateMetadata({ params: Promise.resolve({ id: mat.id }) });
    expect(metadata.description).not.toContain("9999");
    const { container } = render(await MaterialDetailPage({ params: Promise.resolve({ id: mat.id }) }));
    for (const unsupported of ["9999", "8888", "7777", "6666", "5555", "4444", "unsupported-phase", "unsupported-structure", "unsupported-pairing", "Old A: Along c at 5 K"]) {
      expect(container.textContent).not.toContain(unsupported);
    }
    const jsonld = JSON.parse(container.querySelector("#sclib-material-structured-data")!.textContent!);
    expect(jsonld.variableMeasured).toEqual([]);
    expect(screen.getByText("Catalogue risk flag: disputed")).toBeInTheDocument();
    expect(screen.getByText("Catalogue risk flag: retracted")).toBeInTheDocument();
  });

  it("shows selected uncertainty in all headlines and keeps B's Hc2 context", async () => {
    const mat = material();
    const tc = atomicItem("tc_max", 0.001);
    tc.quantity = { ...tc.quantity, approximate: true, uncertainty: 0.0001 };
    mat.property_evidence = propertyEnvelope(tc, atomicItem("hc2_tesla", 100, {
      result_id: "Hc2-B", conditions: { hc2_conditions: "B: Along ab at 0 K", hc2_direction: "ab" },
    }));
    vi.mocked(getMaterial).mockResolvedValue(mat);
    const metadata = await generateMetadata({ params: Promise.resolve({ id: mat.id }) });
    expect(metadata.description).toContain("≈ 0.001 ± 0.0001 K");
    const { container } = render(await MaterialDetailPage({ params: Promise.resolve({ id: mat.id }) }));
    expect(screen.getByText("≈ 0.001 ± 0.0001 K")).toBeInTheDocument();
    expect(screen.getByText("B: Along ab at 0 K")).toBeInTheDocument();
    expect(screen.queryByText("Old A: Along c at 5 K")).not.toBeInTheDocument();
    const jsonld = JSON.parse(container.querySelector("#sclib-material-structured-data")!.textContent!);
    expect(jsonld.variableMeasured).toHaveLength(1);
    expect(jsonld.variableMeasured[0].value).toBe("≈ 0.001 ± 0.0001");
  });

  it("bookmarks share the source guard instead of displaying stale Tc scalars", async () => {
    vi.mocked(listMaterialBookmarks).mockResolvedValue({ total: 1, results: [{ id: "bookmark", target_id: "synthetic", created_at: "2026-09-06T00:00:00Z", formula: "BOOKMARK-TEST", formula_latex: null, family: null, tc_max: 9999, tc_ambient: 8888, arxiv_year: 2026 }] });
    render(<BookmarksPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Materials" }));
    expect(await screen.findByText("BOOKMARK-TEST")).toBeInTheDocument();
    expect(screen.queryByText("9999")).not.toBeInTheDocument();
    expect(screen.queryByText("8888")).not.toBeInTheDocument();
    expect(screen.getAllByText("Source unavailable")).toHaveLength(2);
  });

  it("retains anomalous raw values in a clearly scoped Archive but not headline or SEO", async () => {
    const mat = material();
    const tc = atomicItem("tc_max", 60, { anomaly_review: anomalyAssessment() });
    mat.property_evidence = propertyEnvelope(tc);
    mat.property_evidence.properties.tc_max = { ...mat.property_evidence.properties.tc_max, status: "pending", selected: null, evidence: [tc], warnings: ["anomaly_review_required"] };
    mat.anomaly_review = materialAnomalyReview();
    mat.raw_archive = rawArchive();
    mat.records = [{ tc_kelvin: 60, paper_id: "synthetic-source", anomaly_review: anomalyAssessment() }];
    vi.mocked(getMaterial).mockResolvedValue(mat);
    const metadata = await generateMetadata({ params: Promise.resolve({ id: mat.id }) });
    expect(metadata.description).not.toContain("60 K");
    const { container } = render(await MaterialDetailPage({ params: Promise.resolve({ id: mat.id }) }));
    expect(screen.getByText("Retained Tc (K)")).toBeInTheDocument();
    expect(screen.getByText("Stored extraction, not approval")).toBeInTheDocument();
    expect(screen.getByLabelText("Retained raw scientific fields for synthetic-result:tc_max")).toHaveTextContent("60 K");
    const jsonld = JSON.parse(container.querySelector("#sclib-material-structured-data")!.textContent!);
    expect(jsonld.variableMeasured).toEqual([]);
    expect(vi.mocked(getMaterialHydrideParameters)).not.toHaveBeenCalled();
  });

  it("does not look for Archive or enrichment data when the server hides the material", async () => {
    vi.mocked(getMaterial).mockRejectedValue(new ApiError(404, {}, "Material not found"));
    await expect(MaterialDetailPage({ params: Promise.resolve({ id: "restricted" }) })).rejects.toThrow();
    expect(vi.mocked(getMaterialHydrideParameters)).not.toHaveBeenCalled();
  });
});
