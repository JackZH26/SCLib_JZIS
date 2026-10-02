"use client";

import { useEffect, useId, useState } from "react";
import { getMaterialEnrichment } from "@/lib/api";
import type { MaterialEnrichmentReport, PropertyEvidenceItem } from "@/lib/api";
import Link from "@/components/AppLink";
import { evidenceText, objectValue, propertyValue, sourceHref } from "@/lib/property-evidence";
import { MaterialClassificationCandidates } from "@/components/MaterialClassificationCandidates";
import { MaterialSourceObservations } from "@/components/MaterialSourceObservations";
import { sourceObservationsForRecovery } from "@/lib/material-source-observations";
import { useMaterialProviderAvailability } from "@/components/MaterialProviderAvailability";
import { downloadMaterialRecoveryMetadata, projectSourceCoverage, recoveryReasonLabel } from "@/lib/material-recovery-metadata";
import type { MaterialSourceCoverage } from "@/lib/api";
import { MATERIAL_PROVIDER_ANCHORS, MATERIAL_PROVIDER_LABELS } from "@/lib/material-provider-availability";
import type { MaterialReferenceProvider } from "@/lib/material-provider-availability";

const labels: Record<string, string> = { tc_kelvin: "Tc", pressure_gpa: "Pressure", tc_criterion: "Tc criterion", measurement_method: "Method", space_group: "Space group", crystal_structure: "Structure label", lattice_a: "Lattice a", lattice_b: "Lattice b", lattice_c: "Lattice c", lambda_eph: "Electron–phonon coupling λ", omega_log_source_value: "Logarithmic phonon frequency", mu_star: "Coulomb pseudopotential μ*", hc2_tesla: "Upper critical field", atomic_sites: "Atomic sites", site_occupancies: "Site occupancies", composition_identity: "Composition identity", measurement_temperature_k: "Measurement temperature", calculation_method: "Calculation method" };
const statuses: Record<string, string> = { retained_present: "Retained extraction", pending_review: "Candidate found · review needed", source_unavailable: "Source identity unavailable", not_extracted: "Not extracted", not_found_in_checked_sources: "No candidate in checked chunks", specialist_extraction_needed: "Specialist source extraction needed" };
const routes: Record<string, string> = { source_fulltext_and_supplement: "Paper and supplement", source_table_and_supplement: "Source tables and supplement", supercon_source_lookup: "SuperCon source lookup", cod_structure_lookup: "COD structure match", mp_state_matched_structure: "MP structure match with state review", nomad_state_matched_calculation: "NOMAD run with state review", new_structure_calculation: "New structural calculation", new_electron_phonon_calculation: "New electron–phonon calculation" };
const readable = (value: string) => value.replaceAll("_", " ");
Object.assign(labels, { sample_form: "Sample form", pairing_symmetry: "Pairing symmetry", is_unconventional: "Superconductivity classification", gap_structure: "Gap structure", reported_order: "Reported order", competing_order: "Competing order", lambda_london_nm: "London penetration depth", xi_gl_nm: "Coherence length", t_cdw_k: "CDW transition temperature", t_sdw_k: "SDW transition temperature", t_afm_k: "AFM transition temperature" });
Object.assign(labels, {
  minimum_temperature_k: "Minimum tested temperature", isotope_effect_exponent: "Isotope-effect exponent",
  debye_temperature_source_value: "Debye temperature", maximum_applied_pressure_source_value: "Maximum applied pressure",
  gap_ratio_source_value: "Gap ratio", gap_energy_source_value: "Gap energy", meissner_fraction_percent: "Meissner fraction",
  electronic_specific_heat_coefficient_source_value: "Electronic specific-heat coefficient",
  transition_width_source_value: "Transition width", dtc_dp_source_value: "Pressure derivative of Tc",
  hc1_source_value: "Lower critical field",
});
Object.assign(routes, { specialist_mechanism_study: "Specialist mechanism study", specialist_experiment: "Specialist experiment", new_calculation_or_experiment: "New calculation or experiment", new_composition_characterization: "New composition characterization", new_calculation_declared_assumption: "New calculation with declared assumptions", new_experiment_or_model_estimate: "New experiment or model estimate" });
const routeProviders: Record<string, MaterialReferenceProvider> = { supercon_source_lookup: "MDR", cod_structure_lookup: "COD", mp_state_matched_structure: "MP", nomad_state_matched_calculation: "NOMAD" };

