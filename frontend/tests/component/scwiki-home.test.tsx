import {afterEach,describe,expect,it,vi} from "vitest";
import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {renderToStaticMarkup} from "react-dom/server";
import SCWikiPage from "@/app/scwiki/page";
import {SearchCatalogue} from "@/components/scwiki/SearchCatalogue";
import {articles,searchIndex} from "@/lib/scwiki/catalogue";
import {topicGroups} from "@/lib/scwiki/home";
import highlights from "@/content/scwiki/research-highlights.json";
vi.mock("next/navigation",()=>({useRouter:()=>({replace:vi.fn()})}));
const initial=articles().map(({id,code,slug,title,summary,evidenceTypes})=>({id,code,slug,title,summary,evidenceTypes}));
afterEach(()=>{cleanup();vi.unstubAllGlobals();});

describe("SCWiki home discovery and research provenance",()=>{
 it("renders search before research and a linked topic portal without the old article-summary wall",()=>{
  const html=renderToStaticMarkup(<SCWikiPage/>);
  expect(html.indexOf('id="scwiki-search"')).toBeLessThan(html.indexOf('id="scwiki-research-heading"'));
  expect(html.indexOf('id="scwiki-research-heading"')).toBeLessThan(html.indexOf('id="scwiki-topics-heading"'));
  expect(html).not.toContain('class="scwiki-article-grid"');
  for(const a of articles())expect(html).toContain('href="/scwiki/'+a.slug+'"');
  expect(new Set(topicGroups.flatMap(g=>g.topics.map(t=>t.code))).size).toBe(articles().length);
  expect(html).toContain("Coverage and scientific review are still expanding");
 });
 it("keeps research dated, sourced and distinct from complete scientific verification",()=>{
  const slugs=new Set(articles().map(a=>a.slug));
  expect(highlights.items).toHaveLength(3);
  expect(highlights.items.map(i=>i.publishedAt)).toEqual(highlights.items.map(i=>i.publishedAt).sort().reverse());
  for(const item of highlights.items){
   expect(item.publishedAt).toMatch(/^\d{4}-\d{2}-\d{2}$/);
   expect(item.publishedAt<=item.checkedAt&&item.checkedAt<=highlights.checkedAt).toBe(true);
   expect(new URL(item.url).protocol).toBe("https:");expect(new URL(item.url).hostname).toBe("www.nature.com");
   expect(item.doi).toMatch(/^10\.1038\//);expect(item.paperTitle.length).toBeGreaterThan(20);
   expect(item.limitation.length).toBeGreaterThan(70);expect(item.verificationScope).toMatch(/abstract/);
   expect(slugs.has(item.topicSlug)).toBe(true);
  }
  expect(highlights.items[0].publicationStatus).toBe("peer-reviewed-accepted-early-version");
  expect(highlights.items[0].limitation).toContain("do not uniquely establish");
 });
 it("loads full wiki text on demand, finds a body-only term and restores the portal on clear",async()=>{
  const fetch=vi.fn().mockResolvedValue({ok:true,json:async()=>searchIndex()});vi.stubGlobal("fetch",fetch);
  render(<SearchCatalogue initial={initial}><h2>Latest research</h2></SearchCatalogue>);
  expect(fetch).not.toHaveBeenCalled();
  expect(initial.some(a=>[a.title,a.summary].join(" ").toLowerCase().includes("filaments"))).toBe(false);
  fireEvent.change(screen.getByRole("searchbox",{name:"Search SCWiki"}),{target:{value:"filaments"}});
  await screen.findByRole("link",{name:"Read article: "+initial.find(a=>a.code==="A1")!.title});
  expect(fetch).toHaveBeenCalledTimes(1);expect(screen.queryByRole("heading",{name:"Latest research"})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"Clear filters"}));
  expect(screen.getByRole("heading",{name:"Latest research"})).toBeInTheDocument();
  expect(screen.queryByRole("link",{name:/Read article:/})).not.toBeInTheDocument();
 });
 it("makes an index failure recoverable without replacing it with a false no-results claim",async()=>{
  const fetch=vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({ok:true,json:async()=>searchIndex()});vi.stubGlobal("fetch",fetch);
  render(<SearchCatalogue initial={initial}/>);
  fireEvent.change(screen.getByRole("searchbox"),{target:{value:"Meissner"}});
  await screen.findByRole("alert");expect(screen.queryByRole("heading",{name:"No matching evidence"})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"Retry"}));
  await waitFor(()=>expect(screen.getByRole("link",{name:/Read article: The Meissner effect/})).toBeInTheDocument());
 });
});
