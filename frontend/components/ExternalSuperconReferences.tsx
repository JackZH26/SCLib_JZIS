"use client";

import { useEffect, useId, useState } from "react";
import { getMaterialSuperconReferences } from "@/lib/api";
import type { MaterialSuperconReferences, SuperconReferenceCode, SuperconReferenceQuantity } from "@/lib/api";
import { useProviderAvailabilityPublisher } from "@/components/MaterialProviderAvailability";
import { emptyProviderAvailability, mapMaterialProviderAvailability, MATERIAL_PROVIDER_ANCHORS } from "@/lib/material-provider-availability";

const datasetUrl = "https://doi.org/10.48505/nims.4487";
const licenseUrl = "https://creativecommons.org/licenses/by/4.0/";
const scope = "oxide_metallic_curated_source_rows_composition_references_not_selected_material_properties";
const criteria = new Set(["tc", "t1", "t2", "t3", "tcsus", "tcn"]);
const lengths = ["Å", "nm", "µm", "mm"];
const fields = ["T", "mT", "kT", "µT", "Oe", "kOe", "G", "kG", "kA/m", "10³ A/m"];
const quantityUnits: Record<string, readonly string[]> = {
  tc: ["K"], t1: ["K"], t2: ["K"], t3: ["K"], tcsus: ["K"], tcn: ["K"], tcwidth: ["K"],
  lata: lengths, latb: lengths, latc: lengths, cohere: lengths, pcohere: lengths, ncohere: lengths,
  penet: lengths, ppenet: lengths, npenet: lengths,
  hc1zero: fields, hc1t: fields, hc2zero: fields, phc2zero: fields, nhc2zero: fields,
  hc2t: fields, phc2t: fields, nhc2t: fields,
  gamma: ["mJ/(mol K²)", "J/(mol K²)", "µJ/(g K²)"], gap: ["meV", "K", "cm⁻¹", "µeV"],
  gapene: ["dimensionless"], isotope: ["dimensionless"], vols: ["%"],
  dtcdp: ["K/GPa", "K/kbar", "mK/MPa"], debyet: [], pmax: [],
};
const rawUnits: Record<string, string> = {
  K: "K", A: "Å", Å: "Å", nm: "nm", um: "µm", micron: "µm", micrometer: "µm", mm: "mm",
  T: "T", mT: "mT", kT: "kT", "micro-T": "µT", Oe: "Oe", kOe: "kOe", KOe: "kOe", gauss: "G", G: "G", kG: "kG", KG: "kG", "kA/m": "kA/m", "E+3 A/m": "10³ A/m",
  meV: "meV", "cm-1": "cm⁻¹", "cm(-1)": "cm⁻¹", "micro-eV": "µeV",
  "mJ/mol.K2": "mJ/(mol K²)", "mJ/molK2": "mJ/(mol K²)", "mJ/K2mol": "mJ/(mol K²)", "J/mol.K2": "J/(mol K²)", "uJ/g.K2": "µJ/(g K²)", "uJ/K2.g": "µJ/(g K²)",
  "K/GPa": "K/GPa", "K/GPA": "K/GPa", "K/Gpa": "K/GPa", "K/kbar": "K/kbar", "K/KBAR": "K/kbar", "K/kBar": "K/kbar", "K/Kbar": "K/kbar", "mK/MPa": "mK/MPa",
};
const methodFields = ["mhc1", "mhc2", "mcohere", "mpenet", "gapmeth", "gamcom", "mdebye"];
const hash = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const text = (value: unknown, limit = 1000) => value === null || typeof value === "string" && value.length <= limit;
const code = (value: SuperconReferenceCode) => value && text(value.raw_code) && text(value.label, 256)
  && ["reported", "not_supplied", "requires_review"].includes(value.status);