function RecoveryRoutes({ values }: { values: string[] }) {
  return <ul className="space-y-1">{values.map(route => <li key={route}>{routeProviders[route] ? <a className="text-accent-deep underline underline-offset-2" href={`#${MATERIAL_PROVIDER_ANCHORS[routeProviders[route]]}`}>{routes[route] ?? readable(route)}</a> : routes[route] ?? readable(route)}</li>)}</ul>;
}
function ProviderFieldReferences({ field, values }: { field: string; values: string[] }) {
  const availability = useMaterialProviderAvailability();
  const providers = [...new Set([...values.flatMap(route => routeProviders[route] ? [routeProviders[route]] : []), ...(availability?.fields[field] ?? []).map(entry => entry.provider)])];
  if (!providers.length) return <span className="text-slate-500">No linked external property lookup</span>;
  const checked = providers.filter(provider => availability?.providers[provider] && availability.providers[provider]?.status !== "not_requested");
  if (!checked.length) return <span className="text-slate-500">Lookup not opened</span>;
  return <ul className="space-y-2">{checked.map(provider => {
    const state = availability!.providers[provider]!, entry = availability!.fields[field]?.find(value => value.provider === provider);
    const status = state.status === "loading" ? "Checking…" : state.status === "no_match" ? "No composition match" : state.status === "not_applicable" ? "Not applicable to this composition" : state.status === "unavailable" ? "Lookup unavailable" : "No returned value for this field";
    const unit = provider === "NOMAD" ? "task" : provider === "MDR" ? "source row" : "record";
    return <li key={provider}><a className="text-accent-deep underline underline-offset-2" href={`#${state.anchor}`}>{MATERIAL_PROVIDER_LABELS[provider]}</a>: {entry ? `${entry.reference_count} returned ${unit}${entry.reference_count === 1 ? "" : "s"}` : status}
      {entry && <><span className="mt-1 block text-slate-500">{entry.scope}</span>{entry.review_required_count > 0 && <span className="block text-slate-500">{entry.review_required_count} need value, unit or method interpretation.</span>}{state.truncated && <span className="block text-slate-500">Count covers the returned window.</span>}</>}
    </li>;
  })}</ul>;
}

