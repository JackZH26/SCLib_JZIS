"use client";
import { EvidenceProvenanceNotice } from "@/components/EvidenceProvenanceNotice";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  search,
  ask,
  type SearchResponse,
  type AskResponse,
  friendlyErrorMessage,
} from "@/lib/api";
import { SearchBar } from "@/components/SearchBar";
import { PaperCard } from "@/components/PaperCard";
import { SourceVisibilityNotice } from "@/components/MaterialVisibilityNotice";
import { GuestBanner } from "@/components/GuestBanner";
import { MarkdownAnswer } from "@/components/MarkdownAnswer";
import { AskSupportNotice } from "@/components/AskSupportNotice";
import { ScientificQueryNotice } from "@/components/ScientificQueryNotice";
import { ScientificMixedNotice } from "@/components/ScientificMixedNotice";
import { HistorySaveNotice } from "@/components/HistorySaveNotice";
import { EvidencePackingNotice, PackingSourceNotice } from "@/components/EvidencePackingNotice";
import { resolveAskSource } from "@/lib/ask-support";
import { knownScientificLookup, knownScientificQuery, knownScientificResults } from "@/lib/scientific-query";
import { knownScientificMixedResponse } from "@/lib/scientific-mixed";

export default function SearchPage() {
  return (
    <Suspense fallback={<p className="text-sm text-slate-500">Loading…</p>}>
      <SearchForQuery />
    </Suspense>
  );
}

const Q_WORDS =
  /[?？]|\b(what|how|why|which|when|where|who|explain|describe|compare|list|summarize|can|does|is there|are there|tell me)\b|(?:什么|为什么|如何|哪些|哪个|哪一|怎样|怎么|多少|几个|是否|能否|有没有|请问|介绍|解释|比较|区别|关系|机制|原因)/i;

function isQuestion(q: string): boolean {
  if (Q_WORDS.test(q)) return true;
  // English: more than 6 space-separated words
  if (q.trim().split(/\s+/).length > 6) return true;
  // CJK: longer than 10 characters (Chinese doesn't use spaces)
  const cjkCount = (q.match(/[一-鿿]/g) || []).length;
  if (cjkCount > 10) return true;
  return false;
}

function SearchForQuery() {
  const params = useSearchParams();
  const q = params.get("q") ?? "";
  // Remount before rendering a different query: old results/interpretations
  // must not flash under the new URL while an effect is still pending.
  return <SearchInner key={q} q={q} />;
}

