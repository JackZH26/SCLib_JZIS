import {afterEach,describe,expect,it,vi} from "vitest";
import {cleanup,fireEvent,render,screen} from "@testing-library/react";
import {NextRequest} from "next/server";
import {mkdtempSync,writeFileSync,rmSync} from "node:fs";
import {tmpdir} from "node:os";
import path from "node:path";
import seed from "@/content/scwiki/research-issues.json";
import {researchCollection,issueEnvelope,researchRss} from "@/lib/scwiki/research";
import {ResearchArchive} from "@/components/scwiki/ResearchArchive";
import {ResearchCards} from "@/components/scwiki/ResearchCards";
import {GET} from "@/app/api/scwiki/v1/[[...segments]]/route";
vi.mock("next/navigation",()=>({useRouter:()=>({replace:vi.fn()})}));
const get=(parts:string[],query="",headers={})=>GET(new NextRequest("https://jzis.org/api/scwiki/v1/"+parts.join("/")+query,{headers}),{params:Promise.resolve({segments:parts})});
afterEach(()=>{cleanup();vi.unstubAllEnvs();history.replaceState(null,"","/");});
describe("weekly research and independent runtime content",()=>{
 it("loads a new edition without reimporting code, rebuilding or restarting",()=>{
  const dir=mkdtempSync(path.join(tmpdir(),"scwiki-live-")),file=path.join(dir,"research.json");
  try{
   vi.stubEnv("SCWIKI_RESEARCH_STORE",file);writeFileSync(file,JSON.stringify(seed));
   const before=researchCollection(),old=issueEnvelope(before.issues[0],before);
   const next=structuredClone(seed);next.issues.push({...next.issues[0],id:"2026-W43",selectedAt:"2026-10-20",checkedAt:"2026-10-20",outcome:"no-new-selection",items:[]});
   writeFileSync(file,JSON.stringify(next));
   const after=researchCollection();expect(after.issues[0].id).toBe("2026-W43");expect(after.revision).not.toBe(before.revision);
   expect(issueEnvelope(after.issues[1],after).snapshotRevision).toBe(old.snapshotRevision);
   writeFileSync(file,"interrupted external edit");
   expect(researchCollection().issues[0].id).toBe("2026-W43");expect(researchCollection().warning).toMatch(/last valid/);
  }finally{rmSync(dir,{recursive:true,force:true});}
 });
 it("serves versioned latest/history/Markdown, rejects unknown inputs and supports conditional requests",async()=>{
  const res=await get(["research","latest"]),body=await res.json();
  expect(body.issue.id).toBe("2026-W42");expect(body.snapshotRevision).toMatch(/^[a-f0-9]{20}$/);
  const same=await get(["research","2026-W42"]);expect(await same.json()).toEqual(body);
  expect((await get(["research","latest"],"",{"If-None-Match":res.headers.get("etag")!})).status).toBe(304);
  const text=await(await get(["research","2026-W42","markdown"])).text();expect(text).toContain("Evidence limits:");expect(text).toContain("2026-10-18");expect(text).toContain(body.snapshotRevision);
  const archive=await(await get(["research"],"?limit=1&topic=nickelates")).json();expect(archive.total).toBe(1);expect(archive.editions[0].issue.items).toHaveLength(3);
  expect((await get(["research","2026-W99"])).status).toBe(404);
  expect((await get(["research"],"?year=bad")).status).toBe(400);
  expect((await get(["research","latest"],"?q=x")).status).toBe(400);
 });
 it("supports shareable archive filters with an explicit empty state",()=>{
  history.replaceState(null,"","/scwiki/research?topic=nickelates");
  const data=researchCollection();render(<ResearchArchive issues={data.issues} notices={data.notices}/>);
  expect(screen.getByRole("status")).toHaveTextContent("1 edition · 1 selections");
  fireEvent.change(screen.getByRole("searchbox"),{target:{value:"not-a-paper"}});
  expect(screen.getByText(/No selections match/)).toBeInTheDocument();
  expect(location.search).toContain("q=not-a-paper");
  fireEvent.click(screen.getByRole("button",{name:"Clear filters"}));
  expect(screen.getAllByRole("link",{name:/Read original paper:/})).toHaveLength(3);
 });
 it("shows subsequent retractions visibly and includes them in RSS without rewriting snapshots",()=>{
  const data=researchCollection(),item=data.issues[0].items[0],notice={id:"fixture",paperId:item.paperId,kind:"retraction" as const,date:"2026-10-20",description:"Fixture notice only.",sourceUrl:"https://example.org/notice"};
  render(<ResearchCards items={[item]} notices={[notice]}/>);
  expect(screen.getByText(/Retraction notice/)).toBeInTheDocument();expect(screen.getByText(item.summary)).toBeInTheDocument();
  expect(researchRss({...data,notices:[notice]})).toContain("scwiki-research-notice:fixture");
 });
});
