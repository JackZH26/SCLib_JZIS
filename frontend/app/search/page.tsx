"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  search,
  ask,
  type SearchResponse,
  type AskResponse,
  friendlyErrorMessage,
} from "@/lib/api";
import { loadToken } from "@/lib/auth-storage";
import { SearchBar } from "@/components/SearchBar";
import { PaperCard } from "@/components/PaperCard";
import { GuestBanner } from "@/components/GuestBanner";
import { MarkdownAnswer } from "@/components/MarkdownAnswer";

export default function SearchPage() {
  return (
    <Suspense fallback={<p className="text-sm text-slate-500">Loading…</p>}>
      <SearchInner />
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

function SearchInner() {
  const params = useSearchParams();
  const q = params.get("q") ?? "";

  const [searchData, setSearchData] = useState<SearchResponse | null>(null);
  const [askData, setAskData] = useState<AskResponse | null>(null);
  const [searchErr, setSearchErr] = useState<string | null>(null);
  const [askErr, setAskErr] = useState<string | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const [askLoading, setAskLoading] = useState(false);
  const [manualAsk, setManualAsk] = useState(false);

  useEffect(() => {
    if (q.length < 2) {
      setSearchData(null);
      setAskData(null);
      setManualAsk(false);
      return;
    }

    setSearchLoading(true);
    setSearchErr(null);
    setSearchData(null);
    setAskData(null);
    setAskErr(null);
    setManualAsk(false);

    const token = loadToken() ?? undefined;

    search(
      { query: q, top_k: 20, filters: { exclude_retracted: true } },
      { auth: token },
    )
      .then(setSearchData)
      .catch((e: unknown) => setSearchErr(friendlyErrorMessage(e)))
      .finally(() => setSearchLoading(false));

    if (isQuestion(q)) {
      setAskLoading(true);
      ask({ question: q, max_sources: 8 }, { auth: token })
        .then(setAskData)
        .catch((e: unknown) => setAskErr(friendlyErrorMessage(e)))
        .finally(() => setAskLoading(false));
    }
  }, [q]);

  function triggerAsk() {
    setManualAsk(true);
    setAskLoading(true);
    setAskErr(null);
    const token = loadToken() ?? undefined;
    ask({ question: q, max_sources: 8 }, { auth: token })
      .then(setAskData)
      .catch((e: unknown) => setAskErr(friendlyErrorMessage(e)))
      .finally(() => setAskLoading(false));
  }

  const guestRemaining =
    searchData?.guest_remaining ?? askData?.guest_remaining;
  const showAskButton =
    q.length >= 2 && !isQuestion(q) && !askData && !askLoading && !manualAsk;

  return (
    <main className="space-y-6">
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
            Generating AI answer…
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
            AI Answer
          </h2>
          <MarkdownAnswer markdown={askData.answer} sources={askData.sources} />
          <div className="mt-4 flex flex-wrap gap-2 border-t border-sage-border pt-4">
            {askData.sources.map((s) => (
              <a
                key={s.index}
                id={`src-${s.index}`}
                href={`/paper/${encodeURIComponent(s.paper_id)}`}
                className="group flex items-baseline gap-1.5 rounded-md border border-sage-border px-2.5 py-1.5 text-xs transition-colors hover:bg-sage-bg"
              >
                <span className="font-semibold text-accent">[{s.index}]</span>
                <span className="max-w-[200px] truncate text-sage-muted group-hover:text-sage-ink">
                  {s.title}
                </span>
                {s.year && (
                  <span className="text-sage-tertiary">{s.year}</span>
                )}
              </a>
            ))}
          </div>
          <div className="mt-2 text-xs text-sage-tertiary">
            {askData.query_time_ms} ms · {askData.tokens_used ?? "—"} tokens
          </div>
        </div>
      )}

      {showAskButton && (
        <button
          onClick={triggerAsk}
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

      {searchData && searchData.results.length === 0 && (
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
