import {test} from "node:test";
import assert from "node:assert/strict";
import {readFileSync,mkdtempSync,rmSync,mkdirSync,existsSync} from "node:fs";
import {tmpdir} from "node:os";
import path from "node:path";
import {validateResearch,assertAppendOnly,isoWeek} from "../scripts/scwiki-research-model.mjs";
import {publishResearch} from "../scripts/scwiki-research-publish.mjs";
const seed=path.resolve("content/scwiki/research-issues.json"),data=JSON.parse(readFileSync(seed,"utf8"));
const empty={...data.issues[0],id:"2026-W43",selectedAt:"2026-10-20",checkedAt:"2026-10-20",outcome:"no-new-selection",items:[],title:"No new selections",editorialNote:"Search completed; no eligible records selected."};
test("initial issue retains the real source dates and original three selections",()=>{
 assert.equal(isoWeek("2026-10-18"),"2026-W42");validateResearch(data,"2026-10-20");
 const legacy=JSON.parse(readFileSync("content/scwiki/research-highlights.json","utf8"));
 for(let i=0;i<legacy.items.length;i++)for(const [key,value]of Object.entries(legacy.items[i]))assert.deepEqual(data.issues[0].items[i][key],value);
});
test("future dates, duplicate papers, fake first selections and unlabelled preprints are rejected",()=>{
 for(const mutate of [
  d=>d.issues.push({...empty,selectedAt:"2026-10-26"}),
  d=>d.issues[0].items.push({...d.issues[0].items[0]}),
  d=>d.issues[0].items[0].firstRecommendedIssue="2026-W40",
  d=>d.issues[0].items[0].publicationStatus="preprint",
  d=>d.issues[0].items[0].publishedAt="2026-02-30"
 ]){const changed=structuredClone(data);mutate(changed);assert.throws(()=>validateResearch(changed,"2026-10-20"));}
});
test("repeat recommendations require an actual new version, an explanation and the original first week",()=>{
 const item={...data.issues[0].items[0],version:"Version 2",updateReason:"Publisher issued an updated version."};
 const next={...data,issues:[...data.issues,{...empty,outcome:"selected",items:[item]}]};
 validateResearch(next,"2026-10-20");
 item.version=data.issues[0].items[0].version;assert.throws(()=>validateResearch(next,"2026-10-20"));
});
test("publication is atomic and idempotent; invalid candidates and concurrent workers leave prior content intact",()=>{
 const dir=mkdtempSync(path.join(tmpdir(),"scwiki-research-")),store=path.join(dir,"research.json"),candidate={kind:"issue",record:empty};
 try {
  assert.equal(publishResearch({store,candidate,seed,today:"2026-10-20"}).changed,true);
  const saved=readFileSync(store,"utf8");
  assert.equal(publishResearch({store,candidate,seed,today:"2026-10-20"}).changed,false);
  assert.throws(()=>publishResearch({store,candidate:{kind:"issue",record:{...empty,title:"Replacement"}},seed,today:"2026-10-20"}));
  mkdirSync(store+".lock");assert.throws(()=>publishResearch({store,candidate,seed,today:"2026-10-20"}));
  assert.equal(readFileSync(store,"utf8"),saved);assert.ok(existsSync(store+".history"));
 }finally{rmSync(dir,{recursive:true,force:true});}
});
test("retractions append a dated notice without overwriting the issue",()=>{
 const next={...data,notices:[{id:"test-notice",paperId:data.issues[0].items[0].paperId,kind:"retraction",date:"2026-10-20",description:"Fixture only.",sourceUrl:"https://example.org/notice"}]};
 validateResearch(next,"2026-10-20");assertAppendOnly(data,next);
 next.issues=structuredClone(next.issues);next.issues[0].items[0].summary="Silently rewritten";
 assert.throws(()=>assertAppendOnly(data,next));
});
test("an arXiv-to-journal update keeps one paper identity and its first recommendation",()=>{
 const initial=structuredClone(data),item=initial.issues[0].items[0];
 delete item.doi;item.arxivId="2610.12345v1";item.paperId="arxiv:2610.12345";item.publicationStatus="preprint";item.publicationLabel="Preprint · not peer reviewed";
 const updated={...item,doi:"10.1234/example",arxivId:"2610.12345v2",version:"Journal version",updateReason:"Journal version checked.",publicationStatus:"journal-article",publicationLabel:"Peer-reviewed article"};
 initial.issues.push({...empty,outcome:"selected",items:[updated]});validateResearch(initial,"2026-10-20");
 updated.paperId="doi:10.1234/example";assert.throws(()=>validateResearch(initial,"2026-10-20"));
});
