import Link from "next/link";
import type { MaterialSemanticEvidence, MaterialSemanticField } from "@/lib/api";
import { objectValue } from "@/lib/property-evidence";
import { knownMaterialSemantics, MATERIAL_SEMANTIC_FIELDS, MATERIAL_SEMANTIC_LABELS, materialSemanticProperty, materialSemanticValue, negativeEvidenceQualified, semanticCount, semanticEvidence, semanticText } from "@/lib/material-semantics";

function textList(value: unknown): string[] { return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : []; }
function displayValue(value: unknown): string { return typeof value === "boolean" ? String(value) : semanticText(value) ?? "Unavailable"; }
function countLabel(value: unknown): string { const count = semanticCount(value); return count === null ? "Unknown" : count.toLocaleString("en-US"); }

/** Compact cells use only the current declared-report projection, never family priors. */
export function MaterialSemanticValue({ semantics, field }: { semantics: unknown; field: MaterialSemanticField }) {
  const property = materialSemanticProperty(semantics, field);
  return <div className="text-xs text-sage-ink" data-semantic-field={field}>
    <span>{materialSemanticValue(semantics, field)}</span>
    <span className="mt-0.5 block text-[10px] text-slate-500">{property?.status === "reported" ? "Source-reported · not verified" : property ? "Not a negative finding" : "Semantics unavailable"}</span>
  </div>;
}

export function MaterialSemanticsMini({ semantics }: { semantics: unknown }) {
  return <dl className="space-y-2 text-xs" aria-label="Reported material classifications">{MATERIAL_SEMANTIC_FIELDS.map(field => <div key={field}><dt className="text-slate-500">{MATERIAL_SEMANTIC_LABELS[field]}</dt><dd><MaterialSemanticValue semantics={semantics} field={field} /></dd></div>)}</dl>;
}

