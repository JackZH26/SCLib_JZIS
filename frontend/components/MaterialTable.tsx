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
import { ScientificMatches } from "@/components/ScientificMatches";
import type { MaterialSummary } from "@/lib/api";
import { familyLabel } from "@/lib/families";
import { FormulaDisplay } from "@/components/FormulaDisplay";
import { PropertyEvidenceValue } from "@/components/PropertyEvidence";
import { selectedProperty } from "@/lib/property-evidence";
import { ScientificAnomalyNotice } from "@/components/ScientificAnomalies";

/**
 * Count source-linked selections, not arbitrary non-null legacy scalars.
 * Coverage is not source agreement, experimental confirmation or ML readiness.
 */
const COVERAGE_FIELDS = ["tc_max", "tc_ambient", "pairing_symmetry", "structure_phase", "is_unconventional", "has_competing_order"];
const COMPLETENESS_FIELDS = COVERAGE_FIELDS.length;

function completeness(m: MaterialSummary): number {
  return COVERAGE_FIELDS.filter(field => selectedProperty(m.property_evidence, field)).length;
}

function CompletenessBar({ filled }: { filled: number }) {
  const pct = (filled / COMPLETENESS_FIELDS) * 100;
  // Coverage only; a complete catalogue row may still mix incompatible states.
  const tone =
    filled >= 6
      ? "bg-[color:var(--accent)]"
      : filled >= 4
        ? "bg-[color:var(--accent)]/60"
        : "bg-slate-300";
  return (
    <div
      title={`${filled}/${COMPLETENESS_FIELDS} fields have source-linked selections; not scientific validation`}
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
        <caption className="border-b border-slate-200 px-4 py-3 text-left text-xs text-slate-500">Catalogue selections: expand each property for its own source and conditions. A material row is not a joint observation or an ML feature row. Sorting uses legacy catalogue columns, not validated property values; unsupported selections may remain near the top.</caption>
        <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-4 py-2 text-left font-medium">Formula</th>
            <th className="px-4 py-2 text-left font-medium">Family</th>
            <th className="px-4 py-2 text-right font-medium">Tc max (K)</th>
            <th className="px-4 py-2 text-right font-medium">Tc ambient (K)</th>
            <th className="px-4 py-2 text-left font-medium">Pairing</th>
            <th className="px-4 py-2 text-left font-medium">Phase</th>
            <th className="px-4 py-2 text-left font-medium">Supported flags</th>
            <th className="px-4 py-2 text-right font-medium">arXiv year</th>
            <th className="px-4 py-2 text-right font-medium">Papers</th>
            <th className="px-4 py-2 text-center font-medium" title="Source tier is not experimental confirmation">Source tier</th>
            <th className="px-4 py-2 text-left font-medium">Linked fields</th>
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
                <ScientificMatches results={m.matching_results} />
                <ScientificAnomalyNotice review={m.anomaly_review} compact />
              </td>
              <td className="px-4 py-2 text-slate-600" title="Catalogue family classification, not a measured property or source">{familyLabel(m.family)}</td>
              <td className="px-4 py-2 text-right tabular-nums text-slate-800">
                <PropertyEvidenceValue evidence={m.property_evidence} field="tc_max" compact includeUnit={false} />
              </td>
              <td className="px-4 py-2 text-right tabular-nums text-slate-600">
                <PropertyEvidenceValue evidence={m.property_evidence} field="tc_ambient" compact includeUnit={false} />
              </td>
              <td className="px-4 py-2">
                <PropertyEvidenceValue evidence={m.property_evidence} field="pairing_symmetry" compact />
              </td>
              <td className="px-4 py-2">
                <PropertyEvidenceValue evidence={m.property_evidence} field="structure_phase" compact />
              </td>
              <td className="px-4 py-2">
                <div className="flex flex-wrap gap-1">
                  {[["is_unconventional", "Unconventional"], ["has_competing_order", "Competing order"]].map(([field, label]) => selectedProperty(m.property_evidence, field)?.value === true ? <div key={field} className="rounded border border-slate-200 p-1 text-[10px]"><span>{label}</span><PropertyEvidenceValue evidence={m.property_evidence} field={field} compact /></div> : null)}
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
