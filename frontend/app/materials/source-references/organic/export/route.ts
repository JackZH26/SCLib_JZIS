import { createHash } from "node:crypto";
import { organicExport, type OrganicParams } from "@/lib/mdr-organic";

export function GET(request: Request): Response {
  const search = new URL(request.url).searchParams;
  try {
    const keys = ["q", "structure", "field", "row", "page"] as const;
    if (Array.from(search.keys()).some(key => !keys.some(allowed => allowed === key))) {
      throw new Error("Unknown Organic source filter.");
    }
    const params: OrganicParams = {};
    for (const key of keys) {
      const values = search.getAll(key);
      if (values.length) params[key] = values.length === 1 ? values[0] : values;
    }
    const payload = organicExport(params);
    const hash = createHash("sha256").update(payload).digest("hex");
    return new Response(payload, { headers: { "Content-Type": "application/json; charset=utf-8", "Content-Disposition": `attachment; filename="sclib-mdr-organic-${hash.slice(0, 12)}.json"`, "X-Content-SHA256": hash, "Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff" } });
  } catch {
    return Response.json({ error: "Invalid Organic source filters. Clear the filters and try again." }, { status: 400 });
  }
}
