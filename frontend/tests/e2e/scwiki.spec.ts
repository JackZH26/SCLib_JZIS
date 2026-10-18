import {expect,test} from "./public-site-fixture";
import {readFileSync} from "node:fs";
const catalogue=JSON.parse(readFileSync("content/scwiki/catalogue.json","utf8"));
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
 for(const path of ["/scwiki/open-questions/n1","/scwiki/open-questions/n11","/scwiki/research-methodology"]){expect((await request.get(path)).status()).toBe(404);}
});

for(const [code,slug,label] of [["I","experimental-methods","Experimental methods"],["J","theoretical-tools","Theoretical tools"],["K","applications","Superconducting applications"],["L","history","History of superconductivity"]]) test(code+" handbook keeps all approved section links and scoped API exports usable",async({page,request})=>{
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
