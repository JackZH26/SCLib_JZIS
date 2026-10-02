"use client";

import { useId, useState } from "react";
import Link from "@/components/AppLink";
import { objectValue, propertyValue, sourceHref } from "@/lib/property-evidence";
import type { PropertyEvidenceItem } from "@/lib/api";

const fields: Record<string, string> = {
  pairing_symmetry: "Pairing symmetry", is_unconventional: "Superconductivity classification",
  gap_structure: "Gap structure", reported_order: "Reported order", competing_order: "Competing order",
};
const stances: Record<string, string> = {
  reported: "Author report", fitted: "Fitted model", proposed: "Proposed interpretation",
  not_detected: "Not detected in reported scope",
};
const readable = (value: string) => value.replaceAll("_", " ");
const text = (value: unknown): string | null => typeof value === "string" && value.trim() ? value : null;
const count = (value: unknown): number | null => typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : null;
function primaryUrl(value: unknown): string | null {
  if (!text(value)) return null;
  try {
    const url = new URL(value as string);
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}
function locator(source: Record<string, unknown>): string {
  const location = objectValue(source.locator);
  return ["page", "table", "figure", "section", "row", "column", "char_start", "char_end", "xml_xpath", "chunk_id"].flatMap(key => {
    const value = location[key];
    return typeof value === "string" || (typeof value === "number" && Number.isFinite(value)) ? [`${readable(key)}: ${value}`] : [];
  }).join("; ");
}
function sourceLink(source: Record<string, unknown>) {
  const primary = primaryUrl(source.source_url), linked = sourceHref(source);
  return primary ? <a className="mt-1 inline-block text-xs text-accent-deep underline" href={primary} target="_blank" rel="noopener noreferrer">Open primary source</a>
    : linked ? <Link className="mt-1 inline-block text-xs text-accent-deep underline" href={linked}>Open linked paper</Link> : null;
}
function validCandidate(candidate: Record<string, unknown>, materialId: string) {
  const claim = objectValue(candidate.claim);
  return candidate.version === "material-classification-candidates/1.0.0" && candidate.material_id === materialId &&
    candidate.disposition === "pending" && candidate.source_content_checked === false && candidate.material_state_reviewed === false &&
    ["scientific_acceptance", "ml_training_approved", "public_release", "database_changed"].every(key => candidate[key] === false) &&
    typeof candidate.field === "string" && !!fields[candidate.field] && typeof claim.stance === "string" && !!stances[claim.stance] &&
    claim.scope === "source_statement_only" && claim.source_role === "author_report" && !!text(claim.value_raw) && !!text(claim.normalized_value);
}
function conditionLabels(subject: Record<string, unknown>) {
  const conditions = objectValue(subject.conditions), mentions = Array.isArray(conditions.mentions) ? conditions.mentions : [];
  const labels: string[] = [];
  for (const mention of mentions.slice(0, 12)) {
    const item = objectValue(mention), kind = text(item.kind);
    const field = kind === "pressure" ? "pressure_gpa" : kind === "temperature" ? "measurement_temperature_k" : kind === "magnetic_field" ? "magnetic_field_t" : null;
    if (!field) continue;
    const quantity = objectValue(item.quantity);
    const parsed = quantity.status === "parsed" ? propertyValue({ property: field, value: quantity.value ?? null, quantity } as PropertyEvidenceItem) : null;
    const raw = [text(item.raw_value), text(item.raw_unit)].filter(Boolean).join(" ");
    if (parsed && parsed !== "—") labels.push(`${readable(kind!)}: ${parsed}`);
    else if (raw) labels.push(`${readable(kind!)}: ${raw} (unresolved)`);
  }
  if (conditions.pressure_status === "explicit_ambient_statement") labels.push("explicit ambient-pressure statement");
  return labels;
}
function Candidate({ candidate }: { candidate: Record<string, unknown> }) {
  const claim = objectValue(candidate.claim), subject = objectValue(candidate.subject), source = objectValue(candidate.source);
  const binding = objectValue(subject.binding_proposal), bindingSource = objectValue(binding.source);
  const conditions = conditionLabels(subject), refs = count(candidate.retained_reference_count);
  const methodLabels: Record<string, string> = { point_contact_spectroscopy: "Point-contact spectroscopy", musr: "Muon-spin rotation / relaxation", arpes: "ARPES", stm: "Scanning tunnelling microscopy", resistivity: "Resistivity", susceptibility: "Susceptibility", neutron_diffraction: "Neutron diffraction", nmr: "NMR", specific_heat: "Specific heat" };
  const methods = Array.isArray(subject.methods) ? subject.methods.flatMap(value => {
    const name = text(objectValue(value).name);
    return name && methodLabels[name] ? [methodLabels[name]] : [];
  }) : [];
  return <li className="min-w-0 break-words py-3 text-sm">
    <p className="font-medium">{fields[String(candidate.field)]}: {String(claim.value_raw)} <span className="ml-2 text-xs font-normal text-amber-800">{stances[String(claim.stance)]} · Review needed</span></p>
    <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600" aria-label="Pending classification context">
      <div><dt className="inline font-medium">Source subject: </dt><dd className="inline">{text(subject.formula_raw) ?? "Unresolved"}</dd></div>
      {text(subject.sample_label) && <div><dt className="inline font-medium">Sample: </dt><dd className="inline">{text(subject.sample_label)}</dd></div>}
      {methods.length > 0 && <div><dt className="inline font-medium">Local methods: </dt><dd className="inline">{methods.join("; ")}</dd></div>}
      {conditions.length > 0 && <div className="max-w-full break-words"><dt className="inline font-medium">Local condition mentions: </dt><dd className="inline">{conditions.join("; ")}. Association and tested window need review.</dd></div>}
      <div><dt className="inline font-medium">Association: </dt><dd className="inline">{subject.identity_basis === "explicit_source_alias_definition_proposal" ? "Source-defined alias proposal; sample and state review pending" : "Local subject proposal; sample and state review pending"}</dd></div>
      {claim.relation_to_superconductivity === "competes" && <div><dt className="inline font-medium">Source relationship: </dt><dd className="inline">Competition with superconductivity reported</dd></div>}
      {claim.relation_to_superconductivity === "coexists" && <div><dt className="inline font-medium">Source relationship: </dt><dd className="inline">Coexistence with superconductivity reported</dd></div>}
    </dl>
    {claim.stance === "not_detected" && <p className="mt-2 text-xs text-amber-800">Non-detection applies to the reported test scope. It does not establish absence in this material under every condition.</p>}
    <p className="mt-2 break-words text-xs text-slate-500">{text(source.paper_id) ?? "Source identifier unavailable"}{locator(source) && <span className="block">{locator(source)}</span>}</p>
    {sourceLink(source)}
    <details className="mt-2 text-xs"><summary className="cursor-pointer text-accent-deep">Source identity and statement checks</summary>
      <dl className="mt-2 space-y-1 break-words text-slate-600">
        <div><dt className="inline">Normalized source label: </dt><dd className="inline">{text(claim.normalized_value)}</dd></div>
        <div><dt className="inline">Statement role: </dt><dd className="inline">Author statement; original content and assertion role still need review.</dd></div>
        <div><dt className="inline">Source revision: </dt><dd className="inline">{text(source.source_revision) ?? "Unresolved"}{source.publication_revision_verified !== true && "; publication version not verified"}</dd></div>
        <div><dt className="inline">Source capture: </dt><dd className="inline break-all">{text(source.capture_id) ?? "Unresolved"}</dd></div>
        <div><dt className="inline">Statement span: </dt><dd className="inline">{count(objectValue(source.span).char_start) ?? "Unresolved"} to {count(objectValue(source.span).char_end) ?? "Unresolved"}</dd></div>
        <div><dt className="inline">Content hash: </dt><dd className="inline break-all font-mono">{text(source.content_sha256)}</dd></div>
        <div><dt className="inline">Statement hash: </dt><dd className="inline break-all font-mono">{text(objectValue(source.span).text_sha256)}</dd></div>
        {refs !== null && <div><dt className="inline">Retained record references: </dt><dd className="inline">{refs}; these are references to this statement, not independent experiments.</dd></div>}
        {Object.keys(bindingSource).length > 0 && <div className="pt-2"><dt>Subject definition source:</dt><dd>{text(binding.alias_raw)}{text(binding.doping_assignment_raw) && ` · ${text(binding.doping_assignment_raw)}`}<span className="block">{locator(bindingSource)}</span>{sourceLink(bindingSource)}<span className="block break-all font-mono">{text(bindingSource.content_sha256)}</span></dd></div>}
      </dl>
    </details>
  </li>;
}

export function MaterialClassificationCandidates({ materialId, candidates = [], findings = [], truncated = false, findingsTruncated = false }: {
  materialId: string; candidates?: Array<Record<string, unknown>>; findings?: Array<Record<string, unknown>>; truncated?: boolean; findingsTruncated?: boolean;
}) {
  const [expansion, setExpansion] = useState({ materialId, expanded: false });
  const expanded = expansion.materialId === materialId && expansion.expanded, listId = useId();
  const rows = candidates.map(objectValue).filter(candidate => validCandidate(candidate, materialId));
  const review = findings.map(objectValue).filter(finding => finding.material_id === materialId && Array.isArray(finding.fields) && Array.isArray(finding.reason_codes));
  if (!rows.length && !review.length) return null;
  return <>
    {rows.length > 0 && <details className="mt-3 rounded-lg border border-sage-border bg-white p-4">
      <summary className="cursor-pointer text-sm font-medium">Pairing, gap and order source statements ({rows.length})</summary>
      <p className="mt-3 text-xs text-slate-500">Author reports, fitted models, proposed interpretations and scoped non-detections are separate. These pending source statements do not change the selected material properties.</p>
      {truncated && <p className="mt-2 text-xs text-slate-500">Only a bounded set of source statements was returned. Unreturned statements and unchecked sources remain unresolved.</p>}
      <ul id={listId} className="mt-3 divide-y divide-slate-100">{rows.slice(0, expanded ? rows.length : 40).map((candidate, index) => <Candidate key={text(candidate.candidate_id) ?? index} candidate={candidate} />)}</ul>
      {rows.length > 40 && <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-xs"><p className="text-slate-500">Showing {expanded ? rows.length : 40} of {rows.length} returned source statements.</p><button type="button" className="rounded text-accent-deep underline underline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent-deep" aria-expanded={expanded} aria-controls={listId} onClick={() => setExpansion({ materialId, expanded: !expanded })}>{expanded ? "Show fewer source statements" : `Show remaining source statements (${rows.length - 40})`}</button></div>}
    </details>}
    {review.length > 0 && <details className="mt-3 rounded-lg border border-sage-border bg-white p-4">
      <summary className="cursor-pointer text-sm font-medium">Source statements requiring closer inspection ({review.length})</summary>
      <p className="mt-3 text-xs text-slate-500">These spans were not assigned a property candidate because their subject, assertion role or scope needs review. They are not evidence that the property is absent.</p>
      {findingsTruncated && <p className="mt-2 text-xs text-slate-500">Review findings also have a bounded returned window; additional unresolved spans may exist.</p>}
      <ul className="mt-3 divide-y divide-slate-100">{review.slice(0, 100).map((finding, index) => {
        const source = objectValue(finding.source);
        return <li key={index} className="py-2 text-xs text-slate-600"><p>{(finding.fields as unknown[]).filter((value): value is string => typeof value === "string" && !!fields[value]).map(value => fields[value]).join("; ")}</p><p className="mt-1">{(finding.reason_codes as unknown[]).filter((value): value is string => typeof value === "string").map(readable).join("; ")}</p><p className="mt-1 break-words">{text(source.paper_id)} · {locator(source)}</p>{sourceLink(source)}</li>;
      })}</ul>
      {review.length > 100 && <p className="mt-2 text-xs text-slate-500">Showing the first 100 of {review.length} returned review findings.</p>}
    </details>}
  </>;
}
