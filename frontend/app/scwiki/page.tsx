import {libraryNotes} from "@/lib/scwiki/library";
import type {Metadata} from "next";
import Link from "@/components/AppLink";
import {SearchCatalogue} from "@/components/scwiki/SearchCatalogue";
import {LegacyDocsAnchors} from "@/components/scwiki/LegacyDocsAnchors";
import {TopicGrid} from "@/components/scwiki/TopicGrid";
import {articles,catalogue} from "@/lib/scwiki/catalogue";
import {formatResearchDate,topicGroups} from "@/lib/scwiki/home";
import {researchCollection} from "@/lib/scwiki/research";
import {ResearchCards} from "@/components/scwiki/ResearchCards";
import {absoluteUrl,serializeJsonLd} from "@/lib/seo";
import "./scwiki.css";

export const dynamic="force-dynamic";
export const metadata:Metadata={title:"SCWiki | The superconductivity wiki",description:"Explore superconductivity through core concepts, recent research and source-linked articles. Search the wiki and follow the evidence.",alternates:{canonical:absoluteUrl("/scwiki")},openGraph:{url:absoluteUrl("/scwiki"),locale:"en_US"}};

export default function SCWikiPage(){
 const entries=articles();
 let research:ReturnType<typeof researchCollection>|null=null;
 try{research=researchCollection();}catch{}
 const latest=research?.issues[0];
 const data={"@context":"https://schema.org","@type":"CollectionPage",name:"SCWiki",url:absoluteUrl("/scwiki"),description:metadata.description,hasPart:entries.map(a=>({"@type":"ScholarlyArticle",name:a.title,url:absoluteUrl("/scwiki/"+a.slug),dateModified:a.modifiedAt,identifier:a.id}))};
 return <main className="scwiki scwiki-home" data-revision={catalogue().revision}>
  <script type="application/ld+json" dangerouslySetInnerHTML={{__html:serializeJsonLd(data)}}/>
  <LegacyDocsAnchors/>
  <header className="scwiki-home-intro">
   <p className="scwiki-kicker">An open reference for superconductivity</p>
   <h1>SCWiki<span className="scwiki-title-dot" aria-hidden="true">.</span></h1>
   <p>Reference articles on superconductivity: physical concepts, material families,<br className="scwiki-desktop-break"/> measurement methods and research evidence.</p>
  </header>
  <SearchCatalogue researchCount={libraryNotes.length} initial={entries.map(({id,code,slug,title,summary,evidenceTypes})=>({id,code,slug,title,summary,evidenceTypes}))}>
   <section className="scwiki-research" aria-labelledby="scwiki-research-heading">
    <div className="scwiki-section-heading"><div><p className="scwiki-eyebrow">From the literature</p><h2 id="scwiki-research-heading">Latest research</h2></div>{latest&&<p className="scwiki-updated">{latest.id} · Selected <time dateTime={latest.selectedAt}>{formatResearchDate(latest.selectedAt)}</time><br/>Sources checked {formatResearchDate(latest.checkedAt)}</p>}</div>
    {research?.warning&&<p role="status">{research.warning}</p>}
    {!latest?<p role="status">Research selections are temporarily unavailable. Please check again shortly.</p>:latest.outcome==="no-new-selection"?<p>No new selections in this edition. {latest.editorialNote}</p>:<ResearchCards items={latest.items.slice(0,3)} notices={research?.notices}/>}
    <p className="scwiki-selection-note">Editorial selections, not a popularity ranking. Each evidence note states what was checked and what remains uncertain.</p>
    <nav className="scwiki-research-links" aria-label="Research archive">{latest&&<Link href={"/scwiki/research/"+latest.id}>View this edition →</Link>}<Link href="/scwiki/research">Past selections →</Link><a href="/scwiki/research/feed.xml">RSS ↗</a></nav>
   </section>
   <section className="scwiki-topics" aria-labelledby="scwiki-topics-heading">
    <div className="scwiki-section-heading"><div><p className="scwiki-eyebrow">Superconductivity topics</p><h2 id="scwiki-topics-heading">Explore the key concepts</h2></div><p className="scwiki-updated">Choose a keyword to open its wiki article.</p></div>
    <TopicGrid>{topicGroups.map((group,index)=><nav className="scwiki-topic-group" key={group.id} aria-labelledby={"topic-"+group.id}>
     <p className="scwiki-topic-number" aria-hidden="true">0{index+1}</p><h3 id={"topic-"+group.id}>{group.title}</h3><p>{group.description}</p>
     <ul>{group.topics.slice(0,group.topics.length>16?12:undefined).map(topic=>{const article=entries.find(a=>a.code===topic.code)!;return <li key={topic.code}><Link href={"/scwiki/"+article.slug}>{topic.label}<span aria-hidden="true">↗</span></Link></li>;})}</ul>
     {group.topics.length>16&&<details className="scwiki-more-topics"><summary>More topics ({group.topics.length-12})</summary><ul>{group.topics.slice(12).map(topic=>{const article=entries.find(a=>a.code===topic.code)!;return <li key={topic.code}><Link href={"/scwiki/"+article.slug}>{topic.label}<span aria-hidden="true">↗</span></Link></li>;})}</ul></details>}
    </nav>)}</TopicGrid>
   </section>
  </SearchCatalogue>
  <aside className="scwiki-home-editorial" aria-labelledby="scwiki-editorial-heading">
   <div><p className="scwiki-eyebrow">A growing, source-linked reference</p><h2 id="scwiki-editorial-heading">Sources and scientific review</h2><p>{entries.length} articles are available in this editorial pilot. Each records its sources, review scope and open questions. Coverage and scientific review are still expanding.</p></div>
   <div className="scwiki-editorial-links"><Link href="/scwiki/library">Research library &amp; cross-topic analyses <span aria-hidden="true">→</span></Link><Link href="/scwiki/using-sclib">How to use SCWiki <span aria-hidden="true">→</span></Link><Link href="/scwiki/agent-guide">For researchers &amp; agents <span aria-hidden="true">→</span></Link><Link href="/docs/data">Data &amp; methodology <span aria-hidden="true">→</span></Link><a href="/api/scwiki/v1/openapi.json">OpenAPI <span aria-hidden="true">→</span></a></div>
  </aside>
 </main>;
}
