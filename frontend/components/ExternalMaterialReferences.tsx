"use client";

import { useEffect, useState } from "react";
import { getMaterialExternalReferences } from "@/lib/api";
import type { ExternalMaterialReferences as ReferenceReport } from "@/lib/api";
import { scientificNumber } from "@/lib/result-semantics";

const number = (value: number | null, unit = "") => value == null ? "—" : `${scientificNumber(value)}${unit ? ` ${unit}` : ""}`;

export function ExternalMaterialReferences({ materialId }: { materialId: string }) {
  const [state, setState] = useState<{ materialId: string; report: ReferenceReport | null; failed: boolean }>({ materialId, report: null, failed: false });
  const report = state.materialId === materialId ? state.report : null;
  const failed = state.materialId === materialId && state.failed;
  useEffect(() => {
    const controller = new AbortController();
    setState({ materialId, report: null, failed: false });
    getMaterialExternalReferences(materialId, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      if (value.version !== "material-external-references/1.0.0" || value.scientific_acceptance !== false || value.sample_identity_established !== false || !Array.isArray(value.candidates)) throw new Error("Reference contract unavailable");
      setState({ materialId, report: value, failed: false });
    }).catch(() => { if (!controller.signal.aborted) setState({ materialId, report: null, failed: true }); });
    return () => controller.abort();
  }, [materialId]);
  return <section className="space-y-3 border-t border-sage-border pt-6" aria-label="Calculated external references">
    <div><h2 className="text-lg font-semibold">Calculated references</h2><p className="mt-1 max-w-3xl text-sm text-slate-600">Materials Project structures with the same fixed composition. Phase, sample and pressure correspondence require separate review.</p></div>
    {!report && !failed && <p className="text-sm text-slate-500" role="status">Loading calculated reference data…</p>}
    {(failed || report?.status === "unavailable") && <p className="text-sm text-slate-600">Reference service unavailable. No conclusion about database coverage can be drawn from this request.</p>}
    {report?.status === "not_applicable" && <p className="text-sm text-slate-600">Resolve this composition, interface or isotope notation before matching a bulk reference structure.</p>}
    {report?.status === "no_match" && <p className="text-sm text-slate-600">No fixed-composition match was returned by Materials Project. Related compounds and parent compositions have not been substituted.</p>}
    {report?.status === "available" && <>
      <div className="overflow-x-auto rounded-lg border border-sage-border bg-white">
        <table className="w-full text-left text-sm"><caption className="sr-only">Computed polymorph references; independent of selected superconducting measurements</caption>
          <thead className="border-b border-sage-border bg-slate-50 text-xs text-slate-600"><tr><th className="px-4 py-3">Reference</th><th className="px-4 py-3">Space group</th><th className="px-4 py-3">Band gap (eV)</th><th className="px-4 py-3">Density (g/cm³)</th><th className="px-4 py-3">Above hull (eV/atom)</th><th className="px-4 py-3">Provenance</th></tr></thead>
          <tbody className="divide-y divide-slate-100">{report.candidates.filter(row => row.sample_identity_established === false && row.phase_identity_established === false).map(row => <tr key={row.id}>
            <td className="px-4 py-3"><a href={row.url} target="_blank" rel="noopener noreferrer" className="font-medium text-accent-deep underline underline-offset-2">{row.id} ↗</a><span className="block text-xs text-slate-500">Computed · composition match</span></td>
            <td className="px-4 py-3">{row.space_group ?? "—"}<span className="block text-xs text-slate-500">{row.crystal_system}</span></td>
            <td className="px-4 py-3 tabular-nums">{number(row.band_gap_ev)}</td><td className="px-4 py-3 tabular-nums">{number(row.density_g_cm3)}</td><td className="px-4 py-3 tabular-nums">{number(row.energy_above_hull_ev_atom)}</td>
            <td className="px-4 py-3"><details><summary className="cursor-pointer text-accent-deep">Calculation details</summary><dl className="mt-2 min-w-64 space-y-2 text-xs text-slate-600">
              <div><dt className="font-medium">Calculated cell (Å, degrees)</dt><dd>{Object.entries(row.lattice).map(([key, value]) => `${key} = ${scientificNumber(value)}`).join("; ") || "Not supplied"}</dd></div>
              <div><dt className="font-medium">Formation energy</dt><dd>{number(row.formation_energy_ev_atom, "eV/atom")}</dd></div>
              <div><dt className="font-medium">Functional</dt><dd>{row.functional}</dd></div>
              <div><dt className="font-medium">Property source tasks</dt><dd>{row.origins.map(origin => `${origin.property}: ${origin.task_id}`).join("; ") || "Not supplied"}</dd></div>
              <div><dt className="font-medium">Source updated</dt><dd>{row.last_updated ?? "Not supplied"}</dd></div>
              <div><dt className="font-medium">Snapshot hash</dt><dd className="break-all font-mono">{row.source_snapshot_sha256}</dd></div>
            </dl></details></td>
          </tr>)}</tbody>
        </table>
      </div>
      <p className="max-w-4xl text-xs text-slate-500">{report.reference_conditions} A zero band gap does not establish superconductivity. <a href={report.methodology_url} target="_blank" rel="noopener noreferrer" className="underline">MP methodology ↗</a></p>
      {report.truncated && <p className="text-xs text-amber-800">Only the first 20 returned references are shown; other polymorphs may exist.</p>}
      <p className="text-xs text-slate-500">Retrieved: {report.retrieved_at ? new Date(report.retrieved_at).toLocaleString("en-GB", { timeZone: "UTC" }) + " UTC" : "Unavailable"}</p>
    </>}
  </section>;
}
