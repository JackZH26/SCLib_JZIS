import { listSitemapResources } from "@/lib/api";
import {
  SITEMAP_PAGE_SIZE,
  SITE_BASE_URL,
  sitemapIndexXml,
  xmlResponse,
} from "@/lib/seo";

export const revalidate = 3600;

async function pageCount(kind: "paper" | "material"): Promise<number> {
  try {
    const page = await listSitemapResources(kind, 1, 0);
    return Math.ceil(page.total / SITEMAP_PAGE_SIZE);
  } catch {
    // Keep the static sitemap discoverable during a transient API outage.
    return 0;
  }
}

export async function GET(): Promise<Response> {
  const [paperPages, materialPages] = await Promise.all([
    pageCount("paper"),
    pageCount("material"),
  ]);
  const locations = [`${SITE_BASE_URL}/sitemaps/static.xml`];

  for (let page = 0; page < paperPages; page += 1) {
    locations.push(`${SITE_BASE_URL}/sitemaps/paper/${page}.xml`);
  }
  for (let page = 0; page < materialPages; page += 1) {
    locations.push(`${SITE_BASE_URL}/sitemaps/material/${page}.xml`);
  }

  return xmlResponse(sitemapIndexXml(locations));
}
