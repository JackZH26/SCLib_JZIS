/**
 * Sortable materials table for /materials. Stateless — the page
 * owns the sort / filter state and re-fetches on change. Keeping
 * this component passive makes SSR trivial.
 */
import Link from "next/link";
import type { MaterialSummary } from "@/lib/api";

export function MaterialTable({ rows }: { rows: MaterialSummary[] }) {
  if (rows.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">
        No materials match these filters.
      </div>
    );
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-4 py-3 text-left font-medium">Formula</th>
            <th className="px-4 py-3 text-left font-medium">Family</th>
            <th className="px-4 py-3 text-right font-medium">Tc max (K)</th>
            <th className="px-4 py-3 text-right font-medium">Discovery</th>
            <th className="px-4 py-3 text-right font-medium">Papers</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((m) => (
            <tr key={m.id} className="hover:bg-slate-50">
              <td className="px-4 py-3">
                <Link
                  href={`/materials/${encodeURIComponent(m.id)}`}
                  className="font-medium text-slate-900 hover:underline"
                >
                  {m.formula}
                </Link>
              </td>
              <td className="px-4 py-3 text-slate-600">{m.family ?? "—"}</td>
              <td className="px-4 py-3 text-right tabular-nums text-slate-800">
                {m.tc_max != null ? m.tc_max.toFixed(1) : "—"}
              </td>
              <td className="px-4 py-3 text-right tabular-nums text-slate-600">
                {m.discovery_year ?? "—"}
              </td>
              <td className="px-4 py-3 text-right tabular-nums text-slate-600">
                {m.total_papers}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
