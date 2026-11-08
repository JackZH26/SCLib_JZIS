"use client";

import { type ReactNode, useEffect, useMemo, useState } from "react";
import Link from "@/components/AppLink";
import { LiteratureSearchResults, SearchResultColumns } from "@/components/SearchResultColumns";
import { matchedPassage, searchArticles } from "@/lib/scwiki/search";
import type { SearchEntry } from "@/lib/scwiki/types";

type Card = Pick<SearchEntry, "id" | "code" | "slug" | "title" | "summary" | "evidenceTypes">;

function WikiMatches({ results, query }: { results: SearchEntry[]; query: string }) {
  return <>
    <p className="text-sm text-sage-muted" role="status">
      {results.length} SCWiki {results.length === 1 ? "result" : "results"}
    </p>
    {results.length === 0 && <div className="scwiki-empty">
      <h4>No matching evidence</h4><p>Try fewer terms or remove a condition.</p>
    </div>}
    <ol className="scwiki-article-grid">{results.map(article => {
      const match = matchedPassage(article, query);
      const href = "/scwiki/" + article.slug;
      return <li key={article.id}><article className="scwiki-result">
        <p className="scwiki-article-code">
          {article.kind === "weekly-selection" ? "Weekly selection" : article.kind === "research-note" ? "Research note" : article.code}
          {" "}<span>{article.evidenceTypes.join(" / ")}</span>
        </p>
        <h4><Link href={href}>{article.title}</Link></h4><p>{article.summary}</p>
        {article.notices?.map(notice => <aside className="scwiki-research-notice" key={notice}>{notice}</aside>)}
        {match && <div className="scwiki-match-snippet">
          <p>{match.text}</p>
          {match.sectionId && <Link href={href + "#" + match.sectionId}>Jump to: {match.sectionTitle} →</Link>}
        </div>}
        <Link href={href} className="scwiki-read-link" aria-label={"Read article: " + article.title}>
          {article.kind === "weekly-selection" ? "Read selection" : article.kind === "research-note" ? "Read research note" : "Read article"} <span aria-hidden="true">↗</span>
        </Link>
      </article></li>;
    })}</ol>
  </>;
}

