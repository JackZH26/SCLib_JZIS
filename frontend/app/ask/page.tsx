"use client";

/**
 * /ask — RAG Q&A page. Submit a question, Gemini answers with
 * [n]-cited markdown, sidebar lists the source chunks.
 */
import { useState, type FormEvent } from "react";
import { ask, friendlyErrorMessage, type AskResponse } from "@/lib/api";
import { MarkdownAnswer } from "@/components/MarkdownAnswer";
import { GuestBanner } from "@/components/GuestBanner";

export default function AskPage() {
  const [q, setQ] = useState("");
  const [data, setData] = useState<AskResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (q.trim().length < 3) return;
    setLoading(true);
    setErr(null);
    setData(null);
    const apiKey =
      typeof window !== "undefined"
        ? localStorage.getItem("sclib_api_key") ?? undefined
        : undefined;
    try {
      const r = await ask({ question: q.trim(), max_sources: 8 }, { apiKey });
      setData(r);
    } catch (e: unknown) {
      setErr(friendlyErrorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Ask SCLib</h1>
        <p className="mt-1 text-sm text-slate-600">
          Gemini answers with inline [n] citations grounded in indexed arXiv
          chunks. Each [n] links to the source.
        </p>
      </div>

      <form onSubmit={submit} className="space-y-3">
        <textarea
          value={q}
          onChange={(e) => setQ(e.target.value)}
          rows={3}
          placeholder="e.g. What pairing symmetries have been proposed for iron-based superconductors?"
          className="w-full rounded-md border border-slate-300 bg-white p-3 text-base focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
        />
        <button
          type="submit"
          disabled={loading || q.trim().length < 3}
          className="rounded-md bg-slate-900 px-5 py-2 font-medium text-white hover:bg-slate-700 disabled:bg-slate-400"
        >
          {loading ? "Thinking…" : "Ask"}
        </button>
      </form>

      {data?.guest_remaining != null && (
        <GuestBanner remaining={data.guest_remaining} />
      )}

      {err && (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {err}
        </div>
      )}

      {data && (
        <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
          <article className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
            <MarkdownAnswer markdown={data.answer} sources={data.sources} />
            <div className="mt-4 text-xs text-slate-400">
              {data.query_time_ms} ms · {data.tokens_used ?? "—"} tokens
            </div>
          </article>
          <aside className="space-y-3">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Sources
            </h2>
            {data.sources.map((s) => (
              <div
                key={s.index}
                id={`src-${s.index}`}
                className="rounded-md border border-slate-200 bg-white p-3 text-sm"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-semibold text-slate-700">
                    [{s.index}]
                  </span>
                  {s.year && (
                    <span className="text-xs text-slate-400">{s.year}</span>
                  )}
                </div>
                <a
                  href={`/paper/${encodeURIComponent(s.paper_id)}`}
                  className="block text-sm font-medium text-slate-900 hover:underline"
                >
                  {s.title}
                </a>
                <p className="mt-0.5 text-xs text-slate-500">
                  {s.authors_short}
                  {s.section && ` · ${s.section}`}
                </p>
                <p className="mt-2 line-clamp-4 text-xs text-slate-600">
                  {s.snippet}
                </p>
              </div>
            ))}
          </aside>
        </div>
      )}
    </main>
  );
}
