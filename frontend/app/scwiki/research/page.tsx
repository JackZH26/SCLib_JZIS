import type {Metadata} from "next";
import Link from "@/components/AppLink";
import {ResearchArchive} from "@/components/scwiki/ResearchArchive";
import {researchCollection} from "@/lib/scwiki/research";
import {absoluteUrl} from "@/lib/seo";
import "../scwiki.css";
export const dynamic="force-dynamic";
export const metadata:Metadata={title:"Research archive | SCWiki",description:"Explore dated superconductivity research selections, original sources and evidence limits.",alternates:{canonical:absoluteUrl("/scwiki/research"),types:{"application/rss+xml":"/scwiki/research/feed.xml"}}};
export default function ResearchArchivePage(){
 const data=researchCollection();
 return <main className="scwiki scwiki-home"><p><Link href="/scwiki">← SCWiki</Link></p><header className="scwiki-home-intro"><p className="scwiki-kicker">From the literature</p><h1>Research archive</h1><p>Each edition preserves what was selected and when it was checked.<br/>Paper publication dates remain separate from recommendation dates.</p></header>
  <p>Editorial selections, not an exhaustive feed or popularity ranking. Subsequent corrections appear alongside the original record.</p>
  <p className="scwiki-research-links"><a href="/scwiki/research/feed.xml">Subscribe via RSS ↗</a><a href="/api/scwiki/v1/research">Browse JSON ↗</a></p>
  {data.warning&&<p role="status">{data.warning}</p>}
  <ResearchArchive issues={data.issues} notices={data.notices}/>
 </main>;
}
