import {articles} from "@/lib/scwiki/catalogue";
import type {Metadata} from "next";
import Link from "@/components/AppLink";
import {libraryNotes} from "@/lib/scwiki/library";
import {absoluteUrl} from "@/lib/seo";
import "../scwiki.css";
export const metadata:Metadata={title:"Research library | SCWiki",description:"Source-linked research notes and cross-topic analyses with explicit evidence limits.",alternates:{canonical:absoluteUrl("/scwiki/library")}};
export default function LibraryPage(){return <main className="scwiki">
 <nav className="scwiki-breadcrumb" aria-label="Breadcrumb"><Link href="/scwiki">SCWiki</Link><span>/</span><span>Research library</span></nav>
 <header className="scwiki-article-header"><p className="scwiki-kicker">Papers in context</p><h1>Research library</h1><p className="scwiki-summary">Read a study alongside the concepts it informs. Follow the original source, the local analysis and the questions that remain open.</p></header>
 <p className="scwiki-scope-note">{libraryNotes.length} research {libraryNotes.length===1?"note":"notes"} available. Notes are counted separately from the {articles().length} core and extension articles. Source review is limited and independent scientific review remains open.</p>
 <ol className="scwiki-article-grid">{libraryNotes.map(note=><li key={note.id}><article className="scwiki-result"><p className="scwiki-article-code">Research note &amp; cross-topic analysis</p><h2><Link href={"/scwiki/library/"+note.id}>{note.title}</Link></h2><p>{note.summary}</p><p className="scwiki-muted">{note.review.scope}</p></article></li>)}</ol>
 <p>Use the <Link href="/scwiki">SCWiki search</Link> to search the full text of articles and research notes. <a href="/api/scwiki/v1/library">Read the library as JSON</a>.</p>
 </main>;}
