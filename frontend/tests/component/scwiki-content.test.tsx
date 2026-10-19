import {render,screen,fireEvent} from "@testing-library/react";
import {SearchCatalogue} from "@/components/scwiki/SearchCatalogue";
import {middleware} from "../../middleware";
import {describe,it,expect} from "vitest";
import {readFileSync,existsSync} from "node:fs";
import {createHash} from "node:crypto";
import {join} from "node:path";
const sourceRoot=process.env.SCWIKI_SOURCE_ROOT || "../../sources";
import {renderToStaticMarkup} from "react-dom/server";
import {NextRequest} from "next/server";
import {ScientificMarkdown} from "@/components/scwiki/ScientificMarkdown";
import {articles,catalogue,searchIndex} from "@/lib/scwiki/catalogue";
import {searchArticles,normalizeSearch} from "@/lib/scwiki/search";
import {articleIdPattern,sectionAnchor,validateExtensionInventory,validateExtensionArticle} from "../../scripts/scwiki-publication.mjs";
import {sectionId} from "@/lib/scwiki/safety";
import {safeUrl} from "@/lib/scwiki/safety";
import {legacyDestination} from "@/lib/site-routes";
import {GET} from "@/app/api/scwiki/v1/[[...segments]]/route";
const get=(segments:string[],query="")=>GET(new NextRequest("http://localhost/api/scwiki/v1/"+segments.join("/")+query),{params:Promise.resolve({segments})});
const getAll=async(key:"articles"|"sources"|"topics")=>{
 const items:any[]=[];let cursor:string|null=null;
 do{const response=await get([key],"?limit=50"+(cursor?"&cursor="+encodeURIComponent(cursor):""));expect(response.status).toBe(200);const data=await response.json();items.push(...data[key]);cursor=data.page.nextCursor;}while(cursor);
 return {[key]:items};
};
describe("SCWiki source and scientific-content contracts",()=>{
 it("exports source-backed editorial analysis without presenting a retraction as a scientific hypothesis",async()=>{
  const a=(await(await get(["articles","scwiki-d12"])).json()).article;
  const c=a.claims.find((c:any)=>c.id==="scwiki-d12-claim-limits-and-disputes-1");
  expect(c.evidenceType).toBe("editorial-analysis");expect(c.sourceRelationship).toBe("context-for-editorial-analysis");
  const ref=a.references.find((r:any)=>r.doi==="10.1038/nature26142");expect(ref.retraction.retractedAt).toBe("2021-03-08");
  const md=await(await get(["articles",a.id,"sections","limits-and-disputes"],"?format=markdown")).text();
  expect(md).toContain("Evidence: editorial-analysis");expect(md).toContain("never positive confirmation");expect(md).toContain("not an uncertainty interval");
 });
 it("keeps editorial commentary out of material evidence and exposes the separate claim contract",async()=>{
  const schema=(await(await get(["openapi.json"])).json());
  expect(schema.info.version).toBe("1.5.0");expect(schema.components.schemas.Claim.properties.evidenceType.$ref).toBe("#/components/schemas/ClaimEvidenceType");
  expect(schema.components.schemas.ClaimEvidenceType.enum).toContain("editorial-analysis");
  expect(schema.components.schemas.ClaimEvidenceType.enum).toContain("experimental");
  for(const c of articles().flatMap(a=>a.claims)) expect(schema.components.schemas.ClaimEvidenceType.enum).toContain(c.evidenceType);
  expect(schema.components.schemas.MaterialCase.properties.recordType.$ref).toBe("#/components/schemas/EvidenceType");
  expect(schema.components.schemas.EvidenceType.enum).not.toContain("editorial-analysis");
  expect(schema.components.schemas.EvidenceType.enum).not.toContain("experimental");
  expect(articles().flatMap(a=>a.materialCases).some(m=>String(m.recordType)==="editorial-analysis")).toBe(false);
  const r=await get(["search"],"?q=topological&evidence=editorial-analysis");expect(r.status).toBe(400);
 });
 it("rejects unlabeled source roles for editorial claims and unknown claim evidence values",async()=>{
  const {validateClaimEvidence}=await import("../../scripts/scwiki-claim-evidence.mjs");
  const valid={id:"synthetic-editorial",evidenceType:"editorial-analysis",sourceRelationship:"context-for-editorial-analysis",derivationNote:"Compares source scope without claiming a new experiment."};
  expect(()=>validateClaimEvidence(valid)).not.toThrow();
  expect(()=>validateClaimEvidence({id:"legacy-experiment",evidenceType:"experimental"})).not.toThrow();
  expect(()=>validateClaimEvidence({...valid,sourceRelationship:"direct-support"})).toThrow();
  expect(()=>validateClaimEvidence({...valid,derivationNote:" "})).toThrow();
  expect(()=>validateClaimEvidence({...valid,evidenceType:"editorial-typo"})).toThrow();
 });

 it("retains magnetic-excitation windows and unresolved primary-source calibration conflicts",async()=>{
  const result=await(await get(["library"],"?q="+encodeURIComponent("10.1038/nmat3723"))).json();expect(result.total).toBe(1);
  const n=result.notes[0];expect(n.id).toBe("dean-lsco-magnetic-excitations");const md=await(await get(["library",n.id,"markdown"])).text();
  for(const term of ["0.18","HWHM","FWHM","0.78","97","52","not reconciled","not been independently reproduced","unmeasured diagonal","six inherited series studies remain pending"])expect(md).toContain(term);
  expect(n.sources).toHaveLength(2);expect(n.sources.every((s:any)=>s.date==="2013-08-04"&&s.licenseUrl===null)).toBe(true);
  for(const pr of n.provenance){expect(pr.disposition).toBe("partial-merge");expect(createHash("sha256").update(readFileSync(join(sourceRoot,pr.path))).digest("hex")).toBe(pr.sha256);expect(md).toContain(pr.coverage);}
  const entries=(await import("@/lib/scwiki/library")).librarySearchEntries();expect(searchArticles(entries,"paramagnon").some(x=>x.id===n.id)).toBe(true);expect(searchArticles(entries,"paramagnon",{tcMin:1}).some(x=>x.id===n.id)).toBe(false);
  for(const section of n.sections){expect(renderToStaticMarkup(<ScientificMarkdown markdown={section.markdown}/>)).not.toContain("katex-error");for(const id of section.sourceIds)expect(n.sources.some((s:any)=>s.id===id)).toBe(true);}
 });

 it("keeps THz criterion, scale uncertainty and partial series coverage in discovery and exports",async()=>{
  const result=await(await get(["library"],"?q="+encodeURIComponent("10.1038/nphys1912"))).json();expect(result.total).toBe(1);
  const n=result.notes[0];expect(n.id).toBe("bilbro-thz-fluctuation-window");
  const md=await(await get(["library",n.id,"markdown"])).text();
  for(const phrase of ["5–16 K","0.8 THz","23.5","roughly 40% spread","not a precision universal constant","normal-state masking","Not verified","not a public reuse license","six remain pending"])expect(md).toContain(phrase);
  expect(n.sources[0].dateLabel).toBe("Author version deposited");expect(n.sources[0].date).toBe("2011-10-10");
  for(const pr of n.provenance){expect(pr.disposition).toBe("partial-merge");expect(md).toContain(pr.coverage);expect(createHash("sha256").update(readFileSync(join(sourceRoot,pr.path))).digest("hex")).toBe(pr.sha256);}
  const entries=(await import("@/lib/scwiki/library")).librarySearchEntries();expect(searchArticles(entries,"terahertz").some(x=>x.id===n.id)).toBe(true);expect(searchArticles(entries,"terahertz",{tcMin:20}).some(x=>x.id===n.id)).toBe(false);
  const html=renderToStaticMarkup(<ScientificMarkdown markdown={n.sections[1].markdown}/>);expect(html).not.toContain("katex-error");
 });

 it("exports partial research coverage without implying the whole source series is complete",async()=>{
  const n=(await(await get(["library","cuprate-interface-layer-order"])).json()).note;
  expect(n.provenance).toHaveLength(2);expect(n.provenance.every((p:any)=>p.disposition==="partial-merge")).toBe(true);
  const md=await(await get(["library",n.id,"markdown"])).text();
  for(const p of n.provenance){expect(md).toContain(p.coverage);expect(createHash("sha256").update(readFileSync(join(sourceRoot,p.path))).digest("hex")).toBe(p.sha256);}
  expect(md).toContain("other six study sections remain pending");expect(md).toContain("resistive midpoints");expect(md).toContain("ozone-treated");expect(md).toContain("full methods, Zn profile and calibration have not been reviewed");
  const spec=await(await get(["openapi.json"])).json();expect(spec.components.schemas.ResearchNote.properties.provenance.items.required).toContain("coverage");
  const first=(await(await get(["library","romero-parallel-conduction"])).json()).note;
  expect(first.provenance.every((p:any)=>p.disposition==="merge-into"&&p.coverage.includes("scientific review remains limited"))).toBe(true);
 });

 it("preserves pressure-quench specimen histories and limits in library exports",async()=>{
  const result=await(await get(["library"],"?q="+encodeURIComponent("10.1073/pnas.2536178123"))).json();expect(result.total).toBe(1);
  const n=result.notes[0];const md=await(await get(["library",n.id,"markdown"])).text();
  for(const text of ["5 / S4 | 18.9 GPa | 4.2 K | 151 K warming; 150 K cooling","S1 is used twice","S2 at 151 K","78% superconducting-volume measurement on S4","Figure S6 multiplies the post-quench curve by ten","unassigned anomaly","unidentified peaks"]){
   if(text==="S2 at 151 K")expect(md).not.toContain(text);else expect(md).toContain(text);
  }
  expect(n.sources[0].date).toBe("2026-03-12");expect(n.sources[1].date).toBe("2026-03-09");
  for(const p of n.provenance)expect(createHash("sha256").update(readFileSync(join(sourceRoot,p.path))).digest("hex")).toBe(p.sha256);
  for(const section of n.sections)for(const id of section.sourceIds)expect(n.sources.some((s:any)=>s.id===id)).toBe(true);
  const idx=await(await import("@/lib/scwiki/library")).librarySearchEntries();
  expect(searchArticles(idx,"pressure quench").some(x=>x.id===n.id)).toBe(true);
  expect(searchArticles(idx,"pressure quench",{tcMin:170}).some(x=>x.id===n.id)).toBe(false);
 });

 it("keeps Yang version boundaries and sample criteria through research and core exports",async()=>{
  const found=await(await get(["library"],"?q="+encodeURIComponent("10.1038/s41586-026-10547-y"))).json();expect(found.total).toBe(1);
  const note=found.notes[0];expect(note.sources.map((s:any)=>s.publicationStatus)).toEqual(["preprint","journal-article"]);
  const md=await(await get(["library",note.id,"markdown"])).text();
  for(const phrase of ["6.23 T","13.04 T","0.5Rn","SCE0.36 at 4.2 K","SCE0.40 at 0.3 K","not verified","not a universal","CC BY 4.0","Mingwei Yang"])expect(md).toContain(phrase);
  expect(md).toContain("https://arxiv.org/abs/2508.14666v3");
  for(const section of note.sections)for(const id of section.sourceIds)expect(note.sources.some((s:any)=>s.id===id)).toBe(true);
  for(const p of note.provenance)expect(createHash("sha256").update(readFileSync(join(sourceRoot,p.path))).digest("hex")).toBe(p.sha256);
  const core=articles().find(a=>a.code==="D15")!;
  expect(core.body).not.toContain("SCE0.36 remains superconducting to the 45 T measurement limit at 0.3 K");
  const d15=await(await get(["articles",core.id,"sections","experimental-criteria"],"?format=markdown")).text();
  expect(d15).toContain("withheld pending version and sample reconciliation");
  const h7=articles().find(a=>a.code==="H7")!;expect(h7.body).toContain("does report Hall resistance nonlinear in magnetic field");expect(h7.body).toContain("not measurements of the second-order electric-field response");
 });

 it("paginates research studies separately and keeps the final-paper sample criteria and license",async()=>{
  const first=await(await get(["library"],"?limit=1")).json();expect(first.total).toBeGreaterThan(1);
  const second=await(await get(["library"],"?limit=1&cursor="+first.page.nextCursor)).json();
  expect(second.revision).toBe(first.revision);expect(second.notes[0].id).not.toBe(first.notes[0].id);
  const found=await(await get(["library"],"?q="+encodeURIComponent("10.1038/s41586-026-10446-2"))).json();expect(found.total).toBe(1);
  const note=found.notes[0];expect(note.sources[0].publicationStatus).toBe("journal-article");expect(note.sources[0].date).toBe("2026-04-01");
  const md=await(await get(["library",note.id,"markdown"])).text();
  expect(md).toContain("42 K; zero resistance around 2 K");expect(md).toContain("LAO | −1.2% | −0.9% | Metallic");
  expect(md).toContain("hypothetical controls");expect(md).toContain("not a demonstration");expect(md).toContain("importance of this reduced mixing for superconductivity remains to be established");
  expect(md).toContain("https://creativecommons.org/licenses/by/4.0/");expect(md).toContain("Lopa Bhatt");
  for(const section of note.sections)for(const id of section.sourceIds)expect(note.sources.some((s:any)=>s.id===id)).toBe(true);
  for(const p of note.provenance)expect(createHash("sha256").update(readFileSync(join(sourceRoot,p.path))).digest("hex")).toBe(p.sha256);
  expect((await get(["library"],"?q=Bhatt&limit=1&cursor="+first.page.nextCursor)).status).toBe(400);
 });
 it("exports separate research notes with source versions, local derivations and review limits",async()=>{
  const list=await(await get(["library"],"?q=missing-area&limit=1")).json();
  expect(list.total).toBe(1);expect(list.page.next).toBeNull();expect(articles()).toHaveLength(104);
  const note=list.notes[0];const detail=await get(["library",note.id]);
  expect((await detail.json()).note.revision).toBe(note.revision);
  const md=await(await get(["library",note.id,"markdown"])).text();
  expect(md).toContain("Selected preprint passages");expect(md).toContain("context-for-local-derivation");expect(md).toContain("SHA-256");expect(md).toContain("missing-area");
  for(const s of note.sources)expect(md).toContain(s.url);
  for(const p of note.provenance)expect(createHash("sha256").update(readFileSync(join(sourceRoot,p.path))).digest("hex")).toBe(p.sha256);
  const conditional=new NextRequest("http://localhost/api/scwiki/v1/library/"+note.id,{headers:{"If-None-Match":detail.headers.get("ETag")!}});
  expect((await GET(conditional,{params:Promise.resolve({segments:["library",note.id]})})).status).toBe(304);
  expect((await get(["library"],"?q=absentunique987")).status).toBe(200);
  expect((await get(["library"],"?pressure=ambient")).status).toBe(400);
  expect((await get(["library"],"?q=a&q=b")).status).toBe(400);
  expect((await get(["library","absent"])).status).toBe(404);
  const spec=await(await get(["openapi.json"])).json();expect(spec.paths["/library/{noteId}/markdown"]).toBeDefined();
 });
 it("exports local derivations without presenting contextual sources as direct evidence",async()=>{
  const data=await(await get(["articles","scwiki-a4"])).json();
  const article=data.article??data;
  const claim=article.claims.find((c:any)=>c.id==="scwiki-a4-claim-mathematical-assumptions-9");
  expect(claim.sourceRelationship).toBe("context-for-local-derivation");expect(claim.derivationNote).toContain("not this uncertainty formula");
  const text=await(await get(["articles","scwiki-a4","markdown"])).text();expect(text).toContain("Source relationship: context-for-local-derivation");
  const sectionText=await(await get(["articles","scwiki-a4","sections","mathematical-assumptions"],"?format=markdown")).text();expect(sectionText).toContain("Source relationship: context-for-local-derivation");expect(sectionText).toContain(claim.derivationNote);
  const a1=articles().find(a=>a.code==="A1")!;expect(a1.body).toContain("elapsed time");expect(a1.body).toContain("current magnitude");
 });

 it("paginates complete article and source inventories without duplicates or oversized pages",async()=>{
  for(const key of ["articles","sources","topics"] as const){
   const ids:string[]=[];let cursor:string|null=null;let total=0;
   do{
    const response=await get([key],"?limit=50"+(cursor?"&cursor="+encodeURIComponent(cursor):""));expect(response.status).toBe(200);
    const raw=await response.text();expect(Buffer.byteLength(raw)).toBeLessThanOrEqual(256*1024);
    const data=JSON.parse(raw);total=data.total;expect(data[key].length).toBeLessThanOrEqual(50);expect(data.page.returned).toBe(data[key].length);
    ids.push(...data[key].map((x:{id:string})=>x.id));cursor=data.page.nextCursor;
    if(cursor)expect(data.page.next).toContain(encodeURIComponent(cursor));else expect(data.page.next).toBeNull();
   }while(cursor);
   expect(ids.length).toBe(total);expect(new Set(ids).size).toBe(total);
   if(key!=="sources")expect(total).toBe(articles().length);
  }
 });
 it("rejects malformed, stale and cross-query cursors and ambiguous filter values",async()=>{
  for(const query of ["?limit=0","?limit=51","?limit=1.5","?cursor=","?cursor=not-json","?q=a&q=b","?unknown=x","?tcMin=","?tcMin=0x10"]){
   const response=await get(["search"],query);expect(response.status,query).toBe(400);expect(response.headers.get("Cache-Control")).toBe("no-store");expect(response.headers.get("ETag")).toBeNull();
  }
  const first=await(await get(["search"],"?limit=1")).json();
  expect((await get(["search"],"?limit=1&q=BCS&cursor="+first.page.nextCursor)).status).toBe(400);
  expect((await get(["topics"],"?limit=1&cursor="+first.page.nextCursor)).status).toBe(400);
  const old=JSON.parse(Buffer.from(first.page.nextCursor,"base64url").toString());old.revision="00000000000000000000";
  const stale=await get(["search"],"?limit=1&cursor="+Buffer.from(JSON.stringify(old)).toString("base64url"));
  expect(stale.status).toBe(409);expect((await stale.json()).code).toBe("STALE_CURSOR");
 });
 it("uses representation-specific conditional validators while preserving editorial revisions",async()=>{
  const route=["articles","scwiki-d6"];
  const first=await get(route);const markdown=await get([...route,"markdown"]);
  const tag=first.headers.get("ETag")!;expect(tag).toMatch(/^W\/"[a-f0-9]{64}"$/);
  expect(markdown.headers.get("ETag")).not.toBe(tag);expect(markdown.headers.get("X-SCWiki-Revision")).toBe(first.headers.get("X-SCWiki-Revision"));
  for(const condition of [tag,tag.slice(2),'"unrelated", '+tag,"*"]){
   const request=new NextRequest("http://localhost/api/scwiki/v1/"+route.join("/"),{headers:{"If-None-Match":condition}});
   const response=await GET(request,{params:Promise.resolve({segments:route})});expect(response.status).toBe(304);expect(await response.text()).toBe("");expect(response.headers.get("ETag")).toBe(tag);
  }
  const wrong=new NextRequest("http://localhost/api/scwiki/v1/"+route.join("/"),{headers:{"If-None-Match":markdown.headers.get("ETag")!}});
  expect((await GET(wrong,{params:Promise.resolve({segments:route})})).status).toBe(200);
  const missing=new NextRequest("http://localhost/api/scwiki/v1/articles/not-found",{headers:{"If-None-Match":"*"}});
  expect((await GET(missing,{params:Promise.resolve({segments:["articles","not-found"]})})).status).toBe(404);
 });

 it("ranks curated topic names before incidental body mentions without relaxing conditions",()=>{
  const base=searchIndex().entries[0];
  const incidental={...base,code:"A1",title:"Background",aliases:[],summary:"Background",text:"A short mention of cobalt vortex diagnostics",materialCases:[]};
  const topic={...base,code:"Z9",title:"Dedicated diagnostics",aliases:["cobalt vortex diagnostics"],summary:"A dedicated topic",text:"Evidence and limitations",materialCases:[]};
  expect(searchArticles([incidental,topic],"cobalt vortex diagnostics").map(x=>x.code)).toEqual(["Z9","A1"]);
  expect(searchArticles([incidental,topic],"cobalt vortex diagnostics",{tcMin:1})).toEqual([]);
  for(const [q,codes]of [["equal spin pairing",["B4","C9","G2"]],["two-band superconductivity",["B12","D7"]],["FeSe",["D4","D11"]]] as const){
   expect(searchArticles(searchIndex().entries,q).slice(0,3).some(x=>(codes as readonly string[]).includes(x.code))).toBe(true);
  }
 });
 it("matches DOI identifiers exactly, including DOI URLs, instead of scattered body tokens",()=>{
  const base=searchIndex().entries[0];
  const exact={...base,code:"Z9",dois:["10.1234/Example.567"],text:""};
  const decoy={...base,code:"A1",dois:[],text:"10 1234 example 567"};
  for(const q of ["10.1234/example.567","https://doi.org/10.1234/Example.567","doi:10.1234/Example.567"]){
   expect(searchArticles([decoy,exact],q).map(x=>x.code)).toEqual(["Z9"]);
  }
 });
 it("keeps article review limits attached to every JSON section, including core articles",async()=>{
  const a=articles().find(x=>x.code==="D6")!;
  for(const section of a.sections){
   const response=await get(["articles",a.id,"sections",section.id]);const payload=await response.json();
   expect(payload.review).toEqual(a.review);
   expect(payload.articleRevision).toBe(a.revision);
   expect(response.headers.get("X-SCWiki-Revision")).toBe(a.revision);
  }
  const spec=await(await get(["openapi.json"])).json();
  expect(spec.components.schemas.SectionEnvelope.required).toContain("review");
  expect(spec.components.schemas.Review.required).toContain("limitations");
 });
 it("retains all 71 approved extension targets separately from 282 pinned sources",()=>{
  const manifest=JSON.parse(readFileSync("content/scwiki/source-manifest.json","utf8"));
  const inventory=JSON.parse(readFileSync("content/scwiki/extension-inventory.json","utf8"));
  const published=validateExtensionInventory(inventory,manifest);
  expect(inventory.pages).toHaveLength(15);
  expect(inventory.pages.flatMap((p:{items:unknown[]})=>p.items)).toHaveLength(71);
  expect(inventory.pages.filter((p:{kind:string})=>p.kind==="handbook").flatMap((p:{items:unknown[]})=>p.items)).toHaveLength(61);
  expect(published.map((p:{id:string})=>p.id).sort()).toEqual(articles().filter(a=>a.publicationKind).map(a=>a.id).sort());
  const plan=manifest.files.find((s:{path:string})=>s.path==="02_BATCH_2_IN_PLAN.md");
  expect(plan.publicBody).toBe(false);expect(plan.articleId).toBeNull();
  for(const alter of [(v:any)=>v.pages.pop(),(v:any)=>v.pages[0].items.pop(),(v:any)=>v.pages[0].items[0].target="experimental-methods#changed",(v:any)=>v.pages[0].slug="new-unapproved-scope"]){
   const broken=structuredClone(inventory);alter(broken);expect(()=>validateExtensionInventory(broken,manifest)).toThrow();
  }
  expect(articleIdPattern.test("scwiki-n11")).toBe(false);expect(articleIdPattern.test("scwiki-i1")).toBe(false);
 });
 it("keeps 61 handbook anchors stable and rejects publication without each substantive item review",()=>{
  const inventory=JSON.parse(readFileSync("content/scwiki/extension-inventory.json","utf8"));
  for(const page of inventory.pages.filter((p:{kind:string})=>p.kind==="handbook"))for(const item of page.items){
   for(const title of [item.id+" — Original heading",item.id+" — Revised description"]){
    expect(sectionId(title)).toBe(item.sectionId);expect(sectionAnchor(title)).toBe(item.sectionId);
    expect(renderToStaticMarkup(<ScientificMarkdown markdown={"## "+title+"\n\nA cited explanation."}/>)).toContain('id="'+item.sectionId+'"');
   }
  }
  const a=articles().find(a=>a.code==="N10")!;const registration=inventory.pages.find((p:{code:string})=>p.code==="N10");
  expect(()=>validateExtensionArticle(a,a.sections,registration)).not.toThrow();
  for(const alter of [(v:any)=>v.scopeItems=[],(v:any)=>v.scopeItems[0].sectionIds=["nonexistent"],(v:any)=>v.scopeItems[0].limitations=[]]){
   const broken=structuredClone(a);alter(broken);expect(()=>validateExtensionArticle(broken,broken.sections,registration)).toThrow();
  }
  const chunks=a.sections.map(s=>({...s,markdown:"Short placeholder."}));
  expect(()=>validateExtensionArticle(a,chunks,registration)).toThrow(/substantive/);
 });
 it("exports the N10 question with scoped planning provenance and no experimental Tc invention",async()=>{
  const a=articles().find(a=>a.code==="N10")!;
  expect(a.slug).toBe("open-questions/n10");expect(a.materialCases).toEqual([]);
  expect(a.provenance.path).toBe("02_BATCH_2_IN_PLAN.md");
  const response=await get(["articles",a.id,"sections","mathematical-assumptions"]);
  expect(response.status).toBe(200);const payload=await response.json();
  expect(payload.scopeItems[0].id).toBe("N10");
  const md=await(await get(["articles",a.id,"sections","mathematical-assumptions"],"?format=markdown")).text();
  for(const limit of a.scopeItems![0].limitations){expect(md).toContain(limit);expect(a.markdown).toContain(limit);}
  expect(md).toContain("Approved scope items");expect(a.markdown).toContain("Approved scope items");
  for(const q of ["平带","平带超导温度上限","flat-band Tc bound"]){
   expect(searchArticles(searchIndex().entries,q).some(x=>x.id===a.id)).toBe(true);
   expect(searchArticles(searchIndex().entries,q,{tcMin:0.01}).some(x=>x.id===a.id)).toBe(false);
  }
  const unpub=JSON.parse(readFileSync("content/scwiki/extension-inventory.json","utf8")).pages.filter((p:{publicBody:boolean})=>!p.publicBody);
  for(const p of unpub){expect((await get(["articles",p.id])).status).toBe(404);}
  expect((await get(["articles","scwiki-n11"])).status).toBe(404);
 });

 it("exports the room-temperature question without treating conditional energy scales as measured Tc",async()=>{
  const a=articles().find(a=>a.code==="N1")!;
  expect(a.slug).toBe("open-questions/n1");expect(a.materialCases).toEqual([]);
  expect(a.scopeItems?.[0].id).toBe("N1");
  for(const id of a.scopeItems![0].sectionIds){
   const data=await(await get(["articles",a.id,"sections",id])).json();
   expect(data.scopeItems.map((i:{id:string})=>i.id)).toEqual(["N1"]);
   const md=await(await get(["articles",a.id,"sections",id],"?format=markdown")).text();
   expect(md).toContain(data.section.markdown);
   for(const limit of a.review!.limitations)expect(md).toContain(limit);
  }
  for(const q of ["室温常压超导","room temperature ambient pressure superconductivity","imaginary single sample"]){
   expect(searchArticles(searchIndex().entries,q).some(x=>x.id===a.id)).toBe(true);
   expect(searchArticles(searchIndex().entries,q,{tcMin:0.01}).some(x=>x.id===a.id)).toBe(false);
  }
  expect(a.references.filter(r=>r.title.startsWith("Retraction Note:"))).toHaveLength(2);
  expect(a.body).toContain("S4");expect(a.body).toContain("S2");expect(a.body).toContain("S3");
  expect(a.review!.limitations.join(" ")).toContain("not an exhaustive");
 });

 it("keeps model pairing and a dated preprint separate from measured material transitions",async()=>{
  const a=articles().find(a=>a.code==="N2")!;
  expect(a.slug).toBe("open-questions/n2");expect(a.materialCases).toEqual([]);
  expect(a.scopeItems?.[0].id).toBe("N2");
  for(const id of a.scopeItems![0].sectionIds){
   const data=await(await get(["articles",a.id,"sections",id])).json();
   expect(data.scopeItems.map((i:{id:string})=>i.id)).toEqual(["N2"]);
   const md=await(await get(["articles",a.id,"sections",id],"?format=markdown")).text();
   expect(md).toContain(data.section.markdown);
   for(const limit of a.review!.limitations)expect(md).toContain(limit);
  }
  for(const q of ["非常规超导统一理论","pairing inverse problem","a dome in a zero-temperature order parameter"]){
   expect(searchArticles(searchIndex().entries,q).some(x=>x.id===a.id)).toBe(true);
   expect(searchArticles(searchIndex().entries,q,{tcMin:0.01}).some(x=>x.id===a.id)).toBe(false);
  }
  const preprint=a.references.find(r=>r.doi==="10.48550/arXiv.2608.12465")!;
  expect(preprint.publicationStatus).toBe("preprint");expect(preprint.verification.evidenceUrl).toMatch(/v1$/);
  expect(a.markdown).toContain("Publication: preprint");
  expect(a.references.some(r=>r.doi==="10.1126/science.adh7691")).toBe(true);
  expect(a.references.some(r=>r.doi==="10.1126/science.ade9194")).toBe(false);
 });

 it("exports correlated-material prediction limits without promoting mesh temperatures into material measurements",async()=>{
  const a=articles().find(a=>a.code==="N3")!;
  expect(a.slug).toBe("open-questions/n3");expect(a.materialCases).toEqual([]);
  expect(a.scopeItems?.[0].id).toBe("N3");
  for(const id of a.scopeItems![0].sectionIds){
   const data=await(await get(["articles",a.id,"sections",id])).json();
   expect(data.scopeItems.map((i:{id:string})=>i.id)).toEqual(["N3"]);
   const md=await(await get(["articles",a.id,"sections",id],"?format=markdown")).text();
   expect(md).toContain(data.section.markdown);
   for(const limit of a.review!.limitations)expect(md).toContain(limit);
  }
  for(const q of ["强关联Tc预测","ab initio Tc prediction","a fictitious temperature sets a Matsubara mesh"]){
   expect(searchArticles(searchIndex().entries,q).some(x=>x.id===a.id)).toBe(true);
   expect(searchArticles(searchIndex().entries,q,{tcMin:0.01}).some(x=>x.id===a.id)).toBe(false);
  }
  expect(a.body).toContain("auxiliary bulk gap is not the interacting bulk excitation gap");
  expect(a.body).toContain("mesh temperature is not a computed transition");
  expect(a.references.find(r=>r.doi==="10.1103/PhysRevX.15.021071")!.verification.evidenceUrl).toMatch(/v2$/);
 });

 it("preserves Majorana operation evidence, preprint status and debate access limits",async()=>{
  const a=articles().find(a=>a.code==="N4")!;
  expect(a.slug).toBe("open-questions/n4");expect(a.materialCases).toEqual([]);
  for(const id of a.scopeItems![0].sectionIds){
   const data=await(await get(["articles",a.id,"sections",id])).json();
   expect(data.scopeItems.map((i:{id:string})=>i.id)).toEqual(["N4"]);
   const md=await(await get(["articles",a.id,"sections",id],"?format=markdown")).text();
   expect(md).toContain(data.section.markdown);
   for(const limit of a.review!.limitations)expect(md).toContain(limit);
  }
  for(const q of ["Majorana零模实验证认","non-Abelian braiding evidence","a 50/50 histogram alone"]){
   expect(searchArticles(searchIndex().entries,q).some(x=>x.id===a.id)).toBe(true);
   expect(searchArticles(searchIndex().entries,q,{tcMin:0.01}).some(x=>x.id===a.id)).toBe(false);
  }
  for(const code of ["N4","F5","D12"]){
   const article=articles().find(a=>a.code===code)!;
   expect(article.references.find(r=>r.doi==="10.48550/arXiv.2607.09511")!.publicationStatus).toBe("preprint");
   expect(article.markdown).toContain("Publication: preprint");
  }
  expect(a.references.filter(r=>r.verification.scope==="publication-identity-only")).toHaveLength(2);
  expect(a.body).toContain("not a unique fusion signature");
  expect(articles().find(a=>a.code==="D12")!.body).toContain("Van Loo's 2026 work");
 });

 it("publishes all fifteen experimental-method sections with individual evidence limits",async()=>{
  const a=articles().find(a=>a.code==="I")!;
  expect(a.publicationKind).toBe("handbook");expect(a.slug).toBe("experimental-methods");
  expect(a.scopeItems?.map(i=>i.id)).toEqual(Array.from({length:15},(_,i)=>"I"+(i+1)));
  for(const item of a.scopeItems!){
   expect(item.sectionIds).toEqual([item.id.toLowerCase()]);
   const response=await get(["articles",a.id,"sections",item.sectionIds[0]]);
   const data=await response.json();expect(data.scopeItems.map((s:{id:string})=>s.id)).toEqual([item.id]);
   expect(data.section.markdown).toContain("## "+item.id+" — ");
   const exported=await(await get(["articles",a.id,"sections",item.sectionIds[0]],"?format=markdown")).text();
   for(const limit of item.limitations)expect(exported).toContain(limit);
  }
  expect(a.materialCases).toEqual([]);
  for(const query of ["实验方法","中子散射","reciprocal-lattice sum"]){
   expect(searchArticles(searchIndex().entries,query).some(r=>r.id===a.id)).toBe(true);
   expect(searchArticles(searchIndex().entries,query,{tcMin:0.01}).some(r=>r.id===a.id)).toBe(false);
  }
  expect(a.body).toContain("not a simultaneous demonstration of zero resistance");
  expect(a.body).toContain("different fields");expect(a.body).toContain("lower bounds on correlation lengths");
 });

 it("exports every theoretical-method item without promoting model results into measured Tc",async()=>{
  const a=articles().find(a=>a.code==="J")!;
  expect(a.scopeItems?.map(i=>i.id)).toEqual(Array.from({length:12},(_,i)=>"J"+(i+1)));
  for(const item of a.scopeItems!){
   const id=item.id.toLowerCase();expect(item.sectionIds).toEqual([id]);
   const data=await(await get(["articles",a.id,"sections",id])).json();
   expect(data.scopeItems.map((s:{id:string})=>s.id)).toEqual([item.id]);
   const md=await(await get(["articles",a.id,"sections",id],"?format=markdown")).text();
   expect(md).toContain(data.section.markdown);
   for(const limit of item.limitations)expect(md).toContain(limit);
  }
  for(const q of ["理论工具","重整化群","undersampled distant hopping"]){
   expect(searchArticles(searchIndex().entries,q).some(x=>x.id===a.id)).toBe(true);
   expect(searchArticles(searchIndex().entries,q,{tcMin:0.01}).some(x=>x.id===a.id)).toBe(false);
  }
  expect(a.materialCases).toEqual([]);
  expect(a.body).toContain("not collectively weak-correlation methods");
  expect(a.body).toContain("does not take its width to the two-dimensional thermodynamic limit");
  expect(a.body).toContain("abstract was checked");
  expect(a.body).toContain("loss of perturbative control");
  expect(a.body).toContain("particle-hole redundancy");
 });

 it("preserves all application sections and excludes operating temperatures from Tc filtering",async()=>{
  const a=articles().find(a=>a.code==="K")!;
  expect(a.scopeItems?.map(i=>i.id)).toEqual(Array.from({length:10},(_,i)=>"K"+(i+1)));
  for(const item of a.scopeItems!){
   const id=item.id.toLowerCase();expect(item.sectionIds).toEqual([id]);
   const data=await(await get(["articles",a.id,"sections",id])).json();
   expect(data.scopeItems.map((s:{id:string})=>s.id)).toEqual([item.id]);
   const md=await(await get(["articles",a.id,"sections",id],"?format=markdown")).text();
   expect(md).toContain(data.section.markdown);
   for(const limit of item.limitations)expect(md).toContain(limit);
  }
  for(const q of ["磁悬浮","超导应用","hypothetical rotating annulus"]){
   expect(searchArticles(searchIndex().entries,q).some(x=>x.id===a.id)).toBe(true);
   expect(searchArticles(searchIndex().entries,q,{tcMin:0.01}).some(x=>x.id===a.id)).toBe(false);
  }
  expect(a.materialCases).toEqual([]);
  expect(a.body).toContain("using MoSi, not WSi or NbN");
  expect(a.body).toContain("copper-reinforced, spliced Bi-2223");
  expect(a.body).toContain("ideal 20 minutes, not a measured discharge duration");
  const undated=a.references.filter(r=>r.year===null);expect(undated).toHaveLength(2);
  const fullMd=await(await get(["articles",a.id,"markdown"])).text();
  for(const r of undated){
   expect(fullMd).toContain(r.title+" (Publication date unknown)");
   const exported=await getAll("sources");expect(exported.sources.find((s:{id:string})=>s.id===r.id).year).toBeNull();
  }
  const schema=await(await get(["openapi.json"])).json();
  expect(schema.components.schemas.Source.properties.year.type).toEqual(["integer","null"]);
  const sectionMd=await(await get(["articles",a.id,"sections","k4"],"?format=markdown")).text();
  expect(sectionMd).toContain("ITER magnets (Publication date unknown)");
 });

 it("preserves eighteen historical milestones and distinguishes chronology from transition criteria",async()=>{
  const a=articles().find(a=>a.code==="L")!;
  expect(a.scopeItems?.map(i=>i.id)).toEqual(Array.from({length:18},(_,i)=>"L"+(i+1)));
  for(const item of a.scopeItems!){
   const id=item.id.toLowerCase();expect(item.sectionIds).toEqual([id]);
   const data=await(await get(["articles",a.id,"sections",id])).json();
   expect(data.scopeItems.map((s:{id:string})=>s.id)).toEqual([item.id]);
   const md=await(await get(["articles",a.id,"sections",id],"?format=markdown")).text();
   expect(md).toContain(data.section.markdown);
   for(const limit of item.limitations)expect(md).toContain(limit);
  }
  for(const q of ["超导历史","历史里程碑","metallic shorts"]){
   expect(searchArticles(searchIndex().entries,q).some(x=>x.id===a.id)).toBe(true);
   expect(searchArticles(searchIndex().entries,q,{tcMin:0.01}).some(x=>x.id===a.id)).toBe(false);
  }
  expect(a.materialCases).toEqual([]);
  expect(a.body).toContain("not a 93 K zero-resistance result");
  expect(a.body).toContain("appeared in 2018, not 2022");
  expect(a.body).toContain("LaOFeP paper appeared in 2006");
  expect(a.body).toContain("not the pressure at which the reported transition was measured");
  const guide=a.sections.find(s=>s.id==="chronological-guide")!;
  expect(guide.markdown.indexOf("(#l16)")).toBeLessThan(guide.markdown.indexOf("(#l15)"));
  expect(a.body).toContain("Complete scientific acceptance");
 });

 it("exports six research-method sections without making models or database records experimental evidence",async()=>{
  const a=articles().find(a=>a.code==="M")!;
  expect(a.scopeItems?.map(i=>i.id)).toEqual(Array.from({length:6},(_,i)=>"M"+(i+1)));
  for(const item of a.scopeItems!){
   const id=item.id.toLowerCase();expect(item.sectionIds).toEqual([id]);
   const data=await(await get(["articles",a.id,"sections",id])).json();
   expect(data.scopeItems.map((s:{id:string})=>s.id)).toEqual([item.id]);
   const md=await(await get(["articles",a.id,"sections",id],"?format=markdown")).text();
   expect(md).toContain(data.section.markdown);
   for(const limit of item.limitations)expect(md).toContain(limit);
  }
  for(const q of ["研究方法","论文精读","machine learning Tc","overlapping selections"]){
   expect(searchArticles(searchIndex().entries,q).some(x=>x.id===a.id)).toBe(true);
   expect(searchArticles(searchIndex().entries,q,{tcMin:0.01}).some(x=>x.id===a.id)).toBe(false);
  }
  expect(a.materialCases).toEqual([]);
  expect(a.body).toContain("not independent peer review or experimental replication");
  expect(a.body).toContain("96.6% accuracy and zero positive recall");
  expect(a.body).toContain("approximately 7.69%");
  expect(a.body).toContain("818 retained calculated spectra");
  expect(a.body).toContain("NIMS is the institution that publishes SuperCon");
  expect(a.references.find(r=>r.doi==="10.1038/s41524-024-01475-4")?.year).toBe(2025);
  expect(a.references.find(r=>r.doi==="10.48505/nims.3837")?.publicationStatus).toBe("dataset");
  const section=await(await get(["articles",a.id,"sections","m6"],"?format=markdown")).text();
  expect(section).toContain("Publication date unknown");
 });

 it("matches short Han keywords within phrases while keeping short Latin tokens exact",()=>{
  const entry={...searchIndex().entries[0],title:"Total optical response",aliases:["平带超导温度上限","镍酸盐超导"],dois:[],text:"Spectral weight",materialCases:[]};
  for(const query of ["平带","镍","酸盐"]){expect(searchArticles([entry],query)).toHaveLength(1);}
  for(const query of ["Al","sp","不存在"]){expect(searchArticles([entry],query)).toEqual([]);}
  expect(searchArticles([{...entry,aliases:["Al"]}],"Al")).toHaveLength(1);
 });

 it("separates interface noise-floor zero, BKT analysis and spectroscopic temperatures through API exports",async()=>{
  const a=articles().find(a=>a.code==="D11")!;
  const zero=a.materialCases.filter(c=>c.criterion==="zero-resistance");
  expect(zero.map(c=>c.tcK)).toEqual([0.2,0.1]);
  const bkt=a.materialCases.find(c=>c.criterion==="bkt-iv-alpha-three")!;
  expect(bkt.tcK).toBe(0.188);
  const gap=a.materialCases.find(c=>c.criterion==="spectroscopic-gap")!;
  expect(gap.tcK).toBeNull();expect(gap.reportedTemperatureK).toBe(65);
  for(const q of ["二维超导","interface superconductivity"]){
   expect(searchArticles(searchIndex().entries,q).some(x=>x.id===a.id)).toBe(true);
   expect(searchArticles(searchIndex().entries,q,{tcMin:1}).some(x=>x.id===a.id)).toBe(false);
  }
  const data=await(await get(["articles",a.id,"sections","oxide-interface-controls"])).json();
  const logvenov=data.sources.find((x:{doi:string})=>x.doi==="10.1126/science.1178863");
  expect(logvenov.verification.scope).toBe("original-abstract-only");
  const md=await(await get(["articles",a.id,"sections","mathematical-assumptions"],"?format=markdown")).text();
  expect(md).toContain("model conversion");expect(md).toContain("Complete scientific acceptance remains open");
 });

 it("exposes the approved overview through discovery and exports without inventing material transitions",async()=>{
  const response=await get(["articles","scwiki-overview"]);
  expect(response.status).toBe(200);
  const {article}=await response.json();
  expect(article.topicId).toBe("scwiki-topic-overview");
  expect(article.provenance.path).toBe("A_phenomenology/A_overview.md");
  expect(article.materialCases).toEqual([]);
  const topics=await getAll("topics");
  expect(topics.topics.some((t:{articleId:string})=>t.articleId===article.id)).toBe(true);
  const schema=await(await get(["openapi.json"])).json();
  const idPattern=new RegExp(schema.components.schemas.ArticleId.pattern);
  expect(idPattern.test(article.id)).toBe(true);
  expect(idPattern.test("scwiki-overview-extra")).toBe(false);
  for(const query of ["superconductivity overview","超导总览"]){
   const found=await(await get(["search"],"?q="+encodeURIComponent(query))).json();
   expect(found.results.some((a:{id:string})=>a.id===article.id)).toBe(true);
  }
  expect(searchArticles(searchIndex().entries,"superconductivity overview",{tcMin:1}).some(a=>a.id===article.id)).toBe(false);
  const section=await(await get(["articles",article.id,"sections","material-cases"],"?format=markdown")).text();
  expect(section).toContain("No sample-specific material records");
  expect(section).toContain("Complete scientific acceptance remains open");
 });
 it("exports versioned research datasets without promoting field-sweep temperatures to transition Tc",async()=>{
  const a=articles().find(a=>a.code==="G3")!;
  const dataset=a.references.find(r=>r.doi==="10.6084/m9.figshare.31861684.v1")!;
  const schema=await (await get(["openapi.json"])).json();
  expect(schema.components.schemas.Source.properties.publicationStatus.enum).toContain("dataset");
  const section=await (await get(["articles",a.id,"sections","limits-and-disputes"])).json();
  expect(section.sources.find((r:{id:string})=>r.id===dataset.id).publicationStatus).toBe("dataset");
  const md=await (await get(["articles",a.id,"sections","limits-and-disputes"],"?format=markdown")).text();
  expect(md).toContain(dataset.doi);expect(md).toContain("Publication: dataset");
  expect(md).toContain("noise floor");expect(md).toContain("Complete scientific acceptance remains open");
  expect(a.materialCases.map(r=>r.reportedTemperatureK)).toEqual([2,3,1.7]);
  expect(a.materialCases.every(r=>r.tcK===null&&r.temperatureKind==="measurement")).toBe(true);
  expect(searchArticles(searchIndex().entries,"field reentrance").some(r=>r.code==="G3")).toBe(true);
  expect(searchArticles(searchIndex().entries,"field reentrance",{tcMin:1}).some(r=>r.code==="G3")).toBe(false);
 });

 it("attributes the A1 film-transport theory to Halperin-Nelson without promoting abstract review to full verification",()=>{
  const a=articles().find(a=>a.code==="A1")!;
  const ref=a.references.find(r=>r.doi==="10.1007/BF00116988")!;
  const claim=a.claims.find(c=>c.id==="scwiki-a1-claim-experimental-criteria-1")!;
  expect(ref.title).toBe("Resistive transition in superconducting films");
  expect(ref.verification.scope).toBe("primary-abstract-scoped-check");
  expect(claim.sourceIds).toContain(ref.id);
  expect(claim.evidenceType).toBe("theory");
  expect(a.body).not.toContain("ref-source-6b3c996f39226a0a");
  expect(a.body).toContain("full derivation has not yet been reviewed");
  expect(a.editorialStatus).toBe("scoped-check");
  expect(a.corrections.some(c=>c.id==="scwiki-a1-correction-1")).toBe(true);
 });
 it("keeps the conditional chaos bound theoretical and carries its review scope through section APIs",async()=>{
  const a=articles().find(a=>a.code==="H2")!;
  const response=await get(["articles",a.id,"sections","limits-and-disputes"]);
  const payload=await response.json();
  const claim=payload.claims.find((c:{id:string})=>c.id==="scwiki-h2-claim-limits-and-disputes-1");
  expect(claim.evidenceType).toBe("theory");
  expect(claim.conditions).toContain("factorization");
  expect(claim.conditions).toContain("no transport-time identification");
  expect(claim.verificationScope).toContain("Eq. (2.5)");
  expect(payload.section.markdown).toContain(claim.statement);
  expect(payload.section.markdown).toContain("not a measured charge-transport");
  expect(payload.sources.find((r:{id:string})=>r.id==="source-8339743a9f1c3239").verification.scope).toBe("primary-full-text-scoped-check");
  expect(payload.sources.find((r:{id:string})=>r.id==="source-67da95cac5481029").verification.scope).toBe("review-full-text-scoped-check");
  expect(a.references.find(r=>r.doi==="10.1126/science.1227612")!.verification.scope).toBe("selected-final-opening-page-check");
  expect(a.references.find(r=>r.doi==="10.1126/science.1227612")!.verification.note).toContain("does not include pages 805–807");
  expect(a.editorialStatus).toBe("scoped-check");
 });
 it("preserves source-specific review limitations in Markdown exports",async()=>{
  for(const a of articles()){
   const markdown=await (await get(["articles",a.id,"markdown"])).text();
   for(const ref of a.references){
    expect(markdown).toContain("Checked: "+ref.verification.checkedAt);
    if(ref.verification.note)expect(markdown).toContain(ref.verification.note);
   }
  }
 });
 it("retains claim conditions and article/source review limits in every section export",async()=>{
  for(const a of articles())for(const section of a.sections){
   const route=["articles",a.id,"sections",section.id];
   const data=await (await get(route)).json();
   const response=await get(route,"?format=markdown");
   const markdown=await response.text();
   expect(response.headers.get("X-SCWiki-Revision")).toBe(a.revision);
   expect(markdown).toContain(section.markdown);
   expect(markdown).toContain(a.review.scope);
   for(const limit of a.review.limitations)expect(markdown).toContain(limit);
   for(const c of data.claims){
    expect(markdown).toContain(c.conditions);
    expect(markdown).toContain("Evidence: "+c.evidenceType);
    if(c.verificationScope)expect(markdown).toContain(c.verificationScope);
    expect(a.markdown).toContain(c.conditions);
   }
   for(const ref of data.sources){
    expect(markdown).toContain("Check: "+ref.verification.scope);
    expect(markdown).toContain("Checked: "+ref.verification.checkedAt);
    if(ref.verification.note)expect(markdown).toContain(ref.verification.note);
   }
   for(const citation of section.markdown.matchAll(/\]\(#ref-([a-z0-9-]+)\)/g))expect(data.sources.some((r:{id:string})=>r.id===citation[1])).toBe(true);
  }
 });
 it("retains each material probe in both article and section Markdown",async()=>{
  for(const a of articles()){
   const section=await (await get(["articles",a.id,"sections","material-cases"],"?format=markdown")).text();
   for(const record of a.materialCases){expect(a.markdown).toContain(record.probe);expect(section).toContain(record.probe);}
  }
 });
 it("preserves partial-isotope scope, magnetic criteria and unknown conditions",async()=>{
  const a=articles().find(a=>a.code==="A4")!;
  expect(a.body).toContain("not the total");
  expect(a.body).toContain("not a fit to MgB2");
  expect(a.body).toContain("Shared calibration errors");
  expect(a.materialCases.map(r=>r.tcK)).toEqual([40.2,39.2]);
  expect(a.materialCases.every(r=>r.pressureRegime==="unknown"&&r.equilibrium==="unknown"&&r.criterion==="diamagnetic")).toBe(true);
  const cases=await (await get(["articles",a.id,"sections","material-cases"],"?format=markdown")).text();
  expect(cases).toContain("2% of low-temperature diamagnetic signal");
  expect(cases).toContain("25 G");
  expect(searchArticles(searchIndex().entries,"isotope",{tcMin:40,evidence:"experiment"}).some(x=>x.id===a.id)).toBe(true);
  expect(searchArticles(searchIndex().entries,"isotope",{tcMin:40.3}).some(x=>x.id===a.id)).toBe(false);
  expect(searchArticles(searchIndex().entries,"isotope",{pressure:"ambient"}).some(x=>x.id===a.id)).toBe(false);
  expect(searchArticles(searchIndex().entries,"isotope",{evidence:"theory",tcMin:1}).some(x=>x.id===a.id)).toBe(false);
  expect(a.references.filter(r=>r.year===1950).every(r=>r.verification.scope==="publisher-metadata-only")).toBe(true);
 });
 it("separates spectral gap magnitude, phase evidence and calculated multiband gaps",async()=>{
  const a=articles().find(a=>a.code==="A5")!;
  expect(a.body).toContain("magnitude-only model");
  expect(a.body).toContain("uncoupled spectral contributions");
  expect(a.body).toContain("two unfrustrated NCCO geometries");
  expect(a.body).toContain("spectroscopic gap-closing temperature");
  expect(a.references.some(r=>r.doi==="10.1038/nature00992")).toBe(false);
  const choi=a.references.find(r=>r.doi==="10.1038/nature00898")!;
  const claim=a.claims.find(c=>c.sourceIds.includes(choi.id))!;
  expect(claim.evidenceType).toBe("theory");
  expect(claim.conditions).toContain("not direct measurements");
  expect(a.materialCases).toEqual([]);
  expect(searchArticles(searchIndex().entries,"gap nodes").some(x=>x.id===a.id)).toBe(true);
  expect(searchArticles(searchIndex().entries,"gap",{tcMin:1}).some(x=>x.id===a.id)).toBe(false);
  const section=await (await get(["articles",a.id,"sections","limits-and-disputes"],"?format=markdown")).text();
  expect(section).toContain(claim.conditions);
  expect(section).toContain("image fits");
 });
 it("publishes BCS as a conditional theory entry without inventing experimental Tc records",async()=>{
  const a=articles().find(a=>a.code==="B1")!;
  expect(a.evidenceTypes).toEqual(["theory","hypothesis"]);
  expect(a.materialCases).toEqual([]);
  const cases=a.sections.find(s=>s.id==="material-cases")!;
  expect(cases.markdown).toContain("No sample-specific material records");
  expect(renderToStaticMarkup(<ScientificMarkdown markdown={cases.markdown}/>)).not.toContain("<table");
  expect(a.body).toContain("**one spin**");
  expect(a.body).toContain("angular frequency");
  expect(a.body).toContain("3.528");
  expect(a.body).toContain("not a measured transition temperature");
  expect(a.references).toHaveLength(2);
  expect(a.references.every(r=>r.verification.scope==="primary-full-text-scoped-check")).toBe(true);
  expect(searchArticles(searchIndex().entries,"Cooper pair").some(x=>x.id===a.id)).toBe(true);
  expect(searchArticles(searchIndex().entries,"BCS",{tcMin:1}).some(x=>x.id===a.id)).toBe(false);
  const payload=await (await get(["articles",a.id])).json();
  expect(payload.article.provenance.path).toBe("B_mechanisms/B1_BCS_weak_coupling.md");
 });
 it("does not apply a new article's primary check to other claims citing the same paper",async()=>{
  const payload=await getAll("sources");
  const bcs=payload.sources.find((r:{doi:string})=>r.doi==="10.1103/PhysRev.108.1175");
  expect(bcs.verification.scope).toBe("article-scoped-checks");
  expect(bcs.usedBy).toEqual(expect.arrayContaining(["scwiki-a1","scwiki-b1"]));
  expect(bcs.articleChecks.find((c:{articleId:string})=>c.articleId==="scwiki-a1").verification.scope).toBe("crossref-metadata-only");
  expect(bcs.articleChecks.find((c:{articleId:string})=>c.articleId==="scwiki-b1").verification.scope).toBe("primary-full-text-scoped-check");
 });
 it("keeps B12 spectroscopic gap closure out of transition filters and exports source-specific debate",async()=>{
  const a=articles().find(a=>a.code==="B12")!;
  const gap=a.materialCases.find(r=>r.formula==="FeSe/SrTiO3")!;
  expect(gap.tcK).toBeNull();expect(gap.temperatureKind).toBe("spectroscopic-gap");
  expect(gap.reportedTemperatureK).toBe(58);
  const onset=a.materialCases.find(r=>r.formula==="MgB2")!;
  expect(onset.tcK).toBe(39);expect(onset.criterion).toBe("four-probe-resistive-onset");
  for(const query of ["多能带配对","multichannel pairing"]){
   expect(searchArticles(searchIndex().entries,query).some(r=>r.code==="B12")).toBe(true);
  }
  for(const query of ["?q=FeSe%20STO&tcMin=1","?q=MgB2&criterion=ARPES-mean-field-gap-closure&tcMin=1"]){
   const results=await(await get(["search"],query)).json();
   expect(results.results.some((r:{code:string})=>r.code==="B12")).toBe(false);
  }
  const onsetResults=await(await get(["search"],"?q=MgB2&tcMin=38&criterion=four-probe-resistive-onset")).json();
  expect(onsetResults.results.some((r:{code:string})=>r.code==="B12")).toBe(true);
  const section=await(await get(["articles",a.id,"sections","material-interpretation"],"?format=markdown")).text();
  for(const doi of ["10.1038/nature13894","10.1103/PhysRevLett.120.237001","10.1103/PhysRevLett.127.016803"])expect(section).toContain(doi);
  expect(section).toContain("Full supplementary");
  expect(section).toContain("Complete scientific acceptance remains open");
 });
 it("corrects the unrelated biology DOI and separates calculated MgB2 gaps from experiments",()=>{
  const a=articles().find(a=>a.code==="B12")!;
  expect(a.references.some(r=>r.doi==="10.1038/nature00992")).toBe(false);
  const ref=a.references.find(r=>r.doi==="10.1038/nature00898")!;
  expect(ref.title).toContain("MgB2");
  expect(ref.verification.scope).toBe("selected-published-anisotropic-gap-check");
  const computed=a.claims.find(c=>c.id==="scwiki-b12-claim-experimental-criteria-2")!;
  expect(computed.evidenceType).toBe("theory");
  expect(computed.sourceIds).toEqual([ref.id]);
  expect(a.body).toContain(computed.statement);
  const experimental=a.claims.find(c=>c.id==="scwiki-b12-claim-experimental-criteria-1")!;
  expect(experimental.evidenceType).toBe("experiment");
  expect(experimental.sourceIds).not.toContain(ref.id);
  expect(a.corrections.some(c=>c.id==="scwiki-b12-correction-2")).toBe(true);
  const manifest=JSON.parse(readFileSync("content/scwiki/source-manifest.json","utf8"));
  expect(manifest.correctionRegister.find((c:{id:string})=>c.id==="correction-nature00992-mgb2-doi").affectedTopics).toEqual(["A5","B2","B12","B14","C1","D7"]);
 });
 it("keeps critical-field scales conditional and does not classify model fields as measurements",async()=>{
  const a=articles().find(a=>a.code==="A6")!;
  expect(a.materialCases).toEqual([]);
  expect(a.evidenceTypes).toEqual(["theory","hypothesis"]);
  expect(a.body).toContain("exists for both type-I and type-II");
  expect(a.body).toContain("amperes per metre");
  expect(a.body).toContain("normal-state magnetic response is negligible");
  expect(a.body).toContain("does not uniquely identify triplet pairing");
  expect(a.references.find(r=>r.doi==="10.1103/PhysRevLett.9.266")!.verification.scope).toBe("publisher-metadata-only");
  expect(a.references.find(r=>r.doi==="10.1103/PhysRev.147.295")!.verification.scope).toBe("primary-abstract-scoped-check");
  expect(a.references.find(r=>r.doi==="10.1103/PhysRev.108.1175")!.id).toBe(articles().find(a=>a.code==="B1")!.references.find(r=>r.doi==="10.1103/PhysRev.108.1175")!.id);
  expect(searchArticles(searchIndex().entries,"Pauli limit").some(r=>r.id===a.id)).toBe(true);
  expect(searchArticles(searchIndex().entries,"Hc2",{tcMin:1}).some(r=>r.id===a.id)).toBe(false);
  const result=await (await get(["articles",a.id,"sections","mathematical-assumptions"],"?format=markdown")).text();
  expect(result).toContain("g=2");
  expect(result).toContain("not full scientific validation");
 });
 it("distinguishes heat-capacity models, entropy assumptions and experimental scaling",async()=>{
  const a=articles().find(a=>a.code==="A3")!;
  expect(a.body).toContain("equal extrapolated zero-temperature entropies");
  expect(a.body).toContain("first-order transition has latent heat");
  expect(a.body).toContain("Multiple bands do not necessarily broaden");
  expect(a.body).toContain("jump itself scales as $T_c^3$");
  const empirical=a.claims.find(c=>c.statement.startsWith("Bud'ko"))!;
  expect(empirical.evidenceType).toBe("experiment");
  expect(empirical.verificationScope).toContain("Publisher abstract only");
  expect(a.materialCases).toEqual([]);
  expect(searchArticles(searchIndex().entries,"entropy balance").some(r=>r.id===a.id)).toBe(true);
  expect(searchArticles(searchIndex().entries,"heat capacity",{tcMin:1}).some(r=>r.id===a.id)).toBe(false);
  const section=await (await get(["articles",a.id,"sections","mathematical-assumptions"],"?format=markdown")).text();
  expect(section).toContain("residual entropies");
  expect(section).toContain("No sample-specific heat-capacity curves");
 });
 it("disposes all 282 pinned files and keeps unpublished topics out of the catalogue",()=>{
  const m=JSON.parse(readFileSync("content/scwiki/source-manifest.json","utf8"));
  expect(m.commit).toBe("0a7c9d6696804ec26aa12f8eed68b55c9b3c0fcf");
  expect(m.files).toHaveLength(282);
  expect(new Set(m.files.map((x:{id:string})=>x.id)).size).toBe(282);
  expect(m.files.filter((x:{topicId:string|null})=>x.topicId)).toHaveLength(89);
  expect(m.files.filter((x:{publicBody:boolean})=>x.publicBody).map((x:{articleId:string})=>x.articleId).sort()).toEqual(articles().filter(a=>!a.publicationKind).map(a=>a.id).sort());
  expect(m.files.find((x:{path:string})=>x.path.includes("Al-O")).disposition).toContain("prediction-only");
  expect(articles().map(a=>a.code)).toEqual(expect.arrayContaining(["A1","A2","B12","C2","D11","D3","D4","D5","E4","F7","G7","H2"]));
  expect(articles().every(a=>a.wordCount>=450)).toBe(true);
 });
 it("uses stable IDs, content hashes, complete source mappings and separate review labels",()=>{
  const m=JSON.parse(readFileSync("content/scwiki/source-manifest.json","utf8"));
  for(const a of articles()){
   expect(a.id).toMatch(articleIdPattern);expect(a.topicId).toBe("scwiki-topic-"+a.code.toLowerCase());
   expect(a.revision).toMatch(/^[a-f0-9]{20}$/);expect(a.editorialStatus).toBe("scoped-check");
   const source=m.files.find((x:{id:string})=>x.id===a.provenance.sourceId);
   expect(source.sha256).toBe(a.provenance.sha256);
   expect(a.sourceMap[0].startLine).toBe(1);expect(a.sourceMap.at(-1)?.endLine).toBe(source.lineCount);
   for(let i=1;i<a.sourceMap.length;i++)expect(a.sourceMap[i].startLine).toBe(a.sourceMap[i-1].endLine+1);
   expect(a.review.limitations.join(" ")).toMatch(/\b(?:not|no|pending|remain|open)\b/i);
   expect(a.references.every(r=>r.publicationStatus && r.verification.scope)).toBe(true);
   const {revision,body,markdown,sections,wordCount,...meta}=a;
   expect(createHash("sha256").update("scwiki-export-v4\n"+JSON.stringify(meta)+"\n"+body).digest("hex").slice(0,20)).toBe(revision);
  }
 });
 it.each(articles())("$code resolves claims, citations and article links without treating rendering as proof",(a)=>{
  const slugs=new Set(articles().map(a=>a.slug));
   const refs=new Set(a.references.map(r=>r.id)),sections=new Set(a.sections.map(s=>s.id));
   expect(a.claims.length).toBeGreaterThan(5);
   for(const c of a.claims){expect(sections.has(c.sectionId)).toBe(true);expect(c.conditions.length).toBeGreaterThan(30);expect(c.sourceIds.every(id=>refs.has(id))).toBe(true);}
   for(const match of a.body.matchAll(/\]\(#ref-([a-z0-9-]+)\)/g))expect(refs.has(match[1])).toBe(true);
   for(const match of a.body.matchAll(/\]\(\/scwiki\/([a-z0-9/-]+)\)/g))expect(slugs.has(match[1]) || existsSync("app/scwiki/"+match[1]+"/page.tsx"), "Unresolved SCWiki link: "+match[1]).toBe(true);
   const html=renderToStaticMarkup(<ScientificMarkdown markdown={a.body}/>);
   expect(html).not.toContain('class="katex-error"');expect(html).not.toContain("language-text");
   if(a.body.includes("$$"))expect(html).toContain('class="katex"');
 });
 it("preserves iron-based source-version criteria and excludes nondetection and gap scales",async()=>{
  const a=articles().find(a=>a.code==="D4")!;
  const model=a.claims.find(c=>c.id==="scwiki-d4-claim-mathematical-assumptions-3")!;
  expect(model.sourceRelationship).toBe("mixed-source-and-local-derivation");
  expect(model.conditions).toContain("Near-Tc");expect(model.derivationNote).toContain("not source-fitted");
  expect(model.sourceIds).toContain("source-5717dacf7df85626");
  const modelExport=await(await get(["articles",a.id,"sections","mathematical-assumptions"],"?format=markdown")).text();
  for(const phrase of ["Opposite signs do not require equal gap magnitudes","zero-temperature prediction","mixed-source-and-local-derivation"]){expect(modelExport).toContain(phrase);}
  const limits=await(await get(["articles",a.id,"sections","limits-and-disputes"],"?format=markdown")).text();expect(limits).toContain("initially described as ferromagnetic was misidentified");

  for(const [q,filters,expected] of [["Ba0.6K0.4Fe2As2","&tcMin=38&criterion=resistive-midpoint",true],["Ba0.6K0.4Fe2As2","&tcMin=38&criterion=reported-zero-resistance",false],["Fe1.03Se","&tcMin=1",false],["FeSe STO","&tcMin=1",false],["FeSe0.88","&tcMin=7&criterion=zero-resistance&pressure=ambient",true],["FeSe0.88","&tcMin=7&pressure=high",false]] as const){
   const data=await(await get(["search"],"?q="+encodeURIComponent(q)+filters)).json();expect(data.results.some((r:{code:string})=>r.code==="D4")).toBe(expected);
  }
  const exported=await(await get(["articles",a.id,"sections","experimental-criteria"],"?format=markdown")).text();
  expect(exported).toContain("10% threshold");expect(exported).toContain("Complete scientific acceptance remains open");
  const source=a.references.find(r=>r.doi==="10.1103/PhysRevLett.101.107006")!;
  expect(source.verification.evidenceUrl).toContain("0805.4630v2");
  expect(searchArticles(searchIndex().entries,"铁基超导体").some(r=>r.code==="D4")).toBe(true);
 });
 it("keeps cuprate discovery criteria and recovered sample temperature filters distinct",async()=>{
  const a=articles().find(a=>a.code==="D3")!;
  const history=a.claims.find(c=>c.id==="scwiki-d3-claim-scope-3")!;
  expect(history.evidenceType).toBe("experiment");
  expect(history.sourceRelationship).toBe("context-for-editorial-analysis");
  const phase=a.claims.find(c=>c.id==="scwiki-d3-claim-experimental-criteria-3")!;
  expect(phase.sourceIds).toContain("source-e933e3bbd4beade6");
  const phaseExport=await(await get(["articles",a.id,"sections","experimental-criteria"],"?format=markdown")).text();
  for(const phrase of ["three-junction ring but not the two-junction controls","change in penetration depth","not a direct measurement of gap phase","Original experiment abstracts only","context-for-editorial-analysis"]){expect(phaseExport).toContain(phrase);}
  expect(a.materialCases.find(r=>r.id==="scwiki-d3-material-2")?.pressureGPa).toBeNull();
  expect(a.materialCases.find(r=>r.id==="scwiki-d3-material-3")?.criterion).toBe("resistive-deviation-onset");
  expect(a.materialCases.find(r=>r.id==="scwiki-d3-material-4")?.tcK).toBe(80);
  for(const [q,filters,expected] of [["Deng S4","&tcMin=150&pressure=ambient&criterion=resistive-onset",true],["Deng S4","&tcMin=150&pressure=high",false],["Deng S5","&tcMin=170",false],["Y1.2Ba0.8CuO4-y","&tcMin=90&criterion=zero-resistance",false],["Y1.2Ba0.8CuO4-y","&tcMin=90&criterion=resistive-deviation-onset",true]] as const){
   const response=await get(["search"],"?q="+encodeURIComponent(q)+filters);const data=await response.json();expect(data.results.some((r:{code:string})=>r.code==="D3")).toBe(expected);
  }
  const exported=await(await get(["articles",a.id,"sections","pressure-and-recovered-samples"],"?format=markdown")).text();
  expect(exported).toContain("metastable");expect(exported).toContain("Complete scientific acceptance remains open");
  expect(searchArticles(searchIndex().entries,"铜氧化物超导体").some(r=>r.code==="D3")).toBe(true);
 });
 it("carries C2 preprint limitations through section exports and excludes neutron measurement temperatures",async()=>{
  const a=articles().find(a=>a.code==="C2")!;
  const neutron=a.materialCases.find(r=>r.formula==="Ba0.6K0.4Fe2As2")!;
  expect(neutron.temperatureKind).toBe("measurement");expect(neutron.reportedTemperatureK).toBe(7);expect(neutron.tcK).toBeNull();
  const response=await get(["articles",a.id,"sections","experimental-criteria"]);
  const section=await response.json();
  expect(section.sources.filter((s:{publicationStatus:string})=>s.publicationStatus==="preprint")).toHaveLength(2);
  const md=await(await get(["articles",a.id,"sections","experimental-criteria"],"?format=markdown")).text();
  expect(md).toContain("Publication: preprint");expect(md).toContain("finite");
  expect(md).toContain("Complete scientific acceptance remains open");
  for(const q of ["符号反转配对","s± pairing"]){
   const data=await(await get(["search"],"?q="+encodeURIComponent(q))).json();expect(data.results.some((x:{code:string})=>x.code==="C2")).toBe(true);
   const filtered=await(await get(["search"],"?q="+encodeURIComponent(q)+"&tcMin=1")).json();expect(filtered.results.some((x:{code:string})=>x.code==="C2")).toBe(false);
  }
  expect(a.references.find(r=>r.doi==="10.1038/s41567-023-02348-1")?.verification.scope).toBe("publisher-original-abstract-and-date-check");
 });
 it("corrects the KFe2As2 citation in C2 and records C10 review debt",()=>{
  const a=articles().find(a=>a.code==="C2")!;
  expect(a.body).toMatch(/(?:is about|concerns) KFe2As2/);expect(a.corrections.length).toBeGreaterThanOrEqual(2);
  expect(a.materialCases.find(c=>c.formula==="KFe2As2")?.sourceId).toBe(a.references.find(r=>r.doi==="10.1103/PhysRevLett.109.087001")?.id);
  const m=JSON.parse(readFileSync("content/scwiki/source-manifest.json","utf8"));
  expect(m.correctionRegister.find((r:{id:string})=>r.id==="correction-prl-109-087001-material").affectedTopics).toEqual(["C2","C10"]);
 });
 it("retains unknown and sample conditions for every temperature; no prediction enters an experimental ranking",()=>{
  for(const a of articles())for(const c of a.materialCases){
   expect(c.criterion).toBeTruthy();expect(c.sample).toBeTruthy();expect(c.pressureRegime).toBeTruthy();expect(c.equilibrium).toBeTruthy();
   expect(a.references.some(r=>r.id===c.sourceId)).toBe(true);
   if(c.recordType!=="experiment")expect(c.tcK).toBeNull();
  }
  const index=searchIndex().entries;
  expect(searchArticles(index,"nickelate",{pressure:"ambient",tcMin:70})).toEqual([]);
  expect(searchArticles(index,"FeSe",{criterion:"zero-resistance",tcMin:60})).toEqual([]);
  expect(searchArticles(index,"Al-O")).toEqual([]);
  expect(searchArticles(index,"nickelate",{evidence:"theory",pressure:"high",tcMin:70})).toEqual([]);
  expect(searchArticles(index,"FeSe",{tcMin:60})).toEqual([]);
  const gap=articles().find(a=>a.code==="D11")!.materialCases.find(c=>c.criterion==="spectroscopic-gap")!;
  expect(gap.tcK).toBeNull();expect(gap.reportedTemperatureK).toBe(65);
  expect(searchArticles(index,"La3Ni2O7",{pressure:"high",tcMin:70}).some(a=>a.code==="D5")).toBe(true);
 });
 it("finds aliases, chemical subscripts and DOI without conflating conditional reports",()=>{
  expect(normalizeSearch("La₃Ni₂O₇")).toBe(normalizeSearch("La3Ni2O7"));
  expect(searchArticles(searchIndex().entries,"La₃Ni₂O₇").some(a=>a.code==="D5")).toBe(true);
  expect(searchArticles(searchIndex().entries,"10.1103/PhysRevLett.109.087001").some(a=>a.code==="C2")).toBe(true);
  expect(searchArticles(searchIndex().entries,"s±").some(a=>a.code==="C2")).toBe(true);
  expect(searchArticles(searchIndex().entries,"no-such-material-zzzz")).toEqual([]);
 });
});
describe("SCWiki renderer security",()=>{
 it("rejects executable HTML, protocol smuggling, remote images and KaTeX trust commands",()=>{
  const payload='[bad](javascript:alert(1)) [bad](data:text/html,attack) [bad](//evil.example)\\n\\n<img src=x onerror=alert(1)><script>alert(1)</script>\\n\\n![remote](https://evil.example/x.svg)\\n\\n$\\href{javascript:alert(1)}{bad}$';
  const html=renderToStaticMarkup(<ScientificMarkdown markdown={payload}/>);
  expect(html).not.toMatch(/href="(?:javascript|data):/i);
  expect(html).not.toMatch(/<script|<img|onerror=/i);
  expect(html).not.toContain('src="https://evil.example');
  for(const bad of ["javascript:alert(1)","JaVaScRiPt:alert(1)","data:text/html,x","//evil.example","/\\evil.example","\nhttps://evil.example"])expect(safeUrl(bad)).toBe("");
  expect(safeUrl("https://doi.org/10.1103/PhysRevLett.109.087001")).toContain("https://doi.org/");
 });
});
describe("SCWiki API and migration",()=>{
 it("returns the same revision, text, sources and conditions in JSON and Markdown",async()=>{
  for(const a of articles()){
   const response=await get(["articles",a.id]);expect(response.status).toBe(200);
   const json=await response.json();expect(json.article.revision).toBe(a.revision);expect(response.headers.get("X-SCWiki-Revision")).toBe(a.revision);
   expect(json.article.materialCases).toEqual(a.materialCases);
   const md=await get(["articles",a.id,"markdown"]);expect(await md.text()).toBe(a.markdown);
   for(const s of a.sections){const section=await get(["articles",a.id,"sections",s.id]);const data=await section.json();expect(data.section.markdown).toBe(s.markdown);expect(data.articleRevision).toBe(a.revision);}
  }
  expect(searchIndex().revision).toBe(catalogue().revision);
 });
 it("serves real 404s and rejects invalid filters; API does not invent answers",async()=>{
  expect((await get(["articles","scwiki-x999"])).status).toBe(404);
  expect((await get(["articles","scwiki-a1","sections","unknown"])).status).toBe(404);
  expect((await get(["not-an-endpoint"])).status).toBe(404);
  expect((await get(["search"],"?tcMin=NaN")).status).toBe(400);
  expect((await get(["search"],"?pressure=vacuum")).status).toBe(400);
  const r=await (await get(["search"],"?q=nickelate&pressure=ambient&tcMin=70")).json();expect(r.results).toEqual([]);
  const openapi=await (await get(["openapi.json"])).json();expect(openapi.openapi).toBe("3.1.0");
  expect(Object.values(openapi.paths).every((operation:unknown)=>Object.keys(operation as object).every(k=>k==="get"))).toBe(true);
 });
 it("redirects only the docs landing route and preserves API/data and legacy canonical rules",()=>{
  for(const p of ["/docs","/docs/","/sclib/docs","/sclib/docs/"])expect(legacyDestination(p)).toBe("/scwiki");
  expect(legacyDestination("/docs/api")).toBeNull();expect(legacyDestination("/docs/data")).toBeNull();
  expect(legacyDestination("/sclib/docs/api")).toBe("/docs/api");expect(legacyDestination("/sclib/docs/data/")).toBe("/docs/data");
  expect(legacyDestination("/sclib/scwiki/meissner-effect")).toBe("/scwiki/meissner-effect");
 });
});

it("gives every scientific filter a distinct accessible label",()=>{
 render(<SearchCatalogue initial={articles().map(({id,code,slug,title,summary,evidenceTypes})=>({id,code,slug,title,summary,evidenceTypes}))}/>);
 fireEvent.click(screen.getByRole("button",{name:"Filters"}));
 expect(screen.getByRole("combobox",{name:"Evidence",exact:true})).toBeInTheDocument();
 expect(screen.getByRole("combobox",{name:"Pressure",exact:true})).toBeInTheDocument();
 expect(screen.getByRole("combobox",{name:"State",exact:true})).toBeInTheDocument();
 expect(screen.getByRole("spinbutton",{name:"Reported transition at least (K)",exact:true})).toBeInTheDocument();
 expect(screen.queryByRole("link",{name:/Read article:/})).not.toBeInTheDocument();
});
it.each(["/docs/","/sclib/docs/","/docs"])("keeps exact loopback destination for %s",path=>{
 const response=middleware(new NextRequest("http://localhost:3102"+path+"?q=Fe%2BSe",{headers:{host:"127.0.0.1:3102"}}));
 expect(response.status).toBe(308);
 expect(response.headers.get("location")).toBe("http://127.0.0.1:3102/scwiki?q=Fe%2BSe");
});

it("preserves current criteria, slab geometry and primary engineering source limits in exports",async()=>{
 const a=articles().find(a=>a.code==="A7")!;
 expect(a.materialCases).toEqual([]);
 expect(a.body).toContain("half-thickness in metres");
 expect(a.body).toContain("full vertical loop width in A/m");
 expect(a.body).toContain("perpendicular to the induction");
 expect(a.body).toContain("not a general engineering review");
 expect(a.references.find(r=>r.doi==="10.1103/PhysRevLett.8.250")?.verification.scope).toBe("publisher-metadata-scoped-check");
 expect(searchArticles(searchIndex().entries,"depinning").some(r=>r.code==="A7")).toBe(true);
 expect(searchArticles(searchIndex().entries,"critical current",{tcMin:1}).some(r=>r.code==="A7")).toBe(false);
 const exported=await (await get(["articles",a.id,"sections","mathematical-assumptions"],"?format=markdown")).text();
 expect(exported).toContain("no creep/demagnetization/reversible background");
 expect(exported).toContain("Bean original full text was inaccessible");
});

it("keeps Meissner geometry and source-check boundaries in the article and evidence API",async()=>{
 const a=articles().find(a=>a.code==="A2")!;
 expect(a.body).toContain("not a 150% superconducting volume");
 expect(a.body).toContain("not a formula for a perpendicular-field thin film");
 expect(a.body).toContain("cavity is not a measurement of field penetrating");
 expect(a.references.every(r=>!r.title.includes("\uFFFD")&&!r.title.includes("\n"))).toBe(true);
 const sample=a.materialCases[0];expect(sample.formula).toBe("YBa2Cu3O6.95");expect(sample.tcK).toBeNull();expect(sample.equilibrium).toBe("unknown");expect(sample.pressureRegime).toBe("unknown");
 expect(sample.probe).toContain("900 MHz");
 const section=await (await get(["articles",a.id,"sections","mathematical-assumptions"],"?format=markdown")).text();
 expect(section).toContain("slab full thickness 2a and parallel field");
 expect(section).toContain("Bozovic LSCO is a bibliographic pointer");
 expect(a.claims.filter(c=>c.evidenceType==="experiment")).toHaveLength(2);
});

it("separates transport thresholds, uncertainty and driven measurements in exports",async()=>{
 const a=articles().find(a=>a.code==="A1")!;
 expect(a.body).toContain("constant current-even offset cancels");
 expect(a.body).toContain("current-odd voltage");
 expect(a.body).toContain("not an automatically calibrated confidence statement");
 const driven=a.materialCases.find(c=>c.criterion==="transient-two-terminal-response")!;
 expect(driven.reportedTemperatureK).toBe(100);expect(driven.tcK).toBeNull();expect(driven.equilibrium).toBe("transient");expect(driven.probe).toContain("static four-terminal");
 expect(searchArticles(searchIndex().entries,"K3C60",{tcMin:90}).some(a=>a.code==="A1")).toBe(false);
 const md=await (await get(["articles",a.id,"markdown"])).text();expect(md).toContain("contact calibration from static four-terminal");expect(md).toContain("24 February 2016 caption-correction notice is identified");expect(md).toContain("no exhaustive old/corrected/final-version comparison was performed");
 const schema=await (await get(["openapi.json"])).json();const statuses=schema.components.schemas.Source.properties.publicationStatus.enum;
 expect(statuses).toContain("technical-report");
 for(const a of articles())for(const r of a.references)expect(statuses).toContain(r.publicationStatus);
 expect(a.references.filter(r=>r.publicationStatus==="technical-report")).toHaveLength(2);
});

it("keeps A8 normal-state transport and channel fits separate from transition temperatures",async()=>{
 const a=articles().find(a=>a.code==="A8")!;
 expect(a.materialCases).toHaveLength(3);
 for(const m of a.materialCases){expect(m.temperatureKind).toBe("normal-state");expect(m.tcK).toBeNull();}
 const results=searchArticles(searchIndex().entries,"linear temperature resistivity",{});
 expect(results.some(r=>r.id===a.id)).toBe(true);
 expect(searchArticles(searchIndex().entries,"linear temperature resistivity",{tcMin:1}).some(r=>r.id===a.id)).toBe(false);
 const md=await(await get(["articles",a.id,"sections","experimental-criteria"],"?format=markdown")).text();
 expect(md).toContain("20–40 K");expect(md).toContain("channel-specific fit results");
 const materialMd=await(await get(["articles",a.id,"sections","material-cases"],"?format=markdown")).text();
 expect(materialMd).toContain("ordinary-frequency rate");expect(md).toContain("earlier manuscript passages are version-specific");
 const theory=a.claims.filter(c=>c.sectionId==="mathematical-assumptions");
 expect(theory.length).toBeGreaterThan(5);expect(theory.every(c=>c.evidenceType==="theory")).toBe(true);
 expect(a.body).toContain("g=2");expect(a.body).toContain("2\\pi\\Gamma");
 expect(a.references.find(r=>r.doi==="10.1126/science.1165015")!.verification.scope).toBe("crossref-metadata-only");
});

it("exports historical sources without invented DOIs and separates A9 theory from contact evidence",async()=>{
 const a=articles().find(a=>a.code==="A9")!,historical=a.references.find(r=>r.doi===null)!;
 expect(historical.title).toContain("Thermal Conductivity");expect(historical.url).toContain("jetp.ras.ru");
 const md=await(await get(["articles",a.id,"markdown"])).text();
 const sec=await(await get(["articles",a.id,"sections","scope"],"?format=markdown")).text();
 for(const text of [md,sec]){expect(text).toContain("[Source publication]("+historical.url+")");expect(text).not.toContain("DOI null");}
 const source=await getAll("sources");expect(source.sources.find((r:{id:string})=>r.id===historical.id).doi).toBeNull();
 const spec=await(await get(["openapi.json"])).json();expect(spec.components.schemas.Source.properties.doi.type).toContain("null");
 expect(searchIndex().entries.find(e=>e.id===a.id)!.dois.every(d=>typeof d==="string")).toBe(true);
 const Page=(await import("@/app/scwiki/[slug]/page")).default;
 const html=renderToStaticMarkup(await Page({params:Promise.resolve({slug:a.slug})}));
 expect(html).toContain('href="'+historical.url+'">Source publication</a>');
 expect(html).toContain('"identifier":"'+historical.url+'"');expect(html).not.toContain(">DOI null</a>");
 expect(a.claims.filter(c=>c.evidenceType==="experiment")).toHaveLength(1);
 expect(a.materialCases[0].tcK).toBeNull();
 expect(a.references.find(r=>r.doi==="10.1103/PhysRevB.46.12841")!.verification.scope).toBe("primary-abstract-scoped-check");
 expect(a.body).toContain("zero temperature, bias and magnetic field");
});

it("preserves QPI source identities, phase assumptions and measurement temperatures in evidence exports",async()=>{
 const a=articles().find(a=>a.code==="A10")!;
 expect(a.references.some(r=>r.doi==="10.1038/nature02269")).toBe(false);
 expect(a.references.find(r=>r.doi==="10.1126/science.1066974")!.title).toContain("Vortex Cores");
 expect(a.references.find(r=>r.doi==="10.1126/science.1072640")!.title).toContain("Quasiparticle Interference");
 expect(a.materialCases.map(m=>m.reportedTemperatureK)).toEqual([4.2,.28]);
 expect(a.materialCases.every(m=>m.tcK===null&&m.temperatureKind!=="transition")).toBe(true);
 expect(searchArticles(searchIndex().entries,"QPI",{tcMin:1}).some(r=>r.id===a.id)).toBe(false);
 const md=await(await get(["articles",a.id,"sections","mathematical-assumptions"],"?format=markdown")).text();
 expect(md).toContain("general complex Fourier map");expect(md).toContain("defect, phase origin, band and model assumptions");
 expect(md).toContain("even-in-momentum response condition");
 expect(a.claims.filter(c=>c.evidenceType==="experiment")).toHaveLength(2);
 const json=await(await get(["articles",a.id])).json();expect(json.article.corrections).toHaveLength(2);
 expect(json.article.references.find((r:{doi:string})=>r.doi==="10.1038/nature01496").verification.scope).toBe("publisher-metadata-scoped-check");
});

it("keeps Eliashberg numerical benchmarks separate from material measurements and corrected sources",async()=>{
 const a=articles().find(a=>a.code==="B2")!;
 expect(a.materialCases).toEqual([]);
 expect(searchArticles(searchIndex().entries,"Eliashberg",{tcMin:1}).some(r=>r.id===a.id)).toBe(false);
 const historical=a.references.find(r=>r.doi===null)!;expect(historical.url).toContain("e_007_06_0996.pdf");
 expect(a.references.some(r=>r.doi==="10.1007/BF02745500"||r.doi==="10.1038/nature00992")).toBe(false);
 expect(a.references.find(r=>r.doi==="10.1103/PhysRevLett.122.027001")!.verification.note).toContain("Somayazulu");
 const md=await(await get(["articles",a.id,"sections","mathematical-assumptions"],"?format=markdown")).text();
 expect(md).toContain("zero Coulomb term");expect(md).toContain("synthetic Einstein-model benchmark");
 const full=await(await get(["articles",a.id,"markdown"])).text();
 expect(full).toContain("[Source publication]("+historical.url+")");
 const scope=await(await get(["articles",a.id,"sections","scope"],"?format=markdown")).text();
 expect(scope).toContain("[Source publication]("+historical.url+")");
 expect(a.claims.filter(c=>c.evidenceType==="experiment")).toHaveLength(2);
 expect(a.claims.filter(c=>c.statement.includes("13.30 K")).every(c=>c.evidenceType==="theory")).toBe(true);
 expect(a.corrections).toHaveLength(3);
});

it("exports spin-pairing probe limits and the published erratum without experimental model temperatures",async()=>{
 const a=articles().find(a=>a.code==="B3")!;expect(a.materialCases).toEqual([]);
 expect(searchArticles(searchIndex().entries,"spin fluctuation",{tcMin:1}).some(r=>r.id===a.id)).toBe(false);
 const experimental=await(await get(["articles",a.id,"sections","experimental-criteria"],"?format=markdown")).text();
 expect(experimental).toContain("NMR is not a momentum-resolved magnetic spectrum");
 expect(experimental).toContain("10.1103/PhysRevB.52.R9831");
 const math=await(await get(["articles",a.id,"sections","mathematical-assumptions"],"?format=markdown")).text();
 expect(math).toContain("sign-reversal condition is therefore insufficient");
 expect(math).toContain("not measured transitions");
 for(const code of ["B3","C2"]){
  const article=articles().find(a=>a.code===code)!;
  const md=await(await get(["articles",article.id,"markdown"])).text();
  expect(md).toContain("10.1103/PhysRevLett.101.087004");expect(md).toContain("10.1103/PhysRevLett.102.109902");
  expect(md).toContain("orbital-to-band transformation error");expect(md).toContain("displayed parameter set");
  const json=await(await get(["articles",article.id])).json();
  expect(json.article.references.some((r:{doi:string})=>r.doi==="10.1103/PhysRevLett.102.109902")).toBe(true);
 }
});

it("keeps normal-state magnetic temperatures and extrapolated fields explicit in FM pairing exports",async()=>{
 const a=articles().find(a=>a.code==="B4")!;
 expect(a.materialCases[0].reportedTemperatureK).toBe(4);expect(a.materialCases[0].temperatureKind).toBe("normal-state");expect(a.materialCases[0].tcK).toBeNull();
 expect(searchArticles(searchIndex().entries,"ferromagnetic",{}).some(r=>r.id===a.id)).toBe(true);
 expect(searchArticles(searchIndex().entries,"ferromagnetic",{tcMin:1}).some(r=>r.id===a.id)).toBe(false);
 const md=await(await get(["articles",a.id,"markdown"])).text();
 expect(md).toContain("highest measured field of 20 T");expect(md).toContain("estimated zero-temperature b-axis value of 40 T");
 expect(md).toContain("29 April 2026");expect(md).toContain("4 K is a normal-state measurement temperature");
 expect(md).toContain("10.1038/35020500");expect(md).toContain("10.1038/35098048");
 expect(a.references.some(r=>["10.1038/35050500","10.1038/35065045"].includes(r.doi??""))).toBe(false);
 const sec=await(await get(["articles",a.id,"sections","limits-and-disputes"],"?format=markdown")).text();
 expect(sec).toContain("300 mK superconducting boundaries came from earlier work");expect(sec).toContain("10.1038/s41467-026-71899-7");
 expect(a.claims.filter(c=>c.sectionId==="mathematical-assumptions").every(c=>c.evidenceType==="theory")).toBe(true);
});

it("preserves nematic boundary conditions and unresolved source updates in machine-readable sections",async()=>{
 const a=articles().find(a=>a.code==="B5")!;
 expect(a.materialCases).toEqual([]);
 expect(searchArticles(searchIndex().entries,"elastoresistance",{}).some(r=>r.id===a.id)).toBe(true);
 expect(searchArticles(searchIndex().entries,"elastoresistance",{tcMin:1}).some(r=>r.id===a.id)).toBe(false);
 const math=await(await get(["articles",a.id,"sections","mathematical-assumptions"],"?format=markdown")).text();
 expect(math).toContain("At fixed strain");expect(math).toContain("at fixed stress");expect(math).toContain("These derivatives are not interchangeable");
 expect(math).toContain("Chu2012 correction content remains unverified");
 const exp=await(await get(["articles",a.id,"sections","experimental-criteria"],"?format=markdown")).text();
 expect(exp).toContain("including FeTeSe");expect(exp).toContain("publisher text remains unavailable");
 expect(exp).toContain("10.1126/science.338.6106.469-a");
 const json=await(await get(["articles",a.id])).json();
 expect(json.article.references.find((r:{doi:string})=>r.doi==="10.1126/science.1221713").verification.scope).toBe("author-manuscript-with-update-pending");
 expect(a.claims.filter(c=>c.sectionId==="mathematical-assumptions").every(c=>c.evidenceType==="theory")).toBe(true);
});

it("exports charge-order evidence limits and keeps ordering temperatures out of Tc filters",async()=>{
 const a=articles().find(a=>a.code==="B6")!;
 expect(a.materialCases).toEqual([]);
 expect(searchArticles(searchIndex().entries,"charge fluctuations",{}).some(r=>r.id===a.id)).toBe(true);
 expect(searchArticles(searchIndex().entries,"charge fluctuations",{tcMin:1}).some(r=>r.id===a.id)).toBe(false);
 const exp=await(await get(["articles",a.id,"sections","experimental-criteria"],"?format=markdown")).text();
 expect(exp).toContain("130 meV");expect(exp).toContain("upper energy bound of 20 meV");expect(exp).toContain("not a resolved pairing-boson peak");
 expect(exp).toContain("67 K");expect(exp).toContain("135 K");
 const limits=await(await get(["articles",a.id,"sections","limits-and-disputes"],"?format=markdown")).text();
 expect(limits).toContain("10.1103/PhysRevLett.125.247002");
 expect(a.references.some(r=>r.doi==="10.1103/PhysRevMaterials.4.121801")).toBe(false);
 expect(limits).toContain("single-component counterexample");expect(limits).toContain("exact particle–hole symmetry");
 expect(limits).toContain("full scientific");
 expect(a.claims.filter(c=>c.sectionId==="mathematical-assumptions").every(c=>c.evidenceType==="theory")).toBe(true);
});

it("preserves exciton proposal disputes and transient transport conditions without ranking them as Tc",async()=>{
 const a=articles().find(a=>a.code==="B7")!,m=a.materialCases[0];
 expect(m.reportedTemperatureK).toBe(100);expect(m.tcK).toBeNull();expect(m.temperatureKind).toBe("transient-response");
 expect(searchArticles(searchIndex().entries,"exciton",{}).some(r=>r.id===a.id)).toBe(true);
 expect(searchArticles(searchIndex().entries,"exciton",{tcMin:1}).some(r=>r.id===a.id)).toBe(false);
 const exp=await(await get(["articles",a.id,"sections","experimental-criteria"],"?format=markdown")).text();
 expect(exp).toContain("two-terminal probe");expect(exp).toContain("static four-terminal");expect(exp).toContain("not a direct transient four-terminal");
 const conditions=await(await get(["articles",a.id,"sections","material-cases"],"?format=markdown")).text();
 expect(conditions).toContain("75ps");expect(conditions).toContain("transient");
 const limits=await(await get(["articles",a.id,"sections","limits-and-disputes"],"?format=markdown")).text();
 expect(limits).toContain("10.1103/PhysRevB.8.4429");expect(limits).toContain("10.1103/PhysRevB.8.4433");
 expect(limits).toContain("30 THz");expect(limits).toContain("10 THz");expect(limits).toContain("preprint");
 const theory=a.references.find(r=>r.doi==="10.48550/arXiv.2604.10987")!;expect(theory.publicationStatus).toBe("preprint");expect(theory.url).toContain("v2");
 expect(a.claims.filter(c=>c.sectionId==="mathematical-assumptions").every(c=>c.evidenceType==="theory")).toBe(true);
});

it("keeps plasmon mode energies and spectroscopy temperatures distinct from superconducting transitions",async()=>{
 const a=articles().find(a=>a.code==="B8")!,m=a.materialCases[0];
 expect(m.reportedTemperatureK).toBe(20);expect(m.temperatureKind).toBe("measurement");expect(m.tcK).toBeNull();
 expect(searchArticles(searchIndex().entries,"plasmon",{}).some(r=>r.id===a.id)).toBe(true);
 expect(searchArticles(searchIndex().entries,"plasmon",{tcMin:1}).some(r=>r.id===a.id)).toBe(false);
 const exp=await(await get(["articles",a.id,"sections","experimental-criteria"],"?format=markdown")).text();
 expect(exp).toContain("40 meV");expect(exp).toContain("120 meV");expect(exp).toContain("excluded from the model fit");
 const math=await(await get(["articles",a.id,"sections","mathematical-assumptions"],"?format=markdown")).text();
 expect(math).toContain("finite-momentum static screening");expect(math).toContain("weak Landau damping");
 const limits=await(await get(["articles",a.id,"sections","limits-and-disputes"],"?format=markdown")).text();
 expect(limits).toContain("phenomenologically");expect(limits).toContain("normal-state Coulomb mass renormalization");expect(limits).toContain("normal-state energy-shift correction");expect(limits).toContain("complete version comparison and numerical reproduction remain open");
 expect(a.references.find(r=>r.doi==="10.1103/PhysRevB.94.224515")?.verification.evidenceUrl).toContain("accepted/");
 expect(a.claims.filter(c=>c.sectionId==="mathematical-assumptions").every(c=>c.evidenceType==="theory")).toBe(true);
});

it("keeps RVB model results and organic spin-state alternatives distinct from measured Tc",async()=>{
 const a=articles().find(a=>a.code==="B9")!;
 expect(a.materialCases).toEqual([]);
 expect(searchArticles(searchIndex().entries,"RVB",{}).some(r=>r.id===a.id)).toBe(true);
 expect(searchArticles(searchIndex().entries,"RVB",{tcMin:1}).some(r=>r.id===a.id)).toBe(false);
 const exp=await(await get(["articles",a.id,"sections","experimental-criteria"],"?format=markdown")).text();
 expect(exp).toContain("32 mK");expect(exp).toContain("Neither number is a superconducting transition");
 expect(exp).toContain("0.5 T");expect(exp).toContain("macroscopic or mesoscopic");
 const md=await(await get(["articles",a.id,"markdown"])).text();
 expect(md).toContain("20.7%");expect(md).toContain("no mobile charge degrees of freedom");
 expect(md).toContain("gapped chiral spin liquid");expect(md).toContain("mounting-related microcracks");
 expect(md).toContain("experimental mismatch");
 const g=articles().find(a=>a.code==="G7")!;
 const gs=await(await get(["articles",g.id,"sections","limits-and-disputes"],"?format=markdown")).text();
 expect(gs).toContain("not a directly applied hydrostatic pressure");expect(gs).toContain("leaves a gapped chiral spin liquid possible");
 expect(g.references.find(r=>r.doi==="10.1038/s41467-023-37491-z")?.verification.scope).toBe("published-primary-passages-scoped-check");
 expect(a.claims.filter(c=>c.sectionId==="mathematical-assumptions").every(c=>c.evidenceType==="theory")).toBe(true);
});

it("retains local two-band derivation scope and the uncoupled phase boundary in exports",async()=>{
 const a=articles().find(a=>a.code==="B12")!;
 const math=a.claims.filter(c=>c.sectionId==="mathematical-assumptions");expect(math).toHaveLength(4);expect(math.every(c=>c.sourceRelationship==="context-for-local-derivation")).toBe(true);
 const text=await(await get(["articles",a.id,"sections","mathematical-assumptions"],"?format=markdown")).text();
 expect(text).toContain("neither a unique gap vector nor a relative phase");expect(text).toContain("nondegenerate leading mode");
 for(const c of math)expect(text).toContain(c.derivationNote!);
 expect(text).toContain("bibliographic verification only");
});

it("retains Hund atomic-model limits, corrected material identity and calorimetry conditions",async()=>{
 const a=articles().find(a=>a.code==="B10")!;
 const math=await(await get(["articles",a.id,"sections","mathematical-assumptions"],"?format=markdown")).text();
 expect(math).toContain("spin symmetry alone");expect(math).toContain("only two states");expect(math).toContain("not a prediction of quasiparticle coherence");
 const md=await(await get(["articles",a.id,"markdown"])).text();
 expect(md).toContain("10.1038/nmat3152");expect(md).toContain("BaFe2As2, replacing the original BaFe2Se2");expect(md).toContain("5.5 T, c-axis");expect(md).toContain("Neither is a measured material Tc");expect(md).toContain("fermion sign problem");
 expect(a.materialCases[0].tcK).toBe(3.4);expect(a.materialCases[0].pressureGPa).toBeNull();
 expect(searchArticles(searchIndex().entries,"Hund",{tcMin:3}).some(r=>r.id===a.id)).toBe(true);
 expect(searchArticles(searchIndex().entries,"Hund",{tcMin:5}).some(r=>r.id===a.id)).toBe(false);
 expect(a.claims.filter(c=>c.sectionId==="mathematical-assumptions").every(c=>c.evidenceType==="theory")).toBe(true);
});

it("preserves topological criterion conditions, retraction and readout limits in searchable exports",async()=>{
 const a=articles().find(a=>a.code==="B11")!;
 expect(a.materialCases).toEqual([]);
 expect(searchArticles(searchIndex().entries,"Kitaev",{}).some(r=>r.id===a.id)).toBe(true);
 expect(searchArticles(searchIndex().entries,"Kitaev",{tcMin:1}).some(r=>r.id===a.id)).toBe(false);
 const math=await(await get(["articles",a.id,"sections","mathematical-assumptions"],"?format=markdown")).text();
 expect(math).toContain("even result does not establish");expect(math).toContain("weak pairing");expect(math).toContain("BDI");expect(math).toContain("No leads or conductance are simulated");
 const md=await(await get(["articles",a.id,"markdown"])).text();
 expect(md).toContain("uniform paired surface preserves time reversal");expect(md).toContain("retracted in 2021");expect(md).toContain("11 February 2026");expect(md).toContain("not a demonstration of fault-tolerant braiding");
 expect(a.references.find(r=>r.doi==="10.1038/s41586-025-09927-7")?.verification.scope).toBe("published-abstract-and-date-check");
 const protocol=a.claims.find(c=>c.id==="scwiki-b11-claim-experimental-criteria-3")!;expect(protocol.sourceRelationship).toBe("context-for-editorial-analysis");expect(protocol.sourceIds).toEqual(["source-dca781066e96eecc","source-f127bb2d99183698"]);
 const experimental=await(await get(["articles",a.id,"sections","experimental-criteria"],"?format=markdown")).text();expect(experimental).toContain("Source relationship: context-for-editorial-analysis");expect(experimental).toContain(protocol.derivationNote!);
 const schema=await(await get(["openapi.json"])).json();expect(schema.components.schemas.Claim.properties.sourceRelationship.enum).toContain("context-for-editorial-analysis");
 expect(a.claims.find(c=>c.id==="scwiki-b11-claim-mathematical-assumptions-5")?.sourceRelationship).toBe("context-for-local-derivation");
 expect(a.claims.filter(c=>c.sectionId==="mathematical-assumptions").every(c=>c.evidenceType==="theory")).toBe(true);
});

it("keeps flat-band pairing, frozen geometry and measured stiffness conditions separate",async()=>{
 const a=articles().find(a=>a.code==="B13")!,m=a.materialCases[0];
 expect(m.tcK).toBeNull();expect(m.reportedTemperatureK).toBe(.02);expect(m.temperatureKind).toBe("measurement");
 expect(searchArticles(searchIndex().entries,"flat-band",{}).some(r=>r.id===a.id)).toBe(true);
 expect(searchArticles(searchIndex().entries,"flat-band",{tcMin:1}).some(r=>r.id===a.id)).toBe(false);
 const math=await(await get(["articles",a.id,"sections","mathematical-assumptions"],"?format=markdown")).text();
 expect(math).toContain("not a true finite-temperature superconducting transition");expect(math).toContain("one quarter");expect(math).toContain("frozen projected overlap response");expect(math).toContain("renormalized stiffness");
 const md=await(await get(["articles",a.id,"markdown"])).text();
 expect(md).toContain("parallel electrode-proximitized edge");expect(md).toContain("half normal-state resistance");expect(md).toContain("not an observed universal correlation");
 expect(math).toContain("upper BKT scale only if");expect(math).toContain("Finite-frequency inductive response");expect(math).toContain("mixed-source-and-local-derivation");expect(a.claims.find(c=>c.id==="scwiki-b13-claim-mathematical-assumptions-9")?.sourceIds).toContain("source-8f81510a80c35e3a");
 const ref=a.references.find(r=>r.doi==="10.48550/arXiv.2603.24766")!;expect(ref.publicationStatus).toBe("preprint");expect(ref.url).toContain("v2");
 const f=articles().find(a=>a.code==="F7")!;const fm=await(await get(["articles",f.id,"markdown"])).text();expect(fm).toContain("assumed active-region aspect ratio");
 expect(a.claims.filter(c=>c.sectionId==="mathematical-assumptions").every(c=>c.evidenceType==="theory")).toBe(true);
});

it("preserves Mottness model limits and the nickelate specimen-specific onset in retrieval",async()=>{
 const a=articles().find(a=>a.code==="B14")!;
 const md=await(await get(["articles",a.id,"markdown"])).text();
 expect(md).toContain("does not establish a bulk Mott transition");
 expect(md).toContain("not a quantitative X-ray absorption spectrum");
 expect(md).toContain("lower-branch addition weight becomes");
 expect(a.claims.filter(c=>c.sectionId==="mathematical-assumptions").every(c=>c.sourceRelationship==="context-for-local-derivation")).toBe(true);
 expect(a.references.some(r=>r.doi==="10.1038/nature00898")).toBe(true);
 expect(a.references.some(r=>r.doi==="10.1038/nature00992")).toBe(false);
 expect(searchArticles(searchIndex().entries,"Mottness",{}).some(r=>r.id===a.id)).toBe(true);
 expect(searchArticles(searchIndex().entries,"Mottness",{tcMin:1}).some(r=>r.id===a.id)).toBe(false);
 const d=articles().find(a=>a.code==="D5")!,m=d.materialCases.find(m=>m.formula==="La3Ni2O7")!;
 expect(m.criterion).toBe("resistance-onset");expect(m.pressureGPa).toEqual({min:18.5,max:18.5});
 expect(m.temperatureNote).toContain("nonzero residual resistance");
 expect(searchArticles(searchIndex().entries,"La3Ni2O7",{criterion:"resistance-onset",tcMin:80}).some(r=>r.id===d.id)).toBe(true);
 expect(searchArticles(searchIndex().entries,"La3Ni2O7",{criterion:"zero-resistance",tcMin:80}).some(r=>r.id===d.id)).toBe(false);
 const out=await(await get(["articles",d.id,"sections","experimental-criteria"],"?format=markdown")).text();
 expect(out).toContain("measured separately at 25.2 GPa");
 expect(out).toContain("prevent combining these observations into one zero-resistance");
});

it("keeps s-wave symmetry and imposed-gap checks separate from measured transition criteria",async()=>{
 const a=articles().find(a=>a.code==="C1")!;
 const md=await(await get(["articles",a.id,"markdown"])).text();
 expect(md).toContain("four zeros touch the Fermi surface without sign reversal");
 expect(md).toContain("D4h (4/mmm)");expect(md).toContain("C4h (4/m)");
 expect(md).toContain("Two explicit nonuniform-gap counterexamples");
 expect(a.claims.filter(c=>c.sectionId==="mathematical-assumptions").every(c=>c.sourceRelationship&&c.derivationNote)).toBe(true);
 expect(md).toContain("not a disorder simulation");expect(md).toContain("does not prove an unchanged self-consistent");
 expect(md).toContain("a measurement range, not a range of transition temperatures");
 expect(a.claims.find(c=>c.id==="scwiki-c1-claim-experimental-criteria-1")?.evidenceType).toBe("theory");
 expect(a.claims.find(c=>c.statement.startsWith("Choi"))?.evidenceType).toBe("theory");
 expect(a.materialCases).toHaveLength(1);expect(a.materialCases[0].tcK).toBe(39);expect(a.materialCases[0].criterion).toBe("resistance-onset");
 expect(searchArticles(searchIndex().entries,"s-wave",{tcMin:39,pressure:"ambient",criterion:"resistance-onset"}).some(r=>r.id===a.id)).toBe(true);
 expect(searchArticles(searchIndex().entries,"s-wave",{tcMin:40}).some(r=>r.id===a.id)).toBe(false);
 expect(searchArticles(searchIndex().entries,"s-wave",{tcMin:39,criterion:"zero-resistance"}).some(r=>r.id===a.id)).toBe(false);
 expect(a.references.some(r=>r.doi==="10.1038/nature00992")).toBe(false);
 expect(md).toContain("pressure at the resistance change was not directly measured");
 expect(md).toContain("magnetization of its small samples remained unresolved");
});

it("preserves d-wave phase controls and excludes imaging temperatures from transition filters",async()=>{
 const a=articles().find(a=>a.code==="C3")!;
 const md=await(await get(["articles",a.id,"markdown"])).text();
 expect(md).toContain("only where they intersect the Fermi surface");
 expect(md).toContain("not a reproduction of the extended three-boundary tricrystal geometry");
 expect(md).toContain("two unfrustrated geometries");
 expect(md).toContain("doubling of best-fit chi-square");
 expect(a.references.some(r=>r.doi==="10.1103/PhysRevLett.75.4234")).toBe(false);
 expect(a.references.find(r=>r.doi==="10.1103/PhysRevLett.70.1553")?.year).toBe(1993);
 expect(a.references.find(r=>r.doi==="10.1103/PhysRevLett.73.593")?.verification.scope).toContain("identity");
 expect(a.materialCases[0].reportedTemperatureK).toBe(4.2);
 expect(a.materialCases[0].tcK).toBeNull();expect(a.materialCases[0].temperatureKind).toBe("unassigned");
 expect(searchArticles(searchIndex().entries,"NCCO",{}).some(r=>r.id===a.id)).toBe(true);
 expect(searchArticles(searchIndex().entries,"NCCO",{tcMin:1}).some(r=>r.id===a.id)).toBe(false);
 const section=await(await get(["articles",a.id,"sections","experimental-criteria"],"?format=markdown")).text();
 expect(section).toContain("no single transition criterion is invented");
 expect(section).toContain("Full scientific acceptance");
});

it("keeps dxy orbital weights, model channels and directional evidence distinct",async()=>{
 const a=articles().find(a=>a.code==="C4")!;
 const md=await(await get(["articles",a.id,"markdown"])).text();
 expect(md).toContain("not a proof that no such material exists");
 expect(md).toContain("including their periodic zone-boundary counterparts");
 expect(md).toContain("not an RPA reproduction or a measured transition temperature");
 expect(md).toContain("does not calculate vortices");
 expect(md).toContain("as a subleading channel");
 expect(md).toContain("required companion citation");
 expect(a.references.some(r=>r.doi==="10.1103/PhysRevLett.102.109902")).toBe(true);
 expect(a.claims.find(c=>c.statement.startsWith("Rotating-field"))?.evidenceType).toBe("theory");
 expect(a.materialCases).toHaveLength(0);
 expect(searchArticles(searchIndex().entries,"B2g",{}).some(r=>r.id===a.id)).toBe(true);
 expect(searchArticles(searchIndex().entries,"B2g",{tcMin:1}).some(r=>r.id===a.id)).toBe(false);
 const out=await(await get(["articles",a.id,"sections","limits-and-disputes"],"?format=markdown")).text();
 expect(out).toContain("orbital-to-band transformation error");expect(out).toContain("Full scientific acceptance");
});

it("keeps p-wave symmetry distinct from spin response and measurement temperatures",async()=>{
 const a=articles().find(a=>a.code==="C5")!;
 const md=await(await get(["articles",a.id,"markdown"])).text();
 expect(md).toContain("It is not a synonym for every odd-parity state");
 expect(md).toContain("not a general formula for a ferromagnetic multiband metal");
 expect(md).toContain("not a standalone determination of the full p-wave order parameter");
 expect(md).toContain("insufficiently accurate at 0.2 T");
 expect(md).toContain("do not distinguish fully gapped, line-nodal, helical and interorbital states");
 const recent=a.references.find(r=>r.doi==="10.1103/sgcz-9rc7")!;
 expect(recent.year).toBe(2026);expect(recent.publicationStatus).toBe("journal-article");
 expect(recent.verification.evidenceUrl).toContain("2512.14107v1");
 expect(a.materialCases[0].reportedTemperatureK).toBe(.05);
 expect(a.materialCases[0].tcK).toBeNull();expect(a.materialCases[0].temperatureKind).toBe("unassigned");
 expect(searchArticles(searchIndex().entries,"helical",{}).some(r=>r.id===a.id)).toBe(true);
 expect(searchArticles(searchIndex().entries,"helical",{tcMin:.01}).some(r=>r.id===a.id)).toBe(false);
 const out=await(await get(["articles",a.id,"sections","experimental-criteria"],"?format=markdown")).text();
 expect(out).toContain("field-cooled magnetization");expect(out).toContain("Full scientific acceptance");
});

it("keeps f-wave model nodes and Kerr temperatures separate from established material assignments",async()=>{
 const a=articles().find(a=>a.code==="C6")!;
 const md=await(await get(["articles",a.id,"markdown"])).text();
 expect(md).toContain("These are model angles, not measured node coordinates");
 const detail=await(await get(["articles",a.id])).json();
 const mix=detail.article.claims.find((c:{id:string})=>c.id==="scwiki-c6-claim-mathematical-assumptions-3");
 expect(mix.sourceRelationship).toBe("context-for-local-derivation");
 const interpretation=detail.article.claims.find((c:{id:string})=>c.id==="scwiki-c6-claim-experimental-criteria-3");
 expect(interpretation.evidenceType).toBe("theory");
 expect(interpretation.conditions).toContain("no Zeeman splitting");
 expect(interpretation.statement).toContain("not a calculated f-wave response for UPt3");
 expect(md).toContain("fractional translations of the space group");
 expect(md).toContain("P63/mmc");
 expect(a.references.find(r=>r.doi==="10.1103/PhysRevB.95.024508")?.verification.scope).toBe("selected-accepted-manuscript-check");
 expect(mix.conditions).toContain("real a");
 expect(mix.statement).toContain("nonzero imaginary part removes its horizontal zeros");
 expect(mix.statement).toContain("not a fitted state reported by Tsutsumi");
 const mathExport=await(await get(["articles",a.id,"sections","mathematical-assumptions"],"?format=markdown")).text();
 expect(mathExport).toContain("context-for-local-derivation");
 expect(mathExport).toContain("quadratic equatorial zero");
 expect(mathExport).toContain("cubic polar zeros");
 expect(md).toContain("not a density-of-states or thermal-conductivity calculation");
 expect(md).toContain("not fitted to UPt3 or UTe2");
 expect(md).toContain("Kerr onset is not the upper superconducting transition");
 expect(md).toContain("optical and susceptibility sample sets are different");
 expect(md).toContain("multidimensional point-group representations are not a universal prerequisite");
 expect(a.references.find(r=>r.doi==="10.1103/PhysRevLett.108.157002")?.verification.note).toContain("differs");
 expect(a.references.some(r=>r.doi==="10.1103/PhysRevX.13.041019")).toBe(true);
 expect(a.references.some(r=>r.doi==="10.1126/science.abb0272")).toBe(true);
 expect(a.materialCases[0].reportedTemperatureK).toBe(.46);
 expect(a.materialCases[0].tcK).toBeNull();expect(a.materialCases[0].temperatureKind).toBe("unassigned");
 expect(searchArticles(searchIndex().entries,"E2u",{}).some(r=>r.id===a.id)).toBe(true);
 expect(searchArticles(searchIndex().entries,"E2u",{tcMin:.1}).some(r=>r.id===a.id)).toBe(false);
 const out=await(await get(["articles",a.id,"sections","limits-and-disputes"],"?format=markdown")).text();
 expect(out).toContain("zero-field Kerr signal");expect(out).toContain("Full scientific acceptance");
});

it("separates chiral topology and kagome measurement temperatures in article exports and search",async()=>{
 const a=articles().find(a=>a.code==="C7")!;
 const md=await(await get(["articles",a.id,"markdown"])).text();
 expect(md).toContain("no gapped-band invariant is assigned there");
 expect(md).toContain("not a universal absence of current");
 expect(md).toContain("stays approximately constant across the superconducting transition");
 expect(md).toContain("transverse-field measurements at 5 and 10 mT");
 expect(md).toContain("Zero-field data alone do not establish time-reversal breaking");
 expect(md).toContain("undefined on the nodal slices");
 const detail=await(await get(["articles",a.id])).json();
 const local=detail.article.claims.find((c:{id:string})=>c.id==="scwiki-c7-claim-limits-and-disputes-3");
 expect(local.sourceRelationship).toBe("context-for-local-derivation");
 expect(local.conditions).toContain("exclude gapless slices");
 const muon=detail.article.claims.find((c:{id:string})=>c.id==="scwiki-c7-claim-experimental-criteria-3");
 expect(muon.sourceRelationship).toBe("direct-support");
 expect(muon.conditions).toContain("charge order near 80 K is not Tc near 1.1 K");
 expect(a.materialCases[0].temperatureNote).toContain("transverse-field vortex damping increases below Tc");
 expect(md).toContain("roton excitations were not directly observed");
 expect(md).toContain("bulk signatures near 2.8 K from a surface transition near 2.3 K");
 expect(a.materialCases.map(r=>r.reportedTemperatureK)).toEqual([80,.3]);
 expect(a.materialCases.every(r=>r.tcK===null)).toBe(true);
 expect(searchArticles(searchIndex().entries,"roton PDW",{}).some(r=>r.id===a.id)).toBe(true);
 expect(searchArticles(searchIndex().entries,"roton PDW",{tcMin:1}).some(r=>r.id===a.id)).toBe(false);
 const out=await(await get(["articles",a.id,"sections","experimental-criteria"],"?format=markdown")).text();
 expect(out).toContain("30 mG");expect(out).toContain("Full scientific acceptance");
 expect(a.references.find(r=>r.doi==="10.1038/s41586-021-04327-z")?.verification.evidenceUrl).toContain("2106.13443v2");
 expect(a.references.find(r=>r.doi==="10.1103/PhysRevB.81.134522")?.verification.scope).toBe("publisher-abstract-check");
});


it("all exported temperature classifications are declared by the live API contract",async()=>{
 const spec=await(await get(["openapi.json"])).json();
 const allowed=spec.components.schemas.MaterialCase.properties.temperatureKind.enum;
 expect(allowed).toContain("measurement");
 for(const a of articles()){
  const record=await(await get(["articles",a.id])).json();
  for(const m of record.article.materialCases){
   expect(allowed).toContain(m.temperatureKind);
   if(m.temperatureKind!=="transition")expect(m.tcK).toBeNull();
  }
 }
});

it("keeps the two Bi2212 PDW experiments and limited modern source checks distinct",async()=>{
 const a=articles().find(a=>a.code==="C8")!;
 const md=await(await get(["articles",a.id,"markdown"])).text();
 expect(md).toContain("not the later field-induced vortex-halo");
 expect(md).toContain("explicitly without scanned Josephson tunneling microscopy");
 expect(md).toContain("effective noise temperature");
 expect(md).toContain("not exactly in a two-to-one ratio");
 expect(md).toContain("without additional translation-symmetry breaking");
 expect(a.materialCases.map(r=>r.reportedTemperatureK)).toEqual([null,2]);
 expect(a.materialCases.every(r=>r.tcK===null&&r.temperatureKind==="measurement")).toBe(true);
 expect(a.materialCases[0].sourceId).not.toBe(a.materialCases[1].sourceId);
 expect(searchArticles(searchIndex().entries,"CPDM",{}).some(r=>r.id===a.id)).toBe(true);
 expect(searchArticles(searchIndex().entries,"CPDM",{tcMin:.01}).some(r=>r.id===a.id)).toBe(false);
 const out=await(await get(["articles",a.id,"sections","experimental-criteria"],"?format=markdown")).text();
 expect(out).toContain("8.25 T");expect(out).toContain("Full scientific acceptance");
 expect(a.references.find(r=>r.doi==="10.1038/nature17411")?.verification.scope).toBe("selected-published-and-author-text-check");
 expect(a.references.find(r=>r.doi===null)?.verification.scope).toBe("institutional-bibliographic-check");
 const lo=a.references.find(r=>r.doi===null)!;
 const migdal=articles().find(a=>a.code==="B2")!.references.find(r=>r.id==="source-21442c6eb33d9b94")!;
 expect(lo.id).not.toBe(migdal.id);expect(lo.year).toBe(1965);expect(migdal.year).toBe(1958);
 expect(lo.url).toContain("itp.ac.ru");expect(migdal.url).toContain("e_007_06_0996.pdf");
 const all=await getAll("sources");
 expect(all.sources.find((r:any)=>r.id===lo.id).usedBy).toEqual(["scwiki-c8"]);
 expect(all.sources.find((r:any)=>r.id===migdal.id).usedBy).toEqual(["scwiki-b2"]);
 expect(md).toContain("quadrature component does not");
 expect(md).toContain("equilibrium total current is zero");
 const harmonic=await(await get(["articles",a.id,"sections","mathematical-assumptions"])).json();
 expect(harmonic.claims.find((c:any)=>c.id==="scwiki-c8-claim-mathematical-assumptions-2").sourceRelationship).toBe("context-for-local-derivation");
 expect(a.references.find(r=>r.doi==="10.1038/s41586-026-10325-w")?.verification.scope).toBe("institutional-abstract-and-publication-check");
});

it("exports conditional spin classification with its erratum and searchable orbital exceptions",async()=>{
 const a=articles().find(a=>a.code==="C9")!;
 const md=await(await get(["articles",a.id,"markdown"])).text();
 expect(md).toContain("even-frequency pairing and a symmetric orbital");
 expect(md).toContain("frequency exchange is not the physical time-reversal operation");
 expect(md).toContain("imposed triplet gap is zero");
 expect(md).toContain("adds an omitted linear term");
 expect(md).toContain("not an unlimited physical upper critical field");
 expect(a.references.some(r=>r.doi==="10.1103/PhysRevLett.93.099903")).toBe(true);
 expect(a.references.find(r=>r.doi==="10.1103/PhysRevLett.98.037003")?.verification.scope).toBe("publisher-abstract-check");
 expect(searchArticles(searchIndex().entries,"shadowed triplet",{}).some(r=>r.id===a.id)).toBe(true);
 expect(searchArticles(searchIndex().entries,"shadowed triplet",{tcMin:1}).some(r=>r.id===a.id)).toBe(false);
 const out=await(await get(["articles",a.id,"sections","mathematical-assumptions"],"?format=markdown")).text();
 expect(out).toContain("particle-hole-symmetric test point");expect(out).toContain("Full scientific acceptance");
 const gap=a.claims.find(c=>c.id==="scwiki-c9-claim-mathematical-assumptions-4")!;
 expect(gap.sourceRelationship).toBe("context-for-local-derivation");
 expect(gap.conditions).toContain("same momentum");
 expect(gap.derivationNote).toContain("not results attributed");
 for(const text of ["same helicity Fermi sheet", "Cancellation away", "Equal magnitudes alone", "transverse triplet component", "local imposed-model checks"]) {
  expect(out).toContain(text);expect(md).toContain(text);
 }
 expect(searchArticles(searchIndex().entries,"helicity Fermi sheet",{}).some(r=>r.id===a.id)).toBe(true);
});

it("keeps node studies linked to their actual materials and measurement temperatures",async()=>{
 const a=articles().find(a=>a.code==="C10")!;
 const reid=a.references.find(r=>r.doi==="10.1103/PhysRevLett.109.087001")!;
 const cases=a.materialCases.filter(m=>m.sourceId===reid.id);
 expect(cases).toHaveLength(1);expect(cases[0].formula).toBe("KFe2As2");
 expect(cases[0].reportedTemperatureK).toBe(.05);expect(cases[0].tcK).toBeNull();
 expect(a.materialCases.every(m=>m.temperatureKind==="measurement"&&m.tcK===null)).toBe(true);
 const md=await(await get(["articles",a.id,"markdown"])).text();
 expect(md).toContain("not simply restored symmetry-enforced nodes");
 expect(md).toContain("does not show that every multiband");
 expect(md).toContain("zero-field term was obtained by extrapolation");
 expect(searchArticles(searchIndex().entries,"Pfaffian",{}).some(r=>r.id===a.id)).toBe(true);
 expect(searchArticles(searchIndex().entries,"Pfaffian",{tcMin:1}).some(r=>r.id===a.id)).toBe(false);
 const out=await(await get(["articles",a.id,"sections","experimental-criteria"],"?format=markdown")).text();
 expect(out).toContain("KFe2As2, not P-substituted");expect(out).toContain("Full scientific acceptance");
 const node=a.claims.find(c=>c.id==="scwiki-c10-claim-mathematical-assumptions-1")!;
 expect(node.sourceRelationship).toBe("context-for-local-derivation");
 expect(node.conditions).toContain("finite nonzero transverse velocities");
 const math=await(await get(["articles",a.id,"sections","mathematical-assumptions"],"?format=markdown")).text();
 for(const text of ["finite-window ambiguity", "only zero remains a point", "not their result or a material fit", "scalar impurity-self-energy approximation", "above relevant broadening scales"]) {expect(math).toContain(text);expect(md).toContain(text);}
 expect(searchArticles(searchIndex().entries,"finite-window ambiguity",{}).some(r=>r.id===a.id)).toBe(true);
});

it("keeps elemental pressure cases and calculated temperatures distinct",async()=>{
 const a=articles().find(a=>a.code==="D1")!;
 const sc=a.materialCases.find(m=>m.formula==="Sc"&&m.recordType==="experiment")!;
 expect(sc.tcK).toBe(37.6);expect(sc.pressureGPa).toEqual({min:243,max:243});
 const predicted=a.materialCases.find(m=>m.recordType==="prediction")!;
 expect(predicted.reportedTemperatureK).toBe(30.1);expect(predicted.tcK).toBeNull();
 expect(predicted.pressureGPa).toEqual({min:260,max:260});
 expect(a.materialCases.find(m=>m.formula==="Li")!.tcK).toBe(.0004);
 expect(searchArticles(searchIndex().entries,"scandium",{evidence:"prediction"}).some(r=>r.id===a.id)).toBe(true);
 expect(searchArticles(searchIndex().entries,"scandium",{evidence:"prediction",tcMin:30}).some(r=>r.id===a.id)).toBe(false);
 expect(searchArticles(searchIndex().entries,"scandium",{tcMin:37}).some(r=>r.id===a.id)).toBe(true);
 const md=await(await get(["articles",a.id,"sections","experimental-criteria"],"?format=markdown")).text();
 expect(md).toContain("no Meissner measurement was supplied");
 expect(md).toContain("0.0004 K, not 0.4 K");expect(md).toContain("Full scientific acceptance");
 const math=await(await get(["articles",a.id,"sections","mathematical-assumptions"],"?format=markdown")).text();
 expect(math).toContain("exact reproduction needs unrounded inputs");
 const tunneling=a.claims.find(c=>c.id==="scwiki-d1-claim-experimental-criteria-1")!;
 expect(tunneling.sourceRelationship).toBe("mixed-source-and-local-derivation");
 expect(tunneling.conditions).toContain("common electron temperature");
 const full=await(await get(["articles",a.id,"markdown"])).text();
 for(const text of ["Finite temperature averages the spectrum", "despite zero density at zero energy", "superconducting counterelectrode", "neither invert an experimental spectrum"]) {expect(md).toContain(text);expect(full).toContain(text);}
 expect(a.references.find(r=>r.doi==="10.1103/PhysRevLett.14.108")?.verification.scope).toBe("publisher-metadata-only");
 expect(searchArticles(searchIndex().entries,"thermal convolution",{}).some(r=>r.id===a.id)).toBe(true);
});

it("keeps A15 transitions separate from operating and structural temperatures",async()=>{
 const a=articles().find(a=>a.code==="D2")!;
 const v3si=a.materialCases.find(m=>m.formula==="V3Si")!;
 expect(v3si.tcK).toBe(12.8);expect(v3si.sample).toContain("6.67 T");
 expect(a.materialCases.filter(m=>m.temperatureKind==="measurement").every(m=>m.tcK===null)).toBe(true);
 expect(searchArticles(searchIndex().entries,"Kramer",{tcMin:22}).some(r=>r.id===a.id)).toBe(true);
 expect(searchArticles(searchIndex().entries,"Kramer",{tcMin:23}).some(r=>r.id===a.id)).toBe(false);
 const dissertation=a.references.find(r=>r.url.includes("2605.03171"))!;
 expect(dissertation.publicationStatus).toBe("preprint");
 const cavity=a.materialCases.find(m=>m.sourceId===dissertation.id)!;
 expect(cavity.reportedTemperatureK).toBe(.05);expect(cavity.tcK).toBeNull();
 const math=await(await get(["articles",a.id,"sections","mathematical-assumptions"],"?format=markdown")).text();
 expect(math).toContain("2888.01");expect(math).toContain("2883");
 expect(math).toContain("Neither improved value was measured");expect(math).toContain("Full scientific acceptance");
 expect(a.references.find(r=>r.doi==="10.1063/1.1890447")?.verification.evidenceUrl).toMatch(/v2$/);
 expect(a.relatedCodes).toContain("A6");
 const example=a.claims.find(c=>c.id==="scwiki-d2-claim-mathematical-assumptions-3")!;
 expect(example.sourceRelationship).toBe("mixed-source-and-local-derivation");
 expect(example.conditions).toContain("nearest-0.1-T rounding");
 const fullMarkdown=await(await get(["articles",a.id,"markdown"])).text();
 for(const text of [math,fullMarkdown]){
  for(const boundary of ["Equal-area parallel addition","Two-point secants","series bottleneck","does not establish the cause of the discrepancy"])
   expect(text).toContain(boundary);
 }
 const measurement=await(await get(["articles",a.id,"sections","experimental-criteria"],"?format=markdown")).text();
 expect(measurement).toContain("normalized to non-Cu area");
 expect(measurement).toContain("not material volume fractions");
 expect(measurement).toContain("without establishing a statistical confidence interval");
 const limits=await(await get(["articles",a.id,"sections","limits-and-disputes"],"?format=markdown")).text();
 expect(limits).toContain("calibrated detection threshold");
 expect(limits).toContain("context-for-editorial-analysis");
 const structure=a.claims.find(c=>c.id==="scwiki-d2-claim-scope-1")!;
 const prototype=a.references.find(r=>r.url.includes("A3B_cP8_223"))!;
 expect(structure.sourceIds).toContain(prototype.id);
 expect(structure.statement).toContain("does not make the full crystal body-centered cubic");
 expect(searchArticles(searchIndex().entries,"series bottleneck",{}).some(r=>r.id===a.id)).toBe(true);
});

it("carries retraction status through source, article, section and rendered references",async()=>{
 const a=articles().find(a=>a.code==="D6")!;
 const withdrawn=a.references.filter(r=>r.retraction);expect(withdrawn).toHaveLength(2);
 const articleJson=await(await get(["articles",a.id])).json();
 const full=await(await get(["articles",a.id,"markdown"])).text();
 const section=await(await get(["articles",a.id,"sections","limits-and-disputes"])).json();
 const md=await(await get(["articles",a.id,"sections","limits-and-disputes"],"?format=markdown")).text();
 const {default:ArticlePage}=await import("@/app/scwiki/[slug]/page");
 const html=renderToStaticMarkup(await ArticlePage({params:Promise.resolve({slug:a.slug})}));
 for(const ref of withdrawn){
  const notice=ref.retraction!;
  expect(articleJson.article.references.find((r:{id:string})=>r.id===ref.id).retraction).toEqual(notice);
  expect(section.sources.find((r:{id:string})=>r.id===ref.id).retraction).toEqual(notice);
  const sources=await getAll("sources");
  expect(sources.sources.find((r:{id:string})=>r.id===ref.id).retraction).toEqual(notice);
  for(const text of [full,md]){expect(text).toContain("Retracted: "+notice.retractedAt);expect(text).toContain(notice.evidenceUrl);}
  expect(html).toContain('dateTime="'+notice.retractedAt+'"');
  expect(html).toContain('href="'+notice.evidenceUrl+'">Retraction notice</a>');
  expect(a.materialCases.filter(c=>c.tcK!==null).some(c=>c.sourceId===ref.id)).toBe(false);
 }
 const spec=await(await get(["openapi.json"])).json();
 expect(spec.components.schemas.Source.properties.retraction.required).toEqual(["noticeDoi","retractedAt","evidenceUrl"]);
 expect(html).toContain('"creativeWorkStatus":"Retracted"');
});
it("does not promote hydride negative measurement limits or predictions to measured transition temperatures",async()=>{
 const a=articles().find(a=>a.code==="D6")!;
 for(const formula of ["LuH2±xNy","Y3Fe4H20"]){const c=a.materialCases.find(c=>c.formula===formula)!;expect(c.tcK).toBeNull();expect(c.temperatureKind).toBe("measurement");}
 const prediction=a.materialCases.find(c=>c.recordType==="prediction")!;expect(prediction.tcK).toBeNull();
 expect(a.body).toContain("249 K and 180 K");expect(a.body).toContain("151 and 152 GPa");
 expect(a.body).toContain("not direct measurements at 136 T");
 expect(a.review.limitations[0]).toContain("remain open");
 const negative=a.materialCases.find(c=>c.id==="scwiki-d6-material-4")!;
 expect(negative.pressureGPa).toEqual({min:.4,max:40.1});expect(negative.reportedTemperatureK).toBe(2);
 expect(negative.temperatureNote).toContain("not imply continuous coverage");expect(negative.probe).toContain("room-temperature ruby");
 expect(searchArticles(searchIndex().entries,"LuH2±xNy",{tcMin:.01})).toEqual([]);
 const exported=await(await get(["articles",a.id,"sections","limits-and-disputes"],"?format=markdown")).text();
 for(const phrase of ["not the full transport window","cannot detect hydrogen","arxiv.org/abs/2303.08759v3","mixed-source-and-local-derivation"])expect(exported).toContain(phrase);
 expect(a.claims.find(c=>c.id==="scwiki-d6-claim-limits-and-disputes-2")?.conditions).toContain("discrete pressures");
});


it("matches every material condition to the public search/API enum and retrieves transient optical evidence",()=>{
 for(const a of articles())for(const c of a.materialCases){
  expect(["ambient","high","unknown"]).toContain(c.pressureRegime);
  expect(["equilibrium","transient","metastable","unknown"]).toContain(c.equilibrium);
  expect(["theory","experiment","prediction","hypothesis"]).toContain(c.recordType);
 }
 expect(searchArticles(searchIndex().entries,"Budden",{equilibrium:"transient"}).some(a=>a.code==="B7")).toBe(true);
 expect(searchArticles(searchIndex().entries,"LaH10",{pressure:"high",tcMin:240}).some(a=>a.code==="D6")).toBe(true);
});

it("keeps a driven magnetic null-result temperature out of transition filters and exports its detection limits",async()=>{
 const a=articles().find(a=>a.code==="E6")!;
 expect(searchArticles(searchIndex().entries,"light-driven superconductivity")[0].code).toBe("E6");
 const c=a.materialCases.find(c=>c.criterion==="sensitivity-limited-magnetic-nonobservation")!;
 expect(c.reportedTemperatureK).toBe(50);expect(c.tcK).toBeNull();expect(c.temperatureKind).toBe("measurement");
 const includes=(q:string,filters:any)=>searchArticles(searchIndex().entries,q,filters).some(a=>a.code==="E6");
 expect(includes("De Vecchi magnetic limit",{equilibrium:"transient"})).toBe(true);
 expect(includes("De Vecchi magnetic limit",{tcMin:0})).toBe(false);
 expect(includes("K3C60",{tcMin:50})).toBe(false);
 expect(includes("K3C60",{tcMin:20,equilibrium:"equilibrium"})).toBe(true);
 expect(includes("K3C60",{criterion:c.criterion,tcMin:0})).toBe(false);
 const result=await(await get(["articles",a.id])).json();
 expect(result.article.materialCases.find((x:{id:string})=>x.id===c.id)).toEqual(c);
 const md=await(await get(["articles",a.id,"sections","experimental-criteria"],"?format=markdown")).text();
 for(const phrase of ["160 ps","six reference pellets","systematic error","1 ns","long-lived response"])expect(md).toContain(phrase);
});

it("keeps MgB2 isotope transitions separate from probe temperatures and unresolved mass metadata",async()=>{
 const a=articles().find(a=>a.code==="D7")!;
 expect(a.references.some(r=>r.doi==="10.1038/nature00898")).toBe(true);
 expect(a.references.some(r=>r.doi==="10.1038/nature00992")).toBe(false);
 const budko=a.references.find(r=>r.doi==="10.1103/PhysRevLett.86.1877")!;
 const isotopes=a.materialCases.filter(c=>c.sourceId===budko.id);
 expect(isotopes.map(c=>c.tcK)).toEqual([40.2,39.2]);
 expect(isotopes.every(c=>c.criterion==="two-percent-diamagnetic-onset")).toBe(true);
 for(const c of a.materialCases.filter(c=>c.temperatureKind==="measurement"))expect(c.tcK).toBeNull();
 expect(searchArticles(searchIndex().entries,"MgB2",{tcMin:40,criterion:"two-percent-diamagnetic-onset"}).some(a=>a.code==="D7")).toBe(true);
 expect(searchArticles(searchIndex().entries,"MgB2",{tcMin:41}).some(a=>a.code==="D7")).toBe(false);
 const limits=await(await get(["articles",a.id,"sections","limits-and-disputes"],"?format=markdown")).text();
 expect(limits).toContain("25.001");expect(limits).toContain("No Mg-mass refit");
 expect(a.references.find(r=>r.doi==="10.1038/35078037")!.verification.note).toContain("discrepancy unresolved");
 expect(a.materialCases[0].pressureRegime).toBe("ambient");expect(a.materialCases[0].pressureGPa).toBeNull();
});

it("keeps heavy-fermion transition criteria separate from magnetic and normal-state temperatures",async()=>{
 const a=articles().find(a=>a.code==="D8")!;
 const pang=a.references.find(r=>r.doi==="10.1073/pnas.1720291115")!;
 expect(a.materialCases.filter(c=>c.sourceId===pang.id&&c.criterion==="specific-heat-anomaly").map(c=>c.tcK)).toEqual([.64,.53]);
 const magnetic=a.materialCases.find(c=>c.criterion==="antiferromagnetic-specific-heat-anomaly")!;
 expect(magnetic.reportedTemperatureK).toBe(.7);expect(magnetic.tcK).toBeNull();
 expect(a.materialCases.filter(c=>c.sourceId===pang.id&&c.criterion==="resistive-onset").map(c=>c.tcK)).toEqual([.65,.62]);
 expect(a.materialCases.find(c=>c.criterion==="zero-resistivity")?.tcK).toBe(.6);
 expect(searchArticles(searchIndex().entries,"CeCu2Si2",{tcMin:.66}).some(a=>a.code==="D8")).toBe(false);
 expect(searchArticles(searchIndex().entries,"CeCu2Si2",{tcMin:.64,criterion:"resistive-onset"}).some(a=>a.code==="D8")).toBe(true);
 expect(a.materialCases.find(c=>c.temperatureKind==="normal-state")?.tcK).toBeNull();
 expect(a.materialCases.filter(c=>c.temperatureKind==="measurement").every(c=>c.tcK===null)).toBe(true);
 expect(searchArticles(searchIndex().entries,"heavy fermion",{tcMin:2,criterion:"zero-resistance-and-shielding"}).some(a=>a.code==="D8")).toBe(true);
 expect(searchArticles(searchIndex().entries,"heavy fermion",{tcMin:3}).some(a=>a.code==="D8")).toBe(false);
 const md=await(await get(["articles",a.id,"markdown"])).text();
 expect(md).toContain("not a measured upper boundary");
 expect(md).toContain("complete supplement remain outside this scoped review");
 expect(md).toContain("normal state at 4 K");
});

it("preserves fulleride polymorph and transport criteria while excluding driven and withdrawn Tc",async()=>{
 const a=articles().find(a=>a.code==="D9")!;
 const fcc=a.materialCases.filter(c=>c.formula==="Cs3C60"&&c.tcK!==null);
 expect(fcc.map(c=>[c.tcK,c.pressureGPa])).toEqual([[25.6,{min:.13,max:.13}],[29.7,{min:.22,max:.22}],[35,{min:.7,max:.7}]]);
 const film=a.materialCases.filter(c=>c.formula==="Rb2.98C60");
 expect(film.map(c=>[c.tcK,c.criterion])).toEqual([[26.4,"local-resistivity-maximum"],[14.5,"resistivity-derivative-threshold"]]);
 const driven=a.materialCases.filter(c=>c.reportedTemperatureK===100);
 expect(driven).toHaveLength(2);
 for(const record of driven){
  expect(record.tcK).toBeNull();expect(record.equilibrium).toBe("transient");
  expect(searchArticles(searchIndex().entries,"fullerides",{criterion:record.criterion}).some(a=>a.code==="D9")).toBe(true);
  expect(searchArticles(searchIndex().entries,"fullerides",{tcMin:1,criterion:record.criterion}).some(a=>a.code==="D9")).toBe(false);
 }
 expect(a.materialCases.find(c=>c.reportedTemperatureK===2.2)?.tcK).toBeNull();
 expect(searchArticles(searchIndex().entries,"fullerides",{tcMin:30,pressureRegime:"high"}).some(a=>a.code==="D9")).toBe(true);
 expect(searchArticles(searchIndex().entries,"fullerides",{tcMin:36}).some(a=>a.code==="D9")).toBe(false);
 expect(searchArticles(searchIndex().entries,"fullerides",{tcMin:15,criterion:"resistivity-derivative-threshold"}).some(a=>a.code==="D9")).toBe(false);
 const withdrawn=a.references.find(r=>r.doi==="10.1038/35046008")!;
 expect(withdrawn.retraction?.noticeDoi).toBe("10.1038/nature01466");
 expect(a.materialCases.some(c=>c.sourceId===withdrawn.id)).toBe(false);
 const md=await(await get(["articles",a.id,"markdown"])).text();
 expect(md).toContain("2003-03-06");expect(md).toContain("10.1038/nature01466");
 expect(md).toContain("operational criterion");expect(md).toContain("no equilibrium Tc");
 expect(md).toContain("0.13 to 0.13 GPa");expect(md).toContain("0.7 to 0.7 GPa");
 expect(md).not.toContain("undefined");
});

it("keeps organic transition criteria separate from Mott endpoints and low-temperature probes",async()=>{
 const a=articles().find(a=>a.code==="D10")!;
 expect(a.references.some(r=>r.doi==="10.1021/ic00339a004")).toBe(true);
 expect(a.references.some(r=>r.doi==="10.1021/ic00331a012")).toBe(false);
 const br=a.materialCases.filter(c=>c.formula==="κ-(ET)2Cu[N(CN)2]Br");
 expect(br.map(c=>[c.tcK,c.criterion])).toEqual([[11.6,"inductive-onset"],[12.5,"resistive-onset"]]);
 for(const t of [39.7,13.1,24,.43,.52,.72,.1,.032]){
  const records=a.materialCases.filter(c=>c.reportedTemperatureK===t);
  expect(records.length).toBeGreaterThan(0);expect(records.every(c=>c.tcK===null)).toBe(true);
 }
 for(const criterion of ["angular-thermal-conductivity-probe","high-field-knight-shift-probe"]){
  expect(searchArticles(searchIndex().entries,"organic",{criterion}).some(a=>a.code==="D10")).toBe(true);
  expect(searchArticles(searchIndex().entries,"organic",{tcMin:.01,criterion}).some(a=>a.code==="D10")).toBe(false);
 }
 expect(a.materialCases.find(c=>c.reportedTemperatureK===39.7)?.pressureGPa).toEqual({min:.0248,max:.0248});
 expect(searchArticles(searchIndex().entries,"organic",{tcMin:13}).some(a=>a.code==="D10")).toBe(false);
 expect(searchArticles(searchIndex().entries,"organic",{tcMin:12,criterion:"inductive-onset"}).some(a=>a.code==="D10")).toBe(false);
 expect(searchArticles(searchIndex().entries,"organic",{tcMin:12,criterion:"resistive-onset"}).some(a=>a.code==="D10")).toBe(true);
 expect(searchArticles(searchIndex().entries,"organic",{tcMin:10,criterion:"reported-transition-unspecified"}).some(a=>a.code==="D10")).toBe(true);
 expect(searchArticles(searchIndex().entries,"organic",{tcMin:10,criterion:"resistive-transition"}).some(a=>a.code==="D10")).toBe(false);
 const md=await(await get(["articles",a.id,"markdown"])).text();
 expect(md).toContain("0.0248 to 0.0248 GPa");expect(md).toContain("0.0282 to 0.0282 GPa");
 expect(md).toContain("anion-ordering-temperature");expect(md).toContain("7mK/min");
 expect(md).not.toContain("undefined");expect(md).not.toContain("(#R");
});

it("preserves pressure-probe calibration and does not promote freezing or unknown resistive criteria",async()=>{
 const a=articles().find(a=>a.code==="E1")!;
 expect(a.materialCases.filter(c=>c.formula==="Fe1.01Se").map(c=>[c.tcK,c.pressureGPa?.min,c.criterion])).toEqual([[18.6,.8,"resistive-onset"],[36.7,8.9,"resistive-onset"],[25,15,"resistive-onset"]]);
 const hg=a.materialCases.find(c=>c.tcK===164)!;
 expect(hg.pressureGPa).toBeNull();expect(hg.criterion).toBe("resistive-transition-unspecified");
 expect(a.materialCases.find(c=>c.reportedTemperatureK===96.9)?.tcK).toBeNull();
 expect(a.materialCases.some(c=>c.tcK===151)).toBe(false);
 expect(searchArticles(searchIndex().entries,"pressure tuning",{tcMin:100}).some(a=>a.code==="E1")).toBe(true);
 expect(searchArticles(searchIndex().entries,"pressure tuning",{tcMin:100,criterion:"resistive-onset"}).some(a=>a.code==="E1")).toBe(false);
 expect(searchArticles(searchIndex().entries,"pressure tuning",{criterion:"zero-resistance"}).some(a=>a.code==="E1")).toBe(false);
 const md=await(await get(["articles",a.id,"markdown"])).text();
 expect(md).toContain("8.9 to 8.9 GPa");expect(md).toContain("pressure-medium-freezing-proxy");
 expect(md).toContain("separate Mössbauer paragraph");expect(md).toContain("not the assigned pressure");
 expect(md).not.toContain("undefined");expect(md).not.toContain("(#R");
});

it("binds recognized material names and curated aliases to the same record as numeric filters",async()=>{
 const index=searchIndex().entries;
 expect(searchArticles(index,"FeSe",{tcMin:60})).toEqual([]);
 expect(searchArticles(index,"fese pressure",{tcMin:30}).some(a=>a.code==="E1")).toBe(true);
 expect(searchArticles(index,"iron selenide",{tcMin:60})).toEqual([]);
 expect(searchArticles(index,"iron selenide",{tcMin:30}).some(a=>a.code==="E1")).toBe(true);
 expect(searchArticles(index,"FeSe/SrTiO3",{tcMin:60})).toEqual([]);
 expect(searchArticles(index,"HgBa2Ca2Cu3O8+δ",{tcMin:150}).some(a=>a.code==="E1")).toBe(true);
 expect(searchArticles(index,"pressure tuning",{tcMin:150}).some(a=>a.code==="E1")).toBe(true);
 const data=await(await get(["search"],"?q=FeSe&tcMin=60")).json();expect(data.results).toEqual([]);
 const positive=await(await get(["search"],"?q=FeSe&tcMin=30")).json();expect(positive.results.some((a:{code:string})=>a.code==="E1")).toBe(true);
 const md=await(await get(["articles","scwiki-e1","markdown"])).text();expect(md).toContain("aliases: FeSe, iron selenide");
});

it("keeps composition conventions and doping-series criteria intact across search and exports",async()=>{
 const a=articles().find(a=>a.code==="E2")!;
 const md=await(await get(["articles",a.id,"markdown"])).text();
 expect(md).toContain("y=2x");expect(md).toContain("y=0.35");
 expect(a.claims.find(c=>c.id==="scwiki-e2-claim-scope-2")?.sourceRelationship).toBe("mixed-source-and-local-derivation");
 expect(md).toContain("0.078");expect(md).toContain("final-version");
 expect(a.materialCases.find(c=>c.reportedTemperatureK===20)?.tcK).toBeNull();
 expect(a.materialCases.find(c=>c.tcK===23)?.criterion).toBe("series-maximum-multiple-criteria");
 expect(a.materialCases.find(c=>c.tcK===85.3)?.criterion).toBe("field-cooled-magnetization-midpoint");
 expect(a.materialCases.every(c=>c.pressureGPa===null)).toBe(true);
 const index=searchIndex().entries;
 expect(searchArticles(index,"chemical doping",{tcMin:80}).some(a=>a.code==="E2")).toBe(true);
 expect(searchArticles(index,"chemical doping",{tcMin:20,criterion:"zero-resistance"}).some(a=>a.code==="E2")).toBe(false);
 expect(searchArticles(index,"Ba(Fe1−xCox)2As2",{tcMin:30}).some(a=>a.code==="E2")).toBe(false);
 expect(searchArticles(index,"Nd1−xSrxNiO2",{tcMin:1}).some(a=>a.code==="E2")).toBe(false);
 const data=await(await get(["search"],"?q=chemical%20doping&tcMin=80&criterion=field-cooled-magnetization-midpoint")).json();
 expect(data.results.some((r:{code:string})=>r.code==="E2")).toBe(true);
 expect(md).not.toContain("undefined");expect(md).not.toContain("(#R");
});

it("binds curated material families to their own transitions in a mixed-material article",async()=>{
 const index=searchIndex().entries;
 for(const q of ["nickelate","nickelates","iron-based","fulleride","organic","heavy fermion"]){
  expect(searchArticles(index,q,{tcMin:80}).some(a=>a.code==="E2")).toBe(false);
 }
 expect(searchArticles(index,"cuprate",{tcMin:80}).some(a=>a.code==="E2")).toBe(true);
 expect(searchArticles(index,"iron-based",{tcMin:30}).some(a=>a.code==="E2")).toBe(true);
 expect(searchArticles(index,"nickelates",{tcMin:70,pressure:"high"}).some(a=>a.code==="D5")).toBe(true);
 expect(searchArticles(index,"nickelates",{tcMin:70,pressure:"ambient"})).toEqual([]);
 const negative=await(await get(["search"],"?q=nickelates&tcMin=70&pressure=ambient")).json();
 expect(negative.results).toEqual([]);
 const md=await(await get(["articles","scwiki-e2","markdown"])).text();
 expect(md).toContain("aliases: nickelate, nickelates");
});


it("keeps gate-dependent device thresholds and chemical controls separate in search and exports",async()=>{
 const a=articles().find(a=>a.code==="E3")!;
 const index=searchIndex().entries;
 const cases:[string,number,string|undefined,boolean][]=[
  ["WTe2",.9,"zero-resistance",false],["WTe2",.9,"resistance-50-percent-normal",true],
  ["WTe2",.3,"zero-resistance",true],["ZrNCl",15,undefined,true],
  ["ZrNCl",15,"zero-resistance",false],["MoS2",2.5,"resistance-90-percent-normal",true],
  ["MoS2",2.5,"resistance-50-percent-normal",false],["VO2",1,undefined,false]
 ];
 for(const [q,tcMin,criterion,expected] of cases){
  expect(searchArticles(index,q,{tcMin,criterion}).some(x=>x.code==="E3"),q+" "+criterion).toBe(expected);
 }
 for(const t of [.020,15,300])expect(a.materialCases.find(c=>c.reportedTemperatureK===t)?.tcK).toBeNull();
 const zr=a.materialCases.find(c=>c.formula==="ZrNCl")!;
 expect(a.references.find(r=>r.id===zr.sourceId)?.doi).toBe("10.1038/nmat2587");
 expect(zr.criterion).toBe("transition-unspecified");
 const md=await(await get(["articles",a.id,"markdown"])).text();
 expect(md).toContain("0.950 K");expect(md).toContain("residual resistance");
 expect(md).toContain("oxygen-vacancy");expect(md).toContain("15.2 K");
 expect(md).not.toContain("undefined");expect(md).not.toContain("(#R");
 const negative=await(await get(["search"],"?q=VO2&tcMin=1")).json();
 expect(negative.results.some((r:{code:string})=>r.code==="E3")).toBe(false);
});

it("separates calibrated strain, magnetic midpoints and film resistive endpoints",async()=>{
 const a=articles().find(a=>a.code==="E4")!;
 const index=searchIndex().entries;
 expect(a.materialCases.filter(c=>c.formula==="Sr2RuO4").map(c=>[c.tcK,c.criterion])).toEqual([[3.4,"magnetic-susceptibility-50-percent"],[3.5,"magnetic-susceptibility-50-percent"]]);
 expect(searchArticles(index,"Sr2RuO4",{tcMin:4}).some(a=>a.code==="E4")).toBe(false);
 expect(searchArticles(index,"Sr2RuO4",{tcMin:3,criterion:"zero-resistance"}).some(a=>a.code==="E4")).toBe(false);
 expect(searchArticles(index,"nickelate",{tcMin:40,criterion:"resistive-onset",pressure:"ambient"}).some(a=>a.code==="E4")).toBe(true);
 expect(searchArticles(index,"nickelate",{tcMin:40,criterion:"zero-resistance",pressure:"ambient"}).some(a=>a.code==="E4")).toBe(false);
 expect(searchArticles(index,"nickelate",{tcMin:1,criterion:"zero-resistance",pressure:"ambient"}).some(a=>a.code==="E4")).toBe(true);
 const md=await(await get(["articles",a.id,"markdown"])).text();
 expect(md).toContain("−2.0%/−1.6%");expect(md).toContain("−1.2%/−0.9%");expect(md).toContain("+1.9%/+1.8%");
 expect(md).toContain("10.1038/s41586-026-10335-8");expect(md).toContain("mΩ cm");
 expect(md).toContain("sample broke");expect(md).toContain("not a verified copy of the corrected journal version");
 const ko=a.references.find(r=>r.id==="source-98849f3ad0a2df49")!;
 expect(ko.verification.evidenceUrl).toBe("https://www.osti.gov/servlets/purl/2509524");
 expect(searchArticles(index,"Ko A1",{tcMin:42.1,criterion:"resistive-onset"}).some(a=>a.code==="E4")).toBe(true);
 expect(searchArticles(index,"Ko A1",{criterion:"zero-resistance"}).some(a=>a.code==="E4")).toBe(false);
 expect(a.materialCases.every(c=>c.equilibrium==="unknown")).toBe(true);
 expect(md).not.toContain("undefined");expect(md).not.toContain("(#R");
 const data=await(await get(["search"],"?q=nickelate&tcMin=40&criterion=zero-resistance&pressure=ambient")).json();
 expect(data.results.some((r:{code:string})=>r.code==="E4")).toBe(false);
});

it("keeps high-field measurement temperatures and internal anomalies out of Tc filters",async()=>{
 const a=articles().find(a=>a.code==="E5")!;
 const index=searchIndex().entries;
 expect(a.materialCases.filter(c=>c.formula==="UTe2").every(c=>c.tcK===null)).toBe(true);
 expect(a.materialCases.find(c=>c.reportedTemperatureK===4)?.temperatureKind).toBe("normal-state");
 expect(a.materialCases.find(c=>c.reportedTemperatureK===.3)?.tcK).toBeNull();
 expect(a.materialCases.find(c=>c.reportedTemperatureK===1.1)?.tcK).toBeNull();
 expect(searchArticles(index,"UTe2",{tcMin:2}).some(a=>a.code==="E5")).toBe(false);
 expect(searchArticles(index,"CeCoIn5",{tcMin:2,criterion:"zero-resistance",pressure:"ambient"}).some(a=>a.code==="E5")).toBe(true);
 expect(searchArticles(index,"CeCoIn5",{tcMin:3}).some(a=>a.code==="E5")).toBe(false);
 expect(searchArticles(index,"heavy fermion",{tcMin:3}).some(a=>a.code==="E5")).toBe(false);
 const data=await(await get(["search"],"?q=UTe2&tcMin=2")).json();
 expect(data.results.some((r:{code:string})=>r.code==="E5")).toBe(false);
 const md=await(await get(["articles",a.id,"markdown"])).text();
 expect(md).toContain("3742");expect(md).toContain("extra factor of two");expect(md).toContain("normal-state measurement");
 expect(md).toContain("final definition");expect(md).toContain("10.1038/s41467-026-71899-7");
 expect(md).not.toContain("undefined");expect(md).not.toContain("(#R");
});

it("distinguishes driven base temperatures, equilibrium transitions and optical-method disputes",async()=>{
 const a=articles().find(a=>a.code==="E6")!;
 const index=searchIndex().entries;
 expect(a.materialCases.filter(c=>c.reportedTemperatureK>=100).every(c=>c.tcK===null)).toBe(true);
 expect(a.materialCases.filter(c=>c.tcK!==null).map(c=>[c.formula,c.tcK])).toEqual([["YBa2Cu3O6.5",50],["K3C60",20]]);
 expect(searchArticles(index,"K3C60",{tcMin:30}).some(a=>a.code==="E6")).toBe(false);
 expect(searchArticles(index,"fulleride",{tcMin:100}).some(a=>a.code==="E6")).toBe(false);
 expect(searchArticles(index,"YBCO",{tcMin:100}).some(a=>a.code==="E6")).toBe(false);
 expect(searchArticles(index,"YBCO",{tcMin:40,pressure:"ambient"}).some(a=>a.code==="E6")).toBe(true);
 expect(searchArticles(index,"K3C60",{tcMin:10,pressure:"ambient"}).some(a=>a.code==="E6")).toBe(true);
 const data=await(await get(["search"],"?q=K3C60&tcMin=100")).json();
 expect(data.results.some((r:{code:string})=>r.code==="E6")).toBe(false);
 const response=a.references.find(r=>r.doi==="10.48550/arXiv.2303.10169");expect(response?.publicationStatus).toBe("preprint");
 const md=await(await get(["articles",a.id,"markdown"])).text();
 for(const phrase of ["static four-terminal","transient two-terminal","50 nT","December 2025","100 K it is positive and linear","10.1103/21g5-x5bj"])expect(md).toContain(phrase);
 expect(md).not.toContain("undefined");expect(md).not.toContain("(#R");
});

it("keeps irradiation and Shiba spectroscopy temperatures separate from transition records",async()=>{
 const a=articles().find(a=>a.code==="E7")!;
 const index=searchIndex().entries;
 expect(a.materialCases.filter(c=>c.formula==="MnPc/Pb(111)").every(c=>c.tcK===null)).toBe(true);
 expect(a.materialCases.filter(c=>c.criterion==="irradiation-bath-temperature").every(c=>c.tcK===null)).toBe(true);
 expect(a.materialCases.find(c=>c.reportedTemperatureK===.08)?.temperatureKind).toBe("measurement");
 expect(searchArticles(index,"BaRu122",{tcMin:20}).some(a=>a.code==="E7")).toBe(false);
 expect(searchArticles(index,"BaRu122",{tcMin:17,pressure:"ambient"}).some(a=>a.code==="E7")).toBe(true);
 expect(searchArticles(index,"BaP122",{tcMin:28,criterion:"tdo-frequency-shift"}).some(a=>a.code==="E7")).toBe(true);
 expect(searchArticles(index,"BaP122",{tcMin:28,criterion:"zero-resistance"}).some(a=>a.code==="E7")).toBe(false);
 expect(searchArticles(index,"MnPc",{tcMin:1}).some(a=>a.code==="E7")).toBe(false);
 const data=await(await get(["search"],"?q=BaRu122&tcMin=20")).json();
 expect(data.results.some((r:{code:string})=>r.code==="E7")).toBe(false);
 const md=await(await get(["articles",a.id,"markdown"])).text();
 for(const phrase of ["17.85 K","50–100 microelectronvolt","tip-gap bias","20–22 K","not a completed original-text audit","10.7498/aps.21.75"])expect(md).toContain(phrase);
 expect(md).not.toContain("undefined");expect(md).not.toContain("(#R");
});

it("separates dimensional crossover criteria from measurement floors and electrode transitions",async()=>{
 const a=articles().find(a=>a.code==="E8")!;
 const index=searchIndex().entries;
 expect(a.materialCases.filter(c=>c.temperatureKind!=="transition").every(c=>c.tcK===null)).toBe(true);
 expect(searchArticles(index,"NbSe2",{tcMin:7}).some(a=>a.code==="E8")).toBe(false);
 expect(searchArticles(index,"NbSe2",{tcMin:2,criterion:"aslamazov-larkin-fit"}).some(a=>a.code==="E8")).toBe(true);
 expect(searchArticles(index,"NbSe2",{tcMin:2,criterion:"zero-resistance"}).some(a=>a.code==="E8")).toBe(false);
 expect(searchArticles(index,"MoGe nanowire",{tcMin:1}).some(a=>a.code==="E8")).toBe(false);
 expect(searchArticles(index,"InOx loop",{tcMin:1}).some(a=>a.code==="E8")).toBe(false);
 const data=await(await get(["search"],"?q=NbSe2&tcMin=7")).json();
 expect(data.results.some((r:{code:string})=>r.code==="E8")).toBe(false);
 const md=await(await get(["articles",a.id,"markdown"])).text();
 for(const phrase of ["renormalized","per direction","5.5 K belongs to the electrodes","40 mK","radius roughly 5 nm","9 November 2015"])expect(md).toContain(phrase);
 expect(md).not.toContain("undefined");expect(md).not.toContain("(#R");
 expect(articles().find(a=>a.code==="E7")!.materialCases.filter(c=>c.criterion==="irradiation-bath-temperature").every(c=>c.equilibrium==="unknown")).toBe(true);
});

it("binds moire transition values to the device, pressure and operational criterion",async()=>{
 const a=articles().find(a=>a.code==="E9")!;
 const index=searchIndex().entries;
 expect(a.materialCases.filter(c=>c.temperatureKind!=="transition").every(c=>c.tcK===null)).toBe(true);
 expect(searchArticles(index,"Cao M1",{tcMin:1}).some(a=>a.code==="E9")).toBe(false);
 expect(searchArticles(index,"Cao M2",{tcMin:1.5,criterion:"resistive-midpoint"}).some(a=>a.code==="E9")).toBe(true);
 expect(searchArticles(index,"Cao M2",{tcMin:1.5,criterion:"bkt-current-voltage-fit"}).some(a=>a.code==="E9")).toBe(false);
 expect(searchArticles(index,"Yankowitz D2",{tcMin:3,pressure:"ambient"}).some(a=>a.code==="E9")).toBe(false);
 expect(searchArticles(index,"Yankowitz D2",{tcMin:3,pressure:"high",criterion:"resistive-fit-intersection"}).some(a=>a.code==="E9")).toBe(true);
 expect(searchArticles(index,"Tanaka device",{tcMin:.01}).some(a=>a.code==="E9")).toBe(false);
 const md=await(await get(["articles",a.id,"markdown"])).text();
 for(const phrase of ["carbon–carbon bond length","factor of three","10-ohm noise floor","solvent cleaning","Randeria","Tanaka"])expect(md).toContain(phrase);
 expect(md).not.toContain("undefined");expect(md).not.toContain("(#R");
});

it("keeps post-quench onsets separate from magnetic specimens, storage and unassigned anomalies",async()=>{
 const a=articles().find(a=>a.code==="E10")!;
 const index=searchIndex().entries;
 expect(a.materialCases.every(c=>c.pressureRegime==="ambient"&&c.pressureGPa===null)).toBe(true);
 expect(a.materialCases.filter(c=>c.temperatureKind!=="transition").every(c=>c.tcK===null)).toBe(true);
 expect(searchArticles(index,"Deng S4",{tcMin:150,criterion:"resistive-onset",pressure:"ambient"}).some(a=>a.code==="E10")).toBe(true);
 expect(searchArticles(index,"Deng S4",{tcMin:150,criterion:"magnetic-onset"}).some(a=>a.code==="E10")).toBe(false);
 expect(searchArticles(index,"Deng S2",{tcMin:150}).some(a=>a.code==="E10")).toBe(false);
 expect(searchArticles(index,"Deng S2 magnetization",{tcMin:139,criterion:"magnetic-onset"}).some(a=>a.code==="E10")).toBe(true);
 expect(searchArticles(index,"Deng S5",{tcMin:160}).some(a=>a.code==="E10")).toBe(false);
 expect(searchArticles(index,"Hg1223",{tcMin:150,criterion:"zero-resistance"}).some(a=>a.code==="E10")).toBe(false);
 expect(searchArticles(index,"Hg1223",{tcMin:150,pressure:"high"}).some(a=>a.code==="E10")).toBe(false);
 const md=await(await get(["articles",a.id,"markdown"])).text();
 for(const phrase of ["78% estimate applies at 70 K","multiplies the post-quench curve by ten","Liangzi Deng","no searchable superconducting transition temperature","not a reported confidence interval"])expect(md).toContain(phrase);
 expect(md).not.toContain("undefined");expect(md).not.toContain("(#R");
});

it("preserves quantum-metric conventions and does not promote measurement conditions into Tc",async()=>{
 const a=articles().find(a=>a.code==="F1")!;
 expect(a.materialCases).toHaveLength(1);
 expect(a.materialCases[0]).toMatchObject({reportedTemperatureK:.04,tcK:null,temperatureKind:"measurement"});
 expect(searchArticles(searchIndex().entries,"quantum metric",{}).some(a=>a.code==="F1")).toBe(true);
 expect(searchArticles(searchIndex().entries,"MATBG",{tcMin:.01}).some(a=>a.code==="F1")).toBe(false);
 const md=await(await get(["articles",a.id,"markdown"])).text();
 for(const phrase of ["g^{\\rm Liang}=2g","momentum-dependent change","minimal quantum metric","order-parameter-response","zero Chern number without introducing pairing","Tanaka and colleagues"])expect(md).toContain(phrase);
 expect(a.references.some(r=>r.doi==="10.1103/PhysRevB.106.014518")).toBe(true);
 expect(a.references.find(r=>r.doi==="10.1007/BF02193559")?.verification.scope).toBe("publisher-abstract-and-bibliography");
 const section=await(await get(["articles",a.id,"sections","mathematical-assumptions"])).json();
 expect(section.section.markdown).toContain("factor of one half");
 expect(md).not.toContain("undefined");expect(md).not.toContain("(#R");
});

it("keeps Berry curvature conventions and charge-order observations separate from superconducting Tc",async()=>{
 const a=articles().find(a=>a.code==="F2")!;
 expect(a.materialCases).toHaveLength(1);
 expect(a.materialCases[0]).toMatchObject({formula:"KV3Sb5",reportedTemperatureK:80,tcK:null,criterion:"charge-order-associated-relaxation"});
 expect(searchArticles(searchIndex().entries,"Berry curvature",{}).some(a=>a.code==="F2")).toBe(true);
 expect(searchArticles(searchIndex().entries,"KV3Sb5",{tcMin:1}).some(a=>a.code==="F2")).toBe(false);
 const md=await(await get(["articles",a.id,"markdown"])).text();
 for(const phrase of ["electron charge $-e$","sheet conductance","nonquantized metallic contribution","zero-field results alone","separate superconducting transition","an isolated band with an integer band Chern number"])expect(md).toContain(phrase);
 expect(a.references.some(r=>r.doi==="10.1103/PhysRevB.59.14915")).toBe(true);
 const data=await(await get(["search"],"?q=KV3Sb5&tcMin=1")).json();
 expect(data.results.some((r:{code:string})=>r.code==="F2")).toBe(false);
 expect(md).not.toContain("undefined");expect(md).not.toContain("(#R");
});

it("keeps model Chern numbers out of experimental temperature results and preserves subspace assumptions",async()=>{
 const a=articles().find(a=>a.code==="F3")!;
 expect(a.materialCases).toEqual([]);
 expect(searchArticles(searchIndex().entries,"Fukui Hatsugai Suzuki",{}).some(a=>a.code==="F3")).toBe(true);
 const md=await(await get(["articles",a.id,"markdown"])).text();
 for(const phrase of ["Degeneracies inside the selected multiplet","minus the oriented overlap-product phase","not synonymous","positive gap sampled on a finite grid alone","Do not apply this electron charge-transport formula to a BdG integer"])expect(md).toContain(phrase);
 const data=await(await get(["search"],"?q=Chern%20number&tcMin=1")).json();
 expect(data.results.some((r:{code:string})=>r.code==="F3")).toBe(false);
 const section=await(await get(["articles",a.id,"sections","limits-and-disputes"])).json();
 expect(section.section.markdown).toContain("Overlaps must not vanish");
 expect(md).not.toContain("undefined");expect(md).not.toContain("(#R");
});

it("preserves DIII dimensional and interaction scope without inventing experimental material records",async()=>{
 const a=articles().find(a=>a.code==="F4")!;
 expect(a.materialCases).toEqual([]);
 expect(a.references.find(r=>r.doi==="10.48550/arXiv.1406.3032")?.publicationStatus).toBe("preprint");
 expect(searchArticles(searchIndex().entries,"Majorana Kramers pair",{}).some(a=>a.code==="F4")).toBe(true);
 const md=await(await get(["articles",a.id,"markdown"])).text();
 for(const phrase of ["one and two spatial dimensions","integer $\\mathbb Z$ classification in three","an even count does not establish that the integer is zero","vortex in one component coincides with an antivortex","squares to fermion parity"])expect(md).toContain(phrase);
 const data=await(await get(["search"],"?q=class%20DIII&tcMin=1")).json();
 expect(data.results.some((r:{code:string})=>r.code==="F4")).toBe(false);
 expect(md).not.toContain("undefined");expect(md).not.toContain("(#R");
});


it("keeps topic searches independent of material identity while binding measurement conditions",async()=>{
 const a=articles().find(a=>a.code==="G8")!;
 const index=searchIndex().entries;
 expect(searchArticles(index,"spin orbit coupling",{tcMin:2}).some(r=>r.id===a.id)).toBe(true);
 expect(searchArticles(index,"SOC",{tcMin:2}).some(r=>r.id===a.id)).toBe(true);
 expect(searchArticles(index,"Li2Pt3B",{tcMin:3}).some(r=>r.id===a.id)).toBe(false);
 expect(searchArticles(index,"Li2Pt3B",{criterion:"muon-temperature-scan",tcMin:0.01}).some(r=>r.id===a.id)).toBe(false);
 const exported=await(await get(["articles",a.id,"sections","material-cases"],"?format=markdown")).text();
 expect(exported).toContain("2.68 K");expect(exported).toContain("measurement");
});

it("finds an English altermagnet article from Chinese queries without treating measurement temperatures as Tc",async()=>{
 const a=articles().find(a=>a.code==="G9")!;
 for(const query of ["交错磁性","交替磁序"]){
  const response=await(await get(["search"],"?q="+encodeURIComponent(query))).json();
  expect(response.results.some((r:{id:string})=>r.id===a.id)).toBe(true);
 }
 expect(a.title).toBe("Altermagnetism and superconductivity");
 expect(a.materialCases.every(r=>r.tcK===null&&r.temperatureKind==="measurement")).toBe(true);
 const filtered=await(await get(["search"],"?q="+encodeURIComponent("交错磁性")+"&tcMin=0.01")).json();
 expect(filtered.results.some((r:{id:string})=>r.id===a.id)).toBe(false);
});


it("binds nickelate temperature thresholds to their sample criteria and preprint status",async()=>{
 const a=articles().find(a=>a.code==="D5")!;
 const index=searchIndex().entries;
 expect(searchArticles(index,"Nd0.8Sr0.2NiO2",{tcMin:14,criterion:"resistive-onset-maximum-curvature"}).some(r=>r.id===a.id)).toBe(true);
 expect(searchArticles(index,"Nd0.8Sr0.2NiO2",{tcMin:14,criterion:"zero-resistance"}).some(r=>r.id===a.id)).toBe(false);
 expect(searchArticles(index,"La2PrNi2O7",{tcMin:40,criterion:"resistive-90-percent-normal-fit"}).some(r=>r.id===a.id)).toBe(true);
 expect(searchArticles(index,"La2PrNi2O7",{tcMin:40,criterion:"zero-resistance"}).some(r=>r.id===a.id)).toBe(false);
 expect(searchArticles(index,"Nd0.85Sr0.15NiO2",{tcMin:70,pressure:"ambient"}).some(r=>r.id===a.id)).toBe(false);
 const source=a.references.find(r=>r.doi==="10.48550/arXiv.2604.09525")!;
 expect(source.publicationStatus).toBe("preprint");
 expect(a.materialCases.find(m=>m.sourceId===source.id)?.pressureGPa).toEqual({min:91.5,max:91.5});
 const md=await(await get(["articles",a.id,"sections","recent-structures-and-membranes"],"?format=markdown")).text();
 expect(md).toContain("99.5%");expect(md).toContain("not assigned to a precise searchable Tc record");
 const math=await(await get(["articles",a.id,"sections","mathematical-assumptions"],"?format=markdown")).text();
 expect(math).toContain("opposite majority populations");expect(math).toContain("two finite-field curves differ");
 expect(math).toContain("not fits to nickelate data");expect(math).toContain("mixed-source-and-local-derivation");
 const experiment=await(await get(["articles",a.id,"sections","experimental-criteria"],"?format=markdown")).text();
 expect(experiment).toContain("perovskite precursor");expect(experiment).toContain("not a measured nickelate penetration depth");
 const limits=await(await get(["articles",a.id,"sections","limits-and-disputes"])).json();
 expect(limits.section.markdown).toContain("measurement temperature, not a new transition temperature");
 expect(limits.section.markdown).toContain("long-range magnetic order is not established");
 expect(a.claims.find(c=>c.id==="scwiki-d5-claim-scope-1")?.sourceIds).toContain("source-2337a5bf19bca4c4");
 expect(a.claims.find(c=>c.id==="scwiki-d5-claim-limits-and-disputes-2")?.sourceRelationship).toBe("context-for-editorial-analysis");
});


it("preserves strange-metal evidence limits through search and section exports",async()=>{
 const a=articles().find(a=>a.code==="N5")!;
 expect(a.materialCases).toEqual([]);
 for(const id of a.scopeItems![0].sectionIds){
  const data=await(await get(["articles",a.id,"sections",id])).json();
  expect(data.scopeItems.map((i:{id:string})=>i.id)).toEqual(["N5"]);
  const md=await(await get(["articles",a.id,"sections",id],"?format=markdown")).text();
  expect(md).toContain(data.section.markdown);
  for(const limit of a.review!.limitations)expect(md).toContain(limit);
 }
 for(const q of ["奇异金属微观起源","thermal response width","zero-frequency spline extrapolation"]){
  expect(searchArticles(searchIndex().entries,q).some(x=>x.id===a.id)).toBe(true);
  expect(searchArticles(searchIndex().entries,q,{tcMin:0.01}).some(x=>x.id===a.id)).toBe(false);
 }
 expect(a.references.find(r=>r.doi==="10.1103/611k-yxb9")!.verification.evidenceUrl).toMatch(/v4$/);
 expect(a.references.find(r=>r.doi==="10.1038/s41567-026-03441-x")!.verification.note).toContain("Final main text");
 const md=await(await get(["articles",a.id,"markdown"])).text();
 expect(md).toContain("does not adjudicate the dispute");
 expect(md).toContain("not a microscopic Hamiltonian construction");
});


it("keeps UTe2 inference boundaries in section exports and excludes model quantities from Tc filters",async()=>{
 const a=articles().find(a=>a.code==="N6")!;
 expect(a.materialCases).toEqual([]);
 for(const id of a.scopeItems![0].sectionIds){
  const data=await(await get(["articles",a.id,"sections",id])).json();
  expect(data.scopeItems.map((i:{id:string})=>i.id)).toEqual(["N6"]);
  const md=await(await get(["articles",a.id,"sections",id],"?format=markdown")).text();
  expect(md).toContain(data.section.markdown);
  for(const limit of a.review!.limitations)expect(md).toContain(limit);
 }
 for(const q of ["UTe2三重态","two-site Knight shift","nearly equal hyperfine slopes"]){
  expect(searchArticles(searchIndex().entries,q).some(x=>x.id===a.id)).toBe(true);
  expect(searchArticles(searchIndex().entries,q,{tcMin:0.01}).some(x=>x.id===a.id)).toBe(false);
 }
 const md=await(await get(["articles",a.id,"markdown"])).text();
 for(const phrase of ["single-component even-parity states","not an exact measurement of zero","zero-field temperature dependence alone","not a refit of the spectra"])expect(md).toContain(phrase);
 expect(a.references.find(r=>r.doi==="10.1038/s41567-024-02493-1")!.verification.note).toContain("Online 9 May 2024");
 expect(a.references.find(r=>r.doi==="10.7566/JPSJ.93.123701")!.verification.evidenceUrl).toMatch(/v1$/);
});


it("preserves nickelate sample and publication boundaries across search and section exports",async()=>{
 const a=articles().find(a=>a.code==="N7")!;
 expect(a.materialCases).toEqual([]);
 for(const id of a.scopeItems![0].sectionIds){
  const data=await(await get(["articles",a.id,"sections",id])).json();
  expect(data.scopeItems.map((i:{id:string})=>i.id)).toEqual(["N7"]);
  const md=await(await get(["articles",a.id,"sections",id],"?format=markdown")).text();
  expect(md).toContain(data.section.markdown);
  for(const limit of a.review!.limitations)expect(md).toContain(limit);
 }
 for(const q of ["镍酸盐配对机制","interband sign reversal","fragmented conducting paths"]){
  expect(searchArticles(searchIndex().entries,q).some(x=>x.id===a.id)).toBe(true);
  expect(searchArticles(searchIndex().entries,q,{tcMin:0.01}).some(x=>x.id===a.id)).toBe(false);
 }
 const md=await(await get(["articles",a.id,"markdown"])).text();
 for(const phrase of ["not automatically the full superconducting gap","not experimentally measured universal thresholds","not this high-pressure gap","fixed-hybridization counterexample"])expect(md).toContain(phrase);
 expect(a.references.find(r=>r.doi==="10.48550/arXiv.2509.12606")!.publicationStatus).toBe("preprint");
 expect(a.references.find(r=>r.doi==="10.1126/science.adw8329")!.verification.evidenceUrl).toMatch(/v2$/);
 expect(a.references.find(r=>r.doi==="10.1038/s41467-025-65865-y")!.verification.note).toContain("23 meV");
});


it("preserves LK-99 validation limits in exports and keeps unverified claims out of Tc filters",async()=>{
 const a=articles().find(a=>a.code==="N8")!;
 expect(a.materialCases).toEqual([]);
 for(const id of a.scopeItems![0].sectionIds){
  const data=await(await get(["articles",a.id,"sections",id])).json();
  expect(data.scopeItems.map((i:{id:string})=>i.id)).toEqual(["N8"]);
  const md=await(await get(["articles",a.id,"sections",id],"?format=markdown")).text();
  expect(md).toContain(data.section.markdown);
  for(const limit of a.review!.limitations)expect(md).toContain(limit);
 }
 for(const q of ["LK99科学验证","contact permutations","constant thermoelectric offsets"]){
  expect(searchArticles(searchIndex().entries,q).some(x=>x.id===a.id)).toBe(true);
  expect(searchArticles(searchIndex().entries,q,{tcMin:0.01}).some(x=>x.id===a.id)).toBe(false);
 }
 const md=await(await get(["articles",a.id,"markdown"])).text();
 for(const phrase of ["not a statistical confidence interval","not a reconstruction of any LK-99 experiment","not a universal certification","separate large-sample calibration explicitly subtracts"])expect(md).toContain(phrase);
 expect(a.references.find(r=>r.doi==="10.48550/arXiv.2307.12008")!.publicationStatus).toBe("preprint");
 expect(a.references.find(r=>r.doi===null&&r.url.includes("webstore.iec.ch"))!.verification.scope).toBe("official-public-scope-only");
});


it("separates topology, transition temperature and spectral visibility across exports and search",async()=>{
 const a=articles().find(a=>a.code==="N9")!;
 expect(a.materialCases).toEqual([]);
 for(const id of a.scopeItems![0].sectionIds){
  const data=await(await get(["articles",a.id,"sections",id])).json();
  expect(data.scopeItems.map((i:{id:string})=>i.id)).toEqual(["N9"]);
  const md=await(await get(["articles",a.id,"sections",id],"?format=markdown")).text();
  expect(md).toContain(data.section.markdown);
  for(const limit of a.review!.limitations)expect(md).toContain(limit);
 }
 for(const q of ["拓扑超导与高Tc","vortex orientation","vortex minigap"]){
  expect(searchArticles(searchIndex().entries,q).some(x=>x.id===a.id)).toBe(true);
  expect(searchArticles(searchIndex().entries,q,{tcMin:0.01}).some(x=>x.id===a.id)).toBe(false);
 }
 const md=await(await get(["articles",a.id,"markdown"])).text();
 for(const phrase of ["does not solve its temperature dependence","not a universal device operating limit","7.9 K zero-resistance","not a fit to a measured peak"])expect(md).toContain(phrase);
 expect(a.references.find(r=>r.doi==="10.1038/s41467-025-67957-1")!.verification.note).toContain("26 December 2025");
 expect(a.references.find(r=>r.doi==="10.1126/science.aao1797")!.verification.evidenceUrl).toMatch(/v3$/);
});

it("projects article metadata but keeps scientific conditions and provenance with excerpts",async()=>{
 const full=(await(await get(["articles","scwiki-a4"])).json()).article;
 const thinResponse=await get(["articles","scwiki-a4"],"?fields=title");const thin=(await thinResponse.json()).article;
 expect(Object.keys(thin).sort()).toEqual(["code","editorialStatus","id","modifiedAt","provenance","review","revision","slug","title"]);
 expect(thin.review).toEqual(full.review);expect(thin.provenance).toEqual(full.provenance);expect(thin.claims).toBeUndefined();
 for(const field of ["summary","body","markdown","sections","claims","materialCases","sourceMap","corrections","scopeItems"]){
  const selected=(await(await get(["articles","scwiki-a4"],"?fields="+field)).json()).article;
  expect(selected[field]).toEqual(full[field]);for(const required of ["claims","references","materialCases","corrections","review","provenance"])expect(selected[required]).toEqual(full[required]);
 }
 const complete=await get(["articles","scwiki-a4"]);expect(thinResponse.headers.get("ETag")).not.toBe(complete.headers.get("ETag"));
 for(const fields of ["","title,title","claims.statement","title,","unknown"," title","__proto__"]){expect((await get(["articles"],"?fields="+encodeURIComponent(fields))).status).toBe(400);}
 expect((await get(["search"],"?fields=title")).status).toBe(400);
 const page=await(await get(["articles"],"?fields=title&limit=1")).json();
 expect(page.articles[0].body).toBeUndefined();expect(page.page.next).toContain("fields=title");
 expect((await get(["articles"],"?fields=summary&limit=1&cursor="+page.page.nextCursor)).status).toBe(400);
});
it("paginates the complete lightweight revision manifest at one content revision",async()=>{
 const records:any[]=[];let cursor:string|null=null;
 do{const response=await get(["revisions"],"?limit=13"+(cursor?"&cursor="+cursor:""));expect(response.status).toBe(200);const data=await response.json();expect(data.revision).toBe(catalogue().revision);expect(data.total).toBe(articles().length);expect(data.snapshotKind).toBe("complete-current-inventory");records.push(...data.records);cursor=data.page.nextCursor;}while(cursor);
 expect(records).toEqual(articles().map(a=>({id:a.id,revision:a.revision,modifiedAt:a.modifiedAt,url:"/scwiki/"+a.slug})));
 const first=await(await get(["revisions"],"?limit=1")).json();expect((await get(["topics"],"?limit=1&cursor="+first.page.nextCursor)).status).toBe(400);
 const spec=await(await get(["openapi.json"])).json();expect(spec.paths["/revisions"].get.operationId).toBe("listSCWikiRevisions");
 for(const p of Object.values(spec.components.schemas.ArticleProjection.properties)as any[]){const key=p.$ref.split("/").pop();expect(spec.components.schemas.Article.properties[key]).toBeDefined();}
});
it("derives changes only from complete consistent snapshots, retaining failed-sync safety",async()=>{
 const {diffRevisionSnapshots}=await import("@/lib/scwiki/revisions");
 const record=(id:string,revision:string)=>({id,revision,modifiedAt:"2026-10-19",url:"/scwiki/example"});
 const previous={revision:"a".repeat(20),total:2,records:[record("scwiki-a1","1".repeat(20)),record("scwiki-a2","2".repeat(20))]};
 const current={revision:"b".repeat(20),total:2,records:[record("scwiki-a1","3".repeat(20)),record("scwiki-a3","4".repeat(20))]};
 expect(diffRevisionSnapshots(previous,current)).toMatchObject({added:["scwiki-a3"],updated:["scwiki-a1"],removed:["scwiki-a2"]});
 expect(diffRevisionSnapshots(previous,previous)).toMatchObject({added:[],updated:[],removed:[]});
 expect(()=>diffRevisionSnapshots(previous,{...current,records:current.records.slice(0,1)})).toThrow(/complete/);
 expect(()=>diffRevisionSnapshots(previous,{...current,records:[current.records[0],current.records[0]]})).toThrow(/duplicate/);
 expect(()=>diffRevisionSnapshots(previous,{...current,revision:previous.revision})).toThrow(/Conflicting/);
});

it("propagates the identified Mitrano publisher correction without certifying the full paper",async()=>{
 const sid="source-6ee3670220e24ff1";
 for(const code of ["A1","B7","D9","E6"]){
  const a=articles().find(a=>a.code===code)!;const source=a.references.find(r=>r.id===sid)!;
  expect(source.updates).toHaveLength(1);expect(source.updates![0]).toMatchObject({kind:"correction",date:"2016-02-24",checkedAt:"2026-10-19"});
  expect(source.updates![0].scope).toContain("not compared in full");
  expect(source.verification.note).toContain("24 February 2016");
  expect(JSON.stringify(a)).not.toMatch(/update (?:details )?remain[s]? unresolved|update whose details have not been verified/);
  const json=(await(await get(["articles",a.id])).json()).article;
  expect(json.references.find((r:any)=>r.id===sid).updates).toEqual(source.updates);
  const md=await(await get(["articles",a.id,"markdown"])).text();expect(md).toContain("24 February 2016");
 }
 const sources=await getAll("sources");expect(sources.sources.find((r:any)=>r.id===sid).updates[0].date).toBe("2016-02-24");
});


describe("SCWiki preparation and observation separation",()=>{
 it("retains preparation provenance across full, projected and section exports without changing pressure filters",async()=>{
  const a=(await(await get(["articles","scwiki-e10"])).json()).article;
  expect(a.materialCases).toHaveLength(9);expect(a.materialCases.map((x:any)=>x.tcK)).toEqual([139,147,147,149,151,140,null,null,null]);
  expect(a.materialCases.every((x:any)=>x.pressureRegime==="ambient"&&x.pressureGPa===null&&x.preparation.releaseRateGPaPerSecond===null)).toBe(true);
  expect(a.materialCases[4].preparation.pressureGPa).toEqual({min:18.9,max:18.9});expect(a.materialCases[4].preparation.temperatureK).toBe(4.2);
  for(const query of ["?fields=materialCases","?fields=summary"]){const p=(await(await get(["articles",a.id],query)).json()).article;expect(p.materialCases).toEqual(a.materialCases);expect(p.references.some((r:any)=>r.id===a.materialCases[4].preparation.sourceId)).toBe(true);}
  const context=(await(await get(["articles",a.id,"sections","material-cases"])).json());expect(context.materialCases).toEqual(a.materialCases);
  for(const path of [["articles",a.id,"markdown"],["articles",a.id,"sections","material-cases"]]){const md=await(await get(path,path.length===4?"?format=markdown":"")).text();for(const word of ["Preparation history","not measurement pressure","Unknown release rate is not zero","18.9 to 18.9 GPa","26.3 GPa"])expect(md).toContain(word);}
  for(const [params,want]of [["pressure=ambient&tcMin=151",true],["pressure=high&tcMin=151",false],["pressure=ambient&criterion=zero-resistance&tcMin=151",false]]as const){const d=await(await get(["search"],"?q=Deng%20S4&"+params)).json();expect(d.results.some((x:any)=>x.id===a.id)).toBe(want);}
  expect((await(await get(["articles","scwiki-f7"])).json()).article.materialCases[0]).not.toHaveProperty("preparation");
 });
 it("includes a distinct preparation source in material-section context",async()=>{
  const a=articles().find(x=>x.code==="E10")!,record=a.materialCases[0],before=record.preparation!;
  const different=a.references.find(x=>x.id!==record.sourceId)!.id;
  try{record.preparation={...before,sourceId:different};const d=await(await get(["articles",a.id,"sections","material-cases"])).json();expect(d.sources.map((x:any)=>x.id)).toContain(different);expect(d.sources.map((x:any)=>x.id)).toContain(record.sourceId);}
  finally{record.preparation=before;}
 });
 it("documents the optional nullable preparation contract and English agent guidance",async()=>{
  const s=await(await get(["openapi.json"])).json();expect(s.info.version).toBe("1.5.0");expect(s.components.schemas.MaterialCase.properties.preparation.$ref).toBe("#/components/schemas/SamplePreparation");expect(s.components.schemas.MaterialCase.required).not.toContain("preparation");expect(s.components.schemas.SamplePreparation.properties.releaseRateGPaPerSecond.type).toContain("null");expect(s.paths['/search'].get.parameters.find((x:any)=>x.name==='pressure').description).toContain('Measurement pressure');
  const Guide=(await import("@/app/scwiki/agent-guide/page")).default;const html=renderToStaticMarkup(<Guide/>);expect(html).toContain("Separate preparation from measurement");expect(html).toContain("Preparation temperature is not a critical temperature");
  const llms=await(await(await import("@/app/scwiki/llms.txt/route")).GET()).text();expect(llms).toContain("materialCases[].preparation");expect(llms).toContain("Unknown release rate remains null");
 });
});
