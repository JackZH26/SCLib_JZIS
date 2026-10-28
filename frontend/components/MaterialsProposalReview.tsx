"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, materialsProposalCapabilities, materialsProposalDetail, materialsProposalEvidence, materialsProposalExport, materialsProposalExportFile, materialsProposalRuns } from "@/lib/api";
import { onAuthChange } from "@/lib/auth-session";
import { MaterialsAmendmentReview } from "@/components/MaterialsAmendmentReview";
import { displayValue, proposalAccess, proposalDetail, proposalEvidence, proposalExport, proposalQueue, projectorReview,
  type Body, type Json, type ProposalDetail, type ProposalEvidence, type ProposalQueue, type ProposalRow, type ProposalRun } from "@/lib/materials-proposal-review";

const button = "rounded border border-sage-border bg-white px-3 py-2 text-sm text-accent-deep hover:bg-sage-surface disabled:cursor-not-allowed disabled:opacity-50";
const panel = "min-w-0 rounded-lg border border-sage-border bg-white p-4";
const label = (value: string) => value.replaceAll("_", " ");
const object = (value: Json | undefined): Body => value !== null && typeof value === "object" && !Array.isArray(value) ? value : {};
const present = (value: Json | undefined) => value !== undefined && value !== null && value !== "" && (!Array.isArray(value) || value.length > 0);
function Field({ name, value }: { name: string; value: Json | undefined }) {
  return <div className="min-w-0 py-1"><dt className="text-xs font-medium text-sage-muted">{name}</dt><dd className="break-words text-sm text-sage-ink">{displayValue(value)}</dd></div>;
}
function OptionalField({ name, value }: { name: string; value: Json | undefined }) {
  return present(value) ? <Field name={name} value={value} /> : null;
}
function FullFields({ title, row }: { title: string; row: ProposalRow | undefined }) {
  if (!row) return null;
  return <details className="mt-3 text-sm"><summary className="cursor-pointer">{title}</summary><pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-all rounded bg-sage-surface p-3 text-xs">{JSON.stringify(row, null, 2)}</pre></details>;
}
function SourceItemAccounting({ detail }: { detail: ProposalDetail }) {
  const projector = projectorReview(detail.coverage.projector_review, detail.run);
  if (projector) return <section className={panel} aria-labelledby="projector-source-review">
    <h2 id="projector-source-review" className="font-semibold">Model draft and source review</h2>
    <p className="mt-2 text-sm">Graph authored by {projector.graph_authorship} · source version {projector.publication_version}.</p>
    {projector.disposition === "unparsed_model_graph"
      ? <p className="mt-3 rounded border border-amber-200 bg-amber-50 p-3 text-sm">The model graph failed structural validation. {projector.raw_result_objects ?? "An unknown number of"} raw result objects remain in the diagnostic download; no result rows were admitted from this attempt. This is not evidence that the paper reports no results.</p>
      : <p className="mt-2 text-sm">{projector.retained_result_rows.toLocaleString("en-US")} retained draft results require review. Model output and source-review findings remain separate.</p>}
    {projector.terminal.error_code && <p className="mt-2 break-words text-sm">Failure: {label(projector.terminal.error_code)}</p>}
    <p className="mt-2 text-sm text-sage-muted">Whole-paper reading and independent scientific review are incomplete. {projector.source_completeness_findings.toLocaleString("en-US")} recorded source-completeness findings do not constitute a complete result census.</p>
    {projector.findings_author && <p className="mt-2 text-xs text-sage-muted">Source findings recorded by {projector.findings_author.identity} (assistant). These findings do not approve the draft.</p>}
    <ul className="mt-3 space-y-3">{projector.findings.map(finding => <li key={finding.id} className="rounded border border-sage-border p-3">
      <h3 className="font-medium">{finding.kind === "source_completeness" ? "Missing from draft" : "Scientific review needed"}</h3>
      <p className="mt-1 text-sm">{finding.note}</p><p className="mt-1 break-all text-xs text-sage-muted">Scope: {finding.path}</p>
      {finding.source_quotes.map((q, i) => <div key={i} className="mt-3"><blockquote className="whitespace-pre-wrap break-words border-l-2 border-sage-border pl-3 text-sm">{q.quote}</blockquote><p className="mt-1 break-all text-xs text-sage-muted">{q.locator} · characters {q.start_char.toLocaleString("en-US")}–{q.end_char.toLocaleString("en-US")}</p></div>)}
    </li>)}</ul>
    <details className="mt-3 text-sm"><summary className="cursor-pointer">Attempt identity and retained diagnostics</summary><pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-all rounded bg-sage-surface p-3 text-xs">{JSON.stringify({ terminal: projector.terminal, provider: projector.provider, model: projector.model, producer_interface: projector.producer_interface, evidence_binding: projector.evidence_binding, coverage_sha256: projector.coverage_sha256, findings_sha256: projector.findings_sha256 }, null, 2)}</pre></details>
  </section>;
  const accounting = object(detail.coverage.source_item_accounting);
  const items = Array.isArray(accounting.original_items) ? accounting.original_items.map(object) : [];
  const history = Array.isArray(accounting.observation_hold_history) ? accounting.observation_hold_history.map(object) : [];
  const statuses: Record<string, string> = { emitted: "Result emitted", held: "Held for review", missing: "No result retained", emitted_multiple: "Multiple result mappings", conflicting: "Conflicting dispositions" };
  return <section className={panel} aria-labelledby="proposal-source-items">
    <h2 id="proposal-source-items" className="scroll-mt-24 font-semibold">Source item accounting</h2>
    {accounting.available !== true ? <p className="mt-2 text-sm">Source item accounting is unavailable for this retained version. This does not establish complete extraction.</p> : <>
      <p className="mt-2 text-sm text-sage-muted">Original items remain visible when held or missing. Additional result aliases do not recover a held original item. These counts are not independent scientific recall.</p>
      <Field name="Original item count" value={accounting.original_item_count} />
      <ul className="mt-3 text-sm">{items.map((item, index) => <li key={`${index}:${displayValue(item.item_id)}`} className="border-t border-sage-border py-3">
        <dl className="grid gap-3 break-words md:grid-cols-[70px_minmax(0,1fr)_110px_minmax(0,2fr)]">
          <Field name="Original item" value={item.item_id} />
          <Field name="Model inventory value / description" value={`${displayValue(item.value_as_written)} · ${displayValue(item.quantity_as_written)}`} />
          <Field name="Disposition" value={statuses[displayValue(item.status)] ?? "Unresolved disposition"} />
          <div className="min-w-0 py-1"><dt className="text-xs font-medium text-sage-muted">Result or reason</dt><dd className="break-words text-sm">{Array.isArray(item.holds) && item.holds.length ? item.holds.map((held, i) => <p key={i}>{displayValue(object(held).reason)}: {displayValue(object(held).explanation)}</p>) : displayValue(item.result_ids)}</dd></div>
        </dl>
      </li>)}</ul>
      {Array.isArray(accounting.additional_result_mappings) && accounting.additional_result_mappings.length > 0 && <details className="mt-3 text-sm"><summary className="cursor-pointer">Additional result mappings</summary><pre className="mt-2 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(accounting.additional_result_mappings, null, 2)}</pre></details>}
      {history.length > 0 && <div className="mt-4"><h3 className="scroll-mt-24 font-medium">Held candidate history</h3><p className="mt-1 text-sm text-sage-muted">A model hold is pending review. It is not an accepted scientific exclusion or a negative measurement.</p>
        {history.map((entry, index) => <details key={`${index}:${displayValue(entry.observation_id)}`} className="mt-3 rounded border border-sage-border p-3"><summary className="cursor-pointer text-sm">{displayValue(entry.observation_id)} · original candidate and source</summary>
          <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify({ original_candidate: entry.original_observation, dispositions: entry.new_dispositions }, null, 2)}</pre>
          {Array.isArray(entry.source_quotes) && entry.source_quotes.map((value, i) => { const quote = object(value); return <div key={i} className="mt-3"><blockquote className="whitespace-pre-wrap break-words border-l-2 border-sage-border pl-3 text-sm">{displayValue(quote.quote)}</blockquote><p className="mt-1 break-all text-xs text-sage-muted">{displayValue(quote.locator)} · characters {displayValue(quote.start_char)}–{displayValue(quote.end_char)}</p></div>; })}
        </details>)}</div>}
    </>}
  </section>;
}

