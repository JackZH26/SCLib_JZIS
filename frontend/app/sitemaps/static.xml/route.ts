import {researchCollection} from "@/lib/scwiki/research";
import {libraryNotes} from "@/lib/scwiki/library";
import { articles } from "@/lib/scwiki/catalogue";
import { absoluteUrl, sitemapXml, xmlResponse } from "@/lib/seo";

export const dynamic = "force-dynamic";

export function GET(): Response {
  let editions:ReturnType<typeof researchCollection>["issues"]=[];
  try{editions=researchCollection().issues;}catch{}
  return xmlResponse(
    sitemapXml([
      { loc: absoluteUrl("/"), changeFrequency: "daily", priority: 1 },
      { loc: absoluteUrl("/materials"), changeFrequency: "daily", priority: 0.9 },
      { loc: absoluteUrl("/timeline"), changeFrequency: "daily", priority: 0.8 },
      { loc: absoluteUrl("/discovery"), changeFrequency: "daily", priority: 0.8 },
      { loc: absoluteUrl("/stats"), changeFrequency: "daily", priority: 0.7 },
      { loc: absoluteUrl("/about"), changeFrequency: "monthly", priority: 0.6 },
      { loc: absoluteUrl("/about/join"), changeFrequency: "monthly", priority: 0.6 },
      { loc: absoluteUrl("/research"), changeFrequency: "monthly", priority: 0.6 },
      { loc: absoluteUrl("/scwiki"), lastModified: articles().map(a => a.modifiedAt).sort().at(-1), changeFrequency: "monthly", priority: 0.7 },
      { loc: absoluteUrl("/scwiki/using-sclib"), changeFrequency: "monthly", priority: 0.6 },
      { loc: absoluteUrl("/scwiki/agent-guide"), changeFrequency: "monthly", priority: 0.5 },
      {loc:absoluteUrl("/scwiki/library"),changeFrequency:"weekly",priority:0.6},
      {loc:absoluteUrl("/scwiki/research"),changeFrequency:"weekly",priority:0.7},
      ...editions.map(i=>({loc:absoluteUrl("/scwiki/research/"+i.id),lastModified:i.selectedAt,changeFrequency:"weekly" as const,priority:0.6})),
      ...libraryNotes.map(n=>({loc:absoluteUrl("/scwiki/library/"+n.id),lastModified:n.modifiedAt,changeFrequency:"monthly" as const,priority:0.6})),
      ...articles().map(a => ({ loc: absoluteUrl("/scwiki/" + a.slug), lastModified: a.modifiedAt, changeFrequency: "monthly" as const, priority: 0.6 })),
      { loc: absoluteUrl("/docs/data"), changeFrequency: "monthly", priority: 0.6 },
      { loc: absoluteUrl("/docs/api"), changeFrequency: "monthly", priority: 0.6 },
      { loc: absoluteUrl("/cookies"), changeFrequency: "yearly", priority: 0.3 },
      { loc: absoluteUrl("/privacy"), changeFrequency: "yearly", priority: 0.3 },
      { loc: absoluteUrl("/terms"), changeFrequency: "yearly", priority: 0.3 },
    ]),
  );
}
