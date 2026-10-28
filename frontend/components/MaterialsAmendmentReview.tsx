"use client";

import { useEffect, useRef, useState } from "react";
import { materialsAmendmentTargets, materialsClaimReviewContext, materialsProposalAmendment, materialsProposalAmendments } from "@/lib/api";
import { amendmentFields, amendmentSelection, amendmentTargets, claimSourceContext, displayValue, proposalAmendment, proposalAmendments,
  type AmendmentDetail, type AmendmentList, type AmendmentSummary, type AmendmentTarget, type AmendmentTargets, type ClaimSourceContext, type Body, type Json, type ProposalDetail, type ProposalRow } from "@/lib/materials-proposal-review";

const button = "rounded border border-sage-border bg-white px-3 py-2 text-sm text-accent-deep disabled:opacity-50";
const object = (v: Json | undefined): Body => v !== null && typeof v === "object" && !Array.isArray(v) ? v : {};
const label = (v: string) => v.replaceAll("_", " ");
const meaningful = (v: Json | undefined) => v !== null && v !== undefined && v !== "" && (!Array.isArray(v) || v.length > 0);
function StructuredSummary({ value }: { value: Body }) {
  const quantity = object(value.quantity ?? value.amount ?? value.fraction);
  const name = value.formula_raw ?? value.symbol ?? (value.element ? `${value.element}-${value.mass_number}` : value.kind);
  const entries = [
    name, quantity.raw, quantity.unit ? `Unit: ${quantity.unit}` : undefined,
    value.result_id ? `Result: ${value.result_id}` : undefined,
    value.relation ? `Relation: ${label(String(value.relation))}` : undefined,
    value.role ? `Role: ${label(String(value.role))}` : undefined,
    value.availability ? `Availability: ${label(String(value.availability))}` : undefined,
    value.regime ? `Pressure regime: ${label(String(value.regime))}` : undefined,
    value.basis ? `Basis: ${label(String(value.basis))}` : undefined,
    value.minus !== undefined && value.minus !== null ? `Lower uncertainty: ${value.minus}` : undefined,
    value.plus !== undefined && value.plus !== null ? `Upper uncertainty: ${value.plus}` : undefined,
    value.basis_raw, value.orientation_raw,
  ].filter(meaningful);
  return entries.length > 0 ? <ul className="space-y-1">{entries.map((entry, index) => <li className="whitespace-pre-wrap break-words" key={index}>{displayValue(entry)}</li>)}</ul> : <p>Structured information retained below.</p>;
}
function Value({ value }: { value: Json | undefined }) {
  if (value !== null && typeof value === "object") return <div className="mt-1 min-w-0 text-sm">
    {Array.isArray(value) ? <div className="space-y-3">{value.map((item, index) => <div key={index} className={index ? "border-t border-sage-border pt-2" : ""}>{item && typeof item === "object" && !Array.isArray(item) ? <StructuredSummary value={item} /> : <p className="break-words">{displayValue(item)}</p>}</div>)}</div> : <StructuredSummary value={value} />}
    <details className="mt-2 text-xs"><summary className="cursor-pointer text-accent-deep">Complete structured value</summary><pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-all">{JSON.stringify(value)}</pre></details>
  </div>;
  return <p className="mt-1 whitespace-pre-wrap break-words text-sm">{value === null || value === undefined ? "Not recorded in this version" : displayValue(value)}</p>;
}
function comparedFields(result: Body, sample: Body, state: Body, protocol: Body): [string, Json | undefined][] {
  const q = object(result.quantity), definition = object(result.definition);
  return [
    ["Quantity", q.raw], ["Quantity kind", result.quantity_kind], ["Source quantity name", result.quantity_name_raw], ["Component / direction", result.component_raw],
    ["Quantity availability", q.status], ["Value", q.value], ["Unit", q.unit],
    ["Value relation", q.relation], ["Approximate", q.approximate], ["Lower bound", q.lower], ["Upper bound", q.upper], ["Uncertainty", q.uncertainty],
    ["Sample", sample.label], ["Sample form", sample.form_raw], ["Substrate", sample.substrate_raw], ["Formula", sample.formula_raw], ["Composition basis", sample.composition_basis],
    ["Other formula assertions", sample.additional_formula_assertions], ["Composition variables", sample.variables], ["Isotope assignments", sample.isotopes],
    ["Method class", protocol.method_class], ["Method wording", protocol.method], ["Criterion", definition.criterion], ["Criterion wording", definition.criterion_raw],
    ["Criterion parameters", definition.parameters], ["Pressure declaration", state.pressure], ["Conditions", state.conditions], ["Result origin", result.origin], ["Source role", result.source_role], ["Qualifiers", result.qualifiers],
    ["Result dependencies", result.dependencies],
  ];
}