export function MaterialSemanticsPanel({ semantics }: { semantics: unknown }) {
  const known = knownMaterialSemantics(semantics);
  const support = objectValue(known?.support);
  const conflicts = objectValue(known?.conflicts);
  const priors = Array.isArray(known?.priors) ? known.priors.filter(prior => prior && typeof prior === "object") : [];
  return <section className="space-y-4 rounded-lg border border-slate-200 bg-white p-4" aria-label="Material classification semantics">
    <div><h2 className="text-base font-semibold text-sage-ink">Reported classifications, priors and support</h2><p className="mt-1 text-xs text-slate-600">Unknown, not reported, reported false and not applicable are distinct states. A scoped negative report does not establish universal absence. Reported classifications are source assertions, not scientific approval or a joint Tc/state observation.</p></div>
    {!known && <p className="rounded border border-amber-200 bg-amber-50 p-3 text-xs text-amber-950">Compatible material-semantics metadata is unavailable. Legacy flags and family labels are not used to infer these properties, a scientific dispute, or independent confirmation.</p>}
    {known && support.assessment_complete !== true && <p className="rounded border border-amber-200 bg-amber-50 p-3 text-xs text-amber-950">The semantics assessment is incomplete or its completeness is unknown. No reported-property value is promoted from this incomplete envelope.</p>}
    <div className="overflow-x-auto"><table className="w-full text-left text-xs"><caption className="pb-2 text-left text-slate-500">Current reported-property projection; inspect individual evidence before reuse.</caption><thead className="border-b bg-slate-50"><tr><th scope="col" className="p-2">Property</th><th scope="col" className="p-2">Reported status / value</th><th scope="col" className="p-2">Evidence and conditions</th></tr></thead><tbody>{MATERIAL_SEMANTIC_FIELDS.map(field => {
      const property = materialSemanticProperty(semantics, field);
      const rawProperty = objectValue(known?.properties[field]);
      const evidence = semanticEvidence(semantics, field);
      return <tr className="border-b align-top" key={field}><th scope="row" className="p-2 font-medium">{MATERIAL_SEMANTIC_LABELS[field]}</th><td className="p-2"><MaterialSemanticValue semantics={semantics} field={field} />{property?.basis && <p className="mt-1 text-[10px] text-slate-500">Basis: {property.basis.replaceAll("_", " ")}</p>}</td><td className="min-w-[12rem] p-2">{evidence.length ? <details><summary className="cursor-pointer text-sky-800">Inspect {evidence.length} retained report{evidence.length === 1 ? "" : "s"}</summary><ul className="mt-2 space-y-2">{evidence.map((item, index) => <SemanticEvidenceItem key={`${item.result_id ?? "unknown"}:${index}`} item={item} />)}</ul></details> : <span>No attributable evidence supplied.</span>}{rawProperty.evidence_truncated === true && <p className="mt-1 text-amber-900">Evidence list truncated: {countLabel(rawProperty.total_evidence)} total reports. Open source records for the full context.</p>}{textList(rawProperty.reason_codes).length > 0 && <p className="mt-1 text-slate-500">Reasons: {textList(rawProperty.reason_codes).map(reason => reason.replaceAll("_", " ")).join("; ")}</p>}</td></tr>;
    })}</tbody></table></div>

    <div className="rounded border border-slate-200 bg-slate-50 p-3"><h3 className="text-sm font-semibold">Family and domain priors · Inferred, not measured</h3><p className="mt-1 text-xs text-slate-600">Priors are assumptions for research context. They do not populate reported-property cells or classification filters, and are not observed labels for ML.</p>{priors.length ? <ul className="mt-2 space-y-2 text-xs">{priors.map((prior, index) => <li className="rounded border border-slate-200 bg-white p-2" key={index}><p><span className="font-medium">{semanticText(prior.property) ?? "Unspecified prior"}</span>: {displayValue(prior.value)} · {prior.knowledge_origin === "Inferred" ? "Inferred prior" : "Prior origin unverified"}</p><p className="mt-1 text-slate-600">Basis: {semanticText(prior.basis) ?? "Unknown"} · policy: {semanticText(prior.policy_version) ?? "Unknown"}</p><ContextDetails title="Prior provenance / applicability" value={{ ...pickContext(prior.provenance, ["kind", "family", "source", "scientific_citation", "rule_id", "version", "policy_version"]), ...pickContext(prior.applicability, ["family", "material_family", "sample_state", "universally_applicable", "description", "regime", "conditions"]) }} />{textList(prior.warning_codes).length > 0 && <p className="mt-1 text-amber-900">{textList(prior.warning_codes).map(warning => warning.replaceAll("_", " ")).join("; ")}</p>}</li>)}</ul> : <p className="mt-2 text-xs text-slate-500">{known ? "No priors supplied in this response." : "Prior metadata unavailable."}</p>}</div>

    <div><h3 className="text-sm font-semibold">Variation, extraction conflicts and scientific disputes</h3><div className="mt-2 grid gap-3 md:grid-cols-3"><ConflictSummary kind="state_variability" value={conflicts.state_variability} /><ConflictSummary kind="extraction_conflict" value={conflicts.extraction_conflict} /><ConflictSummary kind="scientific_dispute" value={conflicts.scientific_dispute} /></div></div>

    <div className="rounded border border-slate-200 p-3">
      <h3 className="text-sm font-semibold">Source support counts · not independent confirmation</h3>
      <dl className="mt-2 grid gap-2 text-xs sm:grid-cols-2">
        {[["Source occurrences", support.occurrence_count], ["Bibliographic identifiers", support.bibliographic_identifier_count], ["Occurrences with source identifiers", support.source_backed_occurrence_count], ["Legacy catalogue paper links", support.legacy_total_papers]].map(([label, count]) => <div key={String(label)}><dt className="text-slate-500">{String(label)}</dt><dd>{countLabel(count)}</dd></div>)}
        <div><dt className="text-slate-500">Independent works</dt><dd>Unknown — not established</dd></div>
        <div><dt className="text-slate-500">Independent replications</dt><dd>Unknown — not established</dd></div>
      </dl>
      <p className="mt-2 text-xs text-slate-600">DOI, arXiv and catalogue identifiers may refer to the same work. Legacy paper links may include parent rollups or a different catalogue policy, so these counts need not match. Multiple occurrences or papers do not establish independent experimental replication, agreement, or scientific validity.</p>
      {semanticText(support.count_basis) && <p className="mt-1 break-words text-[10px] text-slate-500">Count basis: {String(support.count_basis).replaceAll("_", " ")}</p>}
    </div>
    {textList(known?.warnings).length > 0 && <details className="text-xs"><summary className="cursor-pointer">Semantics warnings</summary><ul className="mt-2 list-disc pl-4">{textList(known?.warnings).map((warning, index) => <li key={index}>{warning.replaceAll("_", " ")}</li>)}</ul></details>}
  </section>;
}

