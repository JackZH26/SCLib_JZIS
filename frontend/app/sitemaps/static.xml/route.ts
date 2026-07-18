import { absoluteUrl, sitemapXml, xmlResponse } from "@/lib/seo";

export const revalidate = 3600;

export function GET(): Response {
  return xmlResponse(
    sitemapXml([
      { loc: absoluteUrl("/"), changeFrequency: "daily", priority: 1 },
      { loc: absoluteUrl("/materials"), changeFrequency: "daily", priority: 0.9 },
      { loc: absoluteUrl("/timeline"), changeFrequency: "daily", priority: 0.8 },
      { loc: absoluteUrl("/discovery"), changeFrequency: "daily", priority: 0.8 },
      { loc: absoluteUrl("/stats"), changeFrequency: "daily", priority: 0.7 },
      { loc: absoluteUrl("/docs/api"), changeFrequency: "monthly", priority: 0.6 },
      { loc: absoluteUrl("/search"), changeFrequency: "weekly", priority: 0.6 },
      { loc: absoluteUrl("/cookies"), changeFrequency: "yearly", priority: 0.3 },
      { loc: absoluteUrl("/privacy"), changeFrequency: "yearly", priority: 0.3 },
      { loc: absoluteUrl("/terms"), changeFrequency: "yearly", priority: 0.3 },
    ]),
  );
}
