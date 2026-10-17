import type {Metadata} from "next";
import Link from "@/components/AppLink";
import {SearchCatalogue} from "@/components/scwiki/SearchCatalogue";
import {LegacyDocsAnchors} from "@/components/scwiki/LegacyDocsAnchors";
import {articles,catalogue} from "@/lib/scwiki/catalogue";
import {absoluteUrl,serializeJsonLd} from "@/lib/seo";
import "./scwiki.css";
export const metadata:Metadata={title:"SCWiki | Superconductivity evidence and concepts",description:"Read evidence-aware superconductivity articles, compare experimental conditions, and retrieve cited sections as Markdown or JSON.",alternates:{canonical:absoluteUrl("/scwiki")},openGraph:{url:absoluteUrl("/scwiki"),locale:"en_US"}};
export default function SCWikiPage(){
 const entries=articles();
 const data={"@context":"https://schema.org","@type":"CollectionPage",name:"SCWiki",url:absoluteUrl("/scwiki"),description:metadata.description,hasPart:entries.map(a=>({"@type":"ScholarlyArticle",name:a.title,url:absoluteUrl("/scwiki/"+a.slug),dateModified:a.modifiedAt,identifier:a.id}))};
 return <main className="scwiki" data-revision={catalogue().revision}>
  <script type="application/ld+json" dangerouslySetInnerHTML={{__html:serializeJsonLd(data)}}/>
  <LegacyDocsAnchors/>
  <div className="scwiki-intro"><p className="scwiki-kicker">The superconductivity wiki</p><h1>SCWiki</h1><p>Understand the observations, models and open questions behind superconductivity. Follow each claim back to its source.</p></div>
  <aside className="scwiki-scope-note"><strong>A scoped editorial pilot.</strong> Twelve English articles distinguish experimental evidence, theory, predictions and hypotheses. Editorial checks and publication status are recorded separately; unverified source notes are identified.</aside>
  <div className="scwiki-resource-links"><Link href="/scwiki/using-sclib">Using SCLib</Link><Link href="/scwiki/agent-guide">For researchers and agents</Link><a href="/api/scwiki/v1/openapi.json">OpenAPI</a><Link href="/docs/data">Data &amp; methodology</Link></div>
  <SearchCatalogue initial={entries.map(({id,code,slug,title,summary,evidenceTypes})=>({id,code,slug,title,summary,evidenceTypes}))}/>
  <section className="scwiki-method-note"><h2>Compare conditions before numbers</h2><p>Resistance onset, zero resistance, magnetic shielding and a spectroscopic gap measure different things. Pressure, sample preparation and equilibrium or transient state travel with each material record. This pilot does not maintain an experimental record ranking.</p></section>
 </main>;
}
