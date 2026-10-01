"use client";

import { useEffect, useState } from "react";
import { getMaterialStructureReferences } from "@/lib/api";
import type { ExternalStructureQuantity, MaterialStructureReferences } from "@/lib/api";

const codId = /^[1-9][0-9]{6,8}$/;
const fields = ["a", "b", "c", "alpha", "beta", "gamma"] as const;
const allowedUnits = new Set(["Å", "degrees", "Å³", "K", "kPa"]);
function quantity(q: ExternalStructureQuantity | null | undefined) {
  if (!q || !Number.isFinite(q.value) || !allowedUnits.has(q.unit)) return "Not supplied";
  const sigma = q.uncertainty != null && Number.isFinite(q.uncertainty) && q.uncertainty >= 0 ? ` ± ${q.uncertainty}` : "";
  return `${q.value}${sigma} ${q.unit}`;
}
function doiUrl(value: string | null) {
  try { const url = new URL(value ?? ""); return url.protocol === "https:" && url.hostname === "doi.org" && !url.username && !url.password && !url.port ? url.href : null; } catch { return null; }
}
function validReport(value: MaterialStructureReferences) {
  return value.version === "material-crystal-references/1.0.0" && value.provider === "COD"
    && value.scientific_acceptance === false && value.sample_identity_established === false
    && value.phase_identity_established === false && value.database_changed === false
    && ["available", "no_match", "not_applicable", "unavailable"].includes(value.status)
    && Array.isArray(value.references) && value.references.length <= 20
    && value.references.every(row => codId.test(row.id) && ["Observed", "Unresolved"].includes(row.knowledge_origin)
      && row.sample_identity_established === false && row.phase_identity_established === false
      && row.coordinate_model_validated === false && row.cif_validation_status === "external_file_not_validated"
      && row.measurement_conditions && row.lattice && row.bibliography);
}

