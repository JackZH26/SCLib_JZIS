"use client";

import { useEffect, useState } from "react";
import { getMaterialEnrichment } from "@/lib/api";
import type { MaterialEnrichmentReport, PropertyEvidenceItem } from "@/lib/api";
import Link from "@/components/AppLink";
import { evidenceText, objectValue, propertyValue, sourceHref } from "@/lib/property-evidence";

const labels: Record<string, string> = { tc_kelvin: "Tc", pressure_gpa: "Pressure", tc_criterion: "Tc criterion", measurement_method: "Method", space_group: "Space group", crystal_structure: "Structure label", lattice_a: "Lattice a", lattice_b: "Lattice b", lattice_c: "Lattice c", lambda_eph: "Electron–phonon coupling λ", omega_log_source_value: "Logarithmic phonon frequency", mu_star: "Coulomb pseudopotential μ*", hc2_tesla: "Upper critical field", atomic_sites: "Atomic sites", site_occupancies: "Site occupancies", composition_identity: "Composition identity", measurement_temperature_k: "Measurement temperature", calculation_method: "Calculation method" };
const statuses: Record<string, string> = { retained_present: "Retained extraction", pending_review: "Candidate found · review needed", source_unavailable: "Source identity unavailable", not_extracted: "Source text not checked", not_found_in_checked_sources: "No candidate in checked chunks" };
const routes: Record<string, string> = { source_fulltext_and_supplement: "Paper and supplement", source_table_and_supplement: "Source tables and supplement", supercon_source_lookup: "SuperCon source lookup", cod_structure_lookup: "COD structure match", mp_state_matched_structure: "MP structure match with state review", nomad_state_matched_calculation: "NOMAD run with state review", new_structure_calculation: "New structural calculation", new_electron_phonon_calculation: "New electron–phonon calculation" };
const readable = (value: string) => value.replaceAll("_", " ");

