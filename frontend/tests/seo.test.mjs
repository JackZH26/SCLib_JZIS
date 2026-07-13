import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function source(path) {
  return readFile(path, "utf8");
}

test("sitemap inventory is paginated and produces canonical encoded URLs", async () => {
  const [api, indexRoute, resourceRoute, staticRoute] = await Promise.all([
    source("lib/api.ts"),
    source("app/sitemap.xml/route.ts"),
    source("app/sitemaps/[kind]/[page]/route.ts"),
    source("app/sitemaps/static.xml/route.ts"),
  ]);

  assert.match(api, /\/sitemap\/resources\?/);
  assert.match(api, /next: \{ revalidate: 3600 \}/);
  assert.match(indexRoute, /SITEMAP_PAGE_SIZE/);
  assert.match(indexRoute, /sitemaps\/static\.xml/);
  assert.match(resourceRoute, /encodeURIComponent\(resource\.id\)/);
  assert.match(resourceRoute, /offset >= inventory\.total/);
  assert.match(staticRoute, /absoluteUrl\("\/materials"\)/);
});

test("robots, canonical metadata, and structured research data are present", async () => {
  const [robots, layout, paper, material, deployment] = await Promise.all([
    source("app/robots.ts"),
    source("app/layout.tsx"),
    source("app/paper/[id]/page.tsx"),
    source("app/materials/[id]/page.tsx"),
    source("../docs/DEPLOYMENT.md"),
  ]);

  assert.match(robots, /SITE_BASE_URL.*sitemap\.xml/);
  assert.match(robots, /"\/sclib\/dashboard\/"/);
  assert.match(layout, /metadataBase: new URL\(SITE_ORIGIN\)/);
  assert.match(layout, /"@type": \["WebSite", "Dataset"\]/);
  assert.match(paper, /generateMetadata/);
  assert.match(paper, /"@type": "ScholarlyArticle"/);
  assert.match(paper, /citation_title/);
  assert.match(material, /generateMetadata/);
  assert.match(material, /"@type": "Dataset"/);
  assert.match(deployment, /Sitemap: https:\/\/jzis\.org\/sclib\/sitemap\.xml/);
  assert.match(deployment, /Do not[\s\S]*replace or proxy the root file/);
});
