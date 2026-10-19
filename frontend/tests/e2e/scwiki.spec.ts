import {expect,test} from "./public-site-fixture";
import {readFileSync} from "node:fs";
const catalogue=JSON.parse(readFileSync("content/scwiki/catalogue.json","utf8"));
const extensions=JSON.parse(readFileSync("content/scwiki/extension-inventory.json","utf8"));
test("published nickelate note preserves sample table, license and distinct publication status",async({page,request})=>{
 await page.goto("/scwiki/library/bhatt-nickelate-strain-structure");
 await page.getByRole("button",{name:"Reject all",exact:true}).click();
 await expect(page.locator(".scwiki-sources")).toContainText("Journal article");
 await expect(page.locator(".scwiki-sources")).not.toContainText("Preprint");
 await expect(page.getByRole("link",{name:"CC BY 4.0",exact:true})).toHaveAttribute("href","https://creativecommons.org/licenses/by/4.0/");
 await expect(page.locator("table")).toContainText("Onset near 42 K; zero resistance around 2 K");
 await expect(page.locator("table")).toContainText("−1.6%");
 expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
 await expect(page.locator(".katex-error")).toHaveCount(0);
 const data=await(await request.get("/api/scwiki/v1/library/bhatt-nickelate-strain-structure")).json();
 await expect(page.locator("main.scwiki")).toHaveAttribute("data-revision",data.note.revision);
 const broken=await page.locator('main.scwiki a[href^="#"]').evaluateAll(links=>links.map(a=>a.getAttribute("href")!.slice(1)).filter(id=>!document.getElementById(id)));
 expect(broken).toEqual([]);
 await page.screenshot({path:"test-results/scwiki-bhatt-390.png",fullPage:true});
});
test("research library connects homepage search, evidence notes and bounded read-only exports",async({page,request})=>{
 await page.goto("/scwiki");await page.getByRole("button",{name:"Reject all",exact:true}).click();
 await page.getByRole("searchbox",{name:"Search SCWiki"}).fill("missing-area");
 await page.getByRole("link",{name:"Read article: Parallel conduction and Planckian scattering in FeTeSe"}).click();
 await expect(page).toHaveURL(/\/scwiki\/library\/romero-parallel-conduction$/);
 await expect(page.getByRole("heading",{name:"Parallel conduction and Planckian scattering in FeTeSe",exact:true})).toBeVisible();
 await expect(page.locator("main.scwiki")).toContainText("independent scientific review");
 await expect(page.locator(".katex-error")).toHaveCount(0);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
 const broken=await page.locator('main.scwiki a[href^="#"]').evaluateAll(links=>links.map(a=>a.getAttribute("href")!.slice(1)).filter(id=>!document.getElementById(id)));
 expect(broken).toEqual([]);
 const path="/api/scwiki/v1/library/romero-parallel-conduction";
 const response=await request.get(path),detail=await response.json();
 await expect(page.locator("main.scwiki")).toHaveAttribute("data-revision",detail.note.revision);
 expect((await request.get(path,{headers:{"If-None-Match":response.headers().etag}})).status()).toBe(304);
 expect(await(await request.get(path+"/markdown")).text()).toContain("no third-party");
 expect((await request.post(path)).status()).toBe(405);
 expect((await request.get("/api/scwiki/v1/library/absent")).status()).toBe(404);
 expect((await request.get("/scwiki/library/absent")).status()).toBe(404);
 const sitemap=await(await request.get("/sitemaps/static.xml")).text();expect(sitemap).toContain("/scwiki/library/romero-parallel-conduction");
 await page.screenshot({path:"test-results/scwiki-library-390.png",fullPage:true});
});
test("SCWiki ships complete server-rendered English content and lazy search",async({page,request})=>{
 const response=await request.get("/scwiki");expect(response.status()).toBe(200);
 const html=await response.text();for(const a of catalogue.articles)expect(html).toContain("/scwiki/"+a.slug);
 expect(html.indexOf("Latest research")).toBeLessThan(html.indexOf("Explore the key concepts"));
 await page.goto("/scwiki");await page.getByRole("button",{name:"Reject all",exact:true}).click();
 expect(await page.locator(".scwiki-topic-group li").count()).toBe(catalogue.articles.length);
 await expect(page.getByRole("heading",{name:"Latest research",exact:true})).toBeVisible();
 const indexRequests:string[]=[];page.on("request",r=>{if(r.url().includes("search-index.json"))indexRequests.push(r.url());});
 expect(indexRequests).toEqual([]);
 const input=page.getByRole("searchbox",{name:"Search SCWiki",exact:true});
 await input.fill("La₃Ni₂O₇");
 await expect.poll(()=>indexRequests.length).toBe(1);
 await page.getByRole("button",{name:"Filters",exact:true}).click();
 await page.getByLabel("Pressure",{exact:true}).selectOption("ambient");
 await page.getByLabel("Reported transition at least (K)",{exact:true}).fill("70");
 await expect(page.getByRole("heading",{name:"No matching evidence"})).toBeVisible();
 await page.getByLabel("Pressure",{exact:true}).selectOption("high");
 await expect(page.locator(".scwiki-article-grid")).toContainText("Nickelate superconductors");
 expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
 await page.getByRole("button",{name:"Clear filters",exact:true}).click();
 await expect(page.locator(".scwiki-topic-group li")).toHaveCount(catalogue.articles.length);
 await expect(page.getByRole("heading",{name:"Latest research",exact:true})).toBeVisible();
 await page.screenshot({path:"test-results/scwiki-index-390.png",fullPage:true});
});
test("all published articles have formulas, real citation anchors and HTML/Markdown/JSON consistency",async({page,request})=>{
 for(const a of catalogue.articles){
  const response=await page.goto("/scwiki/"+a.slug);expect(response?.status()).toBe(200);
  await expect(page.getByRole("heading",{name:a.title,exact:true})).toBeVisible();
  await expect(page.locator("main.scwiki")).toHaveAttribute("data-revision",a.revision);
  await expect(page.locator(".katex-error")).toHaveCount(0);
  if(a.body.includes("$$"))expect(await page.locator(".katex").count()).toBeGreaterThan(0);
  const broken=await page.locator('main.scwiki a[href^="#"]').evaluateAll(links=>links.map(a=>a.getAttribute("href")!.slice(1)).filter(id=>!document.getElementById(id)));
  expect(broken,a.code+" citation and section anchors").toEqual([]);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  const json=await (await request.get("/api/scwiki/v1/articles/"+a.id)).json();
  expect(json.article.revision).toBe(a.revision);expect(json.article.materialCases).toEqual(a.materialCases);
  const md=await request.get("/api/scwiki/v1/articles/"+a.id+"/markdown");
  expect(await md.text()).toBe(a.markdown);expect(md.headers()["x-scwiki-revision"]).toBe(a.revision);
  for(const c of a.materialCases)if(c.reportedTemperatureK!==null)await expect(page.locator(".scwiki-reading-body")).toContainText(c.reportedTemperatureK+" K");
 }
 await page.goto("/scwiki/s-plus-minus");
 await page.getByRole("button",{name:"Reject all",exact:true}).click();
 await page.screenshot({path:"test-results/scwiki-c2-390.png",fullPage:true});
 await page.setViewportSize({width:1440,height:1000});await page.goto("/scwiki/geometric-superfluid-weight");
 await page.screenshot({path:"test-results/scwiki-f7-desktop.png",fullPage:true});
});
test("SCWiki navigation order, keyboard focus and old docs anchors work",async({page})=>{
 await page.goto("/scwiki");await page.getByRole("button",{name:"Reject all",exact:true}).click();
 const toggle=page.getByRole("button",{name:"Open navigation"});await toggle.click();
 const menu=page.getByRole("navigation",{name:"Mobile navigation"});
 expect((await menu.getByRole("link").allTextContents()).filter(t=>!t.includes("Sign in")).map(t=>t.trim())).toEqual(["Search","SCWiki","Materials","Reported Tc Timeline","Discovery","About JZIS"]);
 await menu.getByRole("link",{name:"SCWiki",exact:true}).focus();await page.keyboard.press("Escape");await expect(toggle).toBeFocused();
 await page.goto("/docs#search-the-literature");
 await expect(page).toHaveURL(/\/scwiki\/using-sclib#search-the-literature$/);
 await expect(page.locator("h2#search-the-literature")).toBeVisible();
});
test("SCWiki retains docs API/data, redirects canonical paths and returns genuine 404/405 responses",async({request})=>{
 for(const path of ["/docs","/docs/","/sclib/docs","/sclib/docs/"]){
  const response=await request.get(path+"?source=legacy",{maxRedirects:0});expect(response.status()).toBe(308);
  const url=new URL(response.headers().location,"http://localhost:3102");expect(url.pathname).toBe("/scwiki");expect(url.search).toBe("?source=legacy");
 }
 for(const path of ["/docs/api","/docs/data"])expect((await request.get(path)).status()).toBe(200);
 const www=await request.get("/sclib/docs/",{headers:{Host:"www.jzis.org"},maxRedirects:0});expect(www.headers().location).toBe("https://jzis.org/scwiki");
 expect((await request.get("/scwiki/unknown-article")).status()).toBe(404);
 expect((await request.get("/api/scwiki/v1/articles/scwiki-x999")).status()).toBe(404);
 expect((await request.post("/api/scwiki/v1/articles")).status()).toBe(405);
 const sitemap=await (await request.get("/sitemaps/static.xml")).text();
 for(const a of catalogue.articles){expect(sitemap).toContain("/scwiki/"+a.slug);expect(sitemap).toContain(a.modifiedAt);}
 expect(sitemap).toContain("/docs/api");expect(sitemap).toContain("/docs/data");expect(sitemap).not.toContain("<loc>https://jzis.org/docs</loc>");
});

test("homepage research, topic links and search stay usable at mobile, tablet and desktop widths",async({page})=>{
 await page.goto("/scwiki");await page.getByRole("button",{name:"Reject all",exact:true}).click();
 for(const width of [390,768,1440]){
  await page.setViewportSize({width,height:900});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  const search=page.getByRole("button",{name:"Search",exact:true});
  expect(await search.evaluate(button=>{const range=document.createRange();range.selectNodeContents(button);return range.getClientRects().length;})).toBe(1);
  expect(await page.locator('.scwiki-research-item').count()).toBe(3);
  const links=await page.locator('.scwiki-topic-group a').all();
  expect(links.length).toBe(catalogue.articles.length);
  const destinations=await Promise.all(links.map(link=>link.getAttribute('href')));
  expect(destinations.sort()).toEqual(catalogue.articles.map(article=>'/scwiki/'+article.slug).sort());
 }
 await page.locator('.scwiki-topic-group').getByRole('link',{name:'Meissner effect',exact:true}).click();
 await expect(page).toHaveURL(/\/scwiki\/meissner-effect$/);
 await expect(page.getByRole('heading',{level:1})).toContainText('Meissner effect');
});


test("approved question routes preserve provenance and exclude unfinished extension pages",async({page,request})=>{
 const a=catalogue.articles.find((a:{code:string})=>a.code==="N10");
 await page.goto("/scwiki");await page.getByRole("button",{name:"Reject all",exact:true}).click();
 await page.getByRole("searchbox",{name:"Search SCWiki",exact:true}).fill("平带");
 await expect(page.locator(".scwiki-article-grid")).toContainText(a.title);
 const searched=await(await request.get("/api/scwiki/v1/search?q="+encodeURIComponent("平带"))).json();
 expect(searched.results.some((r:{code:string})=>r.code==="N10")).toBe(true);
 await page.getByRole("button",{name:"Clear filters",exact:true}).click();
 await page.getByRole("link",{name:"What limits flat-band Tc?",exact:true}).click();
 await expect(page).toHaveURL(/\/scwiki\/open-questions\/n10$/);
 await expect(page.getByRole("heading",{level:1})).toHaveText(a.title);
 await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href",/\/scwiki\/open-questions\/n10$/);
 await page.getByText("Source and editorial mapping",{exact:true}).click();
 await expect(page.getByText("The pinned planning document identifies the approved scope.",{exact:false})).toBeVisible();
 const response=await request.get("/api/scwiki/v1/articles/scwiki-n10/sections/mathematical-assumptions");
 const data=await response.json();expect(data.scopeItems[0].id).toBe("N10");
 for(const path of [...extensions.pages.filter((p:{publicBody:boolean})=>!p.publicBody).map((p:{slug:string})=>"/scwiki/"+p.slug),"/scwiki/open-questions/n11"]){expect((await request.get(path)).status()).toBe(404);}
});

for(const [code,slug,label] of [["I","experimental-methods","Experimental methods"],["J","theoretical-tools","Theoretical tools"],["K","applications","Superconducting applications"],["L","history","History of superconductivity"],["M","research-methodology","Research methodology"]]) test(code+" handbook keeps all approved section links and scoped API exports usable",async({page,request})=>{
 await page.goto("/scwiki");await page.getByRole("button",{name:"Reject all",exact:true}).click();
 await page.getByRole("link",{name:label,exact:true}).click();
 await expect(page).toHaveURL(new RegExp("/scwiki/"+slug+"$"));
 const a=catalogue.articles.find((a:{code:string})=>a.code===code);
 for(const item of a.scopeItems){
  const id=item.sectionIds[0];
  await page.getByRole('navigation',{name:'Article contents'}).locator('a[href="#'+id+'"]').click();
  await expect(page.locator('h2#'+id)).toBeInViewport();
  expect(await page.locator('h2#'+id).evaluate(e=>e.getBoundingClientRect().top)).toBeGreaterThanOrEqual(64);
  const data=await(await request.get('/api/scwiki/v1/articles/scwiki-'+code.toLowerCase()+'/sections/'+id)).json();
  expect(data.scopeItems.map((i:{id:string})=>i.id)).toEqual([item.id]);
 }
 expect(await page.locator('.katex-error').count()).toBe(0);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});


test("long desktop handbook contents keep the final links reachable within a short viewport",async({page})=>{
 await page.setViewportSize({width:1280,height:720});
 await page.goto("/scwiki/history");
 await page.getByRole("button",{name:"Reject all",exact:true}).click();
 const contents=page.locator(".scwiki-contents");
 for(const [label,id] of [["Chronological guide","chronological-guide"],["Revision and review","revision-and-review"]]){
  await page.getByRole("navigation",{name:"Article contents"}).getByRole("link",{name:label,exact:true}).click();
  await expect(page.locator("h2#"+id)).toBeInViewport();
  const bounds=await contents.evaluate(e=>({top:e.getBoundingClientRect().top,bottom:e.getBoundingClientRect().bottom,scrollTop:e.scrollTop}));
  expect(bounds.top).toBeGreaterThanOrEqual(64);expect(bounds.bottom).toBeLessThanOrEqual(720);
  expect(bounds.scrollTop).toBeGreaterThan(0);
 }
 await page.getByRole("navigation",{name:"Article contents"}).getByRole("link",{name:"Scope",exact:true}).click();
 await expect(page.locator("h2#scope")).toBeInViewport();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(1280);
});

 for(const [code,label,query] of [["N1","Room-temperature superconductivity?","室温常压超导"],["N2","A unified pairing mechanism?","非常规超导统一理论"],["N3","Predicting correlated-material Tc?","强关联Tc预测"],["N4","Establishing Majorana zero modes?","Majorana零模实验证认"],["N5","What causes strange metals?","奇异金属微观起源"],["N6","Is UTe2 spin triplet?","UTe2三重态"],["N7","Nickelate s or d pairing?","镍酸盐配对机制"],["N8","Validating claims like LK-99?","LK99科学验证"],["N9","Does topology imply higher Tc?","拓扑超导与高Tc"]]) test(code+" question is reachable and preserves scoped evidence across formats",async({page,request})=>{
 await page.goto("/scwiki");await page.getByRole("button",{name:"Reject all",exact:true}).click();
 await page.getByRole("link",{name:label,exact:true}).click();
 await expect(page).toHaveURL(new RegExp("/scwiki/open-questions/"+code.toLowerCase()+"$"));
 const a=catalogue.articles.find((a:{code:string})=>a.code===code);
 await expect(page.getByRole("heading",{level:1})).toHaveText(a.title);
 for(const id of a.scopeItems[0].sectionIds){
  await page.getByRole("navigation",{name:"Article contents"}).locator('a[href="#'+id+'"]').click();
  await expect(page.locator('h2#'+id)).toBeInViewport();
  const exported=await(await request.get('/api/scwiki/v1/articles/'+a.id+'/sections/'+id)).json();
  expect(exported.scopeItems[0].id).toBe(code);
 }
 await expect(page.locator('.katex-error')).toHaveCount(0);
 const result=await(await request.get('/api/scwiki/v1/search?q='+encodeURIComponent(query))).json();
 expect(result.results.some((x:{id:string})=>x.id===a.id)).toBe(true);
 const filtered=await(await request.get('/api/scwiki/v1/search?q='+encodeURIComponent(query)+'&tcMin=0.01')).json();
 expect(filtered.results.some((x:{id:string})=>x.id===a.id)).toBe(false);
 });

test("SCWiki API pages, conditional requests and write rejection work through the server",async({request})=>{
 const first=await request.get('/api/scwiki/v1/topics?limit=2');expect(first.status()).toBe(200);
 const data=await first.json();expect(data.topics).toHaveLength(2);expect(data.total).toBe(catalogue.articles.length);
 const second=await request.get(data.page.next);expect(second.status()).toBe(200);
 expect((await second.json()).topics.map((x:{id:string})=>x.id)).not.toEqual(data.topics.map((x:{id:string})=>x.id));
 const unchanged=await request.get('/api/scwiki/v1/topics?limit=2',{headers:{'If-None-Match':first.headers().etag}});
 expect(unchanged.status()).toBe(304);expect(await unchanged.text()).toBe('');
 const changedPage=await request.get(data.page.next,{headers:{'If-None-Match':first.headers().etag}});expect(changedPage.status()).toBe(200);
 const head=await request.head('/api/scwiki/v1/topics?limit=2');expect(head.status()).toBe(200);expect(await head.text()).toBe('');expect(head.headers().etag).toBe(first.headers().etag);
 for(const method of ['POST','PUT','PATCH','DELETE']){
  const response=await request.fetch('/api/scwiki/v1/topics',{method});expect(response.status()).toBe(405);expect(response.headers().allow).toBe('GET, HEAD, OPTIONS');expect((await response.json()).code).toBe('METHOD_NOT_ALLOWED');
 }
 const invalid=await request.get('/api/scwiki/v1/search?q=a&q=b');expect(invalid.status()).toBe(400);expect(invalid.headers()['cache-control']).toBe('no-store');
});

test("Agent guide exposes bounded field selection and complete-snapshot change discovery",async({page,request})=>{
 await page.goto('/scwiki/agent-guide');
 await expect(page.getByRole('heading',{name:'Choose fields',exact:true})).toBeVisible();
 await expect(page.getByRole('heading',{name:'Discover changes',exact:true})).toBeVisible();
 const metadata=await(await request.get('/api/scwiki/v1/articles/scwiki-a4?fields=title')).json();
 expect(metadata.article.review.limitations.length).toBeGreaterThan(0);expect(metadata.article.claims).toBeUndefined();
 const excerpt=await(await request.get('/api/scwiki/v1/articles/scwiki-a4?fields=claims')).json();
 expect(excerpt.article.references.length).toBeGreaterThan(0);expect(excerpt.article.materialCases).toBeDefined();
 const records=[];let url:string|null='/api/scwiki/v1/revisions';let revision:string|undefined;
 while(url){const response=await request.get(url);expect(response.status()).toBe(200);const data=await response.json();revision??=data.revision;expect(data.revision).toBe(revision);records.push(...data.records);url=data.page.next;}
 expect(records.length).toBe(catalogue.articles.length);expect(new Set(records.map(r=>r.id)).size).toBe(records.length);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(await page.evaluate(()=>innerWidth));
});


test("Yang note retains author-version limits and sample table on mobile",async({page,request})=>{
 await page.goto("/scwiki/library/yang-eu-nickelate-reentrance");
 await page.getByRole("button",{name:"Reject all",exact:true}).click();
 await expect(page.locator(".scwiki-sources")).toContainText("Preprint");
 await expect(page.locator(".scwiki-sources")).toContainText("Journal article");
 await expect(page.locator("table")).toContainText("13.04 T");
 await expect(page.locator("#angles-and-version-correction")).toHaveText("Angular behavior and an unresolved inherited number");
 const data=await(await request.get("/api/scwiki/v1/library/yang-eu-nickelate-reentrance")).json();
 await expect(page.locator("main.scwiki")).toHaveAttribute("data-revision",data.note.revision);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
 const bad=await page.locator('main.scwiki a[href^="#"]').evaluateAll(links=>links.map(a=>a.getAttribute("href")!.slice(1)).filter(id=>!document.getElementById(id)));
 expect(bad).toEqual([]);await expect(page.locator(".katex-error")).toHaveCount(0);
 await page.screenshot({path:"test-results/scwiki-yang-390.png",fullPage:true});
});


test("pressure-quench note keeps source versions and specimen conditions readable on mobile",async({page,request})=>{
 await page.goto("/scwiki/library/deng-hg1223-pressure-quench");
 await page.getByRole("button",{name:"Reject all",exact:true}).click();
 await expect(page.locator("table")).toContainText("151 K warming; 150 K cooling");
 await expect(page.locator(".scwiki-sources")).toContainText("2026-03-12");
 await expect(page.locator(".scwiki-sources")).toContainText("2026-03-09");
 await page.getByRole("navigation",{name:"Note contents"}).getByRole("link",{name:"The magnetic estimate belongs to retrieved S2"}).click();
 await expect(page.locator("#magnetic-estimate")).toBeInViewport();
 await expect(page.locator(".katex-error")).toHaveCount(0);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
 const data=await(await request.get("/api/scwiki/v1/library/deng-hg1223-pressure-quench")).json();
 await expect(page.locator("main.scwiki")).toHaveAttribute("data-revision",data.note.revision);
 const bad=await page.locator('main.scwiki a[href^="#"]').evaluateAll(links=>links.map(a=>a.getAttribute("href")!.slice(1)).filter(id=>!document.getElementById(id)));expect(bad).toEqual([]);
 await page.screenshot({path:"test-results/scwiki-deng-390.png",fullPage:false});
});


test("interface note distinguishes partial provenance and abstract-only review",async({page,request})=>{
 await page.goto("/scwiki/library/cuprate-interface-layer-order");await page.getByRole("button",{name:"Reject all",exact:true}).click();
 await expect(page.locator(".scwiki-scope-note")).toContainText("Two of ten studies");
 await expect(page.locator(".scwiki-scope-note")).toContainText("partial source-note merge");
 await page.getByText("Source-note provenance",{exact:true}).click();
 await expect(page.locator("details")).toContainText("partial-merge");await expect(page.locator("details")).toContainText("other seven study sections remain pending");
 const data=await(await request.get("/api/scwiki/v1/library/cuprate-interface-layer-order")).json();await expect(page.locator("main.scwiki")).toHaveAttribute("data-revision",data.note.revision);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
 const bad=await page.locator('main.scwiki a[href^="#"]').evaluateAll(links=>links.map(a=>a.getAttribute("href")!.slice(1)).filter(id=>!document.getElementById(id)));expect(bad).toEqual([]);
 await page.getByRole("navigation",{name:"Note contents"}).getByRole("link",{name:"Read layer order and criterion together"}).click();await expect(page.locator("#layer-order")).toBeInViewport();
 await page.screenshot({path:"test-results/scwiki-interface-390.png",fullPage:false});
});


test("THz note keeps angular and cyclic rates readable with source and partial coverage",async({page,request})=>{
 await page.goto("/scwiki/library/bilbro-thz-fluctuation-window");await page.getByRole("button",{name:"Reject all",exact:true}).click();
 await expect(page.locator(".scwiki-scope-note")).toContainText("three of ten");
 await expect(page.locator(".scwiki-sources")).toContainText("Author version deposited");
 await page.getByRole("navigation",{name:"Note contents"}).getByRole("link",{name:"Keep the rate convention and scale uncertainty"}).click();
 await expect(page.locator("#rate-normalization")).toBeInViewport();await expect(page.locator("main.scwiki")).toContainText("roughly 40% spread");await expect(page.locator(".katex-error")).toHaveCount(0);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
 const data=await(await request.get("/api/scwiki/v1/library/bilbro-thz-fluctuation-window")).json();await expect(page.locator("main.scwiki")).toHaveAttribute("data-revision",data.note.revision);
 const bad=await page.locator('main.scwiki a[href^="#"]').evaluateAll(links=>links.map(a=>a.getAttribute("href")!.slice(1)).filter(id=>!document.getElementById(id)));expect(bad).toEqual([]);
 await page.screenshot({path:"test-results/scwiki-bilbro-390.png",fullPage:false});
});
