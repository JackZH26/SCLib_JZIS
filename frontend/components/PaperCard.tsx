/**
 * Compact card for a search hit or similar-paper suggestion.
 *
 * Accepts the slim shape shared by /search and /similar — full
 * chunk/material data stays on the list page so this component
 * can be reused across routes.
 */
import Link from "next/link";

export interface PaperCardInput {
  paper_id: string;
  arxiv_id: string | null;
  title: string;
  authors: string[];
  year: number | null;
  snippet?: string;
  section?: string | null;
  score?: number | null;
  scoreLabel?: string;
  badges?: string[];
}

export function PaperCard(p: PaperCardInput) {
  const authors = formatAuthors(p.authors);
  return (
    <Link
      href={`/paper/${encodeURIComponent(p.paper_id)}`}
      className="block rounded-lg border border-slate-200 bg-white p-5 shadow-sm transition hover:border-slate-400 hover:shadow"
    >
      <div className="flex items-start justify-between gap-4">
        <h3 className="text-base font-semibold leading-snug text-slate-900">
          {p.title}
        </h3>
        {p.score != null && (
          <span className="shrink-0 rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
            {p.scoreLabel ?? "score"} {p.score.toFixed(2)}
          </span>
        )}
      </div>
      <p className="mt-1 text-sm text-slate-600">
        {authors}
        {p.year && <span className="text-slate-400"> · {p.year}</span>}
        {p.arxiv_id && (
          <span className="text-slate-400"> · arXiv:{p.arxiv_id}</span>
        )}
      </p>
      {p.snippet && (
        <p className="mt-3 line-clamp-3 text-sm text-slate-700">
          {p.section && (
            <span className="mr-1 font-medium text-slate-500">
              {p.section}:
            </span>
          )}
          {p.snippet}
        </p>
      )}
      {p.badges && p.badges.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {p.badges.map((b) => (
            <span
              key={b}
              className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600"
            >
              {b}
            </span>
          ))}
        </div>
      )}
    </Link>
  );
}

function formatAuthors(authors: string[]): string {
  if (authors.length === 0) return "Unknown";
  if (authors.length === 1) return authors[0];
  if (authors.length === 2) return `${authors[0]} & ${authors[1]}`;
  return `${authors[0]} et al.`;
}