function SemanticEvidenceItem({ item }: { item: MaterialSemanticEvidence }) {
  const paper = semanticText(item.paper_id);
  const identifiers = Array.isArray(item.bibliographic_identifiers) ? item.bibliographic_identifiers.filter(id => semanticText(id?.kind) && semanticText(id?.value)) : [];
  return <li className="max-w-xl rounded border border-slate-200 bg-slate-50 p-2 text-sage-ink">
    <p className="font-medium">Retained report: {displayValue(item.value)}</p>
    <p className="mt-1">{item.value === false ? negativeEvidenceQualified(item)
      ? "Negative report with stated detection conditions; absence is scoped, not universal."
      : "Unqualified negative report: does not establish absence."
      : "Source assertion only; not a verified material property."}</p>
    {semanticText(item.source_value) && <p className="mt-1">Reported order label: {String(item.source_value)}. An order label does not establish causal competition with superconductivity.</p>}
    {semanticText(item.status_reason) && <p className="mt-1">Source-stated status reason: {item.status_reason}</p>}
    <p className="mt-1 break-all text-[10px]">Result: {semanticText(item.result_id) ?? "Unknown"} · revision: {typeof item.result_revision === "number" && Number.isFinite(item.result_revision) ? item.result_revision : semanticText(item.result_revision) ?? "Unknown"}</p>
    {semanticCount(item.occurrence_count) !== null && <p className="mt-1 text-[10px]">Retained occurrences: {countLabel(item.occurrence_count)} · repeated records are not replications.</p>}
    {paper ? <Link className="mt-1 inline-block break-all text-sky-800 underline" href={`/paper/${encodeURIComponent(paper)}`}>{paper}</Link> : <p className="mt-1 text-amber-900">No direct paper link supplied.</p>}
    {identifiers.length > 0 && <p className="mt-1 break-all">Identifiers: {identifiers.map(id => `${id.kind}: ${id.value}`).join("; ")}</p>}
    <p className="mt-1">Source status: {semanticText(item.source_status) ?? "Unknown"} · origin: {semanticText(item.knowledge_origin) ?? "Unknown"} · role: {semanticText(item.source_role) ?? "Unknown"}</p>
    <p className="mt-1">Method: {semanticText(item.method) ?? "Not reported"} · evidence status: {semanticText(item.status) ?? "Unknown"}</p>
    <ContextDetails title="State / conditions" value={pickContext(item.state, ["state_id", "material_state_id", "sample_id", "structure_id", "run_id", "sample_form", "phase", "structure_phase", "pressure", "pressure_gpa", "temperature_k", "magnetic_field_t", "pressure_type", "doping_level", "doping_type", "doping", "composition", "substrate", "strain", "conditions", "protocol_id", "tc_criterion"])} />
    <ContextDetails title="Detection conditions" value={pickContext(item.detection_conditions, ["description", "temperature_min_k", "temperature_max_k", "magnetic_field_t", "pressure_gpa", "detection_limit", "protocol_id"])} />
    <ContextDetails title="Source locator" value={pickContext(item.source_locator, ["page", "table", "figure", "row", "column", "section", "chunk_id", "span_id"])} />
    {textList(item.reason_codes).length > 0 && <p className="mt-1 text-amber-900">{textList(item.reason_codes).map(reason => reason.replaceAll("_", " ")).join("; ")}</p>}
  </li>;
}

