"use client";

import { useMemo, useState } from "react";
import type { StatsResponse } from "@/lib/api";

type SourceTab = "arxiv" | "aps";

function toYearRows(byYear: Record<string, number>) {
  return Object.entries(byYear)
    .map(([year, count]) => ({ year, count }))
    .sort((a, b) => a.year.localeCompare(b.year));
}

export function PapersByYearTabs({ stats }: { stats: StatsResponse }) {
  const [tab, setTab] = useState<SourceTab>("arxiv");
  const years = useMemo(
    () =>
      toYearRows(
        tab === "arxiv" ? stats.papers_by_year_arxiv : stats.papers_by_year_aps,
      ),
    [stats.papers_by_year_arxiv, stats.papers_by_year_aps, tab],
  );
  const maxYearCount = Math.max(1, ...years.map((y) => y.count));

  return (
    <section>
      <div className="mb-3 flex items-center justify-between gap-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Papers by year
        </h2>
        <div className="inline-flex rounded-lg border border-slate-200 bg-white p-1">
          <button
            type="button"
            onClick={() => setTab("arxiv")}
            className={
              tab === "arxiv"
                ? "rounded-md bg-slate-800 px-3 py-1.5 text-xs font-medium text-white"
                : "rounded-md px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100"
            }
          >
            arXiv
          </button>
          <button
            type="button"
            onClick={() => setTab("aps")}
            className={
              tab === "aps"
                ? "rounded-md bg-slate-800 px-3 py-1.5 text-xs font-medium text-white"
                : "rounded-md px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100"
            }
          >
            APS
          </button>
        </div>
      </div>

      <div className="space-y-1 rounded-lg border border-slate-200 bg-white p-4">
        {years.length === 0 ? (
          <div className="text-xs text-slate-500">No papers available for this source.</div>
        ) : (
          years.map((y) => (
            <div key={y.year} className="flex items-center gap-3 text-xs">
              <span className="w-12 shrink-0 text-slate-500">{y.year}</span>
              <div className="h-4 flex-1 rounded bg-slate-100">
                <div
                  className="h-full rounded bg-slate-700"
                  style={{ width: `${(y.count / maxYearCount) * 100}%` }}
                />
              </div>
              <span className="w-10 shrink-0 text-right tabular-nums text-slate-600">
                {y.count}
              </span>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
