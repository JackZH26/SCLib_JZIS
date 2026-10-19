import { act, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import HomeSearchResults from "@/components/HomeSearchResults";
import LegacySearch from "@/app/search/page";
import { search, ask } from "@/lib/api";

const nav = vi.hoisted(() => ({ query: "FeSe", redirect: vi.fn() }));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams({ q: nav.query }), redirect: nav.redirect }));
vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(), search: vi.fn(), ask: vi.fn() }));
vi.mock("@/components/PaperCard", () => ({ PaperCard: ({ title }: {title:string}) => <article>{title}</article> }));
const entry = (title: string, text = "FeSe", code = "C2") => ({ id: title, topicId: title, code, slug: title,
  title, summary: "Scoped evidence", aliases: [], evidenceTypes: ["experiment"], editorialStatus: "scoped-check",
  revision: "test", materialCases: [], dois: [], text });
const index = (entries: ReturnType<typeof entry>[]) => ({ ok:true, json:async()=>({entries}) });
function deferred<T>() { let resolve!:(value:T)=>void; const promise=new Promise<T>(yes=>{resolve=yes;});return {promise,resolve}; }
beforeEach(() => {
  vi.resetAllMocks(); nav.query="FeSe";
  vi.mocked(search).mockResolvedValue({results:[],query_time_ms:0} as never);
});
afterEach(() => vi.unstubAllGlobals());

it("shows chunk results and full-body wiki matches in separate labelled collections", async () => {
  vi.mocked(search).mockResolvedValue({ results:[{paper_id:"paper",title:"Original passage",authors:[],matched_chunk:"FeSe passage",relevance_score:1}],query_time_ms:1 } as never);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(index([entry("Body-only match"),entry("Research note match","FeSe","Research note")])));
  render(<HomeSearchResults />);
  expect(await within(screen.getByRole("region",{name:"Literature"})).findByText("Original passage")).toBeVisible();
  const wiki=screen.getByRole("region",{name:"SCWiki"});
  expect(await within(wiki).findByRole("link",{name:"Body-only match"})).toHaveAttribute("href","/scwiki/Body-only match");
  expect(within(wiki).getByText("Research note",{exact:true})).toBeVisible();
  expect(vi.mocked(search).mock.calls[0][0].filters).toEqual({exclude_retracted:true});
  expect(ask).not.toHaveBeenCalled();
});
it("keeps Wiki results available when the literature service fails", async () => {
  vi.mocked(search).mockRejectedValue(new Error("unavailable"));
  vi.stubGlobal("fetch",vi.fn().mockResolvedValue(index([entry("Wiki remains available")])));
  render(<HomeSearchResults />);
  expect(await screen.findByRole("link",{name:"Wiki remains available"})).toBeVisible();
});
it("keeps literature results when the Wiki index fails", async () => {
  vi.mocked(search).mockResolvedValue({results:[{paper_id:"paper",title:"Paper remains available",authors:[],matched_chunk:"FeSe",relevance_score:1}],query_time_ms:1} as never);
  vi.stubGlobal("fetch",vi.fn().mockRejectedValue(new Error("unavailable")));
  render(<HomeSearchResults />);
  expect(await screen.findByRole("button",{name:"Retry SCWiki"})).toBeVisible();
  expect(screen.getByText("Paper remains available")).toBeVisible();
});
it("rejects a late previous Wiki response even if transport ignores abort", async () => {
  const old=deferred<ReturnType<typeof index>>(),current=deferred<ReturnType<typeof index>>();
  const fetcher=vi.fn().mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);vi.stubGlobal("fetch",fetcher);
  const view=render(<HomeSearchResults />); const signal=fetcher.mock.calls[0][1].signal;
  nav.query="MgB2";view.rerender(<HomeSearchResults />);expect(signal.aborted).toBe(true);
  await act(async()=>{current.resolve(index([entry("Current wiki","MgB2")]));});
  await act(async()=>{old.resolve(index([entry("Stale wiki")]));});
  expect(screen.getByText("Current wiki")).toBeVisible();expect(screen.queryByText("Stale wiki")).toBeNull();
});
it("does not request results for an empty Home query", () => {
  nav.query="";const fetcher=vi.fn();vi.stubGlobal("fetch",fetcher);render(<HomeSearchResults />);
  expect(fetcher).not.toHaveBeenCalled();expect(search).not.toHaveBeenCalled();
});
it("preserves multilingual and repeated query parameters from old search links", async () => {
  await LegacySearch({searchParams:Promise.resolve({q:"FeSe + 超导",tag:["a","b"]})});
  const destination=nav.redirect.mock.calls[0][0];const parsed=new URL(destination,"https://jzis.org");
  expect(parsed.pathname).toBe("/");expect(parsed.searchParams.get("q")).toBe("FeSe + 超导");expect(parsed.searchParams.getAll("tag")).toEqual(["a","b"]);
});
