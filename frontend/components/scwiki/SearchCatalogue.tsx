"use client";
import {useMemo,useState} from "react";
import Link from "@/components/AppLink";
import {searchArticles} from "@/lib/scwiki/search";
import type {SearchEntry} from "@/lib/scwiki/types";
type Card=Pick<SearchEntry,"id"|"code"|"slug"|"title"|"summary"|"evidenceTypes">;
export function SearchCatalogue({initial}:{initial:Card[]}) {
 const [query,setQuery]=useState(""),[pressure,setPressure]=useState(""),[evidence,setEvidence]=useState(""),[equilibrium,setEquilibrium]=useState(""),[tcMin,setTcMin]=useState("");
 const [index,setIndex]=useState<SearchEntry[]|null>(null),[loading,setLoading]=useState(false),[error,setError]=useState(false);
 async function load(){
  if(index||loading)return;
  setLoading(true);setError(false);
  try{const response=await fetch("/scwiki/search-index.json");if(!response.ok)throw new Error();const data=await response.json();setIndex(data.entries);}
  catch{setError(true);}finally{setLoading(false);}
 }
 const active=Boolean(query||pressure||evidence||equilibrium||tcMin);
 const results=useMemo(()=>index?searchArticles(index,query,{pressure,evidence,equilibrium,tcMin:tcMin!==""?Number(tcMin):undefined}):[],[index,query,pressure,evidence,equilibrium,tcMin]);
 const cards:Card[]=active?results:initial;
 return <section aria-label="SCWiki article search">
  <div className="scwiki-search-panel" onFocus={()=>void load()}>
   <label htmlFor="scwiki-search">Search SCWiki</label>
   <input id="scwiki-search" type="search" value={query} onChange={e=>{setQuery(e.target.value);void load();}} onKeyDown={e=>{if(e.key==="Escape")setQuery("");}} placeholder="Try Meissner, FeSe, s± or a DOI" aria-describedby="scwiki-search-help" maxLength={200}/>
   <p id="scwiki-search-help" className="scwiki-muted">Search titles, aliases, chemical formulas and DOI. Scientific conditions apply to one material report.</p>
   <div className="scwiki-filters">
    <div><label htmlFor="scwiki-evidence">Evidence</label><select id="scwiki-evidence" value={evidence} onChange={e=>{setEvidence(e.target.value);void load();}}><option value="">All evidence types</option><option value="experiment">Experiment</option><option value="theory">Theory</option><option value="prediction">Prediction</option><option value="hypothesis">Hypothesis</option></select></div>
    <div><label htmlFor="scwiki-pressure">Pressure</label><select id="scwiki-pressure" value={pressure} onChange={e=>{setPressure(e.target.value);void load();}}><option value="">Any pressure</option><option value="ambient">Ambient</option><option value="high">High pressure</option><option value="unknown">Unknown</option></select></div>
    <div><label htmlFor="scwiki-equilibrium">State</label><select id="scwiki-equilibrium" value={equilibrium} onChange={e=>{setEquilibrium(e.target.value);void load();}}><option value="">Any state</option><option value="equilibrium">Equilibrium</option><option value="transient">Transient</option><option value="metastable">Metastable</option><option value="unknown">Unknown</option></select></div>
    <div><label htmlFor="scwiki-tc-min">Reported transition at least (K)</label><input id="scwiki-tc-min" type="number" min="0" max="1000" value={tcMin} onChange={e=>{setTcMin(e.target.value);void load();}} placeholder="Any transition"/></div>
   </div>
   {active&&<button type="button" className="scwiki-text-button" onClick={()=>{setQuery("");setPressure("");setEvidence("");setEquilibrium("");setTcMin("");}}>Clear filters</button>}
   {loading&&<p role="status">Loading the search index…</p>}
   {error&&<p role="alert">The search index could not be loaded. <button className="scwiki-text-button" onClick={()=>void load()}>Retry</button></p>}
  </div>
  <p className="scwiki-result-count" role="status" aria-live="polite">{active&&!index?"Search is loading":cards.length+" articles"+(active?" match your search":" in this pilot")}</p>
  {!cards.length&&active&&index&&<div className="scwiki-empty"><h2>No matching evidence</h2><p>Try fewer terms or remove a condition. Unknown conditions do not satisfy a specific filter; a high-pressure report cannot satisfy an ambient-pressure query.</p></div>}
  <ol className="scwiki-article-grid">
   {cards.map(article=><li key={article.id}><article className="scwiki-result"><p className="scwiki-article-code">{article.code} <span>{article.evidenceTypes.join(" / ")}</span></p><h2><Link href={"/scwiki/"+article.slug}>{article.title}</Link></h2><p>{article.summary}</p><Link href={"/scwiki/"+article.slug} className="scwiki-read-link" aria-label={"Read article: "+article.title}>Read article <span aria-hidden="true">↗</span></Link></article></li>)}
  </ol>
 </section>;
}
