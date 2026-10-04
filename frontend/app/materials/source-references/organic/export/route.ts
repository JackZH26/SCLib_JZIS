import { createHash } from "node:crypto";
import { organicExport, type OrganicParams } from "@/lib/mdr-organic";

export function GET(request: Request): Response {
  const search = new URL(request.url).searchParams;
  const params: OrganicParams = Object.create(null);
  for (const key of search.keys()) { const values = search.getAll(key); params[key] = values.length === 1 ? values[0] : values; }
  try {
    const payload = organicExport(params);
    const hash = createHash("sha256").update(payload).digest("hex");
    return new Response(payload, { headers: { "Content-Type": "application/json; charset=utf-8", "Content-Disposition": `attachment; filename="sclib-mdr-organic-${hash.slice(0, 12)}.json"`, "X-Content-SHA256": hash, "Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff" } });
  } catch {
    return Response.json({ error: "Invalid Organic source filters. Clear the filters and try again." }, { status: 400 });
  }
}
