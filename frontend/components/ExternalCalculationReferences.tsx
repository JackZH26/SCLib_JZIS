"use client";

import { useEffect, useId, useState } from "react";
import { getMaterialCalculationReferences } from "@/lib/api";
import type { MaterialCalculationReferences } from "@/lib/api";
import { useProviderAvailabilityPublisher } from "@/components/MaterialProviderAvailability";
import { emptyProviderAvailability, mapMaterialProviderAvailability, MATERIAL_PROVIDER_ANCHORS } from "@/lib/material-provider-availability";

const entryPattern = /^[A-Za-z0-9_-]{1,64}$/;
const entryUrl = (id: string) => `https://nomad-lab.eu/prod/v1/gui/search/entries/entry/id/${id}`;
const archiveUrl = (id: string) => `https://nomad-lab.eu/prod/v1/api/v1/entries/${id}/archive`;
const docsUrl = "https://docs.nomad-lab.eu/1.4.3/howto/manage/program/api.html";

function safeOrigin(url: string): boolean {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.port || parsed.search || parsed.hash) return false;
    if (parsed.hostname === "doi.org") return /^\/10\.[0-9]{4,9}\/.+/.test(parsed.pathname);
    if (parsed.hostname === "next-gen.materialsproject.org") return /^\/materials\/mp-[a-z0-9]{1,40}$/.test(parsed.pathname);
    if (parsed.hostname === "zenodo.org") return /^\/records?\/[0-9]+\/?$/.test(parsed.pathname);
    return ["oqmd.org", "www.oqmd.org", "aflow.org", "aflowlib.org", "www.aflowlib.org"].includes(parsed.hostname);
  } catch { return false; }
}

function validReport(value: MaterialCalculationReferences): boolean {
  return value?.version === "material-calculation-references/1.0.0" && value.provider === "NOMAD"
    && value.scientific_acceptance === false && value.sample_identity_established === false && value.phase_identity_established === false
    && ["available", "no_match", "not_applicable", "unavailable"].includes(value.status)
    && Array.isArray(value.references) && value.references.length <= 20
    && (value.matches_total === null || Number.isInteger(value.matches_total) && value.matches_total >= 0)
    && Number.isInteger(value.inspected_entries) && value.inspected_entries >= 0 && value.inspected_entries <= 21 && typeof value.truncated === "boolean"
    && (value.status !== "available" || value.references.length > 0)
    && (value.status === "available" || value.references.length === 0)
    && (value.status !== "no_match" || value.matches_total === 0)
    && value.references.every(row => entryPattern.test(row.id) && row.url === entryUrl(row.id) && row.archive_url === archiveUrl(row.id)
      && typeof row.formula === "string" && row.formula.length <= 300 && /^[a-f0-9]{64}$/.test(row.source_snapshot_sha256)
      && row.sample_identity_established === false && row.phase_identity_established === false
      && row.conditions_status === "not_inspected" && row.match_level === "fixed_composition_only"
      && [row.method, row.program, row.parser, row.structural_type, row.space_group, row.crystal_system, row.material_id].every(field => field === null || typeof field === "string")
      && row.knowledge_origin === (row.method && row.program ? "Computed" : "Unresolved")
      && (row.xc_functional_names === null || Array.isArray(row.xc_functional_names) && row.xc_functional_names.length > 0 && row.xc_functional_names.length <= 16 && row.xc_functional_names.every(name => typeof name === "string" && name.length > 0 && name.length <= 80 && name === name.trim() && !/[\u0000-\u001f\u007f]/.test(name)))
      && (row.xc_functional_type === null || typeof row.xc_functional_type === "string" && row.xc_functional_type.length > 0 && row.xc_functional_type.length <= 80 && row.xc_functional_type === row.xc_functional_type.trim() && !/[\u0000-\u001f\u007f]/.test(row.xc_functional_type))
      && (row.spin_polarized === null || typeof row.spin_polarized === "boolean")
      && (row.dft_metadata_status === ([row.xc_functional_names, row.xc_functional_type, row.spin_polarized].some(field => field !== null) ? "reported" : "not_supplied") || row.dft_metadata_status === "requires_review" && [row.xc_functional_names, row.xc_functional_type, row.spin_polarized].some(field => field === null))
      && row.dft_metadata_scope === "reported_underlying_dft_metadata_not_complete_method"
      && row.method_status === (row.method ? "reported" : "unresolved") && Array.isArray(row.source_references) && row.source_references.length <= 8
      && row.source_references.every(link => typeof link?.provider === "string" && typeof link?.url === "string"));
}