export function ExternalStructureReferences({ materialId }: { materialId: string }) {
  const [expanded, setExpanded] = useState(false);
  const [state, setState] = useState<{ materialId: string; report: MaterialStructureReferences | null; failed: boolean }>({ materialId, report: null, failed: false });
  const report = state.materialId === materialId ? state.report : null;
  const failed = state.materialId === materialId && state.failed;
  useEffect(() => {
    if (!expanded) return;
    const controller = new AbortController();
    setState({ materialId, report: null, failed: false });
    getMaterialStructureReferences(materialId, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      if (!validReport(value)) throw new Error("Structure reference contract unavailable");
      setState({ materialId, report: value, failed: false });
    }).catch(() => { if (!controller.signal.aborted) setState({ materialId, report: null, failed: true }); });
    return () => controller.abort();
  }, [materialId, expanded]);
  return <details className="border-t border-sage-border pt-5" onToggle={event => { if (event.target === event.currentTarget) setExpanded(event.currentTarget.open); }}>
    <summary className="cursor-pointer text-base font-semibold text-accent-deep">Crystal structure references · COD{report?.status === "available" ? ` (${report.references.length})` : ""}</summary>
    <div className="mt-3 space-y-3">
      <p className="max-w-4xl text-sm text-slate-600">Published crystal metadata matched by composition. These references are separate from this material’s retained properties; sample and phase correspondence need review.</p>
      {!report && !failed && <p role="status" className="text-sm text-slate-500">Loading COD structure references…</p>}
      {(failed || report?.status === "unavailable") && <p role="status" className="text-sm text-slate-600">COD reference service unavailable. Database coverage remains unresolved for this request.</p>}
      {report?.status === "not_applicable" && <p className="text-sm text-slate-600">Resolve the source composition, isotope or interface before querying a bulk crystal reference.</p>}
      {report?.status === "no_match" && <p className="text-sm text-slate-600">No exact-composition reference was returned by COD. This result does not establish scientific absence.</p>}
      {report?.status === "available" && <>
        <div className="overflow-x-auto rounded-lg border border-sage-border bg-white">
          <table className="w-full text-left text-sm"><caption className="sr-only">External crystal references with their own measurement conditions</caption>
            <thead className="border-b border-sage-border bg-slate-50 text-xs text-slate-600"><tr>{["Reference", "Source composition", "Space group", "Cell", "Measurement conditions", "Source"].map(label => <th key={label} className="px-3 py-2">{label}</th>)}</tr></thead>
            <tbody className="divide-y divide-slate-100">{report.references.map(row => {
              const paper = doiUrl(row.bibliography.doi_url);
              const revision = /^svn:[1-9][0-9]{0,11}$/.test(row.source_revision ?? "") ? row.source_revision!.slice(4) : null;
              const cif = `https://www.crystallography.net/cod/${row.id}.cif${revision ? `@${revision}` : ""}`;
              return <tr key={row.id}>
                <td className="px-3 py-3 align-top"><a href={`https://www.crystallography.net/cod/${row.id}.html`} target="_blank" rel="noopener noreferrer" className="font-medium text-accent-deep underline">COD {row.id} ↗</a><a href={cif} target="_blank" rel="noopener noreferrer" className="mt-1 block text-xs text-accent-deep underline">External CIF file ↗</a></td>
                <td className="px-3 py-3 align-top"><span className="block">Declared: {row.declared_formula ?? "Not supplied"}</span><span className="mt-1 block text-xs text-slate-600">Cell contents: {row.cell_content_formula ?? "Not supplied"}</span>{row.composition_relation === "different_composition" && <span className="mt-1 block text-xs text-amber-800">Declared and cell-content compositions differ</span>}{row.composition_relation === "unresolved" && <span className="mt-1 block text-xs text-slate-500">{row.match_level === "cell_content_composition_only_declared_unresolved" ? "Declared composition unresolved" : "Cell-content composition unresolved"}</span>}</td>
                <td className="px-3 py-3 align-top">{row.space_group ?? "Not supplied"}{row.space_group_number != null && <span className="block text-xs text-slate-500">No. {row.space_group_number}</span>}</td>
                <td className="min-w-44 px-3 py-3 align-top tabular-nums">{fields.filter(key => row.lattice[key]).map(key => <span className="block text-xs" key={key}>{key} = {quantity(row.lattice[key])}</span>)}</td>
                <td className="min-w-56 px-3 py-3 align-top text-xs text-slate-600"><span className="block">Cell temperature: {quantity(row.measurement_conditions.cell_temperature)}</span><span className="block">Diffraction temperature: {quantity(row.measurement_conditions.diffraction_temperature)}</span><span className="block">Cell pressure: {quantity(row.measurement_conditions.cell_pressure)}</span><span className="block">Diffraction pressure: {quantity(row.measurement_conditions.diffraction_pressure)}</span></td>
                <td className="min-w-44 px-3 py-3 align-top text-xs text-slate-600"><span className="block">{row.method ?? "Method not supplied"}</span><span className="block">{row.knowledge_origin === "Observed" ? "Experimental method reported" : "Measurement origin unresolved"}</span>{row.bibliography.year != null && <span className="block">Source year: {row.bibliography.year}</span>}{paper && <a href={paper} target="_blank" rel="noopener noreferrer" className="block text-accent-deep underline">Source paper ↗</a>}<details className="mt-2"><summary className="cursor-pointer text-accent-deep">Provenance</summary><dl className="mt-2 space-y-1"><div><dt>COD revision</dt><dd>{row.source_revision ?? "Not supplied; file revision unverified"}</dd></div><div><dt>Source updated</dt><dd>{row.source_updated ?? "Not supplied"}</dd></div><div><dt>Source title</dt><dd>{row.bibliography.title ?? "Not supplied"}</dd></div><div><dt>Cell volume</dt><dd>{quantity(row.volume)}</dd></div><div><dt>Coordinate flag</dt><dd>{row.provider_has_coordinates ? "COD reports coordinates" : "Not supplied by COD"}</dd></div><div><dt>Source status</dt><dd>{row.source_status ?? "No status supplied"}</dd></div><div><dt>Metadata snapshot SHA-256</dt><dd className="break-all font-mono">{row.source_snapshot_sha256}</dd></div></dl></details></td>
              </tr>;
            })}</tbody>
          </table>
        </div>
        <p className="max-w-4xl text-xs text-slate-500">Missing pressure is not assumed to be ambient. COD’s coordinate flag and linked CIF files have not been validated as this sample’s coordinate model. <a href="https://wiki.crystallography.net/cod_mysql_schema/" target="_blank" rel="noopener noreferrer" className="underline">COD field definitions ↗</a></p>
        {report.truncated && <p className="text-xs text-amber-800">Showing 20 references from the bounded response; additional returned references are omitted.</p>}
        <p className="text-xs text-slate-500">Retrieved: {report.retrieved_at ?? "Unavailable"}. Metadata rows inspected: {report.inspected_entries}.</p>
      </>}
    </div>
  </details>;
}
