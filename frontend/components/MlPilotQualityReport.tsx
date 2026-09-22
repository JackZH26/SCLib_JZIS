"use client";

import { useEffect, useRef, useState } from "react";
import { PILOT_AVAILABILITY, PILOT_GROUPS, PILOT_OUTCOMES, type PilotQualityReport, type PilotTiming } from "@/lib/ml-pilot-quality";

const FIELD_LABELS = { source_revision: "Source revision", source_locator: "Source locator", raw_context: "Retained original context", work_identity: "Work identity",
  sample_state: "Sample and state", structure_identity: "Structure identity", tc_value: "Tc value", tc_criterion: "Tc criterion", pressure: "Pressure", origin: "Result origin", method: "Method" };
const STATUS_LABELS = { reported: "Reported", not_reported: "Not reported", not_accessible: "Not accessible", not_extracted: "Not extracted", ambiguous: "Ambiguous", conflicted: "Conflicted", not_applicable: "Not applicable" };
const GROUP_LABELS = { family: "Material family", source_class: "Source class", stratum_id: "Selection stratum" };
const OUTCOME_LABELS = { recovered: "Recovered", inaccessible: "Inaccessible", irrecoverable: "Irrecoverable", no_relevant_result: "No relevant result", unresolved: "Unresolved" };
const table = "w-full border-collapse text-left text-sm", cell = "border border-sage-border p-2 align-top", rowhead = cell + " min-w-36 bg-sage-surface font-medium";
const scroll = "min-w-0 max-w-full overflow-x-auto rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2";
const number = (value: number) => value.toLocaleString("en-US");
export function pilotEffortText(value: PilotTiming) {
  if (value.recordedMinutes === null) return `Not recorded · 0/${number(value.totalRecords)} review records timed`;
  const displayed = value.recordedMinutes.toLocaleString("en-US", { maximumSignificantDigits: 12 });
  const rounded = Number(displayed.replaceAll(",", "")) !== value.recordedMinutes;
  return `${rounded ? "≈ " : ""}${displayed} recorded min · ${number(value.recordedRecords)}/${number(value.totalRecords)} review records timed`;
}