function CanonicalSourceRead({ amendment, resultId, onRefusal }: { amendment: AmendmentDetail; resultId: string; onRefusal: (error: unknown) => void }) {
  const [targets, setTargets] = useState<AmendmentTargets | null>(null), [selected, setSelected] = useState<AmendmentTarget | null>(null);
  const [context, setContext] = useState<ClaimSourceContext | null>(null), [busy, setBusy] = useState(false);
  const request = useRef<AbortController | null>(null), generation = useRef(0);
  function begin() { request.current?.abort(); const controller = new AbortController(); request.current = controller; const id = ++generation.current; setBusy(true); return { signal: controller.signal, active: () => generation.current === id && !controller.signal.aborted }; }
  useEffect(() => () => { generation.current += 1; request.current?.abort(); }, []);
  async function load() {
    const state = begin(); setTargets(null); setContext(null); setSelected(null);
    try {
      const data = amendmentTargets(await materialsAmendmentTargets(amendment.amendment.parent_run_id, amendment.amendment.amendment_id, resultId, state.signal), amendment, resultId);
      if (!state.active()) return;
      if (!data) throw new Error("Candidate ownership could not be checked");
      setTargets(data); setBusy(false);
    } catch (error) { if (state.active()) onRefusal(error); }
  }
  async function inspect(target: AmendmentTarget) {
    const state = begin(); setContext(null); setSelected(null);
    try {
      const data = claimSourceContext(await materialsClaimReviewContext(target.id, state.signal), target);
      if (!state.active()) return;
      if (!data) throw new Error("Canonical source ownership could not be checked");
      setSelected(target); setContext(data); setBusy(false);
    } catch (error) { if (state.active()) onRefusal(error); }
  }
  const groups = new Map<string, { value: ClaimSourceContext["source_occurrences"][number]; count: number }>();
  for (const item of context?.source_occurrences ?? []) {
    const key = JSON.stringify([item.source_revision_id, item.capture_id, item.bytes_sha256, item.binding_status, item.version_status, item.provider_revision, item.representation]);
    const prior = groups.get(key); groups.set(key, { value: item, count: (prior?.count ?? 0) + 1 });
  }
  return <section aria-label="Canonical candidates and source versions" className="min-w-0 rounded border border-sage-border p-3">
    <h3 className="font-semibold">Canonical candidates and source versions</h3>
    <p className="mt-2 text-sm">Candidate links connect this retained revision to stored review targets. A catalogue link does not confirm material equivalence or an independent experiment.</p>
    <button className={`${button} mt-3`} disabled={busy} onClick={() => void load()}>Find stored candidates</button>
    {busy && <p role="status" className="mt-2 text-sm">Checking candidate identity and access…</p>}
    {targets?.items.length === 0 && <p className="mt-2 text-sm">No stored candidate is linked to this result. Source version checks remain pending.</p>}
    {targets && targets.items.length > 1 && <p className="mt-2 text-sm">Multiple retained candidates exist. Select a specific target; no preferred identity is inferred.</p>}
    {targets && <ul className="mt-3 space-y-2">{targets.items.map(target => <li key={target.id}><button className={`${button} break-all text-left`} disabled={busy} onClick={() => void inspect(target)}>Read registered sources · {target.material_id} · {target.id}</button></li>)}</ul>}
    {context && selected && <div className="mt-4 space-y-3 text-sm" data-testid="canonical-source-reading">
      <p>Identity review: pending. Scientific acceptance and ML eligibility are not established by this read.</p>
      <p className="break-all">Candidate material: {selected.material_id} · Claim: {selected.id}</p>
      <p>Versions below belong to registered result occurrences. Source binding status is reported separately from version pinning. Field-context quotes retain their original descriptors.</p>
      {groups.size === 0 && <p>No result source occurrence is registered; source version checks remain pending.</p>}
      {[...groups.entries()].map(([key, { value, count }]) => <div key={key} className="min-w-0 rounded bg-sage-light/20 p-3">
        <p>Registered version: {value.provider_revision ?? "Unknown"} · Version status: {label(value.version_status)}</p>
        <p>Source binding: {label(value.binding_status)} · Representation: {label(value.representation)} · Occurrences: {count.toLocaleString("en-US")}</p>
        <details className="mt-2 text-xs"><summary className="cursor-pointer">Source identity and byte hash</summary><pre className="mt-2 whitespace-pre-wrap break-all">{JSON.stringify({ source_revision_id: value.source_revision_id, capture_id: value.capture_id, bytes_sha256: value.bytes_sha256 }, null, 2)}</pre></details>
      </div>)}
      <details className="text-xs"><summary className="cursor-pointer">Exact review subject and candidate snapshot</summary><pre className="mt-2 whitespace-pre-wrap break-all">{JSON.stringify({ ...selected, subject_sha256: context.subject_sha256, result_row_sha256: context.result_row_sha256, target: context.target }, null, 2)}</pre></details>
    </div>}
  </section>;
}