export function SearchCatalogue({ initial, children, researchCount = 0 }: {
  initial: Card[]; children?: ReactNode; researchCount?: number;
}) {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [pressure, setPressure] = useState("");
  const [evidence, setEvidence] = useState("");
  const [equilibrium, setEquilibrium] = useState("");
  const [tcMin, setTcMin] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [urlReady, setUrlReady] = useState(false);
  const [index, setIndex] = useState<SearchEntry[] | null>(null);
  const [indexRequested, setIndexRequested] = useState(false);
  const [indexAttempt, setIndexAttempt] = useState(0);
  const [indexError, setIndexError] = useState(false);

  useEffect(() => {
    if (!indexRequested) return;
    const controller = new AbortController();
    fetch(`${process.env.NEXT_PUBLIC_BASE_PATH || ""}/scwiki/search-index.json`, { signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error("Index unavailable");
        const data = await response.json();
        if (!Array.isArray(data.entries)) throw new Error("Invalid index");
        if (!controller.signal.aborted) setIndex(data.entries);
      })
      .catch(() => { if (!controller.signal.aborted) setIndexError(true); });
    return () => controller.abort();
  }, [indexRequested, indexAttempt]);

  useEffect(() => {
    function restore() {
      const p = new URLSearchParams(location.search);
      const q = (p.get("q") || "").slice(0, 200);
      const allowed = (key: string, values: string[]) => values.includes(p.get(key) || "") ? p.get(key)! : "";
      const pressure = allowed("pressure", ["ambient", "high", "unknown"]);
      const evidence = allowed("evidence", ["experiment", "theory", "prediction", "hypothesis"]);
      const equilibrium = allowed("equilibrium", ["equilibrium", "transient", "metastable", "unknown"]);
      const tc = p.get("tcMin") || "";
      const validTc = /^(?:\d+(?:\.\d*)?|\.\d+)$/.test(tc) && Number(tc) <= 1000 ? tc : "";
      setQuery(q); setSubmitted(q.trim());
      setPressure(pressure); setEvidence(evidence); setEquilibrium(equilibrium); setTcMin(validTc);
      setFiltersOpen(Boolean(pressure || evidence || equilibrium || validTc));
      if (q.trim() || pressure || evidence || equilibrium || validTc) setIndexRequested(true);
      setUrlReady(true);
    }
    restore();
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);

  useEffect(() => {
    if (!urlReady) return;
    const url = new URL(location.href);
    for (const [key, value] of Object.entries({ q: query, pressure, evidence, equilibrium, tcMin })) {
      if (value) url.searchParams.set(key, value);
      else url.searchParams.delete(key);
    }
    history.replaceState(history.state, "", url);
  }, [urlReady, query, pressure, evidence, equilibrium, tcMin]);

  const term = query.trim();
  const active = Boolean(term || pressure || evidence || equilibrium || tcMin);
  const results = useMemo(() => index ? searchArticles(index, term, {
    pressure, evidence, equilibrium, tcMin: tcMin !== "" ? Number(tcMin) : undefined,
  }) : [], [index, term, pressure, evidence, equilibrium, tcMin]);

  function clear() {
    setQuery(""); setSubmitted(""); setPressure(""); setEvidence(""); setEquilibrium(""); setTcMin("");
  }

  return <>
    <section aria-label="SCWiki article search" className="scwiki-home-search">
      <form className="scwiki-search-panel" role="search" onFocus={() => setIndexRequested(true)} onSubmit={event => {
        event.preventDefault();
        setIndexRequested(true);
        setSubmitted(term);
      }}>
        <label htmlFor="scwiki-search" className="sr-only">Search SCWiki</label>
        <div className="scwiki-search-bar">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></svg>
          <input id="scwiki-search" type="search" value={query} onChange={event => {
            const value = event.target.value;
            setQuery(value);
            if (value.trim() !== submitted) setSubmitted("");
            setIndexRequested(true);
          }} onKeyDown={event => { if (event.key === "Escape") clear(); }}
            placeholder="Search papers, concepts or materials" aria-describedby="scwiki-search-help" maxLength={200}/>
          <button type="submit" className="scwiki-search-submit">Search</button>
        </div>
        <div className="scwiki-search-options">
          <p id="scwiki-search-help">Search papers and the full text of {initial.length} wiki articles{researchCount > 0 ? " and " + researchCount + " research " + (researchCount === 1 ? "note" : "notes") : ""}. Filters apply to SCWiki.</p>
          <button type="button" className="scwiki-filter-toggle" aria-expanded={filtersOpen} aria-controls="scwiki-filter-panel" onClick={() => setFiltersOpen(!filtersOpen)}>Filters <span aria-hidden="true">{filtersOpen ? "−" : "+"}</span></button>
        </div>
        {filtersOpen && <div id="scwiki-filter-panel" className="scwiki-filters" onChange={() => setIndexRequested(true)}>
          <div><label htmlFor="scwiki-evidence">Evidence</label><select id="scwiki-evidence" value={evidence} onChange={e => setEvidence(e.target.value)}><option value="">All evidence types</option><option value="experiment">Experiment</option><option value="theory">Theory</option><option value="prediction">Prediction</option><option value="hypothesis">Hypothesis</option></select></div>
          <div><label htmlFor="scwiki-pressure">Pressure</label><select id="scwiki-pressure" value={pressure} onChange={e => setPressure(e.target.value)}><option value="">Any pressure</option><option value="ambient">Ambient</option><option value="high">High pressure</option><option value="unknown">Unknown pressure</option></select></div>
          <div><label htmlFor="scwiki-equilibrium">State</label><select id="scwiki-equilibrium" value={equilibrium} onChange={e => setEquilibrium(e.target.value)}><option value="">Any state</option><option value="equilibrium">Equilibrium</option><option value="transient">Transient</option><option value="metastable">Metastable</option><option value="unknown">Unknown state</option></select></div>
          <div><label htmlFor="scwiki-tc-min">Reported transition at least (K)</label><input id="scwiki-tc-min" type="number" min="0" max="1000" value={tcMin} onChange={e => setTcMin(e.target.value)} placeholder="Any transition"/></div>
        </div>}
        {active && <button type="button" className="scwiki-text-button" onClick={clear}>Clear filters</button>}
      </form>
      {active && <div className="scwiki-search-results">
        <SearchResultColumns query={term} wiki={
          indexError ? <p role="alert">The Wiki search index could not be loaded. <button type="button" className="scwiki-text-button" onClick={() => { setIndexError(false); setIndexAttempt(x => x + 1); }}>Retry</button></p>
          : index ? <WikiMatches results={results} query={term}/>
          : <p role="status">Searching SCWiki…</p>
        }>
          {submitted.length >= 2 && submitted === term
            ? <LiteratureSearchResults key={submitted} query={submitted}/>
            : <p className="text-sm text-sage-muted">{term.length < 2 ? "Enter at least two characters to search papers." : "Select Search or press Enter to find papers."}</p>}
        </SearchResultColumns>
      </div>}
    </section>
    {!active && children}
  </>;
}
