import {render,screen} from "@testing-library/react";
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
 it("disposes all 282 pinned files and keeps unpublished topics out of the catalogue",()=>{
  const m=JSON.parse(readFileSync("content/scwiki/source-manifest.json","utf8"));
  expect(m.commit).toBe("0a7c9d6696804ec26aa12f8eed68b55c9b3c0fcf");
  expect(m.files).toHaveLength(282);
  expect(new Set(m.files.map((x:{id:string})=>x.id)).size).toBe(282);
  expect(m.files.filter((x:{topicId:string|null})=>x.topicId)).toHaveLength(88);
  expect(m.files.filter((x:{publicBody:boolean})=>x.publicBody)).toHaveLength(12);
  expect(m.files.find((x:{path:string})=>x.path.includes("Al-O")).disposition).toContain("prediction-only");
  expect(articles().map(a=>a.code).sort()).toEqual(["A1","A2","B12","C2","D11","D3","D4","D5","E4","F7","G7","H2"]);
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
   expect(createHash("sha256").update(JSON.stringify(meta)+"\n"+body).digest("hex").slice(0,20)).toBe(revision);
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
 expect(screen.getByRole("combobox",{name:"Evidence",exact:true})).toBeInTheDocument();
 expect(screen.getByRole("combobox",{name:"Pressure",exact:true})).toBeInTheDocument();
 expect(screen.getByRole("combobox",{name:"State",exact:true})).toBeInTheDocument();
 expect(screen.getByRole("spinbutton",{name:"Reported transition at least (K)",exact:true})).toBeInTheDocument();
 for(const article of articles())expect(screen.getByRole("link",{name:"Read article: "+article.title,exact:true})).toHaveTextContent("Read article");
});
it.each(["/docs/","/sclib/docs/","/docs"])("keeps exact loopback destination for %s",path=>{
 const response=middleware(new NextRequest("http://localhost:3102"+path+"?q=Fe%2BSe",{headers:{host:"127.0.0.1:3102"}}));
 expect(response.status).toBe(308);
 expect(response.headers.get("location")).toBe("http://127.0.0.1:3102/scwiki?q=Fe%2BSe");
});