function ResultReading({ detail, result }: { detail: ProposalDetail; result: ProposalRow }) {
  const p = result.payload;
  const sample = detail.entities.samples.find(r => r.local_id === p.sample_id);
  const state = detail.entities.states.find(r => r.local_id === p.state_id);
  const protocol = detail.entities.protocols.find(r => r.local_id === p.protocol_id);
  const q = object(p.quantity), definition = object(p.definition), missing = object(sample?.payload.formula_unavailability);
  const conditions = Array.isArray(state?.payload.conditions) ? state.payload.conditions : [];
  const pressure = object(state?.payload.pressure);
  const explicitAmbient = pressure.availability === "reported" && pressure.regime === "explicit_ambient";
  const hasMeasurementPressure = conditions.some(condition => {
    const c = object(condition); return c.kind === "pressure" && c.role === "measurement" && object(c.quantity).status === "reported";
  });
  const supports = detail.entities.condition_supports.filter(r => r.payload.state_id === p.state_id);
  const relations = detail.entities.sample_relations.filter(r => [r.payload.from_sample_id, r.payload.to_sample_id].includes(p.sample_id));
  const exclusions = detail.training_exclusions.find(x => x.result_id === result.local_id);
  return <article className={panel} aria-labelledby="selected-proposal-heading">
    <div className="flex flex-wrap items-baseline justify-between gap-2"><h2 id="selected-proposal-heading" className="text-lg font-semibold">Reported result · {displayValue(p.quantity_kind)}</h2><span className="rounded bg-amber-50 px-2 py-1 text-xs text-amber-900">{label(result.review_status)}</span></div>
    <p className="mt-2 text-sm text-sage-muted">Original model prediction. Source-backed revisions, when available, are shown separately below.</p>
    <dl className="mt-3 grid gap-x-5 sm:grid-cols-2 lg:grid-cols-3">
      <OptionalField name="Source quantity name" value={p.quantity_name_raw} />
      <Field name="Source value" value={q.raw} /><OptionalField name="Numeric relation" value={q.relation} /><Field name="Unit" value={q.unit} />
      <OptionalField name="Value" value={q.value} /><OptionalField name="Lower bound" value={q.lower} /><OptionalField name="Upper bound" value={q.upper} />
      <OptionalField name="Uncertainty" value={q.uncertainty} />{q.approximate === true && <Field name="Approximate" value={true} />}<Field name="Origin" value={p.origin} /><Field name="Source role" value={p.source_role} />
      {["tc", "tc_pressure_slope"].includes(String(p.quantity_kind)) && <Field name="Transition criterion" value={definition.criterion} />}<OptionalField name="Criterion wording" value={definition.criterion_raw} /><OptionalField name="Component / direction" value={p.component_raw} />
      <OptionalField name="Source interpretation" value={p.interpretation_raw} /><Field name="Sample label" value={sample?.payload.label} />
      <OptionalField name="Result qualifiers" value={p.qualifiers} /><OptionalField name="Criterion parameters" value={definition.parameters} />
      <Field name="Formula as written" value={sample?.payload.formula_raw} /><Field name="Formula availability" value={sample?.payload.formula_raw === null ? missing.status : "Reported"} />
      <Field name="Sample identity" value={sample?.payload.identity_resolution} /><Field name="Composition basis" value={sample?.payload.composition_basis} />
      <OptionalField name="Sample form" value={sample?.payload.form_raw} /><OptionalField name="Substrate" value={sample?.payload.substrate_raw} />
      <Field name="Method" value={protocol?.payload.method} /><Field name="Observable" value={protocol?.payload.observable} /><OptionalField name="Procedure details" value={protocol?.payload.details_raw} />
    </dl>
    {p.quantity_kind === "tc_pressure_slope" && <p className="mt-3 text-sm">This is a pressure slope of the reported transition temperature. Its sign and source criterion are retained. It is not an independent input for predicting Tc.</p>}
    {p.quantity_kind === "electrical_resistivity" && <p className="mt-3 text-sm">Resistivity requires its reported specimen and measurement conditions. A normalization reference does not establish the identity of a pressure-series specimen.</p>}
    {sample?.payload.formula_raw === null && <p className="mt-3 rounded bg-sage-surface p-3 text-sm">Formula missingness: {displayValue(missing.explanation)}</p>}
    <h3 className="mt-4 font-semibold">Sample state and conditions</h3>
    {explicitAmbient && <p className="mt-1 text-sm">The source explicitly reports ambient pressure.{pressure.condition_id === null && " No numeric pressure is reported for this declaration."}</p>}
    {Object.keys(pressure).length > 0 && <dl className="mt-2 grid gap-x-4 sm:grid-cols-3"><Field name="Pressure availability" value={pressure.availability} /><Field name="Pressure regime" value={pressure.regime} /><OptionalField name="Pressure wording" value={pressure.basis_raw} /></dl>}
    {!hasMeasurementPressure && !explicitAmbient && <p className="mt-1 text-sm">Measurement pressure is unavailable for this state. Ambient pressure is not inferred.</p>}
    {conditions.length === 0 ? <p className="mt-1 text-sm">No conditions are retained for this state.</p> : <ul className="mt-2 space-y-2">{conditions.map((condition, i) => {
      const c = object(condition); return <li key={i} className="rounded bg-sage-surface p-3"><dl className="grid gap-x-4 sm:grid-cols-3"><Field name="Condition" value={c.kind === "reported_magnetic_field" ? "Reported magnetic field" : c.kind} /><Field name="Purpose" value={c.role} /><Field name="Source quantity" value={object(c.quantity).raw} /><OptionalField name="Reported basis" value={c.basis_raw} /><OptionalField name="Orientation" value={c.orientation_raw} /><OptionalField name="Window position" value={c.window_position} /></dl>{c.kind === "reported_magnetic_field" && <p className="mt-2 text-sm">Field convention unresolved. Source units are preserved; no B/H conversion is applied.</p>}</li>;
    })}</ul>}
    <h3 className="mt-4 font-semibold">Review issues and task exclusions</h3>
    <p className="mt-1 text-sm">These are extraction candidates. Their source bindings and scientific meaning still require review.</p>
    <ul className="mt-2 list-inside list-disc break-words text-sm">{result.issues.map(code => <li key={code}>{label(code)}</li>)}</ul>
    {exclusions && <details className="mt-2 text-sm"><summary className="cursor-pointer">Training exclusions</summary><pre className="whitespace-pre-wrap break-all p-2 text-xs">{JSON.stringify(exclusions, null, 2)}</pre></details>}
    <FullFields title="Complete result fields and normalization" row={result} /><FullFields title="Complete sample fields" row={sample} /><FullFields title="Complete state fields" row={state} /><FullFields title="Complete procedure fields" row={protocol} />
    <details className="mt-3 text-sm"><summary className="cursor-pointer">Sample relations and condition support · {relations.length} / {supports.length}</summary><p className="mt-2">Retained relations may be invalid. Their presence does not establish physical support.</p><pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all p-2 text-xs">{JSON.stringify({ sample_relations: relations, condition_supports: supports }, null, 2)}</pre></details>
  </article>;
}

