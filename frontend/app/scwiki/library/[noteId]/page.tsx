import type {Metadata} from "next";
import {notFound} from "next/navigation";
import Link from "@/components/AppLink";
import {ScientificMarkdown} from "@/components/scwiki/ScientificMarkdown";
import {libraryNote,libraryNotes} from "@/lib/scwiki/library";
import {articles} from "@/lib/scwiki/catalogue";
import {absoluteUrl,serializeJsonLd} from "@/lib/seo";
import "../../scwiki.css";
export const dynamicParams=false;
export function generateStaticParams(){return libraryNotes.map(n=>({noteId:n.id}));}
export async function generateMetadata({params}:{params:Promise<{noteId:string}>}):Promise<Metadata>{const n=libraryNote((await params).noteId);if(!n)notFound();return {title:n.title+" | SCWiki research library",description:n.summary,alternates:{canonical:absoluteUrl("/scwiki/library/"+n.id)}};}
export default async function NotePage({params}:{params:Promise<{noteId:string}>}){
 const note=libraryNote((await params).noteId);if(!note)notFound();
 const related=articles().filter(a=>note.relatedCodes.includes(a.code));
 return <main className="scwiki" data-revision={note.revision}>
 <script type="application/ld+json" dangerouslySetInnerHTML={{__html:serializeJsonLd({"@context":"https://schema.org","@type":"Article",headline:note.title,description:note.summary,inLanguage:"en",url:absoluteUrl("/scwiki/library/"+note.id),version:note.revision,dateModified:note.modifiedAt,citation:note.sources.map(s=>({"@type":"ScholarlyArticle",name:s.title,url:s.url}))})}}/>
 <nav className="scwiki-breadcrumb" aria-label="Breadcrumb"><Link href="/scwiki">SCWiki</Link><span>/</span><Link href="/scwiki/library">Research library</Link></nav>
 <header className="scwiki-article-header"><p className="scwiki-kicker">Research note &amp; cross-topic analysis</p><h1>{note.title}</h1><p className="scwiki-summary">{note.summary}</p><div className="scwiki-resource-links"><a href={"/api/scwiki/v1/library/"+note.id}>Read JSON</a><a href={"/api/scwiki/v1/library/"+note.id+"/markdown"}>Read Markdown</a></div></header>
 <aside className="scwiki-scope-note"><strong>Review scope:</strong> {note.review.scope}<ul>{note.review.limitations.map(x=><li key={x}>{x}</li>)}</ul></aside>
 <div className="scwiki-reading-layout"><aside className="scwiki-contents"><nav aria-label="Note contents"><ol>{note.sections.map(s=><li key={s.id}><a href={"#"+s.id}>{s.title}</a></li>)}<li><a href="#sources">Sources</a></li><li><a href="#related-topics">Related topics</a></li></ol></nav></aside>
 <article className="scwiki-reading-body scwiki-library-reading">{note.sections.map(s=><section key={s.id}><h2 id={s.id}>{s.title}</h2><ScientificMarkdown markdown={s.markdown}/><p className="scwiki-muted">Evidence: {s.evidenceType}. {s.sourceRelationship==="context-for-editorial-analysis"?"Editorial analysis; source supplies context.":s.sourceRelationship==="context-for-local-derivation"?"Local explanatory derivation; source supplies context.":s.sourceRelationship==="mixed-source-and-local-derivation"?"Selected source passages and local explanatory derivation.":"Selected source passages; see review limits."} {s.sourceIds.map(id=><a href={"#ref-"+id} key={id}>Source ↗</a>)}</p></section>)}
 <section className="scwiki-sources"><h2 id="sources">Sources</h2>{note.sources.map(s=><div id={"ref-"+s.id} key={s.id}><h3><a href={s.url}>{s.title}</a></h3><p>{s.authors}</p><p>{s.publicationStatus==="preprint"?"Preprint":"Journal article"} · {s.dateLabel} <time dateTime={s.date}>{s.date}</time> · {s.version}</p><p>{s.scope}</p>{s.licenseUrl&&<p>Source license: <a href={s.licenseUrl}>{s.licenseLabel}</a>. This editorial note changes the wording and organization.</p>}</div>)}</section>
 <section><h2 id="related-topics">Related topics</h2><ul>{related.map(a=><li key={a.id}><Link href={"/scwiki/"+a.slug}>{a.title}</Link></li>)}</ul></section>
 <section className="scwiki-review"><h2>Editorial corrections and provenance</h2><ul>{note.corrections.map(c=><li key={c.issue}><strong>{c.issue}:</strong> {c.resolution}</li>)}</ul><details><summary>Source-note provenance</summary>{note.provenance.map(p=><p key={p.path}><a href={"https://github.com/"+p.repository+"/blob/"+p.commit+"/"+p.path}>{p.path}</a><br/>Commit: <code>{p.commit}</code><br/>SHA-256: <code>{p.sha256}</code><br/>Disposition: {p.disposition}</p>)}</details><p>{note.rights}</p><p>Note revision: <code>{note.revision}</code></p></section>
 </article></div></main>;
}
