import { StrictMode } from "react";
import { renderToString } from "react-dom/server";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SimilarResponse } from "@/lib/api";

const api = vi.hoisted(() => ({ getSimilar: vi.fn(), getPaper: vi.fn() }));
vi.mock("@/lib/api", async (original) => ({ ...await original<object>(), ...api }));
vi.mock("@/components/BookmarkButton", () => ({ BookmarkButton: () => null }));
import { SimilarPapers } from "@/components/SimilarPapers";
import PaperDetailPage from "@/app/paper/[id]/page";

let callbacks: IntersectionObserverCallback[];
const response: SimilarResponse = {
  source_paper_id: "source", results: [{ paper_id: "neighbor", arxiv_id: null,
    title: "Related superconductivity paper", authors: ["Researcher"], year: 2025, similarity: 0.75 }],
};
const visible = () => act(() => {
  callbacks.at(-1)!([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver);
});

describe("paper recommendations requested only when needed", () => {
  beforeEach(() => {
    vi.clearAllMocks(); callbacks = [];
    vi.stubGlobal("IntersectionObserver", class {
      constructor(callback: IntersectionObserverCallback) { callbacks.push(callback); }
      observe() {} disconnect() {}
    });
    api.getSimilar.mockResolvedValue(response);
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("server-renders the actual paper page without issuing a Similar request", async () => {
    api.getPaper.mockResolvedValue({ id: "source", title: "Bibliographic paper", authors: ["Author"],
      abstract: "Preserved abstract.", materials_extracted: [] });
    const markup = renderToString(await PaperDetailPage({ params: Promise.resolve({ id: "source" }) }));
    expect(markup).toContain("Bibliographic paper");
    expect(markup).toContain("Preserved abstract.");
    expect(markup).toContain("Find similar papers");
    expect(markup).toContain("ScholarlyArticle");
    expect(api.getSimilar).not.toHaveBeenCalled();
  });

  it("makes one unchanged six-result request on visibility and renders the response", async () => {
    render(<StrictMode><SimilarPapers paperId="source" /></StrictMode>);
    expect(api.getSimilar).not.toHaveBeenCalled();
    visible();
    expect(await screen.findByText("Related superconductivity paper")).toBeVisible();
    visible();
    expect(api.getSimilar).toHaveBeenCalledTimes(1);
    expect(api.getSimilar).toHaveBeenCalledWith("source", 6, expect.any(AbortSignal));
    expect(screen.getByText("similarity 0.75")).toBeVisible();
  });

  it("offers an English keyboard-accessible action without an observer and never retries failures", async () => {
    vi.stubGlobal("IntersectionObserver", undefined);
    api.getSimilar.mockRejectedValue(new Error("private endpoint information"));
    const { container, rerender } = render(<SimilarPapers paperId="source" />);
    expect(api.getSimilar).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Find similar papers" }));
    expect(await screen.findByText("Similar papers are unavailable right now.")).toHaveAttribute("role", "status");
    rerender(<SimilarPapers paperId="source" />);
    expect(api.getSimilar).toHaveBeenCalledTimes(1);
    expect(container.textContent).not.toMatch(/private endpoint|[\u3400-\u9fff]/);
  });

  it("aborts navigation away and never shows an old paper's late response", async () => {
    let finish!: (value: SimilarResponse) => void;
    api.getSimilar.mockImplementationOnce(() => new Promise<SimilarResponse>((resolve) => { finish = resolve; }));
    const { rerender, unmount } = render(<SimilarPapers paperId="source" />);
    visible();
    const oldSignal = api.getSimilar.mock.calls[0][2] as AbortSignal;
    rerender(<SimilarPapers paperId="other" />);
    expect(oldSignal.aborted).toBe(true);
    await act(async () => finish(response));
    expect(screen.queryByText("Related superconductivity paper")).not.toBeInTheDocument();
    expect(api.getSimilar).toHaveBeenCalledTimes(1);
    api.getSimilar.mockResolvedValueOnce({ source_paper_id: "other", results: [] });
    visible();
    expect(await screen.findByText("No similar papers found.")).toHaveAttribute("role", "status");
    expect(api.getSimilar.mock.calls[1].slice(0, 2)).toEqual(["other", 6]);
    unmount();
    expect((api.getSimilar.mock.calls[1][2] as AbortSignal).aborted).toBe(true);
  });
});
