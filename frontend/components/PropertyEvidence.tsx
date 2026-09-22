import Link from "next/link";
import { RecordAnomalyReview } from "@/components/ScientificAnomalies";
import type { MaterialPropertyEvidence, PropertyEvidenceItem } from "@/lib/api";
import { pressureLabel } from "@/lib/pressure-semantics";
import {
  anomalyAllowsProperties, eligibleAtomicItem, evidenceText, hasPropertyContract, objectValue, PROPERTY_LABELS, propertyOrigin,
  propertyStatus, propertyValue, selectedProperty, sourceHref,
} from "@/lib/property-evidence";

function Field({ label, value }: { label: string; value: unknown }) {
  return <div className="grid grid-cols-[7rem_1fr] gap-2"><dt className="text-slate-500">{label}</dt><dd className="break-words text-slate-700">{evidenceText(value) ?? "Not reported"}</dd></div>;
}

function locatorText(value: unknown): string | null {
  const direct = evidenceText(value);
  if (direct) return direct;
  const locator = objectValue(value);
  return ["section", "page", "paragraph", "figure", "table", "row", "column", "line", "chunk_id", "span_id"].flatMap(key => evidenceText(locator[key]) ? [`${key}: ${evidenceText(locator[key])}`] : []).join(" · ") || null;
}

/** Only this selected record supplies conditions. Never read a material scalar. */
export function AtomicEvidenceDetails({ item }: { item: PropertyEvidenceItem }) {
  const source = objectValue(item.source);
  const state = objectValue(item.state);
  const conditions = objectValue(item.conditions);
  const origin = objectValue(item.origin);
  const structure = objectValue(item.structure);
  const href = sourceHref(source);
  return <div className="mt-3 min-w-[12rem] max-w-lg space-y-3 text-left text-xs font-normal leading-5">
    <dl className="space-y-1">
      <Field label="Result" value={item.result_id} />
      <Field label="Source" value={source.paper_id} />
      <Field label="DOI" value={source.doi} />
      <Field label="Locator" value={locatorText(source.source_locator)} />
      <Field label="Source year" value={source.year} />
      <Field label="Record origin" value={propertyOrigin(item)} />
      <Field label="Record source role" value={origin.source_role} />
      {origin.classification_status === "conflicted" && <Field label="Classification" value="Conflict — not resolved evidence" />}
      <Field label="Method" value={conditions.calculation_method ?? conditions.measurement_method ?? conditions.method ?? conditions.measurement} />
      <Field label="Protocol" value={conditions.protocol_id ?? conditions.calculation_protocol} />
      <Field label="State ID" value={state.state_id} />
      <Field label="Sample ID" value={state.sample_id} />
      <Field label="Structure ID" value={state.structure_id} />
      <Field label="Run ID" value={state.run_id} />
      <Field label="Source formula" value={state.formula} />
      <Field label="Raw formula" value={state.formula_raw} />
      <Field label="Pressure" value={pressureLabel(state.pressure_semantics, typeof state.pressure_gpa === "number" ? state.pressure_gpa : null)} />
      {[["temperature_k", "Temperature (role unknown)"], ["measurement_temperature_k", "Measurement T"], ["hc2_temperature_k", "Hc2 temperature"]].map(([key, label]) => <Field key={key} label={label} value={conditions[key] ? propertyValue({ ...item, property: key, quantity: objectValue(conditions[key]), value: null }) : null} />)}
      <Field label="Sample form" value={state.sample_form} />
      <Field label="Substrate" value={state.substrate} />
      <Field label="Tc criterion" value={conditions.tc_criterion ?? conditions.tc_type} />
      <Field label="Tc conditions" value={conditions.tc_conditions} />
      {item.property === "hc2_tesla" && <>
        <Field label="Hc2 conditions" value={conditions.hc2_conditions} />
        <Field label="Field direction" value={conditions.hc2_direction ?? conditions.field_orientation ?? conditions.magnetic_field_orientation} />
        <p className="text-slate-500">Hc2 conditions belong to this result only. Missing temperature or direction is not inferred from another record.</p>
      </>}
    </dl>
    <p className="text-slate-500">Record-level classification does not independently establish how each property was measured, computed or inferred.</p>
    <RecordAnomalyReview assessment={item.anomaly_review} />
    {Object.values(structure).some(value => value != null) && <details className="border-t border-slate-200 pt-2">
      <summary className="cursor-pointer font-medium text-slate-600">Structure attached to this result</summary>
      <dl className="mt-2 space-y-1">
        <Field label="Structure" value={structure.crystal_structure} />
        <Field label="Space group" value={structure.space_group} />
        <Field label="Phase" value={structure.structure_phase} />
        <Field label="Lattice" value={propertyValue({ ...item, property: "lattice_params", value: structure.lattice_params, quantity: { status: "parsed", relation: "group", components: structure.lattice_quantities } })} />
      </dl>
      <p className="mt-1 text-slate-500">One source record; not a reconstruction from independently selected lattice and symmetry fields.</p>
    </details>}
    {href && <Link href={href} className="inline-block text-accent underline">Open source paper</Link>}
  </div>;
}

