"use client";
import { useEffect, useState } from "react";
import Link from "@/components/AppLink";
import { searchArticles } from "@/lib/scwiki/search";
import type { SearchEntry } from "@/lib/scwiki/types";

/** Independent from the literature service: either collection can remain usable. */
export function WikiSearchResults({ query }: { query: string }) {
  const [results, setResults] = useState<SearchEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [visible, setVisible] = useState(10);
  useEffect(() => {
    let current = true;
    const controller = new AbortController();
    setLoading(true); setError(false); setResults([]); setVisible(10);
    fetch(`${process.env.NEXT_PUBLIC_BASE_PATH || ""}/scwiki/search-index.json`, { signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error("Index unavailable");
        const data = await response.json();
        if (!Array.isArray(data.entries)) throw new Error("Invalid index");
        const matches = searchArticles(data.entries, query);
        if (current) setResults(matches);
      })
      .catch(() => { if (current) setError(true); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; controller.abort(); };
  }, [query, attempt]);
  return <section aria-labelledby="wiki-results-heading" className="min-w-0 space-y-6 rounded-xl bg-sage-surface p-5 sm:p-6">
    <h3 id="wiki-results-heading" className="text-xl font-semibold">SCWiki</h3>
    <p className="text-sm text-sage-muted">Concepts and research notes, with sources and review limits. Ranked separately from paper passages.</p>
    {loading && <p role="status">Searching SCWiki…</p>}
    {error && <p role="alert">SCWiki search is temporarily unavailable. <button className="underline" onClick={() => setAttempt(value => value + 1)}>Retry SCWiki</button></p>}
    {!loading && !error && <>
      <p role="status" className="text-sm text-sage-muted">{results.length} SCWiki {results.length === 1 ? "result" : "results"}</p>
      {results.length === 0 && <p>No matching wiki articles or research notes. Try a related concept or fewer terms.</p>}
      <ol className="space-y-4">{results.slice(0, visible).map(result => <li key={result.id} className="rounded-lg border border-sage-border bg-white p-5">
        <p className="mb-2 text-xs text-sage-muted">{result.code === "Research note" ? "Research note" : "Wiki article · " + result.code}</p>
        <h4 className="font-semibold"><Link className="site-text-link" href={"/scwiki/" + result.slug}>{result.title}</Link></h4>
        <p className="mt-2 text-sm leading-relaxed text-sage-muted">{result.summary}</p>
        <p className="mt-3 text-xs text-sage-muted">{result.evidenceTypes.join(" / ")} · Scoped editorial review</p>
      </li>)}</ol>
      {visible < results.length && <button className="site-text-link text-sm font-semibold" onClick={() => setVisible(count => count + 10)}>Show more SCWiki results</button>}
    </>}
  </section>;
}
