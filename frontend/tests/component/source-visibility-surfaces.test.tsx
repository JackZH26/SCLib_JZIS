import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PaperDetailPage, { generateMetadata } from "@/app/paper/[id]/page";
import { getPaper, getSimilar, type PaperDetail } from "@/lib/api";
import { sourceVisibility, occurrenceVisibility } from "../fixtures/material-visibility";

vi.mock("@/lib/api", async importOriginal => ({ ...await importOriginal<typeof import("@/lib/api")>(), getPaper: vi.fn(), getSimilar: vi.fn() }));
vi.mock("@/components/BookmarkButton", () => ({ BookmarkButton: () => <span>Save control</span> }));

function paper(): PaperDetail {
  return { id: "arxiv:synthetic", title: "Synthetic test source", abstract: "Source claim: 9999 K", authors: [], materials_extracted: [], citation_count: 0, source_visibility: sourceVisibility() } as unknown as PaperDetail;
}

describe("source visibility surfaces", () => {
  beforeEach(() => { vi.resetAllMocks(); vi.mocked(getSimilar).mockResolvedValue({ source_paper_id: "synthetic", results: [] }); });

  it.each(["retracted", "corrected", "disputed", "unknown"] as const)("retains %s bibliography with warnings but does not publish its abstract claim in SEO", async status => {
    const p = paper();
    p.source_visibility = sourceVisibility(status);
    p.materials_extracted = [{ formula: "TEST", tc_kelvin: 20, visibility: occurrenceVisibility(status === "unknown" ? "unknown" : status) }];
    vi.mocked(getPaper).mockResolvedValue(p);
    const metadata = await generateMetadata({ params: Promise.resolve({ id: p.id }) });
    expect(metadata.robots).toMatchObject({ index: false });
    expect(metadata.description).not.toContain("9999 K");
    const { container } = render(await PaperDetailPage({ params: Promise.resolve({ id: p.id }) }));
    expect(screen.getByText("Source claim: 9999 K")).toBeInTheDocument();
    expect(screen.getByLabelText("Bibliographic source visibility")).toHaveTextContent(status === "unknown" ? "unknown" : `Source Archive — ${status}`);
    expect(screen.getByLabelText("source occurrence visibility")).toHaveTextContent("Archive");
    const jsonld = JSON.parse(container.querySelector("#sclib-paper-structured-data")!.textContent!);
    expect(jsonld.abstract).toBeUndefined();
  });

  it("active bibliography may expose its abstract without asserting material approval", async () => {
    vi.mocked(getPaper).mockResolvedValue(paper());
    const metadata = await generateMetadata({ params: Promise.resolve({ id: paper().id }) });
    expect(metadata.description).toContain("9999 K");
    expect(metadata.robots).toBeUndefined();
    render(await PaperDetailPage({ params: Promise.resolve({ id: paper().id }) }));
    expect(screen.getByText("Active bibliographic source — not scientific approval")).toBeInTheDocument();
  });

  it("links retained bibliography to safe publisher and versioned arXiv sources without changing source review", async () => {
    const p = paper();
    p.doi = "10.1103/PhysRevB.109.054512";
    p.arxiv_id = "0912.2752v2";
    p.source_visibility = sourceVisibility("corrected");
    vi.mocked(getPaper).mockResolvedValue(p);
    const { container } = render(await PaperDetailPage({ params: Promise.resolve({ id: p.id }) }));
    expect(screen.getByRole("link", { name: "Open publisher source" })).toHaveAttribute("href", "https://doi.org/10.1103/PhysRevB.109.054512");
    expect(screen.getByRole("link", { name: "Open arXiv source" })).toHaveAttribute("href", "https://arxiv.org/abs/0912.2752v2");
    expect(screen.getByLabelText("Bibliographic source visibility")).toHaveTextContent("Source Archive — corrected");
    const jsonld = JSON.parse(container.querySelector("#sclib-paper-structured-data")!.textContent!);
    expect(jsonld.abstract).toBeUndefined();
  });

  it("does not turn malformed DOI or arXiv strings into publication links", async () => {
    const p = paper();
    p.doi = "javascript:alert(1)";
    p.arxiv_id = "https://user:password@example.invalid/source";
    vi.mocked(getPaper).mockResolvedValue(p);
    const metadata = await generateMetadata({ params: Promise.resolve({ id: p.id }) });
    expect(metadata.other).not.toHaveProperty("citation_doi");
    expect(metadata.other).not.toHaveProperty("citation_arxiv_id");
    const { container } = render(await PaperDetailPage({ params: Promise.resolve({ id: p.id }) }));
    expect(screen.queryByLabelText("Original publication links")).not.toBeInTheDocument();
    const jsonld = JSON.parse(container.querySelector("#sclib-paper-structured-data")!.textContent!);
    expect(jsonld.sameAs).toEqual([]);
    expect(jsonld.identifier).toEqual([]);
  });
});
