import type { NomadElectronicReferences } from "@/lib/api";
import { electronicGapLabel, electronicGapNumber } from "@/lib/nomad-electronic-references";

export function NomadElectronicReading({ report }: { report?: NomadElectronicReferences }) {
  if (!report) return <span title="Electronic properties were not inspected by this response">—</span>;
  if (report.status === "not_supplied") return <span title="No electronic band-gap value supplied in the returned metadata">—</span>;
  if (report.status === "requires_review") return <span className="text-xs text-amber-800" title="Supplied electronic values need source inspection">Review source values</span>;
  const first = report.band_gaps[0];
  return <details className="min-w-40">
    <summary className="cursor-pointer text-accent-deep">
      <span className="tabular-nums">{electronicGapNumber(first.value_ev)} eV</span>
      <span className="mt-1 block text-xs text-slate-600">{electronicGapLabel(first.source_kind)}{report.band_gaps.length > 1 ? ` · ${report.band_gaps.length.toLocaleString("en-US")} readings` : ""}</span>
    </summary>
    <ul className="mt-3 space-y-3 text-xs text-slate-600" aria-label="Electronic band-gap readings">{report.band_gaps.map((gap, index) => <li key={index} className="space-y-1">
      <p className="font-medium">{electronicGapLabel(gap.source_kind)} · group {gap.group_index.toLocaleString("en-US")}{gap.spin_channel_index === null ? " · channel not supplied" : ` · channel ${gap.spin_channel_index.toLocaleString("en-US")}`}</p>
      <p className="tabular-nums">{electronicGapNumber(gap.value_ev)} eV{gap.gap_type ? ` · ${gap.gap_type}` : ""}</p>
      <p className="break-all">Source: {String(gap.value_j)} J</p>
      <p>{gap.spin_polarized === null ? "DOS / band spin setting not supplied" : gap.spin_polarized ? "Spin-polarized" : "Non-spin-polarized"}</p>
    </li>)}</ul>
    <p className="mt-3 text-xs text-slate-500">1 eV = 1.602176634 × 10⁻¹⁹ J. <a className="underline" href={report.unit_schema_url} target="_blank" rel="noopener noreferrer">Source unit definition</a></p>
  </details>;
}
