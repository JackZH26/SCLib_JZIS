/**
 * /paper/[id] — paper detail page.
 *
 * Paper IDs look like `arxiv:2306.07275`. Next catches the colon in
 * a single dynamic segment, but we still decodeURIComponent to be
 * safe when the client encodes it. The "similar papers" section is
 * rendered as a child server fetch so it can cache independently.
 */
import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError, getPaper, getSimilar } from "@/lib/api";
import { BookmarkButton } from "@/components/BookmarkButton";
import { PaperCard } from "@/components/PaperCard";

export default async function PaperDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const id = decodeURIComponent(params.id);
  let paper;
  try {
    paper = await getPaper(id);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }

  const similar = await getSimilar(id, 6).catch(() => null);

  return (
    <main className="space-y-8">
      <div>
        <Link href="/search" className="text-sm text-slate-500 hover:underline">
          ← Back to search
        </Link>
        <div className="mt-2 flex items-start justify-between gap-4">
          <h1 className="text-3xl font-bold leading-tight tracking-tight">
            {paper.title}
          </h1>
          <div className="shrink-0 pt-1">
            <BookmarkButton targetType="paper" targetId={paper.id} />
          </div>
        </div>
        <p className="mt-2 text-sm text-slate-600">
          {paper.authors.join(", ")}
        </p>
        <p className="mt-1 text-xs text-slate-500">
          {[
            paper.arxiv_id && `arXiv:${paper.arxiv_id}`,
            paper.doi && `DOI ${paper.doi}`,
            paper.date_submitted,
            paper.journal,
            paper.material_family,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          {paper.credibility_tier && (
            <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
              paper.credibility_tier === "T1" ? "bg-emerald-50 text-emerald-700 border border-emerald-200" :
              paper.credibility_tier === "T2" ? "bg-blue-50 text-blue-700 border border-blue-200" :
              paper.credibility_tier === "T3" ? "bg-amber-50 text-amber-700 border border-amber-200" :
              paper.credibility_tier === "T4" ? "bg-orange-50 text-orange-700 border border-orange-200" :
              "bg-red-50 text-red-700 border border-red-200"
            }`}>
              {paper.credibility_tier}
            </span>
          )}
          {paper.paper_type && (
            <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 border border-slate-200">
              {paper.paper_type}
            </span>
          )}
          {paper.citation_count > 0 && (
            <span className="inline-flex items-center rounded-full bg-slate-50 px-2 py-0.5 text-xs text-slate-500 border border-slate-200">
              {paper.citation_count} citations
            </span>
          )}
        </div>
      </div>

      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Abstract
        </h2>
        <p className="whitespace-pre-line rounded-lg border border-slate-200 bg-white p-5 text-sm leading-relaxed text-slate-800">
          {paper.abstract}
        </p>
      </section>

      {paper.materials_extracted.length > 0 && (
        <section>
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Extracted materials
          </h2>
          <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-3 text-left font-medium">Formula</th>
                  <th className="px-4 py-3 text-right font-medium">Tc (K)</th>
                  <th className="px-4 py-3 text-right font-medium">
                    Pressure (GPa)
                  </th>
                  <th className="px-4 py-3 text-left font-medium">Type</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {paper.materials_extracted.map((m, i) => (
                  <tr key={i} className="hover:bg-slate-50">
                    <td className="px-4 py-3 font-medium text-slate-900">
                      {m.formula ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {m.tc_kelvin ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-slate-600">
                      {m.pressure_gpa ?? "ambient"}
                    </td>
                    <td className="px-4 py-3 text-slate-600">
                      {m.tc_type ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {similar && similar.results.length > 0 && (
        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Similar papers
          </h2>
          <div className="grid gap-3 md:grid-cols-2">
            {similar.results.map((s) => (
              <PaperCard
                key={s.paper_id}
                paper_id={s.paper_id}
                arxiv_id={s.arxiv_id}
                title={s.title}
                authors={s.authors}
                year={s.year}
                score={s.similarity}
                scoreLabel="similarity"
              />
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