function validQuantity(q: SuperconReferenceQuantity): boolean {
  if (!q || typeof q.field !== "string" || !Object.hasOwn(quantityUnits, q.field)
    || typeof q.label !== "string" || q.label.length > 256 || typeof q.raw_value !== "string" || q.raw_value.length > 1000
    || !text(q.raw_unit) || !text(q.unit, 120) || !text(q.temperature_raw)
    || q.direction !== null && !["H_parallel_ab", "H_parallel_c", "H_normal_ab"].includes(q.direction)
    || typeof q.meaning !== "string" || q.meaning.length > 2048 || !text(q.source_method_raw) || !text(q.method_label)
    || !["reported", "not_supplied", "requires_review"].includes(q.method_status)
    || q.unit !== null && !quantityUnits[q.field].includes(q.unit)) return false;
  const rawResolved = q.raw_unit === null ? null : rawUnits[q.raw_unit];
  const expectedUnit = q.field === "gapene" || q.field === "isotope" ? "dimensionless" : q.field === "vols" ? "%"
    : rawResolved && quantityUnits[q.field].includes(rawResolved) ? rawResolved : null;
  if (q.unit !== expectedUnit || ["gapene", "isotope", "vols"].includes(q.field) && q.raw_unit !== null) return false;
  if (q.status === "value_requires_review") return q.value === null;
  if (typeof q.value !== "number" || !Number.isFinite(q.value)) return false;
  if (q.status === "reported") return q.unit !== null;
  if (q.status === "unit_not_supplied") return q.unit === null && q.raw_unit === null;
  return q.status === "unit_requires_review" && q.unit === null && typeof q.raw_unit === "string" && q.raw_unit.length > 0;
}

function validReport(value: MaterialSuperconReferences): boolean {
  return value?.version === "material-supercon-references/1.0.0" && value.provider === "MDR SuperCon"
    && value.dataset_version === "240322" && value.dataset_doi === datasetUrl && value.license === "CC BY 4.0"
    && value.scope === scope && value.source_publication_status === "not_checked"
    && value.scientific_acceptance === false && value.sample_identity_established === false && value.phase_identity_established === false
    && ["available", "no_match", "not_applicable", "unavailable"].includes(value.status)
    && Array.isArray(value.references) && value.references.length <= 20
    && Number.isInteger(value.omitted_rows) && value.omitted_rows >= 0 && value.truncated === (value.omitted_rows > 0)
    && (value.matches_total === null || Number.isInteger(value.matches_total) && value.matches_total >= value.references.length)
    && (value.status !== "available" || value.references.length > 0 && hash(value.snapshot_sha256) && hash(value.resource_sha256)
      && value.matches_total === value.references.length + value.omitted_rows && value.references.length === Math.min(20, value.matches_total))
    && (value.status === "available" || value.references.length === 0)
    && (value.status !== "no_match" || value.matches_total === 0)
    && new Set(value.references.map(row => row.id)).size === value.references.length
    && value.references.every(row => typeof row.source_row_id === "string" && /^(?:0|[1-9][0-9]{0,9})$/.test(row.source_row_id)
      && row.id === `mdr:240322:oxide_metallic:${row.source_row_id}` && row.source_table === "oxide_metallic"
      && row.url === datasetUrl && typeof row.formula === "string" && row.formula.length <= 512
      && text(row.raw_common_formula, 512) && hash(row.source_sha256) && hash(row.source_row_sha256)
      && row.source_file === "20240322_MDR_OAndM.txt" && Number.isInteger(row.source_line) && row.source_line >= 3
      && Number.isInteger(row.source_line_end) && row.source_line_end >= row.source_line
      && row.bibliography && Object.values(row.bibliography).every(field => text(field))
      && row.structure && [row.structure.space_group, row.structure.space_group_number_raw, row.structure.common_name].every(field => text(field, 512))
      && (row.structure.space_group_number === null || Number.isInteger(row.structure.space_group_number) && row.structure.space_group_number >= 1 && row.structure.space_group_number <= 230)
      && code(row.sample_form) && code(row.structure_method) && code(row.tc_method)
      && [row.isotope_element, row.isotope_exchange_ratio, row.sample_identifier].every(field => text(field, 512))
      && row.raw_source_method_fields && Object.keys(row.raw_source_method_fields).length === methodFields.length
      && methodFields.every(field => Object.hasOwn(row.raw_source_method_fields, field) && text(row.raw_source_method_fields[field as keyof typeof row.raw_source_method_fields]))
      && Array.isArray(row.quantities) && row.quantities.length <= 32 && new Set(row.quantities.map(q => q.field)).size === row.quantities.length && row.quantities.every(validQuantity));
}

