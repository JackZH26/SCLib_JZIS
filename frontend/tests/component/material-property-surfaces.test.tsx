import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MaterialDetailPage, { generateMetadata } from "@/app/materials/[id]/page";
import { BookmarksPanel } from "@/components/dashboard/BookmarksPanel";
import { ApiError, getMaterial, getMaterialHydrideParameters, listMaterialBookmarks, listPaperBookmarks, type MaterialDetail } from "@/lib/api";
import { atomicItem, propertyEnvelope } from "../fixtures/property-evidence";
import { anomalyAssessment, materialAnomalyReview, rawArchive } from "../fixtures/scientific-anomalies";
import { materialVisibility } from "../fixtures/material-visibility";
import { materialSemantics, semanticProperty, semanticReport } from "../fixtures/material-semantics";

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
    mat.visibility = materialVisibility();
    mat.disputed = false;
    mat.retracted = false;
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

  it("detail and variants use their own classification semantics, never inherited legacy flags", async () => {
    const mat = material();
    mat.material_semantics = materialSemantics({ pairing_symmetry: semanticProperty("synthetic parent symmetry") });
    mat.variants = [{ id: "variant", formula: "TEST-variant", tc_max: null, tc_ambient: null, total_papers: 1, doping_level: null, pressure_type: null, material_semantics: materialSemantics({ is_unconventional: semanticProperty(false, semanticReport(false, { negative_qualified: true, detection_conditions: { pressure_gpa: 0 } })) }) }];
    vi.mocked(getMaterial).mockResolvedValue(mat);
    render(await MaterialDetailPage({ params: Promise.resolve({ id: mat.id }) }));
    expect(screen.getByLabelText("Material classification semantics")).toHaveTextContent("synthetic parent symmetry");
    const variant = screen.getByLabelText("Reported material classifications");
    expect(variant).toHaveTextContent("Reported false (scoped)");
    expect(variant).not.toHaveTextContent("synthetic parent symmetry");
  });

  it("bookmarks expose reported classifications without borrowing stale numeric or prior labels", async () => {
    vi.mocked(listMaterialBookmarks).mockResolvedValue({ total: 1, results: [{ id: "bookmark", target_id: "synthetic", created_at: "2026-09-06T00:00:00Z", formula: "SEMANTICS-BOOKMARK", formula_latex: null, family: "cuprate", tc_max: 9999, tc_ambient: null, arxiv_year: 2026, material_semantics: materialSemantics({ is_unconventional: semanticProperty(true) }) }] });
    render(<BookmarksPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Materials" }));
    expect(await screen.findByText("SEMANTICS-BOOKMARK")).toBeInTheDocument();
    expect(screen.getByLabelText("Reported material classifications")).toHaveTextContent("Reported true");
    expect(screen.getAllByText("Unknown")).toHaveLength(3); // Includes the separate SC11 structure association.
    expect(screen.queryByText("9999")).not.toBeInTheDocument();
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

  it.each(["pending", "disputed", "corrected", "retracted", "unknown"] as const)("%s material stays inspectable but never publishes quantitative SEO", async state => {
    const mat = material();
    mat.family = "hydride";
    mat.visibility = materialVisibility(state);
    mat.property_evidence = propertyEnvelope(atomicItem("tc_max", 20));
    vi.mocked(getMaterial).mockResolvedValue(mat);
    const metadata = await generateMetadata({ params: Promise.resolve({ id: mat.id }) });
    expect(metadata.robots).toMatchObject({ index: false, follow: false });
    expect(metadata.description).not.toContain("20 K");
    expect(metadata.title).toContain("Archive");
    const { container } = render(await MaterialDetailPage({ params: Promise.resolve({ id: mat.id }) }));
    for (const notice of screen.getAllByLabelText("material visibility")) expect(notice).toHaveTextContent("Archive");
    expect(screen.getByText(/source-linked value does not override a material review hold/)).toBeInTheDocument();
    const jsonld = JSON.parse(container.querySelector("#sclib-material-structured-data")!.textContent!);
    expect(jsonld.variableMeasured).toEqual([]);
    expect(jsonld.includedInDataCatalog).toBeUndefined();
    expect(vi.mocked(getMaterialHydrideParameters)).not.toHaveBeenCalled();
  });

  it("missing policy does not gain scientific SEO merely from complete property evidence", async () => {
    const mat = material();
    mat.property_evidence = propertyEnvelope(atomicItem("tc_max", 20));
    vi.mocked(getMaterial).mockResolvedValue(mat);
    const metadata = await generateMetadata({ params: Promise.resolve({ id: mat.id }) });
    expect(metadata.robots).toMatchObject({ index: false });
    expect(metadata.description).not.toContain("20 K");
    expect(metadata.description).toContain("visibility unverified");
  });

  it("explicit quarantine suppresses page data even in a stale successful API response", async () => {
    const mat = material();
    mat.visibility = materialVisibility("quarantined");
    vi.mocked(getMaterial).mockResolvedValue(mat);
    const metadata = await generateMetadata({ params: Promise.resolve({ id: mat.id }) });
    expect(metadata.title).toBe("Material not found");
    await expect(MaterialDetailPage({ params: Promise.resolve({ id: mat.id }) })).rejects.toThrow();
    expect(vi.mocked(getMaterialHydrideParameters)).not.toHaveBeenCalled();
  });

  it("pending bookmarks display the same Archive policy warning", async () => {
    vi.mocked(listMaterialBookmarks).mockResolvedValue({ total: 1, results: [{ id: "bookmark", target_id: "synthetic", created_at: "2026-09-06T00:00:00Z", formula: "PENDING-BOOKMARK", formula_latex: null, family: null, tc_max: 20, tc_ambient: null, arxiv_year: 2026, visibility: materialVisibility("pending") }] });
    render(<BookmarksPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Materials" }));
    expect(await screen.findByText("PENDING-BOOKMARK")).toBeInTheDocument();
    expect(screen.getByText("Archive — review pending")).toBeInTheDocument();
  });
});
