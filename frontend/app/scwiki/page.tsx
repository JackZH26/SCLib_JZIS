import type {Metadata} from "next";
import Link from "@/components/AppLink";
import {SearchCatalogue} from "@/components/scwiki/SearchCatalogue";
import {LegacyDocsAnchors} from "@/components/scwiki/LegacyDocsAnchors";
import {articles,catalogue} from "@/lib/scwiki/catalogue";
import {formatResearchDate,topicGroups} from "@/lib/scwiki/home";
import highlights from "@/content/scwiki/research-highlights.json";
import {absoluteUrl,serializeJsonLd} from "@/lib/seo";
import "./scwiki.css";

export const metadata:Metadata={title:"SCWiki | The superconductivity wiki",description:"Explore superconductivity through core concepts, recent research and source-linked articles. Search the wiki and follow the evidence.",alternates:{canonical:absoluteUrl("/scwiki")},openGraph:{url:absoluteUrl("/scwiki"),locale:"en_US"}};

export default function SCWikiPage(){
 const entries=articles();
 const data={"@context":"https://schema.org","@type":"CollectionPage",name:"SCWiki",url:absoluteUrl("/scwiki"),description:metadata.description,hasPart:entries.map(a=>({"@type":"ScholarlyArticle",name:a.title,url:absoluteUrl("/scwiki/"+a.slug),dateModified:a.modifiedAt,identifier:a.id}))};
 return <main className="scwiki scwiki-home" data-revision={catalogue().revision}>
  <script type="application/ld+json" dangerouslySetInnerHTML={{__html:serializeJsonLd(data)}}/>
  <LegacyDocsAnchors/>
  <header className="scwiki-home-intro">
   <p className="scwiki-kicker">An open reference for superconductivity</p>
   <h1>SCWiki<span className="scwiki-title-dot" aria-hidden="true">.</span></h1>
   <p>Explore the concepts, materials and discoveries behind superconductivity.<br className="scwiki-desktop-break"/> Follow the connections. Go back to the evidence.</p>
  </header>
  <SearchCatalogue initial={entries.map(({id,code,slug,title,summary,evidenceTypes})=>({id,code,slug,title,summary,evidenceTypes}))}>
   <section className="scwiki-research" aria-labelledby="scwiki-research-heading">
    <div className="scwiki-section-heading"><div><p className="scwiki-eyebrow">From the literature</p><h2 id="scwiki-research-heading">Latest research</h2></div><p className="scwiki-updated">Selected papers · checked <time dateTime={highlights.checkedAt}>{formatResearchDate(highlights.checkedAt)}</time></p></div>
    <div className="scwiki-research-grid">
     {highlights.items.map((item,index)=><article className="scwiki-research-item" key={item.id}>
      <div className="scwiki-research-meta"><span aria-hidden="true">0{index+1}</span><time dateTime={item.publishedAt}>{formatResearchDate(item.publishedAt)}</time></div>
      <p className="scwiki-journal">{item.journal}</p>
      <h3><a href={item.url} title={item.paperTitle}>{item.title}<span aria-hidden="true"> ↗</span></a></h3>
      <p className="scwiki-research-summary">{item.summary}</p>
      <p className="scwiki-publication-status">{item.publicationLabel}</p>
      <a className="scwiki-paper-link" href={item.url} aria-label={"Read original paper: "+item.paperTitle}>Read original paper <span aria-hidden="true">↗</span></a>
      <details className="scwiki-research-evidence"><summary>Evidence &amp; context</summary><p>{item.limitation}</p><p>{item.verificationScope}</p><p className="scwiki-paper-title">{item.paperTitle}</p><p>DOI: <a href={"https://doi.org/"+item.doi}>{item.doi}</a></p><Link href={"/scwiki/"+item.topicSlug}>Explore: {item.topicLabel} →</Link></details>
     </article>)}
    </div>
    <p className="scwiki-selection-note">Editorial selections, not a popularity ranking. Summaries are scoped to the publisher abstracts; open each evidence note for limitations and publication status.</p>
   </section>
   <section className="scwiki-topics" aria-labelledby="scwiki-topics-heading">
    <div className="scwiki-section-heading"><div><p className="scwiki-eyebrow">A connected field</p><h2 id="scwiki-topics-heading">Explore the key concepts</h2></div><p className="scwiki-updated">Choose a keyword to open its wiki article.</p></div>
    <div className="scwiki-topic-grid">{topicGroups.map((group,index)=><nav className="scwiki-topic-group" key={group.id} aria-labelledby={"topic-"+group.id}>
     <p className="scwiki-topic-number" aria-hidden="true">0{index+1}</p><h3 id={"topic-"+group.id}>{group.title}</h3><p>{group.description}</p>
     <ul>{group.topics.map(topic=>{const article=entries.find(a=>a.code===topic.code)!;return <li key={topic.code}><Link href={"/scwiki/"+article.slug}>{topic.label}<span aria-hidden="true">↗</span></Link></li>;})}</ul>
    </nav>)}</div>
   </section>
  </SearchCatalogue>
  <aside className="scwiki-home-editorial" aria-labelledby="scwiki-editorial-heading">
   <div><p className="scwiki-eyebrow">A growing, source-linked reference</p><h2 id="scwiki-editorial-heading">Read with the evidence in view.</h2><p>{entries.length} articles are available in this editorial pilot. Each records its sources, review scope and open questions. Coverage and scientific review are still expanding.</p></div>
   <div className="scwiki-editorial-links"><Link href="/scwiki/using-sclib">How to use SCWiki <span aria-hidden="true">→</span></Link><Link href="/scwiki/agent-guide">For researchers &amp; agents <span aria-hidden="true">→</span></Link><Link href="/docs/data">Data &amp; methodology <span aria-hidden="true">→</span></Link><a href="/api/scwiki/v1/openapi.json">OpenAPI <span aria-hidden="true">→</span></a></div>
  </aside>
 </main>;
}
