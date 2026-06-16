/**
 * /stats — public dashboard. Re-uses StatsCards from the landing
 * page and adds a "papers by year" bar list and the top-10 material
 * families.
 */
import { getStats } from "@/lib/api";
import { StatsCards } from "@/components/StatsCards";
import { PapersByYearTabs } from "@/components/PapersByYearTabs";

export default async function StatsPage() {
  const stats = await getStats().catch(() => null);
  if (!stats) {
    return <p className="text-sm text-red-600">Failed to load stats.</p>;
  }

  return (
    <main className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Library statistics</h1>
        <p className="mt-1 text-sm text-slate-600">
          Last updated {new Date(stats.updated_at).toLocaleString()}
        </p>
      </div>

      <StatsCards stats={stats} />
      <PapersByYearTabs stats={stats} />

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