function SearchInner({ q }: { q: string }) {
  const [searchData, setSearchData] = useState<SearchResponse | null>(null);
  const [askData, setAskData] = useState<AskResponse | null>(null);
  const [searchErr, setSearchErr] = useState<string | null>(null);
  const [askErr, setAskErr] = useState<string | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const [askLoading, setAskLoading] = useState(false);
  const [manualAsk, setManualAsk] = useState(false);
  const mounted = useRef(false);
  const askVersion = useRef(0);
  const askController = useRef<AbortController | null>(null);

  const triggerAsk = useCallback((manual = true) => {
    if (!mounted.current || q.length < 2) return;
    const version = ++askVersion.current;
    askController.current?.abort();
    const controller = new AbortController();
    askController.current = controller;
    const current = () => mounted.current && version === askVersion.current;
    setManualAsk(manual);
    setAskLoading(true);
    setAskData(null);
    setAskErr(null);
    ask({ question: q, max_sources: 8 }, { signal: controller.signal })
      .then(data => { if (current()) setAskData(data); })
      .catch((error: unknown) => { if (current()) setAskErr(friendlyErrorMessage(error)); })
      .finally(() => { if (current()) setAskLoading(false); });
  }, [q]);

  useEffect(() => {
    mounted.current = true;
    let current = true;
    const controller = new AbortController();
    if (q.length >= 2) {
      setSearchLoading(true);
      setSearchErr(null);
      search({ query: q, top_k: 20, filters: { exclude_retracted: true } }, { signal: controller.signal })
        .then(data => { if (current) setSearchData(data); })
        .catch((error: unknown) => { if (current) setSearchErr(friendlyErrorMessage(error)); })
        .finally(() => { if (current) setSearchLoading(false); });
      if (isQuestion(q)) triggerAsk(false);
    }
    return () => {
      current = false;
      mounted.current = false;
      askVersion.current += 1;
      controller.abort();
      askController.current?.abort();
    };
  }, [q, triggerAsk]);

  const guestRemaining =
    searchData?.guest_remaining ?? askData?.guest_remaining;
  const showAskButton =
    q.length >= 2 && !isQuestion(q) && !askData && !askLoading && !manualAsk;
  const askQuery = knownScientificQuery(askData?.scientific_query, q);
  const askLookup = knownScientificLookup(askData?.scientific_lookup);
  const isStructuredAsk = askQuery !== null && askLookup !== null && askLookup.status !== "not_requested"
    && knownScientificResults(askData?.scientific_results, askLookup, askData?.retrieval_generation, askQuery) !== null;
  const mixed = askData ? knownScientificMixedResponse(askData, q) : null;
  const showMixed = askData?.scientific_mixed !== undefined && mixed?.status !== "not_requested";

  return (
    <main className="space-y-6">
      <div className="product-page-intro">
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Search</h1>
        {!q && <p className="mt-2 text-sm text-sage-muted">Find publications, material reports and answers grounded in the literature.</p>}
      </div>
      <SearchBar
        initial={q}
        placeholder="Search papers or materials, or just ask a question…"
      />

      {guestRemaining != null && <GuestBanner remaining={guestRemaining} />}

      {/* ── AI answer (auto for questions, manual trigger for keywords) ── */}
      {askLoading && (
        <div className="rounded-lg border border-sage-border bg-white p-6 shadow-sm">
          <div className="flex items-center gap-2 text-sm text-sage-muted">
            <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-accent border-t-transparent" />
            Preparing answer…
          </div>
        </div>
      )}

      {askErr && (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {askErr}
        </div>
      )}

      {askData && (
        <div className="rounded-lg border border-sage-border bg-white p-6 shadow-sm">
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-sage-tertiary">
            {showMixed ? "Separate numerical and original-source lookup" : isStructuredAsk ? "Source-linked extraction lookup" : "Answer"}
          </h2>
          {showMixed ? <ScientificMixedNotice response={askData} rawQuery={q} /> : <>
          <AskSupportNotice response={askData} />
          <EvidencePackingNotice packing={askData.evidence_packing} inputBudget={askData.input_budget} sources={askData.sources} />
          <ScientificQueryNotice context="Ask" rawQuery={q} query={askData.scientific_query}
            lookup={askData.scientific_lookup} results={askData.scientific_results} generation={askData.retrieval_generation} />
          <MarkdownAnswer markdown={askData.answer} sources={askData.sources} />
          <div className="mt-4 flex flex-wrap gap-2 border-t border-sage-border pt-4">
            {askData.sources.map((s, sourcePosition) => (
              <Link
                key={`${s.index}:${sourcePosition}`}
                id={resolveAskSource(s.index, askData.sources) ? `src-${s.index}` : undefined}
                href={`/paper/${encodeURIComponent(s.paper_id)}`}
                className="group flex max-w-sm flex-col items-start gap-1.5 rounded-md border border-sage-border px-2.5 py-1.5 text-xs transition-colors hover:bg-sage-bg"
              >
                <span className="font-semibold text-accent">[{s.index}]</span>
                <span className="max-w-[200px] truncate text-sage-muted group-hover:text-sage-ink">
                  {s.title}
                </span>
                {s.year && (
                  <span className="text-sage-tertiary">{s.year}</span>
                )}
                <SourceVisibilityNotice visibility={s.source_visibility} compact />
                <EvidenceProvenanceNotice evidence={s.evidence_provenance} />
                <PackingSourceNotice source={s} sources={askData.sources} />
              </Link>
            ))}
          </div>
          </>}
          <div className="mt-2 text-xs text-sage-tertiary">
            {askData.query_time_ms} ms{showMixed ? mixed ? " · No generation requested" : " · Mixed metadata withheld" : ` · ${askData.tokens_used ?? "—"} tokens`}
          </div>
          <HistorySaveNotice value={askData.history} />
        </div>
      )}

      {showAskButton && (
        <button
          onClick={() => triggerAsk()}
          className="rounded-md border border-sage-border bg-white px-4 py-2 text-sm text-sage-muted shadow-sm transition-colors hover:bg-sage-bg hover:text-sage-ink"
        >
          Summarize with AI
        </button>
      )}

      {/* ── Search results ── */}
      {searchLoading && (
        <p className="text-sm text-sage-muted">Searching…</p>
      )}
      {searchErr && (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {searchErr}
        </div>
      )}

      {searchData && <ScientificQueryNotice rawQuery={q} query={searchData.scientific_query}
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
                sourceVisibility={r.source_visibility}
                evidenceProvenance={r.evidence_provenance}
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

      {!q && (
        <p className="text-sm text-sage-muted">
          Enter a query above to start searching.
        </p>
      )}
    </main>
  );
}
