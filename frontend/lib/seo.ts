export const SITE_ORIGIN = "https://jzis.org";
export const SITE_BASE_URL = `${SITE_ORIGIN}/sclib`;
export const SITEMAP_PAGE_SIZE = 10_000;

export interface SitemapUrl {
  loc: string;
  lastModified?: string;
  changeFrequency?:
    | "always"
    | "hourly"
    | "daily"
    | "weekly"
    | "monthly"
    | "yearly"
    | "never";
  priority?: number;
}

export function absoluteUrl(path = ""): string {
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return `${SITE_BASE_URL}${suffix === "/" ? "/" : suffix}`;
}

function xmlEscape(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

export function sitemapXml(urls: SitemapUrl[]): string {
  const entries = urls
    .map(
      ({ loc, lastModified, changeFrequency, priority }) =>
        [
          "  <url>",
          `    <loc>${xmlEscape(loc)}</loc>`,
          lastModified
            ? `    <lastmod>${xmlEscape(lastModified)}</lastmod>`
            : null,
          changeFrequency
            ? `    <changefreq>${changeFrequency}</changefreq>`
            : null,
          priority != null ? `    <priority>${priority.toFixed(1)}</priority>` : null,
          "  </url>",
        ]
          .filter(Boolean)
          .join("\n"),
    )
    .join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${entries}\n</urlset>\n`;
}

export function sitemapIndexXml(locations: string[]): string {
  const entries = locations
    .map((loc) => `  <sitemap>\n    <loc>${xmlEscape(loc)}</loc>\n  </sitemap>`)
    .join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${entries}\n</sitemapindex>\n`;
}

export function xmlResponse(body: string): Response {
  return new Response(body, {
    headers: {
      "Cache-Control": "public, max-age=300, s-maxage=3600",
      "Content-Type": "application/xml; charset=utf-8",
    },
  });
}

/** Serialize JSON-LD without allowing a literal closing script tag. */
export function serializeJsonLd(value: unknown): string {
  return JSON.stringify(value).replaceAll("<", "\\u003c");
}
