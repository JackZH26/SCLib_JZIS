import type {Metadata} from "next";
import {notFound} from "next/navigation";
import Link from "@/components/AppLink";
import {ResearchCards} from "@/components/scwiki/ResearchCards";
import {researchCollection,issueEnvelope} from "@/lib/scwiki/research";
import {formatResearchDate} from "@/lib/scwiki/home";
import {absoluteUrl} from "@/lib/seo";
import "../../scwiki.css";
export const dynamic="force-dynamic";
type Props={params:Promise<{issue:string}>};
export async function generateMetadata({params}:Props):Promise<Metadata>{
 const id=(await params).issue,issue=researchCollection().issues.find(i=>i.id===id);
 return {title:issue?`${id}: ${issue.title} | SCWiki`:"Edition not found | SCWiki",alternates:{canonical:absoluteUrl("/scwiki/research/"+id)}};
}
export default async function ResearchIssuePage({params}:Props){
 const id=(await params).issue,data=researchCollection(),issue=data.issues.find(i=>i.id===id);
 if(!issue)notFound();
 const index=data.issues.indexOf(issue),doc=issueEnvelope(issue,data);
 return <main className="scwiki scwiki-home" data-research-revision={doc.snapshotRevision}>
  <p><Link href="/scwiki/research">← All research editions</Link></p>
  <header className="scwiki-home-intro"><p className="scwiki-kicker">Research selection · {issue.id}</p><h1>{issue.title}</h1><p>Selected {formatResearchDate(issue.selectedAt)} · Sources checked {formatResearchDate(issue.checkedAt)}</p></header>
  {data.warning&&<p role="status">{data.warning}</p>}
  <p>{issue.selectionBasis}</p><p className="scwiki-selection-note">{issue.editorialNote}</p>
  {issue.outcome==="no-new-selection"?<p>No new selections in this edition. Previous editions remain in the archive.</p>:<ResearchCards items={issue.items} notices={doc.notices}/>}
  <p className="scwiki-research-links"><a href={"/api/scwiki/v1/research/"+id}>Read JSON ↗</a><a href={"/api/scwiki/v1/research/"+id+"/markdown"}>Read Markdown ↗</a><a href="/scwiki/research/feed.xml">RSS ↗</a></p>
  <nav className="scwiki-research-links" aria-label="Research editions">
   {data.issues[index-1]&&<Link href={"/scwiki/research/"+data.issues[index-1].id}>← Newer: {data.issues[index-1].id}</Link>}
   {data.issues[index+1]&&<Link href={"/scwiki/research/"+data.issues[index+1].id}>Older: {data.issues[index+1].id} →</Link>}
  </nav>
 </main>;
}