function SourceCode({ value }: { value: SuperconReferenceCode }) {
  if (value.status === "not_supplied") return <>Not supplied</>;
  return <>{value.label ?? "Unresolved code"}{value.raw_code !== null && <span className="ml-1 text-slate-500">({value.raw_code})</span>}</>;
}

function Quantity({ quantity }: { quantity: SuperconReferenceQuantity }) {
  const unit = quantity.unit ?? quantity.raw_unit;
  const directions: Record<string, string> = { H_parallel_ab: "H parallel to ab", H_parallel_c: "H parallel to c", H_normal_ab: "H normal to ab" };
  const direction = quantity.direction === null ? null : directions[quantity.direction];
  return <div>
    <dt className="text-xs text-slate-500">{quantity.label}</dt>
    <dd className="break-words font-medium text-slate-800">{quantity.raw_value}{unit === "dimensionless" ? " (dimensionless)" : unit !== null ? ` ${unit}` : " (unit not supplied)"}
      {quantity.status === "unit_requires_review" && <span className="ml-1 text-xs font-normal text-amber-800">Unit unresolved</span>}
      {quantity.status === "value_requires_review" && <span className="ml-1 text-xs font-normal text-amber-800">Value unresolved</span>}
    </dd>
    {quantity.raw_unit !== null && quantity.unit !== null && quantity.raw_unit !== quantity.unit && <p className="text-xs text-slate-500">Source unit (raw): {quantity.raw_unit}</p>}
    {quantity.field === "tcn" && <p className="text-xs text-slate-600">Lowest tested temperature for a non-superconducting report; this is not Tc.</p>}
    {quantity.field === "pmax" && <p className="text-xs text-slate-600">Maximum applied pressure; pressure at the selected Tc is not established.</p>}
    {quantity.temperature_raw !== null && <p className="text-xs text-slate-600">Temperature condition (raw): {quantity.temperature_raw}; unit not supplied.</p>}
    {direction !== null && <p className="text-xs text-slate-600">Direction: {direction}</p>}
    {!criteria.has(quantity.field) && quantity.source_method_raw !== null && <p className="text-xs text-slate-600">Source method: {quantity.method_label ?? quantity.source_method_raw}{quantity.method_label && quantity.method_label !== quantity.source_method_raw ? ` (raw: ${quantity.source_method_raw})` : ""}{quantity.method_status === "requires_review" ? "; unresolved code" : ""}</p>}
  </div>;
}