function pickContext(raw: unknown, keys: string[]): Record<string, unknown> {
  const value = objectValue(raw);
  const result = Object.fromEntries(keys.filter(key => value[key] === null || typeof value[key] === "string" || typeof value[key] === "boolean" || (typeof value[key] === "number" && Number.isFinite(value[key]))).map(key => [key, value[key]]));
  for (const key of ["pressure", "doping_level"]) {
    if (keys.includes(key) && Object.keys(objectValue(value[key])).length) result[key] = pickContext(value[key], ["state", "status", "relation", "value", "lower", "upper", "uncertainty", "approximate", "unit"]);
  }
  return result;
}
function ContextDetails({ title, value }: { title: string; value: Record<string, unknown> }) {
  return <div className="mt-1"><span className="font-medium">{title}: </span>{Object.keys(value).length ? <pre className="mt-1 max-w-full whitespace-pre-wrap break-words text-[10px]">{JSON.stringify(value, null, 2)}</pre> : <span>Not supplied</span>}</div>;
}

function ConflictSummary({ kind, value }: { kind: "state_variability" | "extraction_conflict" | "scientific_dispute"; value: unknown }) {
  const raw = objectValue(value);
  const labels = { state_variability: "Reported Tc / state variability", extraction_conflict: "Extraction inconsistency", scientific_dispute: "Scientific dispute" };
  const status = kind === "scientific_dispute" ? raw.status === "reported_unadjudicated" ? "Reported — unadjudicated" : raw.status === "not_reported" ? "No dispute report in this metadata" : "Unknown" : raw.detected === true ? "Detected in reported records" : raw.detected === false ? "Not detected by this check" : "Unknown";
  return <div className="rounded border border-slate-200 p-3 text-xs">
    <h4 className="font-semibold">{labels[kind]}</h4><p className="mt-1">{status}</p><p className="mt-1 text-slate-500">Count: {countLabel(raw.count)}</p>
    <p className="mt-1 text-slate-600">{kind === "state_variability" ? "Variation across Tc values or state metadata is not itself a scientific dispute." : kind === "extraction_conflict" ? "An extraction inconsistency needs source inspection; it does not adjudicate the underlying physics." : "No report is not proof of consensus. An explicit dispute remains unadjudicated."}</p>
    {textList(raw.properties).length > 0 && <p className="mt-1">Fields: {textList(raw.properties).join(", ")}</p>}
    {Array.isArray(raw.evidence) && raw.evidence.length > 0 && <details className="mt-2"><summary className="cursor-pointer">Inspect {raw.evidence.length} retained items</summary><ul className="mt-2 space-y-2">{raw.evidence.filter(item => item && typeof item === "object" && !Array.isArray(item)).map((item, index) => {
      const entry = objectValue(item);
      const paper = semanticText(entry.paper_id);
      return <li className="rounded bg-slate-50 p-2" key={index}>
        <ContextDetails title="Reported context" value={pickContext(item, ["result_id", "result_revision", "paper_id", "property", "value", "state_id", "sample_id", "tc_kelvin", "pressure_gpa", "reason", "basis", "status"])} />
        {paper && <Link className="break-all text-sky-800 underline" href={`/paper/${encodeURIComponent(paper)}`}>{paper}</Link>}
        {textList(entry.result_ids).length > 0 && <p className="mt-1 break-all">Result IDs: {textList(entry.result_ids).join("; ")}</p>}
        {textList(entry.occurrence_ids).length > 0 && <p className="mt-1 break-all">Occurrence IDs: {textList(entry.occurrence_ids).join("; ")}</p>}
        {textList(entry.reason_codes).length > 0 && <p className="mt-1">{textList(entry.reason_codes).map(reason => reason.replaceAll("_", " ")).join("; ")}</p>}
      </li>;
    })}</ul></details>}
    {raw.evidence_truncated === true && <p className="mt-1 text-amber-900">This evidence list is truncated; it is not a complete dispute or conflict history.</p>}
  </div>;
}