export function MaterialsProposalReview({ initialWorkId = "" }: { initialWorkId?: string }) {
  const [work, setWork] = useState(initialWorkId), [queryWork, setQueryWork] = useState(initialWorkId);
  const [queue, setQueue] = useState<ProposalQueue | null>(null);
  const [detail, setDetail] = useState<ProposalDetail | null>(null);
  const [selected, setSelected] = useState<ProposalRow | null>(null);
  const [evidence, setEvidence] = useState<ProposalEvidence | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const generation = useRef(0), request = useRef<AbortController | null>(null);
  function begin() { request.current?.abort(); request.current = new AbortController(); const id = ++generation.current; setBusy(true); setError(null); return { signal: request.current.signal, active: () => generation.current === id && !request.current?.signal.aborted }; }
  function clear() { setQueue(null); setDetail(null); setSelected(null); setEvidence(null); }
  function fail(caught: unknown) {
    request.current?.abort(); generation.current += 1; clear(); setBusy(false);
    setError(caught instanceof ApiError && caught.status === 401 ? "Sign in, then refresh access to inspect proposals."
      : caught instanceof ApiError && caught.status === 403 ? "An active curator or reviewer grant is required. Previously displayed evidence has been cleared."
      : caught instanceof ApiError && caught.status === 404 ? "The private proposal review is unavailable. No empty-dataset conclusion is implied."
      : "The review data could not be checked. Previously displayed evidence has been cleared. Refresh access to try again.");
  }
  async function load(workId = work, after: string | null = null) {
    const state = begin(); clear(); setQueryWork(workId);
    try {
      const access = await materialsProposalCapabilities(state.signal); if (!state.active()) return;
      if (!proposalAccess(access)) throw new Error("Unsupported access response");
      const value = proposalQueue(await materialsProposalRuns(workId, after, state.signal)); if (!state.active()) return;
      if (!value || value.after !== after || value.work_id !== (workId || null)) throw new Error("Mismatched proposal page");
      setQueue(value); setBusy(false);
    } catch (caught) { if (state.active()) fail(caught); }
  }
  async function open(run: ProposalRun, after: string | null = null) {
    const state = begin(); setDetail(null); setSelected(null); setEvidence(null);
    try {
      const value = proposalDetail(await materialsProposalDetail(run.run_id, after, state.signal), run); if (!state.active()) return;
      if (!value || value.after !== after) throw new Error("Mismatched detail page");
      setDetail(value); setBusy(false);
    } catch (caught) { if (state.active()) fail(caught); }
  }
  async function inspect(result: ProposalRow, after = -1) {
    if (!detail) return;
    const state = begin(); setSelected(result); setEvidence(null);
    try {
      const value = proposalEvidence(await materialsProposalEvidence(detail.run.run_id, result.local_id, after, state.signal), detail.run, result.local_id); if (!state.active()) return;
      if (!value || value.after !== after) throw new Error("Mismatched evidence page");
      setEvidence(value); setBusy(false);
    } catch (caught) { if (state.active()) fail(caught); }
  }
  async function download() {
    if (!detail || !selected || !evidence) return;
    const state = begin();
    try {
      const freshDetail = proposalDetail(await materialsProposalDetail(detail.run.run_id, detail.after, state.signal), detail.run); if (!state.active()) return;
      const freshEvidence = proposalEvidence(await materialsProposalEvidence(detail.run.run_id, selected.local_id, evidence.after, state.signal), detail.run, selected.local_id); if (!state.active()) return;
      if (!freshDetail || !freshEvidence || freshDetail.after !== detail.after || freshEvidence.after !== evidence.after) throw new Error("Export snapshot mismatch");
      const body = { version: "materials-proposal-review-export/1", scope: "visible_review_pages", detail: freshDetail, evidence: freshEvidence };
      const url = URL.createObjectURL(new Blob([JSON.stringify(body, null, 2) + "\n"], { type: "application/json" }));
      const link = document.createElement("a"); link.href = url; link.download = `materials-review-${detail.run.run_id.slice(0, 12)}.json`; link.click(); URL.revokeObjectURL(url); setBusy(false);
    } catch (caught) { if (state.active()) fail(caught); }
  }
  async function downloadRun() {
    if (!detail) return;
    const state = begin();
    try {
      const descriptor = proposalExport(await materialsProposalExport(detail.run.run_id, state.signal), detail.run); if (!state.active()) return;
      if (!descriptor) throw new Error("Unsupported complete export");
      const bytes = await materialsProposalExportFile(descriptor.run.run_id, descriptor.sha256, descriptor.bytes, state.signal); if (!state.active()) return;
      const url = URL.createObjectURL(new Blob([bytes.slice().buffer as ArrayBuffer], { type: "application/zip" }));
      const link = document.createElement("a"); link.href = url; link.download = descriptor.filename; link.click(); URL.revokeObjectURL(url); setBusy(false);
    } catch (caught) { if (state.active()) fail(caught); }
  }
  useEffect(() => {
    void load(initialWorkId);
    const unsubscribe = onAuthChange(() => fail(new ApiError(401, null, "Session changed")));
    const hide = () => { if (document.visibilityState === "hidden") { request.current?.abort(); generation.current += 1; clear(); setBusy(false); setError("Private evidence was cleared while this page was inactive. Refresh access to continue."); } };
    document.addEventListener("visibilitychange", hide);
    return () => { generation.current += 1; request.current?.abort(); unsubscribe(); document.removeEventListener("visibilitychange", hide); };
    // Mount only. Each explicit read and download rechecks server authorization.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return <main className="mx-auto max-w-7xl space-y-5 p-4 sm:p-6">
    <header><p className="text-xs font-medium uppercase tracking-wide text-sage-muted">Materials · Private source review</p><h1 className="mt-1 text-2xl font-semibold">Paper assertions and evidence</h1><p className="mt-2 max-w-3xl text-sm text-sage-muted">Inspect each extraction by paper, sample and state. Quarantined and pending records are retained for review. No result here is approved for training or publication.</p></header>
    <form className={`${panel} flex flex-wrap items-end gap-3`} onSubmit={event => { event.preventDefault(); void load(); }}>
      <label className="flex min-w-56 flex-1 flex-col gap-1 text-sm">Paper ID (optional)<input className="rounded border border-sage-border p-2" value={work} onChange={e => setWork(e.target.value)} maxLength={100} placeholder="arxiv:1410.1696" /></label>
      <button className={button} disabled={busy} type="submit">Refresh access and search</button>
    </form>
    {error && <p role="alert" className="rounded border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">{error}</p>}
    {busy && <p role="status" className="text-sm text-sage-muted">Checking retained data and access…</p>}
    {queue && <section className={panel} aria-labelledby="proposal-runs"><h2 id="proposal-runs" className="font-semibold">Retained extraction runs</h2><p className="mt-1 text-xs text-sage-muted">Alternate attempts are separate. Row counts are not independent measurements or accepted results.</p>
      {queue.items.length === 0 ? <p className="mt-3 text-sm">No runs were returned for this query.</p> : <ul className="mt-3 divide-y divide-sage-border">{queue.items.map(run => <li key={run.run_id} className="py-3"><button className="w-full text-left text-sm text-accent-deep disabled:opacity-50" disabled={busy} onClick={() => void open(run)}><span className="font-semibold">{run.work_id}</span> · {run.title}<span className="mt-1 block text-xs text-sage-muted">{run.model} · {run.worker_state} · {run.result_count.toLocaleString("en-US")} result versions · {run.run_id.slice(0, 12)}</span></button></li>)}</ul>}
      <button className={`${button} mt-3`} disabled={busy || queue.next_cursor === null} onClick={() => void load(queryWork, queue.next_cursor)}>Next run page</button>
    </section>}
    {detail && <section className={panel} aria-labelledby="proposal-results"><h2 id="proposal-results" className="font-semibold">Results by sample and state</h2>
      <p className="mt-1 text-sm">{detail.run.work_id} · {detail.run.worker_state}. Canonical material identity has not been assigned by this review.</p>
      {detail.results.length === 0 ? <p className="mt-3 text-sm">This attempt retained no result rows. Its failure and source coverage remain available below.</p> : <div className="mt-3 overflow-x-auto"><table className="w-full min-w-[640px] text-left text-sm"><thead><tr><th className="p-2">Result</th><th className="p-2">Source value</th><th className="p-2">Sample / state</th><th className="p-2">Review</th></tr></thead><tbody>{detail.results.map(row => <tr key={row.local_id} className="border-t border-sage-border"><td className="p-2"><button className="text-accent-deep underline" disabled={busy} onClick={() => void inspect(row)}>{row.local_id} · {displayValue(row.payload.quantity_kind)}</button></td><td className="p-2">{displayValue(object(row.payload.quantity).raw)}</td><td className="p-2">{displayValue(row.payload.sample_id)} / {displayValue(row.payload.state_id)}</td><td className="p-2">{label(row.review_status)}</td></tr>)}</tbody></table></div>}
      <button className={`${button} mt-3`} disabled={busy || detail.next_cursor === null} onClick={() => void open(detail.run, detail.next_cursor)}>Next result page</button>
      <button className={`${button} mt-3 sm:ml-3`} disabled={busy} onClick={() => void downloadRun()}>Download complete run (ZIP)</button>
      <p className="mt-2 text-xs text-sage-muted">Includes every retained result in this run as an English CSV, the complete scientific graph, source evidence and file checksums. Paper coverage and scientific review remain separate.</p>
      <details className="mt-3 text-sm"><summary className="cursor-pointer">Source coverage, versions and run failures</summary><pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-all rounded bg-sage-surface p-3 text-xs">{JSON.stringify({ sources: detail.source_documents, coverage: detail.coverage, validation: detail.validation }, null, 2)}</pre></details>
    </section>}
    {detail && <SourceItemAccounting detail={detail} />}
    {detail && selected && <ResultReading detail={detail} result={selected} />}
    {detail && selected && <MaterialsAmendmentReview key={`${detail.run.run_id}:${detail.run.packet_sha256}:${selected.local_id}`} detail={detail} original={selected} onRefusal={fail} />}
    {evidence && selected && <section className={panel} aria-labelledby="proposal-evidence"><div className="flex flex-wrap items-center justify-between gap-3"><h2 id="proposal-evidence" className="font-semibold">Captured source passages</h2><button className={button} disabled={busy} onClick={() => void download()}>Download visible review (JSON)</button></div><p className="mt-2 text-sm text-sage-muted">Exact captured text for the selected result and related context. A resolved quotation does not prove the field binding or scientific interpretation. This page shows {evidence.items.length.toLocaleString("en-US")} of {evidence.total_count.toLocaleString("en-US")} bindings.</p>
      {evidence.items.length === 0 && <p className="mt-3 text-sm">No resolved evidence is retained for this selection.</p>}
      <ol className="mt-4 space-y-4">{evidence.items.map(item => <li key={item.ordinal} className="rounded border border-sage-border p-3"><code className="block break-all text-xs text-accent-deep">{item.path}</code><blockquote className="mt-2 whitespace-pre-wrap break-words border-l-2 border-sage-border pl-3 text-sm">{item.quote}</blockquote><p className="mt-3 break-all text-xs text-sage-muted">{item.locator} · characters {item.start_char.toLocaleString("en-US")}–{item.end_char.toLocaleString("en-US")}</p><details className="mt-2 text-xs"><summary className="cursor-pointer">Source hashes and document identity</summary><pre className="whitespace-pre-wrap break-all">{JSON.stringify({ document_id: item.document_id, block_id: item.block_id, block_sha256: item.block_sha256, quote_sha256: item.quote_sha256 }, null, 2)}</pre></details></li>)}</ol>
      <button className={`${button} mt-4`} disabled={busy || evidence.next_cursor === null} onClick={() => void inspect(selected, evidence.next_cursor ?? -1)}>Next evidence page</button><p className="mt-2 text-xs text-sage-muted">The JSON download contains the visible review pages and their continuation cursors. It is not a full-paper or training dataset export.</p>
    </section>}
  </main>;
}