/** Assistant-authored amendments are review candidates, never independent scientific decisions. */
export function MaterialsAmendmentReview({ detail, original, onRefusal }: { detail: ProposalDetail; original: ProposalRow; onRefusal: (error: unknown) => void }) {
  const [listing, setListing] = useState<AmendmentList | null>(null), [current, setCurrent] = useState<AmendmentDetail | null>(null);
  const [selected, setSelected] = useState<AmendmentSummary | null>(null), [busy, setBusy] = useState(false);
  const request = useRef<AbortController | null>(null), generation = useRef(0);
  function begin() { request.current?.abort(); const controller = new AbortController(); request.current = controller; const id = ++generation.current; setBusy(true); return { signal: controller.signal, active: () => generation.current === id && !controller.signal.aborted }; }
  useEffect(() => () => { generation.current += 1; request.current?.abort(); }, []);
  async function load() {
    const state = begin(); setCurrent(null); setSelected(null); setListing(null);
    try {
      const value = proposalAmendments(await materialsProposalAmendments(detail.run.run_id, state.signal), detail.run);
      if (!state.active()) return;
      if (!value) throw new Error("Amendment ownership could not be checked");
      setListing(value); setBusy(false);
    } catch (error) { if (state.active()) onRefusal(error); }
  }
  async function open(summary: AmendmentSummary) {
    const state = begin(); setCurrent(null); setSelected(null);
    try {
      const value = proposalAmendment(await materialsProposalAmendment(detail.run.run_id, summary.id, state.signal), detail.run, summary);
      if (!state.active()) return;
      if (!value || !amendmentSelection(value, original.local_id)) throw new Error("Amendment selection could not be checked");
      setSelected(summary); setCurrent(value); setBusy(false);
    } catch (error) { if (state.active()) onRefusal(error); }
  }
  async function download() {
    if (!selected || !current) return;
    const state = begin();
    try {
      const value = proposalAmendment(await materialsProposalAmendment(detail.run.run_id, selected.id, state.signal), detail.run, selected);
      if (!state.active()) return;
      if (!value || value.storage_hash !== current.storage_hash) throw new Error("Amendment export changed");
      const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2) + "\n"], { type: "application/json" }));
      const link = document.createElement("a"); link.href = url; link.download = `materials-amendment-${selected.id}.json`; link.click(); URL.revokeObjectURL(url); setBusy(false);
    } catch (error) { if (state.active()) onRefusal(error); }
  }
  const selection = current ? amendmentSelection(current, original.local_id) : null;
  const oldSample = detail.entities.samples.find(x => x.local_id === original.payload.sample_id)?.payload ?? {};
  const oldState = detail.entities.states.find(x => x.local_id === original.payload.state_id)?.payload ?? {};
  const oldProtocol = detail.entities.protocols.find(x => x.local_id === original.payload.protocol_id)?.payload ?? {};
  const before = comparedFields(original.payload, oldSample, oldState, oldProtocol);
  const after = selection ? comparedFields(selection.result, selection.sample, selection.state, selection.protocol) : [];
  const items = listing?.items.filter(x => x.selected_result_ids.includes(original.local_id));
  const prefixes = current && selection ? [selection.mapping.sample_pointer, selection.mapping.state_pointer, selection.mapping.protocol_pointer,
    `/graph/results/${current.amendment.graph.results.indexOf(selection.result)}`].map(x => String(x).replace(/^\/graph/, "")) : [];
  const changes = current?.amendment.changes.filter(c => prefixes.some(p => c.path === p || c.path.startsWith(`${p}/`))) ?? [];
  return <section className="min-w-0 rounded-lg border border-sage-border bg-white p-4" aria-labelledby="amendment-review-heading">
    <div className="flex flex-wrap items-center justify-between gap-3"><h2 id="amendment-review-heading" className="scroll-mt-24 text-lg font-semibold">Source-backed amendments</h2><button className={button} disabled={busy} onClick={() => void load()}>Load source-backed amendments</button></div>
    <p className="mt-2 text-sm text-sage-muted">Assistant revisions for {original.local_id}. Original predictions remain retained. These revisions require independent scientific review and do not approve training or publication.</p>
    {busy && <p role="status" className="mt-2 text-sm">Checking amendment data and access…</p>}
    {items?.length === 0 && <p className="mt-3 text-sm">No amendment selects this result. Other retained results remain outside this revision scope.</p>}
    {items && items.length > 0 && <ul className="mt-3 space-y-2">{items.map(item => <li key={item.id}><button className={`${button} break-all text-left`} disabled={busy} onClick={() => void open(item)}>Inspect amendment {item.id.slice(0, 12)} · {item.selected_result_ids.length.toLocaleString("en-US")} selected results</button></li>)}</ul>}
    {current && selection && <div className="mt-5 space-y-5" data-testid="amendment-reading">
      <div className="rounded border border-amber-200 bg-amber-50 p-3 text-sm">
        <p>Canonical identity: independent review pending. Scientific acceptance: pending independent review. ML eligibility: not established.</p>
        <p className="mt-2">Retained source descriptors can differ from later version verification. Registered source versions can be inspected below when a stored candidate exists. Character offsets refer to parsed text blocks.</p>
        <p className="mt-2">Pressure absent from the reviewed scope remains unknown; it is not treated as ambient.</p>
      </div>
      <p className="break-words text-sm">Revision author: {displayValue(current.amendment.author.identity)} · {current.amendment.created_at}</p>
      {current.mapping.schema === "materials-reviewed-result-mapping/1"
        ? <section aria-label="Result review status" className="rounded border border-sage-border p-3 text-sm"><h3 className="font-semibold">Result review status</h3>
          <p className="mt-2">{label(String(selection.mapping.review_status))} · Canonical quantity mapping is pending.</p>
          <p className="mt-2">Source quantities, missingness and dependencies are retained. Normalization alone does not establish scientific correctness or training eligibility.</p>
          <details className="mt-2"><summary className="cursor-pointer">Retained normalization and validation issues</summary><pre className="mt-2 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify({ normalized: selection.mapping.normalized, issues: selection.mapping.validation_issues }, null, 2)}</pre></details>
        </section>
        : <CanonicalSourceRead key={`${current.storage_hash}:${original.local_id}`} amendment={current} resultId={original.local_id} onRefusal={onRefusal} />}
      {current.amendment.source_review && <section aria-label="Source findings pending reassessment" className="rounded border border-sage-border p-3 text-sm">
        <h3 className="font-semibold">Source findings pending reassessment</h3>
        <p className="mt-2">This amendment retains the original source findings. A local correction does not discharge other findings or complete the paper review.</p>
        {current.amendment.source_review.findings_author && <p className="mt-2">Original findings author: {current.amendment.source_review.findings_author.identity} (assistant).</p>}
        <ul className="mt-3 space-y-3">{current.amendment.source_review.findings.map(finding => <li key={finding.id} className="rounded border border-sage-border p-3">
          <h4 className="font-medium">{finding.kind === "source_completeness" ? "Missing from draft" : "Scientific review needed"}</h4>
          <p className="mt-2">{finding.note}</p><p className="mt-1 break-all text-xs text-sage-muted">Scope: {finding.path}</p>
          {finding.anchors.map((anchor, index) => { const block = current.amendment.bundle.blocks.find(b => b.id === anchor.block_id)!; return <figure key={index} className="mt-3">
            <blockquote className="whitespace-pre-wrap break-words border-l-2 border-sage-border pl-3">{anchor.quote}</blockquote>
            <figcaption className="mt-1 break-all text-xs text-sage-muted">{block.locator} · characters {anchor.start_char.toLocaleString("en-US")}–{anchor.end_char.toLocaleString("en-US")}</figcaption>
          </figure>; })}
        </li>)}</ul>
      </section>}
      <section aria-labelledby="amendment-comparison"><h3 id="amendment-comparison" className="scroll-mt-24 font-semibold">Prediction and revision</h3>
        <div className="mt-3 space-y-3">{after.map(([name, value], index) => {
          const originalValue = before[index][1];
          if (!meaningful(value) && !meaningful(originalValue)) return null;
          return <section key={name} aria-label={name} className="min-w-0 rounded border border-sage-border p-3"><h4 className="font-medium">{name}</h4><div className="mt-2 grid min-w-0 gap-3 md:grid-cols-2">
            <div className="min-w-0"><p className="text-xs text-sage-muted">Original model prediction</p><Value value={originalValue} /></div>
            <div className="min-w-0"><p className="text-xs text-sage-muted">Assistant revision</p><Value value={value} /></div>
          </div></section>;
        })}</div>
      </section>
      <section aria-labelledby="amendment-field-evidence"><h3 id="amendment-field-evidence" className="scroll-mt-24 font-semibold">Field review and literal source passages</h3>
        <p className="mt-2 text-sm text-sage-muted">Dispositions and notes below are assistant judgments. Quoted passages are checked against retained source blocks; a literal match does not establish a correct scientific interpretation.</p>
        {amendmentFields.map(field => { const review = selection.review.fields[field]; return <details key={field} className="mt-3 rounded border border-sage-border p-3">
          <summary className="cursor-pointer break-words text-sm font-medium">{label(field)} · {label(review.disposition)}</summary>
          <p className="mt-3 whitespace-pre-wrap break-words text-sm">Assistant note: {review.note}</p>
          {review.anchors.length === 0 && <p className="mt-2 text-sm">No literal source passage is attached to this field review.</p>}
          {review.anchors.map((anchor, index) => { const block = current.amendment.bundle.blocks.find(b => b.id === anchor.block_id)!; return <figure key={index} className="mt-4 min-w-0">
            <blockquote className="whitespace-pre-wrap break-words border-l-2 border-sage-border pl-3 text-sm">{anchor.quote}</blockquote>
            <figcaption className="mt-2 break-all text-xs text-sage-muted">{block.locator} · characters {anchor.start_char.toLocaleString("en-US")}–{anchor.end_char.toLocaleString("en-US")} · block {block.id}</figcaption>
          </figure>; })}
        </details>; })}
      </section>
      <section aria-labelledby="amendment-holds"><h3 id="amendment-holds" className="font-semibold">Unresolved admission requirements</h3><ul className="mt-2 list-inside list-disc text-sm">{[...new Set([...(selection.mapping.holds as string[]), ...selection.review.holds])].map(hold => <li className="break-words" key={hold}>{label(hold)}</li>)}</ul></section>
      <details className="text-sm"><summary className="cursor-pointer">Changes to this result and its sample, state and protocol ({changes.length.toLocaleString("en-US")})</summary><pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(changes, null, 2)}</pre></details>
      <details className="text-sm"><summary className="cursor-pointer">Amendment identity and retained source descriptors (version verification pending)</summary><pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify({ amendment_id: current.amendment.amendment_id, parent_run_id: detail.run.run_id, parent_packet_hash: detail.run.packet_sha256, storage_hash: current.storage_hash, documents: current.amendment.bundle.documents }, null, 2)}</pre></details>
      <button className={button} disabled={busy} onClick={() => void download()}>Download amendment (JSON)</button><p className="text-xs text-sage-muted">The download contains the complete amendment, selected result IDs, field reviews and pending mapping. Other retained result versions are included for provenance and are not approved by this amendment.</p>
    </div>}
  </section>;
}