/** A parsed pending quantity may be displayed without promoting it to a selected fact. */
function quantityText(field: string, value: unknown, quantity: unknown): string | null {
  const parsed = objectValue(quantity);
  if (!Object.keys(parsed).length) return null;
  const formatted = propertyValue({ property: field, value: value ?? parsed.value ?? null, quantity: parsed } as PropertyEvidenceItem);
  return formatted === "—" ? null : formatted;
}
function candidateValue(candidate: Record<string, unknown>): string | null {
  const sourceValue = objectValue(candidate.source_value);
  if (sourceValue.normalization === "none") return evidenceText(sourceValue.raw_value) ?? evidenceText(candidate.raw_value);
  const formatted = quantityText(evidenceText(candidate.field) ?? "candidate", candidate.value, candidate.quantity);
  if (formatted) return formatted;
  // Original tokens can already contain a unit. Preserve them verbatim instead
  // of appending raw_unit or inferring a canonical unit when parsing failed.
  return evidenceText(candidate.raw_value) ?? evidenceText(candidate.value);
}
function candidateContext(candidate: Record<string, unknown>): [string, string][] {
  const subject = objectValue(candidate.subject), field = evidenceText(candidate.field);
  const entries: [string, string][] = [];
  const sourceValue = objectValue(candidate.source_value);
  const roles: Record<string, string> = {
    study_extent: "Pressure range studied; association with Tc unresolved",
    measurement_limit: "Lowest measurement temperature; not a transition temperature",
    reported_order_transition: "Reported ordering transition; state association pending",
    reported_property: "Reported property; sample and state association pending",
  };
  const role = evidenceText(sourceValue.role) ?? evidenceText(subject.field_role);
  if (role && roles[role]) entries.push(["Source role", roles[role]]);
  if (field === "tc_kelvin") {
    const criterion = evidenceText(subject.tc_criterion) ?? "unknown";
    entries.push(["Tc criterion", ({ onset: "Onset", midpoint: "Midpoint", zero_resistance: "Zero resistance", unknown: "Unknown" } as Record<string, string>)[criterion] ?? readable(criterion)]);
    const pressure = quantityText("pressure_gpa", null, subject.pressure_quantity);
    const pressureState = evidenceText(subject.pressure_state);
    entries.push(["Pressure context", pressureState === "ambiguous" ? "Ambiguous in source context" : pressure && ["reported", "explicit_ambient"].includes(pressureState ?? "") ? `${pressure}${pressureState === "explicit_ambient" ? " (explicit ambient)" : ""}` : pressureState === "not_reported" ? "Not reported in source context" : "Unresolved"]);
  }
  if (field === "pressure_gpa") {
    // A pressure value or interval alone cannot identify its scientific role.
    // Only explicit role metadata can distinguish stability from a Tc condition.
    const role = evidenceText(subject.pressure_role) ?? evidenceText(candidate.pressure_role);
    entries.push(["Pressure role", role === "stability_range" ? "Stability range; not a Tc condition" : role === "tc_condition" ? "Tc condition; association pending" : "Unresolved; stability ranges are not Tc conditions"]);
    if (subject.pressure_state === "ambiguous") entries.push(["Pressure context", "Ambiguous in source context"]);
  }
  const origin = evidenceText(subject.knowledge_origin);
  if (origin || field === "tc_kelvin") entries.push(["Source origin", origin && ["Observed", "Computed", "Inferred", "AI-Proposed"].includes(origin) ? `${origin} report` : "Unknown"]);
  const method = evidenceText(subject.measurement_method);
  if (method) entries.push(["Method", readable(method)]);
  for (const [key, label] of [["sample_label", "Sample"], ["state_label", "State"], ["phase_label", "Phase"], ["run_label", "Run"]]) {
    const value = evidenceText(subject[key]);
    if (value) entries.push([label, value]);
  }
  const rowLabel = evidenceText(candidate.table_row_label);
  if (rowLabel) entries.push(["Source table row", rowLabel]);
  const sourceFormula = evidenceText(subject.source_formula) ?? evidenceText(subject.table_column_formula);
  if (sourceFormula) entries.push(["Source formula", sourceFormula]);
  const identity = evidenceText(subject.identity_basis);
  const associations: Record<string, string> = {
    retained_quantity_source_scoped_search_hit: "Source-scoped value match; local material binding unresolved",
    nominal_refined_composition_proposal: "Nominal/refined sample association pending",
    source_refinement_context_proposal: "Refined-site association pending",
    exact_table_column_formula: "Table-column association pending",
    exact_formula_local: "Local formula match; sample and state association pending",
  };
  if (identity) entries.push(["Association", associations[identity] ?? "Source, sample and state association pending"]);
  if ((field === "atomic_sites" || field === "site_occupancies") && candidateValue(candidate)) entries.push(["Structure", "Site and structure association pending; validated coordinates unavailable"]);
  return entries;
}
function CandidateContext({ candidate }: { candidate: Record<string, unknown> }) {
  const entries = candidateContext(candidate);
  return entries.length ? <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600" aria-label="Pending source context">{entries.map(([label, value]) => <div className="max-w-full break-words" key={label}><dt className="inline font-medium">{label}: </dt><dd className="inline">{value}</dd></div>)}</dl> : null;
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
const inspectionCount = (value: unknown) => typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString("en-US") : "Not inspected";
function SourceInspectionScope({ sources }: { sources: Record<string, MaterialSourceCoverage> }) {
  const entries = Object.entries(sources);
  if (!entries.length) return null;
  return <details className="mt-3 rounded-lg border border-sage-border bg-white p-4">
    <summary className="cursor-pointer text-sm font-medium">Per-paper inspection scope ({entries.length})</summary>
    <p className="mt-3 text-xs text-slate-500">Counts describe this bounded chunk request. Reading or supplying a chunk does not mean the full paper or supplement was checked. Uninspected counts remain unknown.</p>
    <ul className="mt-3 divide-y divide-slate-100">{entries.map(([paper, row]) => {
      const reasonCounts = { ...row.omitted_chunk_reasons, ...row.excluded_chunk_reasons };
      const reasons = [...new Set([...Object.keys(reasonCounts), ...(row.reason_codes ?? [])])];
      return <li key={paper} className="min-w-0 py-3 text-xs text-slate-600">
        <p className="break-words font-medium text-slate-700">{paper}</p>
        <p className="mt-1">{row.reason_codes?.includes("paper_sampling_limit") ? "Not sampled · paper limit" : row.chunks_inspected ? "Chunks read within this request" : "No chunks read in this request"}</p>
        <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
          {[["Indexed", row.indexed_chunks_total], ["Within length bounds", row.bounded_indexed_chunks_total], ["Considered", row.chunks_considered], ["Read", row.chunks_inspected], ["Supplied to extractor", row.chunks_supplied], ["Excluded", row.excluded_chunks_total], ["Omitted", row.omitted_chunks_total]].map(([label, count]) => <div key={String(label)}><dt className="text-slate-500">{label}</dt><dd className="mt-0.5 tabular-nums">{inspectionCount(count)}</dd></div>)}
        </dl>
        {reasons.length > 0 && <ul className="mt-2 list-disc space-y-1 pl-4">{reasons.map(reason => <li key={reason}>{recoveryReasonLabel(reason)}{reasonCounts[reason] !== undefined ? ` (${inspectionCount(reasonCounts[reason])} chunk${reasonCounts[reason] === 1 ? "" : "s"})` : ""}</li>)}</ul>}
      </li>;
    })}</ul>
  </details>;
}
export function MaterialEnrichment({ materialId }: { materialId: string }) {
  const [state, setState] = useState<{ materialId: string; report: MaterialEnrichmentReport | null; failed: boolean }>({ materialId, report: null, failed: false });
  const [candidateExpansion, setCandidateExpansion] = useState({ materialId, expanded: false });
  const [downloadFailure, setDownloadFailure] = useState<string | null>(null);
  const showAllCandidates = candidateExpansion.materialId === materialId && candidateExpansion.expanded;
  const candidateListId = useId();
  const report = state.materialId === materialId ? state.report : null;
  const failed = state.materialId === materialId && state.failed;
  useEffect(() => {
    const controller = new AbortController();
    setState({ materialId, report: null, failed: false });
    setCandidateExpansion({ materialId, expanded: false });
    setDownloadFailure(null);
    getMaterialEnrichment(materialId, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      if (value.version !== "materials-enrichment/1.0.0" || value.scientific_acceptance !== false || value.database_changed !== false || !Array.isArray(value.coverage) || !Array.isArray(value.candidates)) throw new Error("Recovery contract unavailable");
      setState({ materialId, report: value, failed: false });
    }).catch(() => { if (!controller.signal.aborted) setState({ materialId, report: null, failed: true }); });
    return () => controller.abort();
  }, [materialId]);
  const fields = report?.coverage.find(row => row.material_id === materialId)?.fields ?? [];
  const sourceCoverage = projectSourceCoverage(report?.coverage.find(row => row.material_id === materialId)?.source_coverage);
  const missing = fields.filter(field => !field.retained_present);
  const sourceObservations = report ? sourceObservationsForRecovery(report, materialId) : null;
  return <section className="border-t border-sage-border pt-6" aria-label="Field coverage and source recovery">
    <h2 className="text-lg font-semibold">Field coverage &amp; source recovery</h2>
    <p className="mt-1 max-w-3xl text-sm text-slate-600">See which fields are retained, which need source review, and where missing information can be recovered.</p>
    {!report && !failed && <p className="mt-3 text-sm text-slate-500" role="status">Checking linked source chunks…</p>}
    {failed && <p className="mt-3 text-sm text-slate-600">Source recovery is unavailable for this request. Retained values above are unchanged.</p>}
    {report && <>
      <p className="mt-3 text-sm text-slate-600">{fields.length - missing.length} fields have retained extractions in inspected records · {missing.length} need further source work · {report.candidates.length} recovery candidates.</p>
      {report.inspection_scope && <p className="mt-2 text-xs text-slate-500">Inspected {report.inspection_scope.records_inspected} of {report.inspection_scope.records_total} eligible retained records across {report.inspection_scope.papers_inspected} of {report.inspection_scope.papers_total} linked papers.{(report.inspection_scope.records_truncated || report.inspection_scope.papers_truncated) && " This is a sampled recovery check; remaining records and sources have not been inspected."}</p>}
      {report.inspection_scope?.chunks_inspected !== undefined && <p className="mt-1 text-xs text-slate-500">Read {report.inspection_scope.chunks_inspected} whole chunks within a {report.inspection_scope.chunks_limit ?? 40}-chunk limit, shared across selected papers. Full papers and supplements have not been checked by this request.</p>}
      {report.candidates_truncated && <p className="mt-2 text-xs text-slate-500">A bounded list of 100 candidates was returned. Field counts may include additional candidates; none represents independent confirmation.</p>}
      <div className="mt-3 text-xs"><button type="button" className="rounded text-accent-deep underline underline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent-deep" onClick={() => {
        try { setDownloadFailure(downloadMaterialRecoveryMetadata(report, materialId) ? null : materialId); }
        catch { setDownloadFailure(materialId); }
      }}>Download recovery metadata (JSON)</button><p className="mt-1 text-slate-500">Returned candidates, sources and record references. This is a bounded snapshot for review.</p>{downloadFailure === materialId && <p className="mt-1 text-slate-600" role="status">Metadata download is unavailable for this request.</p>}</div>
      <SourceInspectionScope sources={sourceCoverage} />
      <details className="mt-3 rounded-lg border border-sage-border bg-white p-4">
        <summary className="cursor-pointer text-sm font-medium">Inspect field coverage and recovery routes</summary>
        <p className="mt-3 text-xs text-slate-500">This bounded check covers linked chunks, not every full paper or supplement. A missing candidate does not establish that the paper omitted the property. Retained and candidate values still need sample, state and source review.</p>
        <p className="mt-2 text-xs text-slate-500">External field counts appear after opening a reference lookup below. They count returned composition references, not completed catalogue fields or independent experiments.</p>
        <div className="mt-3 overflow-x-auto"><table className="w-full text-left text-sm"><thead className="border-b border-slate-200 text-xs text-slate-500"><tr><th className="py-2 pr-4">Field</th><th className="py-2 pr-4">Coverage</th><th className="py-2 pr-4">Recovery route</th><th className="py-2">Queried external references</th></tr></thead><tbody className="divide-y divide-slate-100">{fields.map(field => <tr key={field.field}><td className="py-2 pr-4 align-top">{labels[field.field] ?? readable(field.field)}</td><td className="py-2 pr-4 align-top">{statuses[field.status] ?? readable(field.status)}{field.candidate_count > 0 && <span className="block text-xs text-slate-500">{field.candidate_count} source candidates</span>}{(field.classification_review_finding_count ?? 0) > 0 && <span className="block text-xs text-slate-500">{field.classification_review_finding_count} spans need assertion or subject review</span>}{field.reason_codes?.length > 0 && <details className="mt-1 text-xs text-slate-500"><summary className="cursor-pointer text-accent-deep">Why this status</summary><ul className="mt-1 space-y-1">{field.reason_codes.map(reason => <li key={reason}>{recoveryReasonLabel(reason)}</li>)}</ul></details>}</td><td className="py-2 pr-4 align-top text-xs text-slate-600"><RecoveryRoutes values={field.routes} /></td><td className="py-2 align-top text-xs text-slate-600"><ProviderFieldReferences field={field.field} values={field.routes} /></td></tr>)}</tbody></table></div>
      </details>
      {report.candidates.length > 0 && <details className="mt-3 rounded-lg border border-sage-border bg-white p-4">
        <summary className="cursor-pointer text-sm font-medium">Source recovery candidates ({report.candidates.length})</summary>
        <p className="mt-3 text-xs text-slate-500">These extraction candidates are separate from the selected properties above. Source spans identify retained content; publication version and material-state correspondence may remain unresolved.</p>
        <ul id={candidateListId} className="mt-3 divide-y divide-slate-100">{report.candidates.slice(0, showAllCandidates ? report.candidates.length : 40).map((candidate, index) => {
          const source = objectValue(candidate.source), quantity = objectValue(candidate.quantity), sourceValue = objectValue(candidate.source_value);
          const value = candidateValue(candidate);
          const primaryUrl = primarySourceUrl(source.source_url);
          const paperHref = sourceHref(source);
          const field = evidenceText(candidate.field) ?? "Field";
          const structured = !value && Object.keys(objectValue(candidate.raw_value ?? candidate.value)).length > 0;
          return <li key={evidenceText(candidate.candidate_id) ?? index} className="py-3 text-sm">
            <p className="font-medium">{labels[field] ?? readable(field)}: {value ?? (field === "composition_identity" ? "Sample association proposal" : structured ? ["atomic_sites", "site_occupancies"].includes(field) ? "Reported site context" : "Structured source value" : "Value unavailable")} <span className="ml-2 text-xs font-normal text-amber-800">Review needed</span></p>
            <CandidateContext candidate={candidate} />
            {structured && <StructuredCandidate candidate={candidate} />}
            <p className="mt-1 text-xs text-slate-500">{evidenceText(source.paper_id) ?? "Source identifier unavailable"} · {readable(evidenceText(source.kind) ?? "unknown source")} {sourceLocator(source) && <span className="block">{sourceLocator(source)}</span>}</p>
            {primaryUrl ? <a className="mt-1 inline-block text-xs text-accent-deep underline" href={primaryUrl} target="_blank" rel="noopener noreferrer">Open primary source</a> : paperHref && <Link className="mt-1 inline-block text-xs text-accent-deep underline" href={paperHref}>Open linked paper</Link>}
            <details className="mt-2 text-xs"><summary className="cursor-pointer text-accent-deep">Source identity and checks</summary><dl className="mt-2 space-y-1 break-words text-slate-600">
              <div><dt className="inline">Candidate ID: </dt><dd className="inline font-mono">{evidenceText(candidate.candidate_id) ?? "Not supplied"}</dd></div>
              {Array.isArray(candidate.retained_result_refs) && <div><dt className="inline">Retained record references: </dt><dd className="inline">{candidate.retained_result_refs.length}; full identifiers are included in the metadata download, not counts of independent experiments.</dd></div>}
              <div><dt className="inline">Raw source value: </dt><dd className="inline">{evidenceText(candidate.raw_value) ?? (structured ? "See structured fields above" : "Not supplied")}</dd></div>
              {sourceValue.normalization === "none" && <>
                <div><dt className="inline">Source unit: </dt><dd className="inline">{evidenceText(sourceValue.raw_unit) ?? "No unit printed"}</dd></div>
                {evidenceText(sourceValue.raw_uncertainty) && <div><dt className="inline">Printed uncertainty: </dt><dd className="inline">{evidenceText(sourceValue.raw_uncertainty)}</dd></div>}
                <div><dt className="inline">Value handling: </dt><dd className="inline">Original source tokens; no unit conversion or uncertainty interpretation</dd></div>
                {evidenceText(sourceValue.field_cue) && <div><dt className="inline">Property label in source: </dt><dd className="inline">{evidenceText(sourceValue.field_cue)}</dd></div>}
                {Array.isArray(sourceValue.qualifiers) && sourceValue.qualifiers.length > 0 && <div><dt className="inline">Context requiring review: </dt><dd className="inline">{sourceValue.qualifiers.filter((code): code is string => typeof code === "string").map(recoveryReasonLabel).join("; ")}</dd></div>}
              </>}
              {Object.keys(quantity).length > 0 && <><div><dt className="inline">Source unit: </dt><dd className="inline">{evidenceText(quantity.raw_unit) ?? "Not supplied"}</dd></div><div><dt className="inline">Quantity relation / parser status: </dt><dd className="inline">{evidenceText(quantity.relation) ?? "Unavailable"} / {evidenceText(quantity.status) ?? "Unavailable"}</dd></div></>}
              <div><dt className="inline">Content hash: </dt><dd className="inline font-mono">{evidenceText(source.content_sha256)}</dd></div><div><dt className="inline">Retained revision: </dt><dd className="inline">{evidenceText(source.source_revision)}</dd></div>
              <div><dt className="inline">Source span: </dt><dd className="inline">{["char_start", "char_end", "text_sha256"].flatMap(key => evidenceText(objectValue(source.span)[key]) ? [`${readable(key)}: ${evidenceText(objectValue(source.span)[key])}`] : []).join("; ") || "Not supplied"}</dd></div><div><dt className="inline">Checks still required: </dt><dd className="inline">{Array.isArray(candidate.reason_codes) ? candidate.reason_codes.filter((code): code is string => typeof code === "string").map(recoveryReasonLabel).join("; ") : "Source and state review"}</dd></div></dl></details>
          </li>;
        })}</ul>
        {report.candidates.length > 40 && <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs"><p className="text-slate-500">Showing {showAllCandidates ? report.candidates.length : 40} of {report.candidates.length} returned candidates.</p><button type="button" className="rounded text-accent-deep underline underline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent-deep" aria-expanded={showAllCandidates} aria-controls={candidateListId} onClick={() => setCandidateExpansion({ materialId, expanded: !showAllCandidates })}>{showAllCandidates ? "Show fewer candidates" : `Show remaining candidates (${report.candidates.length - 40})`}</button></div>}
      </details>}
      {["materials-source-statement-extractor/1.0.0", "materials-source-statement-extractor/1.0.1"].includes(report.classification_extractor_version ?? "") && <MaterialClassificationCandidates materialId={materialId} candidates={Array.isArray(report.classification_candidates) ? report.classification_candidates : []} findings={Array.isArray(report.classification_review_findings) ? report.classification_review_findings : []} truncated={report.classification_candidates_truncated === true} findingsTruncated={report.classification_review_findings_truncated === true} />}
      {sourceObservations && <div className="mt-4"><MaterialSourceObservations window={sourceObservations} /></div>}
    </>}
  </section>;
}
