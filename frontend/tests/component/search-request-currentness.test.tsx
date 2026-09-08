import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SearchPage from "@/app/search/page";
import { ApiError, ask, search, type AskResponse, type SearchResponse } from "@/lib/api";
import { generation, scientificLookup, scientificQuery, scientificResult } from "../fixtures/scientific-query";
import { mixedResponse } from "../fixtures/scientific-mixed";

const navigation = vi.hoisted(() => ({ query: "old material" }));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams({ q: navigation.query }) }));
vi.mock("@/components/SearchBar", () => ({ SearchBar: ({ initial }: { initial: string }) => <input aria-label="Query" value={initial} readOnly /> }));
vi.mock("@/components/PaperCard", () => ({ PaperCard: ({ title }: { title: string }) => <article>{title}</article> }));
vi.mock("@/components/MarkdownAnswer", () => ({ MarkdownAnswer: ({ markdown }: { markdown: string }) => <p>{markdown}</p> }));
vi.mock("@/components/AskSupportNotice", () => ({ AskSupportNotice: () => null }));
vi.mock("@/lib/api", async importOriginal => ({
  ...await importOriginal<typeof import("@/lib/api")>(), search: vi.fn(), ask: vi.fn(),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function searchResponse(title: string): SearchResponse {
  return { total: 1, results: [{ paper_id: title, arxiv_id: null, title, authors: [], year: null,
    date_submitted: null, relevance_score: 1, matched_chunk: "Synthetic excerpt", matched_section: null,
    materials: [], citation_count: 0, material_family: null, has_equation: false, has_table: false }],
    query_time_ms: 10, guest_remaining: null, remaining: null };
}

function answer(text: string): AskResponse {
  return { answer: text, sources: [], tokens_used: null, query_time_ms: 10, citation_valid: false,
    citation_warnings: [], guest_remaining: null, remaining: null };
}

describe("query-bound asynchronous Search and Ask responses", () => {
  beforeEach(() => { vi.resetAllMocks(); navigation.query = "old material"; });

  it("does not display a late previous search under the new query even if transport ignores abort", async () => {
    const old = deferred<SearchResponse>(), current = deferred<SearchResponse>();
    vi.mocked(search).mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
    const view = render(<SearchPage />);
    const oldSignal = vi.mocked(search).mock.calls[0][1]?.signal;
    navigation.query = "new material";
    view.rerender(<SearchPage />);
    expect(oldSignal?.aborted).toBe(true);
    await act(async () => { current.resolve(searchResponse("CURRENT_RESULT")); });
    await act(async () => { old.resolve(searchResponse("OLD_RESULT")); });
    expect(screen.getByText("CURRENT_RESULT")).toBeVisible();
    expect(screen.queryByText("OLD_RESULT")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Query")).toHaveValue("new material");
  });

  it("clears previously visible results before a new request completes", async () => {
    vi.mocked(search).mockResolvedValueOnce(searchResponse("OLD_RESULT")).mockReturnValueOnce(new Promise(() => {}));
    const view = render(<SearchPage />);
    await screen.findByText("OLD_RESULT");
    navigation.query = "new material";
    view.rerender(<SearchPage />);
    expect(screen.queryByText("OLD_RESULT")).not.toBeInTheDocument();
    expect(screen.getByText("Searching…")).toBeVisible();
  });

  it("ignores both old automatic Ask success and old search error", async () => {
    navigation.query = "What is old?";
    const oldSearch = deferred<SearchResponse>(), currentSearch = deferred<SearchResponse>();
    const oldAsk = deferred<AskResponse>(), currentAsk = deferred<AskResponse>();
    vi.mocked(search).mockReturnValueOnce(oldSearch.promise).mockReturnValueOnce(currentSearch.promise);
    vi.mocked(ask).mockReturnValueOnce(oldAsk.promise).mockReturnValueOnce(currentAsk.promise);
    const view = render(<SearchPage />);
    const oldSignal = vi.mocked(ask).mock.calls[0][1]?.signal;
    navigation.query = "What is current?";
    view.rerender(<SearchPage />);
    expect(oldSignal?.aborted).toBe(true);
    await act(async () => { currentAsk.resolve(answer("CURRENT_ANSWER")); currentSearch.resolve(searchResponse("CURRENT_RESULT")); });
    await act(async () => { oldAsk.resolve(answer("OLD_ANSWER")); oldSearch.reject(new ApiError(422, {}, "OLD_ERROR")); });
    expect(screen.getByText("CURRENT_ANSWER")).toBeVisible();
    expect(screen.getByText("CURRENT_RESULT")).toBeVisible();
    expect(screen.queryByText(/OLD_ANSWER|OLD_ERROR/)).not.toBeInTheDocument();
  });

  it("isolates manual Ask from a later query and does not clear the newer loading state", async () => {
    vi.mocked(search).mockResolvedValue({ ...searchResponse("unused"), total: 0, results: [] });
    const old = deferred<AskResponse>(), current = deferred<AskResponse>();
    vi.mocked(ask).mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
    const view = render(<SearchPage />);
    fireEvent.click(screen.getByRole("button", { name: "Summarize with AI" }));
    const oldSignal = vi.mocked(ask).mock.calls[0][1]?.signal;
    navigation.query = "new material";
    view.rerender(<SearchPage />);
    expect(oldSignal?.aborted).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Summarize with AI" }));
    await act(async () => { old.resolve(answer("OLD_MANUAL_ANSWER")); });
    expect(screen.getByText("Preparing answer…")).toBeVisible();
    expect(screen.queryByText("OLD_MANUAL_ANSWER")).not.toBeInTheDocument();
    await act(async () => { current.resolve(answer("CURRENT_MANUAL_ANSWER")); });
    expect(screen.getByText("CURRENT_MANUAL_ANSWER")).toBeVisible();
  });

  it("clears automatic Ask loading and errors on short/empty queries without new requests", async () => {
    navigation.query = "What is old?";
    const oldSearch = deferred<SearchResponse>(), oldAsk = deferred<AskResponse>();
    vi.mocked(search).mockReturnValueOnce(oldSearch.promise);
    vi.mocked(ask).mockReturnValueOnce(oldAsk.promise);
    const view = render(<SearchPage />);
    navigation.query = "";
    view.rerender(<SearchPage />);
    await act(async () => { oldSearch.reject(new ApiError(422, {}, "OLD_ERROR")); oldAsk.resolve(answer("OLD_ANSWER")); });
    expect(screen.queryByText(/Searching…|Preparing answer…|OLD_ERROR|OLD_ANSWER/)).not.toBeInTheDocument();
    expect(screen.getByText("Enter a query above to start searching.")).toBeVisible();
    expect(search).toHaveBeenCalledTimes(1);
    expect(ask).toHaveBeenCalledTimes(1);
  });

  it("aborts outstanding Search and Ask on unmount", async () => {
    navigation.query = "什么是超导？";
    vi.mocked(search).mockReturnValue(new Promise(() => {}));
    vi.mocked(ask).mockReturnValue(new Promise(() => {}));
    const view = render(<SearchPage />);
    await waitFor(() => expect(ask).toHaveBeenCalledOnce());
    view.unmount();
    expect(vi.mocked(search).mock.calls[0][1]?.signal?.aborted).toBe(true);
    expect(vi.mocked(ask).mock.calls[0][1]?.signal?.aborted).toBe(true);
  });

  it("shows qualified numerical results even when the paper-results array is intentionally empty", async () => {
    navigation.query = "Tc > 20 K for MgB₂";
    vi.mocked(search).mockResolvedValue({ ...searchResponse("unused"), results: [], total: 0,
      scientific_query: scientificQuery(navigation.query), scientific_results: [scientificResult()],
      scientific_lookup: scientificLookup(), retrieval_generation: generation });
    render(<SearchPage />);
    expect(await screen.findByText("39 K")).toBeVisible();
    expect(screen.queryByText("No results.")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Source paper · extraction 1" })).toBeVisible();
  });

  it("labels deterministic numeric Ask as a reported-result lookup, not an AI numerical finding", async () => {
    navigation.query = "What is Tc of MgB₂?";
    vi.mocked(search).mockResolvedValue({ ...searchResponse("unused"), results: [], total: 0 });
    vi.mocked(ask).mockResolvedValue({ ...answer("See the qualified extraction records below."),
      scientific_query: scientificQuery(navigation.query), scientific_results: [scientificResult()],
      scientific_lookup: scientificLookup(), retrieval_generation: generation });
    render(<SearchPage />);
    expect(await screen.findByRole("heading", { name: "Source-linked extraction lookup" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "AI Answer" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Ask scientific query")).toHaveTextContent("not an original quotation");
  });

  it("never shows an old numerical interpretation or result under a newer query", async () => {
    navigation.query = "Tc > 20 K for MgB₂";
    const oldQuery = navigation.query, old = deferred<SearchResponse>(), current = deferred<SearchResponse>();
    vi.mocked(search).mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
    const view = render(<SearchPage />);
    navigation.query = "current material";
    view.rerender(<SearchPage />);
    await act(async () => { current.resolve(searchResponse("CURRENT_RESULT")); });
    await act(async () => { old.resolve({ ...searchResponse("unused"), results: [], total: 0,
      scientific_query: scientificQuery(oldQuery), scientific_results: [scientificResult()],
      scientific_lookup: scientificLookup(), retrieval_generation: generation }); });
    expect(screen.getByText("CURRENT_RESULT")).toBeVisible();
    expect(screen.queryByText("39 K")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Search scientific query")).not.toBeInTheDocument();
  });

  it("renders separate mixed panels without passing an unchecked answer to Markdown", async () => {
    navigation.query = "Why is Tc of MgB₂ 39 K?";
    vi.mocked(search).mockResolvedValue({ ...searchResponse("unused"), total: 0, results: [] });
    vi.mocked(ask).mockResolvedValue(mixedResponse(navigation.query));
    render(<SearchPage />);
    expect(await screen.findByRole("heading", { name: "Separate numerical and original-source lookup" })).toBeVisible();
    expect(screen.getByRole("region", { name: "Structured extraction records" })).toHaveTextContent("39 K");
    expect(screen.getByRole("region", { name: "Original explanation candidates" })).toHaveTextContent("Synthetic passage 1");
    expect(screen.getByText(/No generation requested/)).toBeVisible();
    expect(screen.queryByText(/UNREVIEWED_MIXED_PROSE/)).not.toBeInTheDocument();
  });

  it("withholds both mixed inventories and untrusted answer on a malformed present envelope", async () => {
    navigation.query = "Why is Tc of MgB₂ 39 K?";
    vi.mocked(search).mockResolvedValue({ ...searchResponse("unused"), total: 0, results: [] });
    const response = mixedResponse(navigation.query);
    Object.assign(response, { scientific_mixed: { status: "completed" } });
    vi.mocked(ask).mockResolvedValue(response);
    render(<SearchPage />);
    expect(await screen.findByText(/Numerical records, explanation candidates and association links are withheld/)).toBeVisible();
    expect(screen.getByText(/Mixed metadata withheld/)).toBeVisible();
    expect(screen.queryByText("39 K")).not.toBeInTheDocument();
    expect(screen.queryByText("Synthetic passage 1")).not.toBeInTheDocument();
    expect(screen.queryByText(/UNREVIEWED_MIXED_PROSE/)).not.toBeInTheDocument();
  });

  it("ignores a late mixed matrix under a new query and never keeps old extraction/citation targets", async () => {
    navigation.query = "Why is Tc of MgB₂ 39 K?";
    const oldQuery = navigation.query, old = deferred<AskResponse>(), current = deferred<AskResponse>();
    vi.mocked(search).mockResolvedValue({ ...searchResponse("unused"), total: 0, results: [] });
    vi.mocked(ask).mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
    const view = render(<SearchPage />);
    const oldSignal = vi.mocked(ask).mock.calls[0][1]?.signal;
    navigation.query = "What is the current mechanism?";
    view.rerender(<SearchPage />);
    expect(oldSignal?.aborted).toBe(true);
    await act(async () => { current.resolve(answer("CURRENT_ANSWER")); });
    await act(async () => { old.resolve(mixedResponse(oldQuery)); });
    expect(screen.getByText("CURRENT_ANSWER")).toBeVisible();
    expect(screen.queryByRole("region", { name: "Mixed scientific retrieval" })).not.toBeInTheDocument();
    expect(screen.queryByText("39 K")).not.toBeInTheDocument();
    expect(screen.queryByText("Synthetic passage 1")).not.toBeInTheDocument();
    expect(document.getElementById("src-1")).toBeNull();
  });
});
