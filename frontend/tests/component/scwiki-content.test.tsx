import {render,screen,fireEvent} from "@testing-library/react";
import {SearchCatalogue} from "@/components/scwiki/SearchCatalogue";
import {middleware} from "../../middleware";
import {describe,it,expect} from "vitest";
import {readFileSync} from "node:fs";
import {createHash} from "node:crypto";
import {renderToStaticMarkup} from "react-dom/server";
import {NextRequest} from "next/server";
import {ScientificMarkdown} from "@/components/scwiki/ScientificMarkdown";
import {articles,catalogue,searchIndex} from "@/lib/scwiki/catalogue";
import {searchArticles,normalizeSearch} from "@/lib/scwiki/search";
import {safeUrl} from "@/lib/scwiki/safety";
import {legacyDestination} from "@/lib/site-routes";
import {GET} from "@/app/api/scwiki/v1/[[...segments]]/route";
const get=(segments:string[],query="")=>GET(new NextRequest("http://localhost/api/scwiki/v1/"+segments.join("/")+query),{params:Promise.resolve({segments})});
describe("SCWiki source and scientific-content contracts",()=>{
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
  expect(a.references.find(r=>r.doi==="10.1126/science.1227612")!.verification.scope).toBe("crossref-metadata-only");
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
  const payload=await (await get(["sources"])).json();
  const bcs=payload.sources.find((r:{doi:string})=>r.doi==="10.1103/PhysRev.108.1175");
  expect(bcs.verification.scope).toBe("article-scoped-checks");
  expect(bcs.usedBy).toEqual(expect.arrayContaining(["scwiki-a1","scwiki-b1"]));
  expect(bcs.articleChecks.find((c:{articleId:string})=>c.articleId==="scwiki-a1").verification.scope).toBe("crossref-metadata-only");
  expect(bcs.articleChecks.find((c:{articleId:string})=>c.articleId==="scwiki-b1").verification.scope).toBe("primary-full-text-scoped-check");
 });
 it("corrects the unrelated biology DOI and separates calculated MgB2 gaps from experiments",()=>{
  const a=articles().find(a=>a.code==="B12")!;
  expect(a.references.some(r=>r.doi==="10.1038/nature00992")).toBe(false);
  const ref=a.references.find(r=>r.doi==="10.1038/nature00898")!;
  expect(ref.title).toContain("MgB2");
  expect(ref.verification.scope).toBe("primary-full-text-scoped-check");
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
  expect(m.files.filter((x:{topicId:string|null})=>x.topicId)).toHaveLength(88);
  expect(m.files.filter((x:{publicBody:boolean})=>x.publicBody).map((x:{articleId:string})=>x.articleId).sort()).toEqual(articles().map(a=>a.id).sort());
  expect(m.files.find((x:{path:string})=>x.path.includes("Al-O")).disposition).toContain("prediction-only");
  expect(articles().map(a=>a.code)).toEqual(expect.arrayContaining(["A1","A2","B12","C2","D11","D3","D4","D5","E4","F7","G7","H2"]));
  expect(articles().every(a=>a.wordCount>=450)).toBe(true);
 });
 it("uses stable IDs, content hashes, complete source mappings and separate review labels",()=>{
  const m=JSON.parse(readFileSync("content/scwiki/source-manifest.json","utf8"));
  for(const a of articles()){
   expect(a.id).toMatch(/^scwiki-[a-h]\d+$/);expect(a.topicId).toBe("scwiki-topic-"+a.code.toLowerCase());
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
 it("resolves every claim, citation and published article link without treating rendering as proof",()=>{
  const slugs=new Set(articles().map(a=>a.slug));
  for(const a of articles()){
   const refs=new Set(a.references.map(r=>r.id)),sections=new Set(a.sections.map(s=>s.id));
   expect(a.claims.length).toBeGreaterThan(5);
   for(const c of a.claims){expect(sections.has(c.sectionId)).toBe(true);expect(c.conditions.length).toBeGreaterThan(30);expect(c.sourceIds.every(id=>refs.has(id))).toBe(true);}
   for(const match of a.body.matchAll(/\]\(#ref-([a-z0-9-]+)\)/g))expect(refs.has(match[1])).toBe(true);
   for(const match of a.body.matchAll(/\]\(\/scwiki\/([a-z0-9-]+)\)/g))expect(slugs.has(match[1])).toBe(true);
   const html=renderToStaticMarkup(<ScientificMarkdown markdown={a.body}/>);
   expect(html).not.toContain('class="katex-error"');expect(html).not.toContain("language-text");
   if(a.body.includes("$$"))expect(html).toContain('class="katex"');
  }
 });
 it("corrects the KFe2As2 citation in C2 and records C10 review debt",()=>{
  const a=articles().find(a=>a.code==="C2")!;
  expect(a.body).toContain("is about KFe2As2");expect(a.corrections.length).toBeGreaterThanOrEqual(2);
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
 const md=await (await get(["articles",a.id,"markdown"])).text();expect(md).toContain("contact calibration from static four-terminal");expect(md).toContain("Mitrano publisher update details remain unresolved");
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
 const source=await(await get(["sources"])).json();expect(source.sources.find((r:{id:string})=>r.id===historical.id).doi).toBeNull();
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
 expect(limits).toContain("phenomenologically");expect(limits).toContain("normal self-energy");expect(limits).toContain("full final-version comparison is still pending");
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
 const ref=a.references.find(r=>r.doi==="10.48550/arXiv.2603.24766")!;expect(ref.publicationStatus).toBe("preprint");expect(ref.url).toContain("v2");
 const f=articles().find(a=>a.code==="F7")!;const fm=await(await get(["articles",f.id,"markdown"])).text();expect(fm).toContain("assumed active-region aspect ratio");
 expect(a.claims.filter(c=>c.sectionId==="mathematical-assumptions").every(c=>c.evidenceType==="theory")).toBe(true);
});

it("preserves Mottness model limits and the nickelate specimen-specific onset in retrieval",async()=>{
 const a=articles().find(a=>a.code==="B14")!;
 const md=await(await get(["articles",a.id,"markdown"])).text();
 expect(md).toContain("does not establish a bulk Mott transition");
 expect(md).toContain("not a quantitative X-ray absorption spectrum");
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
 expect(out).toContain("separate measurement at 25.2 GPa");
 expect(out).toContain("must not be relabeled as zero resistance");
});

it("keeps s-wave symmetry and imposed-gap checks separate from measured transition criteria",async()=>{
 const a=articles().find(a=>a.code==="C1")!;
 const md=await(await get(["articles",a.id,"markdown"])).text();
 expect(md).toContain("four zeros touch the Fermi surface without sign reversal");
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
 expect(md).toContain("approximately constant across the superconducting transition");
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
  const sources=await(await get(["sources"])).json();
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
it("does not promote hydride negative measurement limits or predictions to measured transition temperatures",()=>{
 const a=articles().find(a=>a.code==="D6")!;
 for(const formula of ["LuH2±xNy","Y3Fe4H20"]){const c=a.materialCases.find(c=>c.formula===formula)!;expect(c.tcK).toBeNull();expect(c.temperatureKind).toBe("measurement");}
 const prediction=a.materialCases.find(c=>c.recordType==="prediction")!;expect(prediction.tcK).toBeNull();
 expect(a.body).toContain("249 K and 180 K");expect(a.body).toContain("151 and 152 GPa");
 expect(a.body).toContain("not direct measurements at 136 T");
 expect(a.review.limitations[0]).toContain("remain open");
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
 expect(a.materialCases.filter(c=>c.sourceId===pang.id).map(c=>c.tcK)).toEqual([.64,.53]);
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
 expect(a.materialCases.find(c=>c.reportedTemperatureK===100)?.tcK).toBeNull();
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
 for(const t of [39.7,13.1,24,.43,.1,.032])expect(a.materialCases.find(c=>c.reportedTemperatureK===t)?.tcK).toBeNull();
 expect(a.materialCases.find(c=>c.reportedTemperatureK===39.7)?.pressureGPa).toEqual({min:.0248,max:.0248});
 expect(searchArticles(searchIndex().entries,"organic",{tcMin:13}).some(a=>a.code==="D10")).toBe(false);
 expect(searchArticles(searchIndex().entries,"organic",{tcMin:12,criterion:"inductive-onset"}).some(a=>a.code==="D10")).toBe(false);
 expect(searchArticles(searchIndex().entries,"organic",{tcMin:12,criterion:"resistive-onset"}).some(a=>a.code==="D10")).toBe(true);
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
 expect(md).toContain("y=2x");expect(md).toContain("factor-of-two mismatch");
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
