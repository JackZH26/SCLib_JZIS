import Link from "@/components/AppLink";
import {formatResearchDate} from "@/lib/scwiki/home";
import type {ResearchItem,ResearchNotice} from "@/lib/scwiki/research-types";
export function ResearchCards({items,notices=[]}:{items:ResearchItem[];notices?:ResearchNotice[]}) {
 return <div className="scwiki-research-grid">{items.map((item,index)=><article className="scwiki-research-item" id={item.id} key={item.id}>
  <div className="scwiki-research-meta"><span aria-hidden="true">{String(index+1).padStart(2,"0")}</span><span>Published <time dateTime={item.publishedAt}>{formatResearchDate(item.publishedAt)}</time></span></div>
  <p className="scwiki-journal">{item.journal}</p>
  <h3><a href={item.url} title={item.paperTitle}>{item.title}<span aria-hidden="true"> ↗</span></a></h3>
  <p className="scwiki-research-summary">{item.summary}</p>
  <p className="scwiki-publication-status">{item.publicationLabel}</p>
  {notices.filter(n=>n.paperId===item.paperId).map(n=><aside className="scwiki-research-notice" key={n.id}><strong>{n.kind==="retraction"?"Retraction notice":n.kind==="correction"?"Correction":"Version update"} · {formatResearchDate(n.date)}</strong><p>{n.description} <a href={n.sourceUrl}>Read notice ↗</a></p></aside>)}
  <a className="scwiki-paper-link" href={item.url} aria-label={"Read original paper: "+item.paperTitle}>Read original paper ↗</a>
  <details className="scwiki-research-evidence"><summary>Why it matters &amp; evidence limits</summary>
   <p><strong>Why it matters.</strong> {item.whyItMatters}</p><p><strong>Evidence limits.</strong> {item.limitation}</p><p>{item.verificationScope}</p>
   <p className="scwiki-paper-title">{item.paperTitle}</p><p>Checked {formatResearchDate(item.checkedAt)}. {item.version}{item.versionDate&&" · Version dated "+formatResearchDate(item.versionDate)}</p>
   {item.doi&&<p>DOI: <a href={"https://doi.org/"+item.doi}>{item.doi}</a></p>}
   <p>First selected in <Link href={"/scwiki/research/"+item.firstRecommendedIssue}>{item.firstRecommendedIssue}</Link>.</p>
   {item.updateReason&&<p>Version update: {item.updateReason}</p>}
   <Link href={"/scwiki/"+item.topicSlug}>Explore: {item.topicLabel} →</Link>
  </details>
 </article>)}</div>;
}
