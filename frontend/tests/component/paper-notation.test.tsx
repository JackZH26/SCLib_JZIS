import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PaperDetailPage from "@/app/paper/[id]/page";
import { PaperCard } from "@/components/PaperCard";
import { LiteratureSearchResults } from "@/components/SearchResultColumns";
import { getPaper, search, type PaperDetail, type SearchResponse } from "@/lib/api";
import { sourceNotationLabel } from "@/lib/source-notation";
import { occurrenceVisibility, sourceVisibility } from "../fixtures/material-visibility";

vi.mock("@/lib/api", async original => ({
  ...await original<typeof import("@/lib/api")>(), getPaper: vi.fn(), search: vi.fn(),
}));
vi.mock("@/components/BookmarkButton", () => ({ BookmarkButton: () => null }));
vi.mock("@/components/SimilarPapers", () => ({ SimilarPapers: () => null }));

// Source strings from the reported arXiv:2411.14600 record, including math
// delimited only around each subscript rather than the whole formula.
const title = "Fermi surface reconstruction and enhanced spin fluctuations in strained La$_3$Ni$_2$O$_{7}$ on LaAlO$_3$(001) and SrTiO$_3$(001)";
const abstract = "For La$_3$Ni$_2$O$_{7}$/LaAlO$_3$(001), we find occupation of the antibonding Ni $3d_{z^2}$ states. Strain controls the Ni $e_g$ orbital polarization.";
const titleLabel = "Fermi surface reconstruction and enhanced spin fluctuations in strained La3Ni2O7 on LaAlO3(001) and SrTiO3(001)";

function paper(): PaperDetail {
  return {
    id: "arxiv:2411.14600", arxiv_id: "2411.14600", title, abstract,
    authors: ["Benjamin Geisler"], citation_count: 5,
    source_visibility: sourceVisibility(),
    materials_extracted: [{ formula: "La_3Ni_2O_7", visibility: occurrenceVisibility() }],
  } as PaperDetail;
}

describe("paper source notation across search and detail", () => {
  beforeEach(() => vi.resetAllMocks());

  it("renders the reported search title and excerpt through the same notation renderer", () => {
    const { container } = render(<PaperCard paper_id="arxiv:2411.14600" arxiv_id="2411.14600"
      title={title} snippet={abstract} section="Body" authors={["Benjamin Geisler"]} year={2025} />);
    const heading = screen.getByRole("heading");
    expect(sourceNotationLabel(heading.innerHTML)).toBe(titleLabel);
    expect(heading.querySelectorAll(".katex")).toHaveLength(5);
    const excerpt = container.querySelector(".line-clamp-3")!;
    expect(sourceNotationLabel(excerpt.innerHTML)).toContain("La3Ni2O7/LaAlO3(001)");
    expect(excerpt.querySelectorAll(".katex")).toHaveLength(6);
    expect(sourceNotationLabel(excerpt.innerHTML)).not.toMatch(/[$_{}^]/);
    expect(excerpt.querySelector("math")).not.toBeNull();
    expect(screen.getByRole("link")).toHaveAttribute("href", "/paper/arxiv%3A2411.14600");
  });

  it("preserves formulas crossing the former 400-character excerpt boundary", async () => {
    const prefix = "Excerpt ".repeat(49) + "In "; // 395 characters; the cut was inside $_{3}$.
    const matched = `${prefix}La$_{3}$Ni$_2$O$_7$ after the formula.`;
    vi.mocked(search).mockResolvedValue({ results: [{
      paper_id: "arxiv:2411.14600", arxiv_id: "2411.14600", title,
      authors: [], year: 2025, matched_chunk: matched, relevance_score: 0.99,
    }], query_time_ms: 1 } as SearchResponse);
    const { container } = render(<LiteratureSearchResults query="La3Ni2O7" />);
    await screen.findByRole("link");
    const excerpt = container.querySelector(".line-clamp-3")!;
    expect(sourceNotationLabel(excerpt.innerHTML)).toBe(`${prefix}La3Ni2O7 after the formula.`);
    expect(excerpt.querySelectorAll(".katex")).toHaveLength(3);
    expect(excerpt.querySelector("[data-notation-unresolved]")).toBeNull();
    expect(excerpt.classList.contains("line-clamp-3")).toBe(true);
  });

  it("renders the detail heading, abstract and extracted formula without changing source data", async () => {
    const source = paper();
    vi.mocked(getPaper).mockResolvedValue(source);
    const { container } = render(await PaperDetailPage({ params: Promise.resolve({ id: source.id }) }));
    const heading = screen.getByRole("heading", { level: 1 });
    expect(sourceNotationLabel(heading.innerHTML)).toBe(titleLabel);
    expect(heading.querySelectorAll(".katex")).toHaveLength(5);
    const summary = screen.getByText("Abstract", { selector: "h2" }).parentElement!;
    expect(summary.querySelectorAll(".katex")).toHaveLength(6);
    expect(sourceNotationLabel(summary.innerHTML)).not.toMatch(/[$_{}^]/);
    const formulaCell = within(screen.getByRole("table")).getAllByRole("cell")[0];
    expect(formulaCell.querySelectorAll(".katex")).toHaveLength(1);
    expect(sourceNotationLabel(formulaCell.innerHTML)).toContain("La3Ni2O7");
    const jsonld = JSON.parse(container.querySelector("#sclib-paper-structured-data")!.textContent!);
    expect(jsonld.headline).toBe(title);
    expect(jsonld.abstract).toBe(abstract);
    expect(source.title).toBe(title);
    expect(source.abstract).toBe(abstract);
  });

  it("keeps plain abstracts and source HTML literal while rendering embedded chemistry", () => {
    const raw = '<img src=x onerror="alert(1)"> Ni $3d_{z^2}$ in La$_3$Ni$_2$O$_7$';
    const { container } = render(<PaperCard paper_id="source" arxiv_id={null} title="Plain title"
      snippet={raw} authors={[]} year={null} />);
    expect(container.querySelector("img,script")).toBeNull();
    expect(sourceNotationLabel(container.querySelector(".line-clamp-3")!.innerHTML)).toContain('<img src=x onerror="alert(1)">');
    expect(container.querySelectorAll(".katex")).toHaveLength(4);
    expect(screen.getByRole("heading")).toHaveTextContent("Plain title");
  });
});
