/**
 * Sortable materials table for /materials. Stateless — the page
 * owns the sort / filter state and re-fetches on change. Keeping
 * this component passive makes SSR trivial.
 *
 * v2 columns surface the most-scanned superconductor properties
 * (ambient-pressure flag, pairing symmetry, structure phase) so
 * operators can eyeball-filter the table without clicking through
 * to each material.
 */
import Link from "next/link";
import type { MaterialSummary } from "@/lib/api";

function Badge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "accent" | "warn" | "muted";
}) {
  const palette: Record<string, string> = {
    neutral:
      "bg-slate-100 text-slate-700 border border-slate-200",
    accent:
      "bg-[rgba(58,125,92,0.08)] text-accent-deep border border-sage-border",
    warn:
      "bg-amber-50 text-amber-800 border border-amber-200",
    muted:
      "bg-slate-50 text-slate-500 border border-slate-200",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${palette[tone]}`}
    >
      {children}
    </span>
  );
}

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
            <th className="px-4 py-3 text-right font-medium">Tc ambient</th>
            <th className="px-4 py-3 text-left font-medium">Pairing</th>
            <th className="px-4 py-3 text-left font-medium">Phase</th>
            <th className="px-4 py-3 text-left font-medium">Flags</th>
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
                {m.tc_ambient != null ? m.tc_ambient.toFixed(1) : "—"}
              </td>
              <td className="px-4 py-3">
                {m.pairing_symmetry ? (
                  <Badge tone="accent">{m.pairing_symmetry}</Badge>
                ) : (
                  <span className="text-slate-400">—</span>
                )}
              </td>
              <td className="px-4 py-3">
                {m.structure_phase ? (
                  <Badge tone="neutral">{m.structure_phase}</Badge>
                ) : (
                  <span className="text-slate-400">—</span>
                )}
              </td>
              <td className="px-4 py-3">
                <div className="flex flex-wrap gap-1">
                  {m.ambient_sc === true && (
                    <Badge tone="accent">ambient</Badge>
                  )}
                  {m.is_unconventional === true && (
                    <Badge tone="warn">unconv</Badge>
                  )}
                  {m.is_topological === true && (
                    <Badge tone="neutral">topo</Badge>
                  )}
                  {m.is_2d_or_interface === true && (
                    <Badge tone="neutral">2D</Badge>
                  )}
                  {m.has_competing_order === true && (
                    <Badge tone="muted">CDW/SDW</Badge>
                  )}
                </div>
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
