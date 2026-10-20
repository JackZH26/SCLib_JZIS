"use client";
import {useEffect,useMemo,useState,type ReactNode} from "react";
import Link from "@/components/AppLink";
import {searchArticles,matchedPassage} from "@/lib/scwiki/search";
import type {SearchEntry} from "@/lib/scwiki/types";
type Card=Pick<SearchEntry,"id"|"code"|"slug"|"title"|"summary"|"evidenceTypes">;
export function SearchCatalogue({initial,children,researchCount=0}:{initial:Card[];children?:ReactNode;researchCount?:number}) {
 const [query,setQuery]=useState(""),[pressure,setPressure]=useState(""),[evidence,setEvidence]=useState(""),[equilibrium,setEquilibrium]=useState(""),[tcMin,setTcMin]=useState("");
 const [filtersOpen,setFiltersOpen]=useState(false);
 const [urlReady,setUrlReady]=useState(false);
 const [index,setIndex]=useState<SearchEntry[]|null>(null),[loading,setLoading]=useState(false),[error,setError]=useState(false);
 async function load(){
  if(index||loading)return;
  setLoading(true);setError(false);
  try{const response=await fetch("/scwiki/search-index.json");if(!response.ok)throw new Error();const data=await response.json();setIndex(data.entries);}
  catch{setError(true);}finally{setLoading(false);}
 }
 useEffect(()=>{
  function restore(){
   const p=new URLSearchParams(location.search),q=(p.get("q")||"").slice(0,200);
   const allowed=(key:string,values:string[])=>values.includes(p.get(key)||"")?p.get(key)!:"";
   const pressure=allowed("pressure",["ambient","high","unknown"]),evidence=allowed("evidence",["experiment","theory","prediction","hypothesis"]),equilibrium=allowed("equilibrium",["equilibrium","transient","metastable","unknown"]);
   const tc=p.get("tcMin")||"",validTc=/^(?:\d+(?:\.\d*)?|\.\d+)$/.test(tc)&&Number(tc)<=1000?tc:"";
   setQuery(q);setPressure(pressure);setEvidence(evidence);setEquilibrium(equilibrium);setTcMin(validTc);setUrlReady(true);
   if(pressure||evidence||equilibrium||validTc)setFiltersOpen(true);
   if(q||pressure||evidence||equilibrium||validTc)void load();
  }
  restore();addEventListener("popstate",restore);return()=>removeEventListener("popstate",restore);
 // Restore from the navigation entry, including when returning from a result.
 // eslint-disable-next-line react-hooks/exhaustive-deps
 },[]);
 useEffect(()=>{
  if(!urlReady)return;
  const url=new URL(location.href);
  for(const [key,value]of Object.entries({q:query,pressure,evidence,equilibrium,tcMin})){if(value)url.searchParams.set(key,value);else url.searchParams.delete(key);}
  history.replaceState(history.state,"",url);
 },[urlReady,query,pressure,evidence,equilibrium,tcMin]);
 const active=Boolean(query.trim()||pressure||evidence||equilibrium||tcMin);
 const results=useMemo(()=>index?searchArticles(index,query,{pressure,evidence,equilibrium,tcMin:tcMin!==""?Number(tcMin):undefined}):[],[index,query,pressure,evidence,equilibrium,tcMin]);
 function clear(){setQuery("");setPressure("");setEvidence("");setEquilibrium("");setTcMin("");}
 return <>
  <section aria-label="SCWiki article search" className="scwiki-home-search">
   <form className="scwiki-search-panel" onSubmit={e=>{e.preventDefault();void load();}} onFocus={()=>void load()} role="search">
    <label htmlFor="scwiki-search" className="sr-only">Search SCWiki</label>
    <div className="scwiki-search-bar"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></svg><input id="scwiki-search" type="search" value={query} onChange={e=>{setQuery(e.target.value);void load();}} onKeyDown={e=>{if(e.key==="Escape")clear();}} placeholder="Search concepts or materials" aria-describedby="scwiki-search-help" maxLength={200}/><button type="submit" className="scwiki-search-submit">Search</button></div>
    <div className="scwiki-search-options"><p id="scwiki-search-help">Search the full text of {initial.length} wiki articles{researchCount>0?" and "+researchCount+" research "+(researchCount===1?"note":"notes"):""}, their aliases and references.</p><button type="button" className="scwiki-filter-toggle" aria-expanded={filtersOpen} aria-controls="scwiki-filter-panel" onClick={()=>setFiltersOpen(!filtersOpen)}>Filters <span aria-hidden="true">{filtersOpen?"−":"+"}</span></button></div>
    {filtersOpen&&<div id="scwiki-filter-panel" className="scwiki-filters">
     <div><label htmlFor="scwiki-evidence">Evidence</label><select id="scwiki-evidence" value={evidence} onChange={e=>{setEvidence(e.target.value);void load();}}><option value="">All evidence types</option><option value="experiment">Experiment</option><option value="theory">Theory</option><option value="prediction">Prediction</option><option value="hypothesis">Hypothesis</option></select></div>
     <div><label htmlFor="scwiki-pressure">Pressure</label><select id="scwiki-pressure" value={pressure} onChange={e=>{setPressure(e.target.value);void load();}}><option value="">Any pressure</option><option value="ambient">Ambient</option><option value="high">High pressure</option><option value="unknown">Unknown</option></select></div>
     <div><label htmlFor="scwiki-equilibrium">State</label><select id="scwiki-equilibrium" value={equilibrium} onChange={e=>{setEquilibrium(e.target.value);void load();}}><option value="">Any state</option><option value="equilibrium">Equilibrium</option><option value="transient">Transient</option><option value="metastable">Metastable</option><option value="unknown">Unknown</option></select></div>
     <div><label htmlFor="scwiki-tc-min">Reported transition at least (K)</label><input id="scwiki-tc-min" type="number" min="0" max="1000" value={tcMin} onChange={e=>{setTcMin(e.target.value);void load();}} placeholder="Any transition"/></div>
    </div>}
    {active&&<button type="button" className="scwiki-text-button" onClick={clear}>Clear filters</button>}
    {loading&&<p role="status">Loading the search index…</p>}
    {error&&<p role="alert">The search index could not be loaded. <button type="button" className="scwiki-text-button" onClick={()=>void load()}>Retry</button></p>}
   </form>
   {active&&<div className="scwiki-search-results">
    <p className="scwiki-result-count" role="status" aria-live="polite">{error?"Search unavailable":!index?"Search is loading":results.length+" results match your search"}</p>
    {!results.length&&index&&<div className="scwiki-empty"><h2>No matching evidence</h2><p>Try fewer terms or remove a condition. Unknown conditions do not satisfy a specific filter; a high-pressure report cannot satisfy an ambient-pressure query.</p></div>}
    <ol className="scwiki-article-grid">{results.map(article=>{
     const match=matchedPassage(article,query),href="/scwiki/"+article.slug;
     return <li key={article.id}><article className="scwiki-result"><p className="scwiki-article-code">{article.kind==="weekly-selection"?"Weekly selection":article.kind==="research-note"?"Research note":article.code} <span>{article.evidenceTypes.join(" / ")}</span></p><h2><Link href={href}>{article.title}</Link></h2><p>{article.summary}</p>
      {article.notices?.map(notice=><aside className="scwiki-research-notice" key={notice}>{notice}</aside>)}
      {match&&<div className="scwiki-match-snippet"><p>{match.text}</p>{match.sectionId&&<Link href={href+"#"+match.sectionId}>Jump to: {match.sectionTitle} →</Link>}</div>}
      <Link href={href} className="scwiki-read-link" aria-label={"Read article: "+article.title}>{article.kind==="weekly-selection"?"Read selection":article.kind==="research-note"?"Read research note":"Read article"} <span aria-hidden="true">↗</span></Link></article></li>;
    })}</ol>
   </div>}
  </section>
  {!active&&children}
 </>;
}
