"use client";
import {useEffect,useMemo,useState} from "react";
import Link from "@/components/AppLink";
import {normalizeSearch} from "@/lib/scwiki/search";
import {formatResearchDate} from "@/lib/scwiki/home";
import {ResearchCards} from "./ResearchCards";
import type {ResearchIssue,ResearchNotice} from "@/lib/scwiki/research-types";
export function ResearchArchive({issues,notices}:{issues:ResearchIssue[];notices:ResearchNotice[]}) {
 const [q,setQ]=useState(""),[topic,setTopic]=useState(""),[year,setYear]=useState(""),[ready,setReady]=useState(false);
 useEffect(()=>{const restore=()=>{const p=new URLSearchParams(location.search);setQ((p.get("q")||"").slice(0,200));setTopic(p.get("topic")||"");setYear(p.get("year")||"");setReady(true);};restore();addEventListener("popstate",restore);return()=>removeEventListener("popstate",restore);},[]);
 useEffect(()=>{if(!ready)return;const u=new URL(location.href);for(const [k,v]of Object.entries({q,topic,year})){if(v)u.searchParams.set(k,v);else u.searchParams.delete(k);}history.replaceState(history.state,"",u);},[q,topic,year,ready]);
 const topics=[...new Map(issues.flatMap(i=>i.items.map(p=>[p.topicSlug,p.topicLabel] as const))).entries()].sort((a,b)=>a[1].localeCompare(b[1]));
 const filtered=useMemo(()=>issues.filter(i=>!year||i.selectedAt.startsWith(year)).map(issue=>({...issue,items:issue.items.filter(item=>(!topic||item.topicSlug===topic)&&normalizeSearch([item.title,item.paperTitle,item.summary,item.whyItMatters,item.doi||"",item.arxivId||"",issue.id].join(" ")).includes(normalizeSearch(q)))})).filter(i=>i.items.length||i.outcome==="no-new-selection"&&!q&&!topic),[issues,q,topic,year]);
 return <>
  <form className="scwiki-archive-filters" role="search" onSubmit={e=>e.preventDefault()}>
   <div><label htmlFor="research-query">Search past selections</label><input id="research-query" type="search" maxLength={200} value={q} onChange={e=>setQ(e.target.value)} placeholder="Title, topic, DOI or issue"/></div>
   <div><label htmlFor="research-topic">Topic</label><select id="research-topic" value={topic} onChange={e=>setTopic(e.target.value)}><option value="">All topics</option>{topics.map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></div>
   <div><label htmlFor="research-year">Selection year</label><select id="research-year" value={year} onChange={e=>setYear(e.target.value)}><option value="">All years</option>{[...new Set(issues.map(i=>i.selectedAt.slice(0,4)))].map(y=><option key={y}>{y}</option>)}</select></div>
   <button type="button" className="scwiki-text-button" onClick={()=>{setQ("");setTopic("");setYear("");}}>Clear filters</button>
  </form>
  <p role="status">{filtered.length} {filtered.length===1?"edition":"editions"} · {filtered.reduce((n,i)=>n+i.items.length,0)} selections</p>
  {!filtered.length&&<p className="scwiki-empty">No selections match these filters. Try another topic or clear the search.</p>}
  {filtered.map(issue=><section key={issue.id} className="scwiki-archive-issue" aria-labelledby={"issue-"+issue.id}>
   <p className="scwiki-eyebrow">Selected {formatResearchDate(issue.selectedAt)} · {issue.id}</p>
   <h2 id={"issue-"+issue.id}><Link href={"/scwiki/research/"+issue.id}>{issue.title} →</Link></h2>
   {issue.outcome==="no-new-selection"?<p>No new selections. {issue.editorialNote}</p>:<ResearchCards items={issue.items} notices={notices}/>}
  </section>)}
 </>;
}
