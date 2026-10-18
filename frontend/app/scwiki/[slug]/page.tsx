import type {Metadata} from "next";
import {notFound} from "next/navigation";
import Link from "@/components/AppLink";
import {ScientificMarkdown} from "@/components/scwiki/ScientificMarkdown";
import {articleById,articles} from "@/lib/scwiki/catalogue";
import {absoluteUrl,serializeJsonLd} from "@/lib/seo";
import "../scwiki.css";
export const dynamicParams=false;
export function generateStaticParams(){return articles().filter(a=>!a.slug.includes("/")).map(a=>({slug:a.slug}));}
export async function generateMetadata({params}:{params:Promise<{slug:string}>}):Promise<Metadata>{
 const article=articleById((await params).slug);if(!article)notFound();
 return {title:article.title+" | SCWiki",description:article.summary,alternates:{canonical:absoluteUrl("/scwiki/"+article.slug)},openGraph:{type:"article",url:absoluteUrl("/scwiki/"+article.slug),modifiedTime:article.modifiedAt,locale:"en_US"}};
}
export default async function ArticlePage({params}:{params:Promise<{slug:string}>}){
 const article=articleById((await params).slug);if(!article)notFound();
 const structured={"@context":"https://schema.org","@type":"ScholarlyArticle",headline:article.title,description:article.summary,url:absoluteUrl("/scwiki/"+article.slug),identifier:article.id,inLanguage:"en",dateModified:article.modifiedAt,version:article.revision,citation:article.references.map(r=>({"@type":"ScholarlyArticle",name:r.title,identifier:r.doi??r.url,url:r.url,...(r.retraction?{creativeWorkStatus:"Retracted"}:{})})),isPartOf:{"@type":"WebSite",name:"SCWiki",url:absoluteUrl("/scwiki")}};
 const conditionSection=article.sections.find(s=>s.id==="material-cases")!;
 return <main className="scwiki" data-article-id={article.id} data-revision={article.revision}>
  <script type="application/ld+json" dangerouslySetInnerHTML={{__html:serializeJsonLd(structured)}}/>
  <nav aria-label="Breadcrumb" className="scwiki-breadcrumb"><Link href="/scwiki">SCWiki</Link><span aria-hidden="true">/</span><span>{article.code}</span></nav>
  <header className="scwiki-article-header"><p className="scwiki-article-code">{article.code} <span>{article.evidenceTypes.join(" / ")}</span></p><h1>{article.title}</h1><p className="scwiki-summary">{article.summary}</p><p className="scwiki-muted">Editorial check: scoped review. Updated <time dateTime={article.modifiedAt}>{new Date(article.modifiedAt).toLocaleDateString("en-GB",{day:"numeric",month:"long",year:"numeric",timeZone:"UTC"})}</time>.</p><div className="scwiki-resource-links"><a href={"/api/scwiki/v1/articles/"+article.id+"/markdown"}>Read Markdown</a><a href={"/api/scwiki/v1/articles/"+article.id}>Read JSON</a><a href="#revision-and-review">Review scope &amp; provenance</a></div></header>
  <aside className="scwiki-scope-note"><strong>Review scope:</strong> {article.review.scope} {article.review.limitations[0]}</aside>
  <div className="scwiki-reading-layout">
   <aside className="scwiki-contents"><details open><summary>On this page</summary><nav aria-label="Article contents"><ol>{article.sections.map(s=><li key={s.id}><a href={"#"+s.id}>{s.title}</a></li>)}<li><a href="#sources">Sources</a></li><li><a href="#revision-and-review">Revision and review</a></li></ol></nav></details></aside>
   <article className="scwiki-reading-body">
    <ScientificMarkdown markdown={article.body+"\n\n"+conditionSection.markdown}/>
    <section className="scwiki-sources" aria-labelledby="sources"><h2 id="sources">Sources</h2><p className="scwiki-muted">Publication status describes the source. The check label describes this pilot's review, not peer review of this article.</p><ol>{article.references.map((ref,i)=><li id={"ref-"+ref.id} key={ref.id}><strong>[R{i+1}] {ref.title}</strong> <span>({ref.year??"Publication date unknown"})</span><p><a href={ref.url}>{ref.doi?"DOI "+ref.doi:"Source publication"}</a></p><p className="scwiki-muted">Publication: {ref.publicationStatus}. {ref.retraction&&<>Retracted on <time dateTime={ref.retraction.retractedAt}>{ref.retraction.retractedAt}</time>. <a href={ref.retraction.evidenceUrl}>Retraction notice</a>. </>}Check: {ref.verification.scope}. {ref.verification.note}</p></li>)}</ol></section>
    <section className="scwiki-review" aria-labelledby="revision-and-review"><h2 id="revision-and-review">Revision and review</h2><p>{article.review.scope}</p><ul>{article.review.limitations.map(note=><li key={note}>{note}</li>)}</ul><dl><div><dt>Article ID</dt><dd><code>{article.id}</code></dd></div><div><dt>Revision</dt><dd><code>{article.revision}</code></dd></div><div><dt>Pinned source</dt><dd><a href={"https://github.com/"+article.provenance.repository+"/blob/"+article.provenance.commit+"/"+article.provenance.path}>{article.provenance.path}</a></dd></div><div><dt>Source commit</dt><dd><code>{article.provenance.commit}</code></dd></div><div><dt>Source SHA-256</dt><dd><code>{article.provenance.sha256}</code></dd></div></dl>{article.corrections.length>0&&<><h3>Scientific corrections</h3><ul>{article.corrections.map(item=><li key={item.id}>{item.description}</li>)}</ul></>}{article.scopeItems&&<><h3>Approved scope items</h3><ul>{article.scopeItems.map(item=><li key={item.id}><strong>{item.id}</strong>: {item.scope} Checked {item.checkedAt}.<ul>{item.limitations.map(limit=><li key={limit}>{limit}</li>)}</ul></li>)}</ul></>}<details><summary>Source and editorial mapping</summary><p>{article.publicationKind?"The pinned planning document identifies the approved scope. Scientific content is newly authored from the cited research; the plan is not evidence for those claims.":"This is an edited English adaptation. Omitted source sections are not asserted by this article."}</p><ul>{article.sourceMap.map((map,i)=><li key={i}>Source lines {map.startLine}-{map.endLine}: {map.decision}. {map.note}</li>)}</ul></details></section>
   </article>
  </div>
 </main>;
}