export function ExternalCalculationReferences({ materialId }: { materialId: string }) {
  const publishAvailability = useProviderAvailabilityPublisher(materialId, "NOMAD");
  const headingId = useId();
  const [expansion, setExpansion] = useState<{ materialId: string; open: boolean }>({ materialId, open: false });
  const expanded = expansion.materialId === materialId && expansion.open;
  const [state, setState] = useState<{ materialId: string; report: MaterialCalculationReferences | null; failed: boolean }>({ materialId, report: null, failed: false });
  const report = state.materialId === materialId ? state.report : null;
  const failed = state.materialId === materialId && state.failed;
  useEffect(() => {
    if (!expanded) return;
    const controller = new AbortController();
    let settled = false;
    setState({ materialId, report: null, failed: false });
    publishAvailability(emptyProviderAvailability("NOMAD", "loading"));
    getMaterialCalculationReferences(materialId, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      if (!validReport(value)) throw new Error("Calculation reference contract unavailable");
      settled = true;
      setState({ materialId, report: value, failed: false });
      publishAvailability(mapMaterialProviderAvailability("NOMAD", value));
    }).catch(() => {
      if (!controller.signal.aborted) { settled = true; setState({ materialId, report: null, failed: true }); publishAvailability(emptyProviderAvailability("NOMAD", "unavailable")); }
    });
    return () => { controller.abort(); if (!settled) publishAvailability(null); };
  }, [materialId, expanded, publishAvailability]);
  const count = report?.status === "available" ? `${report.references.length}${report.matches_total != null && report.matches_total > report.references.length ? ` of ${report.matches_total}` : ""} tasks` : null;
  const retrieved = report?.retrieved_at ? new Date(report.retrieved_at) : null;
  return <section id={MATERIAL_PROVIDER_ANCHORS.NOMAD} aria-labelledby={headingId} className="border-t border-sage-border pt-5">
    <details key={materialId} open={expanded} onToggle={event => {
      if (event.target === event.currentTarget) setExpansion({ materialId, open: event.currentTarget.open });
    }}>
      <summary className="cursor-pointer rounded-sm py-1 text-accent-deep focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent-deep">
        <span id={headingId} className="font-semibold">NOMAD calculation references</span>
        <span className="ml-3 text-sm font-normal text-slate-600">{count ?? (!report && !failed ? expanded ? "Loading…" : "Inspect calculation tasks" : failed || report?.status === "unavailable" ? "Unavailable" : report?.status === "no_match" ? "No match returned" : "Composition review needed")}</span>
      </summary>
      <div className="mt-3 space-y-3">
        {expanded && !report && !failed && <p className="text-sm text-slate-600" role="status">Loading public calculation metadata…</p>}
        {(failed || report?.status === "unavailable") && <p className="text-sm text-slate-600">NOMAD is unavailable for this request. Database coverage cannot be determined.</p>}
        {report?.status === "not_applicable" && <p className="text-sm text-slate-600">Resolve the exact source composition, isotope or interface notation before querying calculation references.</p>}
        {report?.status === "no_match" && <p className="text-sm text-slate-600">No exact fixed-composition task was returned by NOMAD. Parent compounds have not been substituted.</p>}
        {report?.status === "available" && <>
          <p className="max-w-4xl text-sm text-slate-600">Temperature and pressure: <span className="font-medium">Not inspected</span>. Matching composition does not establish sample or phase identity.</p>
          <div className="overflow-x-auto rounded-lg border border-sage-border bg-white">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Public NOMAD tasks matched by composition, separate from reported superconducting measurements</caption>
              <thead className="border-b border-sage-border bg-slate-50 text-xs text-slate-600"><tr><th className="px-4 py-3">Task</th><th className="px-4 py-3">Structure</th><th className="px-4 py-3">Method / program</th><th className="px-4 py-3">Provenance</th></tr></thead>
              <tbody className="divide-y divide-slate-100">{report.references.map(row => {
                const dftFallback = row.dft_metadata_status === "requires_review" ? "Unresolved from returned metadata" : "Not supplied in returned metadata";
                return <tr key={row.id}>
                <td className="px-4 py-3 align-top"><a href={row.url} target="_blank" rel="noopener noreferrer" className="break-all font-medium text-accent-deep underline underline-offset-2">{row.id} ↗</a><span className="mt-1 block text-xs text-slate-500">{row.formula} · {row.knowledge_origin === "Computed" ? "Computed" : "Context unresolved"}</span></td>
                <td className="px-4 py-3 align-top">{row.space_group ?? "Not supplied"}<span className="block text-xs text-slate-500">{[row.crystal_system, row.structural_type].filter(Boolean).join(" · ")}</span></td>
                <td className="px-4 py-3 align-top">{row.method ?? "Method not resolved"}<span className="block text-xs text-slate-500">{row.program ?? "Program not supplied"}</span>{row.xc_functional_names && <span className="mt-1 block text-xs text-slate-600">Underlying DFT XC: {row.xc_functional_names.join(" + ")}</span>}</td>
                <td className="px-4 py-3 align-top"><details><summary className="cursor-pointer text-accent-deep">Task details</summary><dl className="mt-2 min-w-56 space-y-2 text-xs text-slate-600">
                  <div><dt className="font-medium">Underlying DFT XC names</dt><dd>{row.xc_functional_names?.join(" + ") ?? dftFallback}</dd></div>
                  <div><dt className="font-medium">DFT functional class</dt><dd>{row.xc_functional_type ?? dftFallback}</dd></div>
                  <div><dt className="font-medium">DFT spin polarization</dt><dd>{row.spin_polarized === null ? dftFallback : row.spin_polarized ? "Reported spin-polarized" : "Reported non-spin-polarized"}</dd></div>
                  <div><dt className="font-medium">Source archive</dt><dd><a href={row.archive_url} target="_blank" rel="noopener noreferrer" className="text-accent-deep underline">Inspect NOMAD archive ↗</a></dd></div>
                  <div><dt className="font-medium">Parser</dt><dd>{row.parser ?? "Not supplied"}</dd></div>
                  <div><dt className="font-medium">NOMAD structure identity</dt><dd className="break-all">{row.material_id ?? "Not supplied"}</dd></div>
                  <div><dt className="font-medium">Repository and citation links</dt><dd className="flex flex-wrap gap-x-3 gap-y-1">{row.source_references.filter(link => safeOrigin(link.url)).map(link => <a key={link.url} href={link.url} target="_blank" rel="noopener noreferrer" className="text-accent-deep underline">{link.provider} ↗</a>)}{!row.source_references.some(link => safeOrigin(link.url)) && "Not supplied"}</dd></div>
                  <div><dt className="font-medium">Metadata snapshot hash</dt><dd className="break-all font-mono">{row.source_snapshot_sha256}</dd></div>
                </dl></details></td>
              </tr>;
              })}</tbody>
            </table>
          </div>
          <p className="max-w-4xl text-xs text-slate-500">Counts describe tasks, not independent experiments. Imported MP, OQMD or AFLOW tasks can overlap other reference panels. Reported DFT metadata describes the underlying DFT calculation, including for GW tasks; it does not specify the complete method. Archive conditions remain uninspected. <a href={docsUrl} target="_blank" rel="noopener noreferrer" className="underline">NOMAD API documentation ↗</a></p>
          {report.truncated && <p className="text-xs text-amber-800">Showing at most 20 tasks in entry ID order; this is not a census of phases or methods.</p>}
          <p className="text-xs text-slate-500">Retrieved: {retrieved && !Number.isNaN(retrieved.getTime()) ? `${retrieved.toLocaleString("en-GB", { timeZone: "UTC" })} UTC` : "Unavailable"}</p>
        </>}
      </div>
    </details>
  </section>;
}