export function ExternalSuperconReferences({ materialId }: { materialId: string }) {
  const publishAvailability = useProviderAvailabilityPublisher(materialId, "MDR");
  const headingId = useId();
  const [expansion, setExpansion] = useState({ materialId, open: false });
  const expanded = expansion.materialId === materialId && expansion.open;
  const [state, setState] = useState<{ materialId: string; report: MaterialSuperconReferences | null; failed: boolean }>({ materialId, report: null, failed: false });
  const report = state.materialId === materialId ? state.report : null;
  const failed = state.materialId === materialId && state.failed;
  useEffect(() => {
    if (!expanded) return;
    const controller = new AbortController();
    let settled = false;
    setState({ materialId, report: null, failed: false });
    publishAvailability(emptyProviderAvailability("MDR", "loading"));
    getMaterialSuperconReferences(materialId, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      if (!validReport(value)) throw new Error("SuperCon reference contract unavailable");
      settled = true;
      setState({ materialId, report: value, failed: false });
      publishAvailability(mapMaterialProviderAvailability("MDR", value));
    }).catch(() => {
      if (!controller.signal.aborted) { settled = true; setState({ materialId, report: null, failed: true }); publishAvailability(emptyProviderAvailability("MDR", "unavailable")); }
    });
    return () => { controller.abort(); if (!settled) publishAvailability(null); };
  }, [materialId, expanded, publishAvailability]);
  const summary = report?.status === "available" ? `${report.references.length} of ${report.matches_total} source rows`
    : failed || report?.status === "unavailable" ? "Unavailable" : report?.status === "no_match" ? "No match in this snapshot"
      : report?.status === "not_applicable" ? "Composition review needed" : expanded ? "Loading…" : "Inspect reported criteria";
  return <section id={MATERIAL_PROVIDER_ANCHORS.MDR} aria-labelledby={headingId} className="border-t border-sage-border pt-5">
    <details key={materialId} open={expanded} onToggle={event => {
      if (event.target === event.currentTarget) setExpansion({ materialId, open: event.currentTarget.open });
    }}>
      <summary className="cursor-pointer rounded-sm py-1 text-accent-deep focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent-deep">
        <span id={headingId} className="font-semibold">MDR SuperCon references</span><span className="ml-3 text-sm font-normal text-slate-600">{summary}</span>
      </summary>
      <div className="mt-3 space-y-3">
        {expanded && !report && !failed && <p role="status" className="text-sm text-slate-600">Loading the versioned SuperCon snapshot…</p>}
        {(failed || report?.status === "unavailable") && <p className="text-sm text-slate-600">This snapshot could not be assessed. Source coverage cannot be determined.</p>}
        {report?.status === "not_applicable" && <p className="text-sm text-slate-600">Resolve the exact source composition, isotope or interface notation before matching SuperCon rows.</p>}
        {report?.status === "no_match" && <p className="text-sm text-slate-600">No matching fixed-composition row was found in the oxide and metallic table of version 240322. Organic data and other versions are outside this view.</p>}
        {report?.status === "available" && <>
          <p className="max-w-4xl text-sm text-slate-600">Curated source rows matched by composition. Tc criteria remain separate; sample and phase correspondence require review.</p>
          <div className="overflow-x-auto rounded-lg border border-sage-border bg-white">
            <table className="w-full min-w-[760px] text-left text-sm">
              <caption className="sr-only">Versioned SuperCon source rows, preserving separate Tc criteria and raw units</caption>
              <thead className="border-b border-sage-border bg-slate-50 text-xs text-slate-600"><tr><th className="px-4 py-3">Source row</th><th className="px-4 py-3">Tc criteria / test limit</th><th className="px-4 py-3">Structure / sample</th><th className="px-4 py-3">Source details</th></tr></thead>
              <tbody className="divide-y divide-slate-100">{report.references.map(row => {
                const hasContext = row.structure.space_group || row.structure.space_group_number || row.structure.common_name || [row.sample_form, row.structure_method, row.tc_method].some(value => value.status !== "not_supplied");
                return <tr key={row.id}>
                <td className="px-4 py-3 align-top"><span className="font-medium">{row.source_row_id}</span><span className="mt-1 block text-xs text-slate-600">{row.formula}</span>{row.bibliography.publication_year_raw && <span className="mt-1 block text-xs text-slate-500">Source year: {row.bibliography.publication_year_raw}</span>}{row.sample_identifier && <span className="mt-1 block text-xs text-slate-500">Sample: {row.sample_identifier}</span>}</td>
                <td className="min-w-64 px-4 py-3 align-top"><dl className="space-y-2">{row.quantities.filter(q => criteria.has(q.field)).map(q => <Quantity key={q.field} quantity={q} />)}</dl>{!row.quantities.some(q => criteria.has(q.field)) && <span className="text-slate-500">Criteria not supplied</span>}</td>
                <td className="min-w-48 px-4 py-3 align-top">{row.structure.space_group && <p>{row.structure.space_group}</p>}{row.structure.space_group_number && <p className="text-xs text-slate-500">Space group no. {row.structure.space_group_number}</p>}{row.structure.common_name && <p className="text-xs text-slate-600">{row.structure.common_name}</p>}<dl className="mt-2 space-y-2 text-xs text-slate-600">{[{ label: "Sample form", value: row.sample_form }, { label: "Structure method", value: row.structure_method }, { label: "Tc method", value: row.tc_method }].filter(item => item.value.status !== "not_supplied").map(item => <div key={item.label}><dt className="text-slate-500">{item.label}</dt><dd><SourceCode value={item.value} /></dd></div>)}</dl>{!hasContext && <span className="text-slate-500">Context not supplied</span>}</td>
                <td className="px-4 py-3 align-top"><details><summary className="cursor-pointer text-accent-deep">Inspect source row</summary><div className="mt-2 min-w-64 space-y-3 text-xs text-slate-600">
                  {row.bibliography.title && <p>{row.bibliography.title}</p>}<p>{[row.bibliography.journal, row.bibliography.publication_year_raw].filter(Boolean).join(", ") || "Bibliography not supplied"}</p>
                  {row.bibliography.reference_code && <p>Database reference code: {row.bibliography.reference_code}</p>}
                  {row.raw_common_formula && <p>Common formula (raw): {row.raw_common_formula}</p>}
                  {row.structure.space_group_number_raw && row.structure.space_group_number === null && <p>Unresolved space group number (raw): {row.structure.space_group_number_raw}</p>}
                  {row.isotope_element && <p>Isotope element: {row.isotope_element}</p>}{row.isotope_exchange_ratio && <p>Isotope exchange ratio (raw): {row.isotope_exchange_ratio}</p>}
                  <dl className="space-y-2">{row.quantities.filter(q => !criteria.has(q.field)).map(q => <Quantity key={q.field} quantity={q} />)}</dl>
                  <a href={datasetUrl} target="_blank" rel="noopener noreferrer" className="block text-accent-deep underline">Versioned NIMS dataset ↗</a>
                  <details><summary className="cursor-pointer">Row provenance</summary><dl className="mt-2 space-y-2"><div><dt>Source file / lines</dt><dd>{row.source_file}:{row.source_line}{row.source_line_end !== row.source_line ? `-${row.source_line_end}` : ""}</dd></div><div><dt>Raw row SHA-256</dt><dd className="break-all font-mono">{row.source_row_sha256}</dd></div><div><dt>Source file SHA-256</dt><dd className="break-all font-mono">{row.source_sha256}</dd></div>{Object.entries(row.raw_source_method_fields).filter(([, value]) => value !== null).map(([field, value]) => <div key={field}><dt>Method column (raw): {field}</dt><dd>{value}</dd></div>)}</dl></details>
                </div></details></td>
              </tr>;
              })}</tbody>
            </table>
          </div>
          {report.omitted_rows > 0 && <p className="text-xs text-slate-600">{report.omitted_rows} additional matched rows omitted. Showing the first 20 in numeric source-row order.</p>}
          <p className="max-w-4xl text-xs text-slate-500">Version 240322 includes oxide and metallic source rows; Organic data is outside this view. Current publication status has not been checked. Row counts do not establish independent experiments.</p>
        </>}
        {report && <details className="text-xs text-slate-600"><summary className="cursor-pointer text-accent-deep">Dataset and attribution</summary><div className="mt-2 space-y-2"><p>{report.attribution}</p><p>SCLib projects selected source columns and normalizes recognized unit labels. Original values and method descriptions remain attributed to NIMS.</p><p><a href={datasetUrl} target="_blank" rel="noopener noreferrer" className="underline">MDR SuperCon version 240322 ↗</a>{" / "}<a href={licenseUrl} target="_blank" rel="noopener noreferrer" className="underline">CC BY 4.0 ↗</a></p>{report.snapshot_sha256 && <p className="break-all font-mono">Snapshot SHA-256: {report.snapshot_sha256}</p>}{report.resource_sha256 && <p className="break-all font-mono">Resource SHA-256: {report.resource_sha256}</p>}</div></details>}
      </div>
    </details>
  </section>;
}