export function PropertyEvidenceValue({ evidence, field, compact = false, includeUnit = true }: {
  evidence?: MaterialPropertyEvidence; field: string; compact?: boolean; includeUnit?: boolean;
}) {
  const item = selectedProperty(evidence, field);
  const entry = hasPropertyContract(evidence) ? evidence?.properties?.[field] : undefined;
  const label = PROPERTY_LABELS[field] ?? field;
  const candidates = entry?.evidence?.filter(candidate => candidate.result_id !== entry.selected?.result_id && candidate.property === field) ?? [];
  return <details className={`property-evidence ${compact ? "text-xs" : "text-sm"}`}>
    <summary className="cursor-pointer text-slate-800 marker:text-slate-400" aria-label={`${label}: ${item ? propertyValue(item, includeUnit) : propertyStatus(evidence, field)} — source and conditions`}>
      <span className="font-medium tabular-nums">{item ? propertyValue(item, includeUnit) : "—"}</span>
      <span className={`font-normal text-slate-500 ${compact ? "block text-[10px]" : "ml-2 text-xs"}`}>{item ? `Record: ${propertyOrigin(item)}` : propertyStatus(evidence, field)}</span>
    </summary>
    {item ? <AtomicEvidenceDetails item={item} /> : <>
      <p className="mt-2 max-w-sm text-left text-xs font-normal text-slate-500">{propertyStatus(evidence, field)}. A legacy catalogue value is not substituted without its contributing result.</p>
      {entry?.selected?.property === field && <AtomicEvidenceDetails item={entry.selected} />}
    </>}
    {entry && <p className="mt-2 max-w-sm text-left text-xs font-normal text-slate-500">Selection: {entry.selection.replaceAll("_", " ")}{entry.statistic ? ` · ${entry.statistic.replaceAll("_", " ")}` : ""}. Catalogue property only, not a joint observation.</p>}
    {entry?.warnings?.length ? <p className="mt-2 max-w-sm text-left text-xs font-normal text-amber-800">Notes: {entry.warnings.map(code => code.replaceAll("_", " ")).join(" · ")}</p> : null}
    {candidates.length > 0 && <details className="mt-2 text-left text-xs font-normal">
      <summary className="cursor-pointer text-slate-600">Other source results ({candidates.length})</summary>
      <p className="mt-2 text-slate-500">These are retained proposals, not public-eligible headline selections. Some may require anomaly review; numerical display does not approve them for scientific use.</p>
      <ul className="mt-2 space-y-3">{candidates.map((candidate, index) => <li key={`${candidate.result_id}:${index}`} className="border-t border-slate-200 pt-2">
        <p className="font-medium">{propertyValue(candidate)} · record origin: {propertyOrigin(candidate)} · not the headline selection</p>
        <AtomicEvidenceDetails item={candidate} />
      </li>)}</ul>
    </details>}
    {entry?.total_evidence_count != null && (evidence?.evidence_scope === "selected_only" || entry.truncated) && <p className="mt-2 max-w-sm text-left text-xs font-normal text-slate-500">{entry.total_evidence_count} source results in the catalogue; this response contains {evidence?.evidence_scope === "selected_only" ? "the selection only. Open the material page for available alternatives." : "a bounded set of alternatives."}</p>}
  </details>;
}