/** A parsed pending quantity may be displayed without promoting it to a selected fact. */
function candidateValue(candidate: Record<string, unknown>): string | null {
  const quantity = objectValue(candidate.quantity);
  if (Object.keys(quantity).length) {
    const formatted = propertyValue({ property: evidenceText(candidate.field) ?? "candidate", value: candidate.value ?? quantity.value ?? null, quantity } as PropertyEvidenceItem);
    if (formatted !== "—") return formatted;
  }
  // Original tokens can already contain a unit. Preserve them verbatim instead
  // of appending raw_unit or inferring a canonical unit when parsing failed.
  return evidenceText(candidate.raw_value) ?? evidenceText(candidate.value);
}
function primarySourceUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}
function structuredEntries(field: string, value: unknown): [string, string][] {
  const raw = objectValue(value);
  const fields: Record<string, string> = field === "composition_identity" ? {
    catalogue_formula: "Catalogue formula", source_formula: "Source formula", nominal_formula_raw: "Nominal formula (source)", refined_formula_raw: "Refined formula (source)", relation: "Proposed relationship",
  } : { site: "Site", fractional_coordinate_raw: "Fractional coordinate (source)", wyckoff_position: "Wyckoff position", coordinates_raw: "Coordinates (source)", interpretation: "Source interpretation" };
  const entries: [string, string][] = Object.entries(fields).flatMap(([key, label]) => {
    const text = evidenceText(raw[key]);
    if (!text) return [];
    return [[label, key === "relation" || key === "interpretation" ? readable(text) : text]];
  });
  const elements = Array.isArray(raw.site_elements) ? raw.site_elements.filter((item): item is string => typeof item === "string" && /^[A-Z][a-z]?$/.test(item)) : [];
  if (elements.length) entries.push(["Site elements", elements.join(" / ")]);
  for (const [element, fraction] of Object.entries(objectValue(raw.fractions_raw))) {
    const text = evidenceText(fraction);
    if (/^[A-Z][a-z]?$/.test(element) && text) entries.push([`${element} occupancy (source)`, text]);
  }
  return entries;
}
function StructuredCandidate({ candidate }: { candidate: Record<string, unknown> }) {
  const field = evidenceText(candidate.field) ?? "";
  const entries = structuredEntries(field, candidate.raw_value ?? candidate.value);
  if (!entries.length) return <p className="mt-2 text-xs text-slate-600">Structured value needs source inspection.</p>;
  return <dl className="mt-2 grid gap-2 text-xs sm:grid-cols-2" aria-label="Structured recovery candidate">{entries.map(([label, value]) => <div key={label}><dt className="text-slate-500">{label}</dt><dd className="mt-0.5 break-words text-slate-700">{value}</dd></div>)}<div className="sm:col-span-2 text-amber-800">{field === "composition_identity" ? "Nominal and refined formulas are a proposed sample association; they are not automatically equivalent." : "Site, occupancy and structure correspondence still need source review. These fields do not supply validated coordinates."}</div></dl>;
}
function sourceLocator(source: Record<string, unknown>): string {
  const locator = objectValue(source.locator);
  return ["page", "table", "figure", "section", "row", "column", "char_start", "char_end", "xml_xpath", "chunk_id"].flatMap(key => {
    const value = evidenceText(locator[key]);
    return value ? [`${readable(key)}: ${value}`] : [];
  }).join("; ");
}
export function MaterialEnrichment({ materialId }: { materialId: string }) {
  const [state, setState] = useState<{ materialId: string; report: MaterialEnrichmentReport | null; failed: boolean }>({ materialId, report: null, failed: false });
  const report = state.materialId === materialId ? state.report : null;
  const failed = state.materialId === materialId && state.failed;
  useEffect(() => {
    const controller = new AbortController();
    setState({ materialId, report: null, failed: false });
    getMaterialEnrichment(materialId, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      if (value.version !== "materials-enrichment/1.0.0" || value.scientific_acceptance !== false || value.database_changed !== false || !Array.isArray(value.coverage) || !Array.isArray(value.candidates)) throw new Error("Recovery contract unavailable");
      setState({ materialId, report: value, failed: false });
    }).catch(() => { if (!controller.signal.aborted) setState({ materialId, report: null, failed: true }); });
    return () => controller.abort();
  }, [materialId]);
  const fields = report?.coverage.find(row => row.material_id === materialId)?.fields ?? [];
  const missing = fields.filter(field => !field.retained_present);
  return <section className="border-t border-sage-border pt-6" aria-label="Field coverage and source recovery">
    <h2 className="text-lg font-semibold">Field coverage &amp; source recovery</h2>
    <p className="mt-1 max-w-3xl text-sm text-slate-600">See which fields are retained, which need source review, and where missing information can be recovered.</p>
    {!report && !failed && <p className="mt-3 text-sm text-slate-500" role="status">Checking linked source chunks…</p>}
    {failed && <p className="mt-3 text-sm text-slate-600">Source recovery is unavailable for this request. Retained values above are unchanged.</p>}
    {report && <>
      <p className="mt-3 text-sm text-slate-600">{fields.length - missing.length} fields have retained extractions in inspected records · {missing.length} need further source work · {report.candidates.length} recovery candidates.</p>
      {report.inspection_scope && <p className="mt-2 text-xs text-slate-500">Inspected {report.inspection_scope.records_inspected} of {report.inspection_scope.records_total} eligible retained records across {report.inspection_scope.papers_inspected} of {report.inspection_scope.papers_total} linked papers.{(report.inspection_scope.records_truncated || report.inspection_scope.papers_truncated) && " This is a sampled recovery check; remaining records and sources have not been inspected."}</p>}
      {report.candidates_truncated && <p className="mt-2 text-xs text-slate-500">A bounded list of 100 candidates was returned. Field counts may include additional candidates; none represents independent confirmation.</p>}
      <details className="mt-3 rounded-lg border border-sage-border bg-white p-4">
        <summary className="cursor-pointer text-sm font-medium">Inspect field coverage and recovery routes</summary>
        <p className="mt-3 text-xs text-slate-500">This bounded check covers linked chunks, not every full paper or supplement. A missing candidate does not establish that the paper omitted the property. Retained and candidate values still need sample, state and source review.</p>
        <div className="mt-3 overflow-x-auto"><table className="w-full text-left text-sm"><thead className="border-b border-slate-200 text-xs text-slate-500"><tr><th className="py-2 pr-4">Field</th><th className="py-2 pr-4">Coverage</th><th className="py-2">Recovery route</th></tr></thead><tbody className="divide-y divide-slate-100">{fields.map(field => <tr key={field.field}><td className="py-2 pr-4">{labels[field.field] ?? readable(field.field)}</td><td className="py-2 pr-4">{statuses[field.status] ?? readable(field.status)}{field.candidate_count > 0 && <span className="block text-xs text-slate-500">{field.candidate_count} source candidates</span>}</td><td className="py-2 text-xs text-slate-600">{field.routes.map(route => routes[route] ?? readable(route)).join("; ")}</td></tr>)}</tbody></table></div>
      </details>
      {report.candidates.length > 0 && <details className="mt-3 rounded-lg border border-sage-border bg-white p-4">
        <summary className="cursor-pointer text-sm font-medium">Source recovery candidates ({report.candidates.length})</summary>
        <p className="mt-3 text-xs text-slate-500">These extraction candidates are separate from the selected properties above. Source spans identify retained content; publication version and material-state correspondence may remain unresolved.</p>
        <ul className="mt-3 divide-y divide-slate-100">{report.candidates.slice(0, 40).map((candidate, index) => {
          const source = objectValue(candidate.source), quantity = objectValue(candidate.quantity);
          const value = candidateValue(candidate);
          const primaryUrl = primarySourceUrl(source.source_url);
          const paperHref = sourceHref(source);
          const field = evidenceText(candidate.field) ?? "Field";
          const structured = !value && Object.keys(objectValue(candidate.raw_value ?? candidate.value)).length > 0;
          return <li key={evidenceText(candidate.candidate_id) ?? index} className="py-3 text-sm">
            <p className="font-medium">{labels[field] ?? readable(field)}: {value ?? (field === "composition_identity" ? "Sample association proposal" : structured ? ["atomic_sites", "site_occupancies"].includes(field) ? "Reported site context" : "Structured source value" : "Value unavailable")} <span className="ml-2 text-xs font-normal text-amber-800">Review needed</span></p>
            {structured && <StructuredCandidate candidate={candidate} />}
            <p className="mt-1 text-xs text-slate-500">{evidenceText(source.paper_id) ?? "Source identifier unavailable"} · {readable(evidenceText(source.kind) ?? "unknown source")} {sourceLocator(source) && <span className="block">{sourceLocator(source)}</span>}</p>
            {primaryUrl ? <a className="mt-1 inline-block text-xs text-accent-deep underline" href={primaryUrl} target="_blank" rel="noopener noreferrer">Open primary source</a> : paperHref && <Link className="mt-1 inline-block text-xs text-accent-deep underline" href={paperHref}>Open linked paper</Link>}
            <details className="mt-2 text-xs"><summary className="cursor-pointer text-accent-deep">Source identity and checks</summary><dl className="mt-2 space-y-1 break-all text-slate-600">
              <div><dt className="inline">Raw source value: </dt><dd className="inline">{evidenceText(candidate.raw_value) ?? (structured ? "See structured fields above" : "Not supplied")}</dd></div>
              {Object.keys(quantity).length > 0 && <><div><dt className="inline">Source unit: </dt><dd className="inline">{evidenceText(quantity.raw_unit) ?? "Not supplied"}</dd></div><div><dt className="inline">Quantity relation / parser status: </dt><dd className="inline">{evidenceText(quantity.relation) ?? "Unavailable"} / {evidenceText(quantity.status) ?? "Unavailable"}</dd></div></>}
              <div><dt className="inline">Content hash: </dt><dd className="inline font-mono">{evidenceText(source.content_sha256)}</dd></div><div><dt className="inline">Retained revision: </dt><dd className="inline">{evidenceText(source.source_revision)}</dd></div>
              <div><dt className="inline">Source span: </dt><dd className="inline">{["char_start", "char_end", "text_sha256"].flatMap(key => evidenceText(objectValue(source.span)[key]) ? [`${readable(key)}: ${evidenceText(objectValue(source.span)[key])}`] : []).join("; ") || "Not supplied"}</dd></div><div><dt className="inline">Checks still required: </dt><dd className="inline">{Array.isArray(candidate.reason_codes) ? candidate.reason_codes.filter((code): code is string => typeof code === "string").map(readable).join("; ") : "Source and state review"}</dd></div></dl></details>
          </li>;
        })}</ul>
        {report.candidates.length > 40 && <p className="mt-2 text-xs text-slate-500">Showing the first 40 returned candidates.</p>}
      </details>}
    </>}
  </section>;
}
