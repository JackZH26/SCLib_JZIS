import { listSitemapResources, type SitemapResourceKind } from "@/lib/api";
import {
  SITEMAP_PAGE_SIZE,
  absoluteUrl,
  sitemapXml,
  xmlResponse,
} from "@/lib/seo";

export const revalidate = 3600;

function parseRoute(
  kind: string,
  pageWithExtension: string,
): { kind: SitemapResourceKind; page: number } | null {
  if (kind !== "paper" && kind !== "material") return null;
  if (!/^\d+\.xml$/.test(pageWithExtension)) return null;
  const page = Number(pageWithExtension.slice(0, -4));
  if (!Number.isSafeInteger(page) || page < 0) return null;
  return { kind, page };
}

export async function GET(
  _request: Request,
  context: { params: Promise<{ kind: string; page: string }> },
): Promise<Response> {
  const params = await context.params;
  const route = parseRoute(params.kind, params.page);
  if (!route) return new Response("Not found", { status: 404 });

  const offset = route.page * SITEMAP_PAGE_SIZE;
  const inventory = await listSitemapResources(
    route.kind,
    SITEMAP_PAGE_SIZE,
    offset,
  );
  if (offset >= inventory.total && inventory.total !== 0) {
    return new Response("Not found", { status: 404 });
  }

  return xmlResponse(
    sitemapXml(
      inventory.results.map((resource) => ({
        loc:
          resource.kind === "paper"
            ? absoluteUrl(`/paper/${encodeURIComponent(resource.id)}`)
            : absoluteUrl(`/materials/${encodeURIComponent(resource.id)}`),
        lastModified: resource.updated_at,
        changeFrequency: "monthly",
        priority: resource.kind === "paper" ? 0.7 : 0.6,
      })),
    ),
  );
}