export function PropertyEvidenceFact({ evidence, field }: { evidence?: MaterialPropertyEvidence; field: string }) {
  return <div className="rounded-lg border border-sage-border bg-white p-4 shadow-sage">
    <div className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">{PROPERTY_LABELS[field] ?? field}</div>
    <PropertyEvidenceValue evidence={evidence} field={field} />
  </div>;
}

export function PropertyEvidenceSection({ title, fields, evidence }: { title: string; fields: string[]; evidence?: MaterialPropertyEvidence }) {
  return <section>
    <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h2>
    <div className="rounded-lg border border-sage-border bg-white"><dl className="divide-y divide-slate-100">
      {fields.map(field => <div key={field} className="grid grid-cols-[minmax(8rem,180px)_1fr] gap-4 px-4 py-3 text-sm">
        <dt className="text-slate-500">{PROPERTY_LABELS[field] ?? field}</dt><dd><PropertyEvidenceValue evidence={evidence} field={field} /></dd>
      </div>)}
    </dl></div>
  </section>;
}

export function JointEpcNotice({ evidence }: { evidence?: MaterialPropertyEvidence }) {
  const joint = hasPropertyContract(evidence) ? evidence?.joint_epc : undefined;
  const pair = objectValue(joint?.selected);
  const lambda = pair.lambda as PropertyEvidenceItem | undefined;
  const omega = pair.omega_log as PropertyEvidenceItem | undefined;
  const stateFields = ["pressure_gpa", "lattice_params", "doping_level", "temperature_k", "measurement_temperature_k", "hc2_temperature_k"];
  const paired = joint?.status === "eligible" && typeof pair.pair_id === "string" &&
    pair.eligible_meaning === "association_complete_only" && eligibleAtomicItem(lambda, "lambda_eph") && eligibleAtomicItem(omega, "omega_log_k") &&
    anomalyAllowsProperties(lambda, stateFields) && anomalyAllowsProperties(omega, stateFields);
  const review = objectValue(pair.review);
  return <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
    <h3 className="font-medium">EPC association — separate from model applicability</h3>
    <p className="mt-1">{paired ? "The API reports an association-complete EPC record. This is not scientific validation or permission to apply Allen–Dynes." : joint?.status === "not_evaluated" ? "EPC association was not evaluated in this response. This is not evidence that no compatible pair exists." : "No association-complete EPC input is established here. Separately selected λ and ω_log must not be combined as paired calculation inputs."}</p>
    <p className="mt-1 text-xs">A shared structure, state and compatible run protocol or an explicit reviewed match is required. Missing run/state association is not inferred from formula, pressure or paper alone.</p>
    {joint?.warnings?.length ? <p className="mt-2 text-xs">Association notes: {joint.warnings.map(code => code.replaceAll("_", " ")).join(" · ")}</p> : null}
    {paired && lambda && omega && <details className="mt-3 rounded border border-amber-300 bg-white p-3">
      <summary className="cursor-pointer font-medium">Inspect the linked EPC pair</summary>
      <p className="mt-2 break-all text-xs">Pair ID: {evidenceText(pair.pair_id)} · association basis: {evidenceText(pair.association_basis)?.replaceAll("_", " ")}</p>
      <p className="mt-2 text-xs">This pair is separate from the two independent catalogue selections above. Its result identities, not equal numbers, establish which records were linked.</p>
      <div className="mt-3 grid gap-4 md:grid-cols-2">
        <div><h4 className="font-medium">Linked λ_eph: {propertyValue(lambda)}</h4><AtomicEvidenceDetails item={lambda} /></div>
        <div><h4 className="font-medium">Linked ω_log: {propertyValue(omega)}</h4><AtomicEvidenceDetails item={omega} /></div>
      </div>
      {Object.keys(review).length > 0 && <dl className="mt-3 space-y-1 text-xs">{["review_id", "review_revision", "state_id", "structure_id", "protocol_id"].map(key => <Field key={key} label={key.replaceAll("_", " ")} value={review[key]} />)}</dl>}
      {joint?.truncated && <p className="mt-2 text-xs">Additional pairs may be omitted by the bounded response; this is not a complete pair inventory.</p>}
    </details>}
  </div>;
}