export function MlPilotQualityReport({ value }: { value: PilotQualityReport }) {
  const [dimension, setDimension] = useState<typeof PILOT_GROUPS[number]>("family"), [groupIndex, setGroupIndex] = useState(0);
  const heading = useRef<HTMLHeadingElement | null>(null);
  useEffect(() => { heading.current?.focus({ preventScroll: true }); heading.current?.scrollIntoView({ block: "start" }); }, []);
  const groups = value.groups[dimension], group = groups[groupIndex] ?? groups[0];
  return <section className="min-w-0 space-y-4 rounded-lg border border-sage-border bg-white p-4" aria-label="Verified private field report">
    <header className="space-y-2"><h3 ref={heading} tabIndex={-1} className="scroll-mt-24 text-lg font-semibold">Pilot field recovery and curation effort</h3>
      <p className="text-sm">A view of the exact locally supplied canary and conclusion bound to the historical byte-integrity snapshot. Statistics come from the verified canary, not a new browser analysis of scientific evidence.</p>
      <p className="rounded border border-amber-200 bg-amber-50 p-3 text-sm">Private review text and small-group summaries may be sensitive. Do not share without separate permission. This report does not establish scientific correctness, source rights, reviewer independence or ML readiness.</p>
      <p className="break-all text-xs">Bound account snapshot (UTC): {value.snapshotStartedAt}</p>
    </header>
    <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3" aria-label="Separate pilot accounting units">
      {([["Selected candidate events", value.selected], ["Review records, including superseded revisions", value.reviewRecords],
        ["Distinct effective atomic result IDs", value.atomicResults], ["Event–result associations", value.associations],
        ["Events requiring a second review", value.requiredSecondary]] as const).map(([label, n]) => <div key={label}><dt>{label}</dt><dd>{number(n)}</dd></div>)}
      <div><dt>Independent works / replications</dt><dd>Not established</dd></div>
    </dl>
    <p className="text-sm">Reported distinct IDs: {number(value.identities.work_id)} works; {number(value.identities.sample_id)} samples; {number(value.identities.state_id)} states; {number(value.identities.structure_id)} structures. These are recorded identifiers, not independent materials or replications. A structure ID does not establish available coordinates or calculation readiness.</p>
    <p className="text-sm">Total recorded effort: {pilotEffortText(value.effort)}. Missing time is not zero; partial recorded time is not total human effort. Timing includes all revisions, including failures and superseded assessments. ≈ denotes display rounding only.</p>
    <div className={scroll} tabIndex={0} role="region" aria-label="All selected event outcomes"><table className={table}>
      <caption className="pb-2 text-left font-semibold">Event outcomes — fixed denominator {number(value.selected)}</caption>
      <thead><tr>{PILOT_OUTCOMES.map(k => <th className={cell} scope="col" key={k}>{OUTCOME_LABELS[k]}</th>)}</tr></thead>
      <tbody><tr>{PILOT_OUTCOMES.map(k => <td className={cell} key={k}>{number(value.outcomes[k])}/{number(value.selected)}</td>)}</tr></tbody>
    </table></div>
    {value.atomicResults === 0 && <p className="rounded border border-sage-border p-3 text-sm">No atomic results were recovered. Missingness has a zero atomic denominator, not 100% missingness. Failed events remain in the selected-event denominator; no Tc = 0 or negative examples are manufactured.</p>}
    <p className="text-sm">Recorded atomic-result decisions: {number(value.decisions.accepted)} accepted, {number(value.decisions.pending)} pending, {number(value.decisions.rejected)} rejected. “Accepted” is a recorded reviewer assertion, not automatic scientific acceptance. Candidate recovery below includes any reported result, including pending/rejected results; it is not extraction accuracy or complete recovery.</p>
    <div className={scroll} tabIndex={0} role="region" aria-label="Priority field recovery and proposals"><table className={table}>
      <caption className="pb-2 text-left font-semibold">Eleven priority fields — recorded recovery, effort and human proposals</caption>
      <thead><tr>{["Field", "Events with any reported result / selected", "Recorded field effort, all revisions", "Human proposal", "Recorded reason"].map(k => <th className={cell} scope="col" key={k}>{k}</th>)}</tr></thead>
      <tbody>{value.fields.map(f => <tr key={f.field}><th className={rowhead} scope="row">{FIELD_LABELS[f.field]}</th>
        <td className={cell}>{number(f.candidateRecovered)}/{number(value.selected)}</td><td className={cell + " min-w-44"}>{pilotEffortText(f.effort)}</td>
        <td className={cell}>{f.action}</td><td className={cell + " min-w-48 whitespace-pre-wrap break-words"}>{f.reason}</td></tr>)}</tbody>
    </table></div>
    <p className="text-sm">Keep/narrow/defer proposals are copied from the original conclusion; the website does not choose, endorse or apply them. Field time is recorded disjoint effort, not an estimate from the number of populated cells. Unrecorded and unallocated effort remain unknown.</p>
    <div className={scroll} tabIndex={0} role="region" aria-label="Atomic field availability"><table className={table}>
      <caption className="pb-2 text-left font-semibold">Atomic-result availability — {number(value.atomicResults)} distinct effective result IDs</caption>
      <thead><tr><th className={cell} scope="col">Field</th>{PILOT_AVAILABILITY.map(k => <th className={cell} scope="col" key={k}>{STATUS_LABELS[k]}</th>)}</tr></thead>
      <tbody>{value.fields.map(f => <tr key={f.field}><th className={rowhead} scope="row">{FIELD_LABELS[f.field]}</th>
        {PILOT_AVAILABILITY.map(k => <td className={cell} key={k}>{number(f.availability[k])}</td>)}</tr>)}</tbody>
    </table></div>
    <p className="text-sm">Each availability row sums to the atomic denominator, not 60 events. “Not applicable” is distinct from missing data. Unknown pressure is not ambient pressure; a not-detected transition remains an observation over a tested temperature window, not Tc = 0.</p>
    <details className="min-w-0 space-y-3"><summary className="cursor-pointer font-semibold">Frozen-group recovery and effort</summary>
      <p className="text-sm">Groups follow the preregistered selection. They are descriptive, not independent samples, family performance rankings or proof of cross-family ML readiness. Each group uses its own selected-event denominator. Global atomic missingness above is not a within-group statistic.</p>
      <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2"><label className="min-w-0 text-sm">Group dimension<select className="mt-1 w-full min-w-0 rounded border border-sage-border p-2" value={dimension}
        onChange={e => { setDimension(e.target.value as typeof dimension); setGroupIndex(0); }}>{PILOT_GROUPS.map(k => <option key={k} value={k}>{GROUP_LABELS[k]}</option>)}</select></label>
        <label className="min-w-0 text-sm">Frozen selection group<select className="mt-1 w-full min-w-0 rounded border border-sage-border p-2" value={groupIndex} onChange={e => setGroupIndex(Number(e.target.value))}>
          {groups.map((g, i) => <option key={g.label} value={i}>{g.label}</option>)}</select></label></div>
      <p className="break-words text-sm">{GROUP_LABELS[dimension]}: {group.label}. Selected events: {number(group.selected)}. {pilotEffortText(group.effort)}.</p>
      <p className="text-sm">{PILOT_OUTCOMES.map(k => `${OUTCOME_LABELS[k]}: ${number(group.outcomes[k])}`).join(" · ")}</p>
      <div className={scroll} tabIndex={0} role="region" aria-label="Selected group field recovery"><table className={table}>
        <caption className="pb-2 text-left font-semibold">Any reported result / selected events in this group</caption>
        <thead><tr><th className={cell} scope="col">Field</th><th className={cell} scope="col">Candidate recovery</th></tr></thead>
        <tbody>{value.fields.map(f => <tr key={f.field}><th className={rowhead} scope="row">{FIELD_LABELS[f.field]}</th><td className={cell}>{number(group.recovered[f.field])}/{number(group.selected)}</td></tr>)}</tbody>
      </table></div>
      <p className="text-xs">Group effort here is total recorded review effort. For group-by-field timing, original missingness reasons and all review revisions, use the complete independently verified offline review report. This view does not regenerate or replace that report.</p>
    </details>
    <details className="space-y-2"><summary className="cursor-pointer font-semibold">Errors and comparisons, separate from availability</summary>
      <dl className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">{Object.entries(value.errors).map(([k, n]) => <div key={k}><dt>{k.replaceAll("_", " ")} error occurrences</dt><dd>{number(n)}</dd></div>)}</dl>
      <p className="text-sm">Error occurrences may overlap within one result; no accuracy/error-rate denominator is inferred. Missingness is not correctness.</p>
      <dl className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">{Object.entries(value.comparisons).map(([k, n]) => <div key={k}><dt>{k.replaceAll("_", " ")} — latest comparison records</dt><dd>{number(n)}</dd></div>)}</dl>
      <p className="text-sm">Secondary and arbitration records are not additional materials or independent replications. Disagreements and unresolved findings require human interpretation, not an aggregate passing percentage.</p>
    </details>
    <div className="space-y-2 text-sm"><h4 className="font-semibold">Recorded overall proposal: {value.recommendation}</h4>
      <p className="whitespace-pre-wrap break-words">{value.rationale}</p><h5 className="font-medium">Recorded limitations</h5>
      {value.limitations.length ? <ul className="list-disc space-y-1 pl-5">{value.limitations.map((item, i) => <li className="whitespace-pre-wrap break-words" key={i}>{item}</li>)}</ul> : <p>No limitations were recorded. This does not establish absence of limitations.</p>}
      <p>No schema, importer, dataset or model is changed by this view. Sixty candidate events assess workflow feasibility, not statistical sufficiency for cross-family learning. A recorded go proposal is not approval to train.</p>
    </div>
    <details><summary className="cursor-pointer font-semibold">Exact report input references</summary><dl className="break-all text-xs"><dt>Verified canary SHA-256</dt><dd>{value.canarySha256}</dd><dt>Original conclusion SHA-256</dt><dd>{value.conclusionSha256}</dd></dl></details>
  </section>;
}
