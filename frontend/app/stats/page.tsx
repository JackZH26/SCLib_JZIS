/**
 * /stats — public dashboard. Re-uses StatsCards from the landing
 * page and adds a "papers by year" bar list and the top-10 material
 * families.
 */
import { getStats } from "@/lib/api";
import { StatsCards } from "@/components/StatsCards";

export default async function StatsPage() {
  const stats = await getStats().catch(() => null);
  if (!stats) {
    return <p className="text-sm text-red-600">Failed to load stats.</p>;
  }

  const years = Object.entries(stats.papers_by_year)
    .map(([y, n]) => ({ year: y, count: n }))
    .sort((a, b) => a.year.localeCompare(b.year));
  const maxYearCount = Math.max(1, ...years.map((y) => y.count));

  return (
    <main className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Library statistics</h1>
        <p className="mt-1 text-sm text-slate-600">
          Last updated {new Date(stats.updated_at).toLocaleString()}
        </p>
      </div>

      <StatsCards stats={stats} />

      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Papers by year
        </h2>
        <div className="space-y-1 rounded-lg border border-slate-200 bg-white p-4">
          {years.map((y) => (
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
          ))}
        </div>
      </section>

      {stats.top_material_families.length > 0 && (
        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Top material families
          </h2>
          <div className="rounded-lg border border-slate-200 bg-white">
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
