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
import { FormulaDisplay } from "@/components/FormulaDisplay";

/**
 * How "filled in" is this material's summary? Count non-null values
 * across the MaterialSummary fields we care about. Used to render a
 * compact progress indicator in the list so users can see at a glance
 * which materials are well-sourced vs. skeletal (name only).
 *
 * The list is the same set we surface as dedicated columns + the
 * badge flags, so a "fully green" bar means every column has data,
 * not just "papers agreed".
 */
const COMPLETENESS_FIELDS = 10;

function completeness(m: MaterialSummary): number {
  let n = 0;
  if (m.family) n += 1;
  if (m.tc_max != null) n += 1;
  if (m.tc_ambient != null) n += 1;
  if (m.arxiv_year != null) n += 1;
  if (m.pairing_symmetry) n += 1;
  if (m.structure_phase) n += 1;
  if (m.ambient_sc != null) n += 1;
  if (m.is_unconventional != null) n += 1;
  if (m.has_competing_order != null) n += 1;
  if (m.total_papers > 0) n += 1;
  return n;
}

function CompletenessBar({ filled }: { filled: number }) {
  const pct = (filled / COMPLETENESS_FIELDS) * 100;
  // 3 tiers: thin = skeletal, mid = partial, full = well-sourced. The
  // accent green signals "data you can trust", muted slate signals
  // "only the formula is known".
  const tone =
    filled >= 8
      ? "bg-[color:var(--accent)]"
      : filled >= 4
        ? "bg-[color:var(--accent)]/60"
        : "bg-slate-300";
  return (
    <div
      title={`${filled}/${COMPLETENESS_FIELDS} fields populated`}
      className="flex items-center gap-2"
    >
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100">
        <div
          className={`h-full ${tone} transition-all`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs tabular-nums text-slate-500">
        {filled}/{COMPLETENESS_FIELDS}
      </span>
    </div>
  );
}

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
      className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${palette[tone]}`}
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
            <th className="px-4 py-2 text-left font-medium">Formula</th>
            <th className="px-4 py-2 text-left font-medium">Family</th>
            <th className="px-4 py-2 text-right font-medium">Tc max (K)</th>
            <th className="px-4 py-2 text-right font-medium">Tc ambient</th>
            <th className="px-4 py-2 text-left font-medium">Pairing</th>
            <th className="px-4 py-2 text-left font-medium">Phase</th>
            <th className="px-4 py-2 text-left font-medium">Flags</th>
            <th className="px-4 py-2 text-right font-medium">arXiv year</th>
            <th className="px-4 py-2 text-right font-medium">Papers</th>
            <th className="px-4 py-2 text-center font-medium">Tier</th>
            <th className="px-4 py-2 text-left font-medium">Data</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((m) => (
            <tr key={m.id} className="hover:bg-slate-50">
              <td className="px-4 py-2">
                <Link
                  href={`/materials/${encodeURIComponent(m.id)}`}
                  className="block max-w-[18rem] truncate font-medium text-slate-900 hover:underline"
                  title={m.formula}
                >
                  <FormulaDisplay formula={m.formula} />
                </Link>
              </td>
              <td className="px-4 py-2 text-slate-600">{m.family ?? "—"}</td>
              <td className="px-4 py-2 text-right tabular-nums text-slate-800">
                {m.tc_max != null ? m.tc_max.toFixed(1) : "—"}
              </td>
              <td className="px-4 py-2 text-right tabular-nums text-slate-600">
                {m.tc_ambient != null ? m.tc_ambient.toFixed(1) : "—"}
              </td>
              <td className="px-4 py-2">
                {m.pairing_symmetry ? (
                  <Badge tone="accent">{m.pairing_symmetry}</Badge>
                ) : (
                  <span className="text-slate-400">—</span>
                )}
              </td>
              <td className="px-4 py-2">
                {m.structure_phase ? (
                  <Badge tone="neutral">{m.structure_phase}</Badge>
                ) : (
                  <span className="text-slate-400">—</span>
                )}
              </td>
              <td className="px-4 py-2">
                <div className="flex flex-wrap gap-1">
                  {m.ambient_sc === true && (
                    <Badge tone="accent">ambient</Badge>
                  )}
                  {m.is_unconventional === true && (
                    <Badge tone="warn">unconv</Badge>
                  )}
                  {m.has_competing_order === true && (
                    <Badge tone="muted">CDW/SDW</Badge>
                  )}
                </div>
              </td>
              <td className="px-4 py-2 text-right tabular-nums text-slate-600">
                {m.arxiv_year ?? "—"}
              </td>
              <td className="px-4 py-2 text-right tabular-nums text-slate-600">
                {m.total_papers}
                {m.variant_count > 0 && (
                  <span className="ml-1 text-[10px] text-slate-400" title={`${m.variant_count} doping variant${m.variant_count === 1 ? "" : "s"}`}>
                    +{m.variant_count}v
                  </span>
                )}
              </td>
              <td className="px-4 py-2 text-center">
                {m.best_credibility_tier ? (
                  <span className={`inline-flex items-center rounded-full border px-1.5 py-0.5 text-[10px] font-medium ${
                    m.best_credibility_tier === "T1" ? "bg-emerald-50 text-emerald-700 border-emerald-200" :
                    m.best_credibility_tier === "T2" ? "bg-blue-50 text-blue-700 border-blue-200" :
                    "bg-slate-50 text-slate-500 border-slate-200"
                  }`}>{m.best_credibility_tier}</span>
                ) : (
                  <span className="text-slate-400">—</span>
                )}
              </td>
              <td className="px-4 py-2">
                <CompletenessBar filled={completeness(m)} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
