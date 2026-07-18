/**
 * /stats — public dashboard. Re-uses StatsCards from the landing
 * page and adds a "papers by year" bar list and the top-10 material
 * families.
 */
import type { Metadata } from "next";
import { getStats } from "@/lib/api";
import { StatsCards } from "@/components/StatsCards";
import { PapersByYearTabs } from "@/components/PapersByYearTabs";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Library statistics",
  description:
    "View SCLib paper, material, literature coverage, data snapshot, and ingestion-pipeline statistics.",
  alternates: { canonical: absoluteUrl("/stats") },
  openGraph: { url: absoluteUrl("/stats") },
};

function formatUtc(value: string | null | undefined) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(date)} UTC`;
}

function statusClass(status: string) {
  if (status === "complete") return "border-emerald-200 bg-emerald-50 text-emerald-800";
  if (status === "partial") return "border-amber-200 bg-amber-50 text-amber-800";
  if (status === "failed") return "border-red-200 bg-red-50 text-red-800";
  return "border-slate-200 bg-slate-50 text-slate-700";
}

export default async function StatsPage() {
  const stats = await getStats().catch(() => null);
  if (!stats) {
    return <p className="text-sm text-red-600">Failed to load stats.</p>;
  }
  const statsRefreshedAt = stats.stats_refreshed_at ?? stats.updated_at;
  const pipeline = stats.data_pipeline ?? {
    status: "unknown" as const,
    last_run_at: null,
    stages: {},
  };
  const stageOrder = ["incremental", "retry", "aggregate"];

  return (
    <main className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Library statistics</h1>
        <p className="mt-1 text-sm text-slate-600">
          Statistics refreshed {formatUtc(statsRefreshedAt)}. Data snapshot and
          pipeline state are reported separately below.
        </p>
      </div>

      <section className="grid gap-4 md:grid-cols-3" aria-label="Statistics and data status">
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Statistics snapshot
          </p>
          <p className="mt-2 font-medium text-slate-900">{formatUtc(statsRefreshedAt)}</p>
          <p className="mt-1 text-xs text-slate-500">When dashboard aggregates were recomputed</p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Data snapshot
          </p>
          <p className="mt-2 font-medium text-slate-900">{formatUtc(stats.last_ingest_at)}</p>
          <p className="mt-1 text-xs text-slate-500">
            Latest indexed paper{stats.dataset_version ? ` · ${stats.dataset_version}` : ""}
          </p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Data pipeline
            </p>
            <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold capitalize ${statusClass(pipeline.status)}`}>
              {pipeline.status}
            </span>
          </div>
          <p className="mt-2 font-medium text-slate-900">{formatUtc(pipeline.last_run_at)}</p>
          <p className="mt-1 text-xs text-slate-500">Most recently reported cron run</p>
        </div>
      </section>

      {Object.keys(pipeline.stages).length > 0 && (
        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            Pipeline stages
          </h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            {stageOrder.map((name) => {
              const stage = pipeline.stages[name];
              if (!stage) return null;
              return (
                <div key={name} className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-sm">
                  <span className="font-medium capitalize text-slate-800">{name}</span>
                  <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold capitalize ${statusClass(stage.status)}`}>
                    {stage.status}
                    {stage.exit_code == null ? "" : ` · ${stage.exit_code}`}
                  </span>
                </div>
              );
            })}
          </div>
        </section>
      )}

      <StatsCards stats={stats} />
      <PapersByYearTabs stats={stats} />

      {stats.top_material_families.length > 0 && (
        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Top material families
          </h2>
          <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-2 text-left font-medium">Family</th>
                  <th className="px-4 py-2 text-right font-medium">Papers</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {stats.top_material_families.map((f) => (
                  <tr key={f.family}>
                    <td className="px-4 py-2">{f.family}</td>
                    <td className="px-4 py-2 text-right tabular-nums">
                      {f.count}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </main>
  );
}
