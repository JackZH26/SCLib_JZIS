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
   expect(a.review.limitations.join(" ")).toContain("not");
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
