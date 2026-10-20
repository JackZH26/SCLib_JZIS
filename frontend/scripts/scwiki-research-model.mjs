/** Shared validation for the read-only site and the independent content publisher. */
export function isoWeek(day) {
 const d=new Date(day+"T12:00:00Z");
 d.setUTCDate(d.getUTCDate()+4-(d.getUTCDay()||7));
 const year=d.getUTCFullYear();
 return year+"-W"+String(Math.ceil((((d-new Date(Date.UTC(year,0,1)))/86400000)+1)/7)).padStart(2,"0");
}
export function validateResearch(data, today=new Date().toLocaleDateString("en-CA",{timeZone:"Asia/Shanghai"})) {
 const fail=message=>{throw new Error("Research content: "+message);};
 const required=(obj,keys)=>{for(const key of keys)if(typeof obj[key]!=="string"||!obj[key].trim())fail("missing "+key);};
 const date=value=>typeof value==="string"&&/^\d{4}-\d{2}-\d{2}$/.test(value)&&!Number.isNaN(Date.parse(value))&&new Date(value).toISOString().slice(0,10)===value;
 const https=value=>{try{return new URL(value).protocol==="https:";}catch{return false;}};
 if(data?.schemaVersion!=="1.0"||!Array.isArray(data.issues)||!Array.isArray(data.notices))fail("invalid collection");
 const weeks=new Set(),identities=new Map(),allIds=new Set();
 for(const issue of [...data.issues].sort((a,b)=>a.id.localeCompare(b.id))) {
  required(issue,["id","selectedAt","checkedAt","title","selectionBasis","editorialNote"]);
  if(!date(issue.selectedAt)||!date(issue.checkedAt)||issue.checkedAt>issue.selectedAt||issue.selectedAt>today||isoWeek(issue.selectedAt)!==issue.id)fail("invalid issue dates");
  if(weeks.has(issue.id))fail("duplicate week");
  weeks.add(issue.id);
  if(issue.status!=="published"||!["selected","no-new-selection"].includes(issue.outcome)||!Array.isArray(issue.items)||issue.items.length>6)fail("invalid issue status or size");
  if((issue.outcome==="selected")!==(issue.items.length>0))fail("outcome does not match items");
  const seen=new Set(),itemIds=new Set();
  for(const item of issue.items) {
   required(item,["id","paperId","version","firstRecommendedIssue","title","paperTitle","journal","publishedAt","publicationStatus","publicationLabel","url","summary","whyItMatters","limitation","topicSlug","topicLabel","verificationScope","checkedAt"]);
   if(!/^[a-z0-9-]+$/.test(item.id)||!/^[-a-z0-9/]+$/.test(item.topicSlug))fail("invalid item or topic ID");
   if(!date(item.publishedAt)||!date(item.checkedAt)||item.publishedAt>item.checkedAt||item.checkedAt>issue.checkedAt)fail("invalid source dates");
   if(item.versionDate&&(!date(item.versionDate)||item.versionDate<item.publishedAt||item.versionDate>item.checkedAt))fail("invalid version date");
   if(!https(item.url))fail("source must use HTTPS");
   const identity=item.doi?"doi:"+item.doi.toLowerCase():item.arxivId?"arxiv:"+item.arxivId.replace(/v\d+$/,""):null;
   const aliases=[...(item.doi?["doi:"+item.doi.toLowerCase()]:[]),...(item.arxivId?["arxiv:"+item.arxivId.replace(/v\d+$/,"")]:[])];
   if(!identity||!aliases.includes(item.paperId))fail("invalid DOI/arXiv identity");
   if(item.doi&&!/^10\.\d{4,9}\/\S+$/.test(item.doi))fail("invalid DOI");
   if(item.arxivId&&!/^\d{4}\.\d{4,5}(?:v\d+)?$/.test(item.arxivId))fail("invalid arXiv ID");
   if(!["journal-article","peer-reviewed-accepted-early-version","preprint"].includes(item.publicationStatus))fail("invalid publication status");
   if(item.publicationStatus==="preprint"&&!/preprint/i.test(item.publicationLabel))fail("preprint must be labelled");
   const matches=aliases.map(alias=>identities.get(alias)).filter(Boolean);
   if(new Set(matches.map(p=>p.paperId)).size>1)fail("conflicting paper identities");
   const prior=matches[0];
   if(prior&&item.paperId!==prior.paperId)fail("preserve the established paper identity");
   if(seen.has(item.paperId)||itemIds.has(item.id))fail("duplicate paper or item in issue");
   seen.add(item.paperId);itemIds.add(item.id);allIds.add(item.paperId);
   if(item.firstRecommendedIssue!==(prior?.week||issue.id))fail("incorrect first recommendation");
   if(prior&&(!item.updateReason?.trim()||prior.versions.has(item.version)))fail("repeat requires a new version and update reason");
   const state={paperId:item.paperId,week:prior?.week||issue.id,versions:new Set([...(prior?.versions||[]),item.version])};
   for(const [alias,value]of identities)if(value.paperId===item.paperId)identities.set(alias,state);
   for(const alias of aliases)identities.set(alias,state);
  }
 }
 const notices=new Set();
 for(const notice of data.notices) {
  required(notice,["id","paperId","kind","date","description","sourceUrl"]);
  if(notices.has(notice.id)||!allIds.has(notice.paperId)||!date(notice.date)||notice.date>today||!https(notice.sourceUrl)||!["correction","retraction","version-update"].includes(notice.kind))fail("invalid notice");
  notices.add(notice.id);
 }
 return data;
}
export function assertAppendOnly(previous,next) {
 for(const key of ["issues","notices"])for(const old of previous[key]) {
  const current=next[key].find(x=>x.id===old.id);
  if(JSON.stringify(current)!==JSON.stringify(old))throw new Error("Published "+key+" are immutable; append a dated notice instead.");
 }
}
