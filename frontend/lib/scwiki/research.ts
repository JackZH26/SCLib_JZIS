import {readFileSync} from "node:fs";
import {createHash} from "node:crypto";
import seed from "@/content/scwiki/research-issues.json";
import {validateResearch} from "@/scripts/scwiki-research-model.mjs";
import type {ResearchCollection,ResearchIssue} from "./research-types";
import {absoluteUrl} from "@/lib/seo";

export const researchDigest=(data:unknown)=>createHash("sha256").update(JSON.stringify(data)).digest("hex").slice(0,20);
let lastGood:{path:string;data:ResearchCollection}|undefined;
/** Read at request time. The publisher atomically replaces this data, not the site build. */
export function researchCollection() {
 const path=process.env.SCWIKI_RESEARCH_STORE;
 let data:ResearchCollection,warning:string|null=null;
 if(!path)data=validateResearch(seed) as ResearchCollection;
 else try {
  const raw=readFileSync(path);
  if(raw.byteLength>8*1024*1024)throw new Error("content too large");
  data=validateResearch(JSON.parse(raw.toString("utf8"))) as ResearchCollection;
  lastGood={path,data};
 } catch {
  if(lastGood?.path===path){data=lastGood.data;warning="The content update is temporarily unavailable. Showing the last valid edition.";}
  else throw new Error("Research content is temporarily unavailable.");
 }
 const issues=[...data.issues].sort((a,b)=>b.id.localeCompare(a.id));
 return {...data,issues,revision:researchDigest(data),warning};
}
export function issueEnvelope(issue:ResearchIssue,data:ReturnType<typeof researchCollection>) {
 const notices=data.notices.filter(n=>issue.items.some(i=>i.paperId===n.paperId));
 return {schemaVersion:"1.0",revision:researchDigest([issue,notices]),snapshotRevision:researchDigest(issue),issue,notices,warning:data.warning};
}
export function researchMarkdown(issue:ResearchIssue,data:ReturnType<typeof researchCollection>) {
 const doc=issueEnvelope(issue,data);
 return `# SCWiki research · ${issue.id}\n\n${issue.title}\n\nSelected: ${issue.selectedAt}. Sources checked: ${issue.checkedAt}.\n\n${issue.selectionBasis}\n\n${issue.editorialNote}\n`+
 (issue.outcome==="no-new-selection"?"\nNo new selections in this edition.\n":"")+
 issue.items.map(item=>`\n## ${item.title}\n\n${item.summary}\n\nWhy it matters: ${item.whyItMatters}\n\nEvidence limits: ${item.limitation}\n\nReview scope: ${item.verificationScope}\n\n[${item.paperTitle}](${item.url}) · ${item.journal} · ${item.publicationLabel}. Published: ${item.publishedAt}. Checked: ${item.checkedAt}. Version: ${item.version}${item.versionDate?" ("+item.versionDate+")":""}.\n\nPaper ID: ${item.paperId}. First recommended: ${item.firstRecommendedIssue}.\n\n[${item.topicLabel}](${absoluteUrl("/scwiki/"+item.topicSlug)})\n`).join("")+
 "\n## Subsequent notices\n\n"+(doc.notices.map(n=>`${n.date} · ${n.kind}: ${n.description} [Source](${n.sourceUrl})`).join("\n\n")||"No subsequent notices recorded.")+
 `\n\nSnapshot revision: ${doc.snapshotRevision}. Representation revision: ${doc.revision}.\n`;
}
export const xml=(s:string)=>s.replace(/[<>&"']/g,c=>({"<":"&lt;",">":"&gt;","&":"&amp;",'"':"&quot;","'":"&apos;"}[c]!));
export function researchRss(data:ReturnType<typeof researchCollection>) {
 const entries=data.issues.slice(0,52).map(issue=>`<item><title>${xml(issue.id+" · "+issue.title)}</title><link>${xml(absoluteUrl("/scwiki/research/"+issue.id))}</link><guid isPermaLink="true">${xml(absoluteUrl("/scwiki/research/"+issue.id))}</guid><pubDate>${new Date(issue.selectedAt+"T09:00:00+08:00").toUTCString()}</pubDate><description>${xml(issue.selectionBasis+" "+issue.editorialNote)}</description></item>`);
 // Notices get their own stable feed identity so corrections are discoverable.
 entries.push(...data.notices.slice(-52).reverse().map(n=>`<item><title>${xml(n.kind+": "+n.paperId)}</title><link>${xml(n.sourceUrl)}</link><guid isPermaLink="false">${xml("scwiki-research-notice:"+n.id)}</guid><pubDate>${new Date(n.date+"T09:00:00+08:00").toUTCString()}</pubDate><description>${xml(n.description)}</description></item>`));
 return `<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>SCWiki research selections</title><link>${xml(absoluteUrl("/scwiki/research"))}</link><description>Weekly editorial selections and dated corrections. Source-check scope is stated in each edition.</description><language>en</language>${entries.join("")}</channel></rss>`;
}
