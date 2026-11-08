"use client";

import { type ReactNode, useEffect, useRef, useState } from "react";
import { GuestBanner } from "@/components/GuestBanner";
import { PaperCard } from "@/components/PaperCard";
import { ScientificQueryNotice } from "@/components/ScientificQueryNotice";
import { friendlyErrorMessage, search, type SearchResponse } from "@/lib/api";

export function SearchResultColumns({ query, children, wiki }: {
  query: string;
  children: ReactNode;
  wiki: ReactNode;
}) {
  const wikiHeading = useRef<HTMLHeadingElement>(null);
  return (
    <section aria-label="Search results" className="mb-12 scroll-mt-24" id="search-results">
      <h2 className="mb-6 text-2xl font-semibold">{query ? `Results for “${query}”` : "Search results"}</h2>
      <button type="button" onClick={() => wikiHeading.current?.focus()} className="site-text-link mb-4 text-sm lg:hidden">
        Jump to SCWiki results
      </button>
      <div className="grid items-start gap-8 lg:grid-cols-2">
        <section aria-labelledby="literature-results-heading" className="min-w-0 space-y-6">
          <h3 id="literature-results-heading" className="text-xl font-semibold">Literature</h3>
          {children}
        </section>
        <section aria-labelledby="wiki-results-heading" className="min-w-0 space-y-6 rounded-xl bg-sage-surface p-5 sm:p-6">
          <h3 ref={wikiHeading} tabIndex={-1} id="wiki-results-heading" className="scroll-mt-24 text-xl font-semibold">SCWiki</h3>
          {wiki}
        </section>
      </div>
    </section>
  );
}

export function LiteratureSearchResults({ query, fallbackRemaining, children }: {
  query: string;
  fallbackRemaining?: number | null;
  children?: ReactNode;
}) {
  const [outcome, setOutcome] = useState<
    { query: string; data: SearchResponse; error?: never } | { query: string; error: string; data?: never }
  >();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    search({ query, top_k: 20, filters: { exclude_retracted: true } }, { signal: controller.signal })
      .then(data => { if (!controller.signal.aborted) setOutcome({ query, data }); })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setOutcome({ query, error: friendlyErrorMessage(error) });
      });
    return () => controller.abort();
  }, [query, attempt]);

  const current = outcome?.query === query ? outcome : undefined;
  const searchData = current?.data;
  const searchErr = current?.error;
  const remaining = searchData?.guest_remaining ?? fallbackRemaining;
  return (
    <>
      {remaining != null && <GuestBanner remaining={remaining} />}
      {children}
      {!searchData && !searchErr && (
        <p role="status" className="text-sm text-sage-muted">Searching…</p>
      )}
      {searchErr && (
        <div role="alert" className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {searchErr}{" "}
          <button type="button" className="underline" onClick={() => { setOutcome(undefined); setAttempt(n => n + 1); }}>
            Retry literature search
          </button>
        </div>
      )}

      {searchData && <ScientificQueryNotice rawQuery={query} query={searchData.scientific_query}
        lookup={searchData.scientific_lookup} results={searchData.scientific_results} generation={searchData.retrieval_generation} />}

      {searchData && searchData.results.length > 0 && (
        <>
          <div className="text-xs text-sage-tertiary">
            {searchData.results.length} result
            {searchData.results.length === 1 ? "" : "s"} ·{" "}
            {searchData.query_time_ms} ms
          </div>
          <div className="space-y-3">
            {searchData.results.map((r, i) => (
              <PaperCard
                key={`${r.paper_id}-${i}`}
                paper_id={r.paper_id}
                arxiv_id={r.arxiv_id}
                title={r.title}
                authors={r.authors}
                year={r.year}
                snippet={r.matched_chunk.slice(0, 400)}
                section={r.matched_section}
                score={r.relevance_score}
                scoreLabel="relevance"
                matchingResults={r.matching_results}
                badges={[
                  ...(r.material_family ? [r.material_family] : []),
                  ...(r.has_equation ? ["equations"] : []),
                  ...(r.has_table ? ["tables"] : []),
                ]}
              />
            ))}
          </div>
        </>
      )}

      {searchData && searchData.results.length === 0 && (!searchData.scientific_query || searchData.scientific_lookup?.status === "not_requested") && (
        <p className="text-sm text-sage-muted">No results.</p>
      )}
    </>
  );
}
