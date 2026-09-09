"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import { onAuthChange } from "@/lib/auth-session";
import { MaterialDetails, PolicyDetails } from "@/components/ScientificDiscoveryMatrix";
import { AVAILABILITY_LABELS, SCIENTIFIC_DISCLAIMER, SCIENTIFIC_FIELDS, SCIENTIFIC_KEYS, scientificQuantity, type ScientificKey } from "@/lib/discovery-scientific";
import { BUNDLE_LIMIT, SELECTION_FAILURE, getSelectionAccess, getSelectionContext, getSelectionOutcome, inventoryCell,
  parsePreparedSelection, parseRegistrationReceipt, parseSelectionAccess, parseSelectionContext, prepareSelection,
  recoveryFor, registerSelection, selectedInventory, selectionCode, selectionSourceFromFile, selectionUUID,
  type CellChoice, type ContextReceipt, type MaterialChoice, type PreparedSelection, type RegistrationReceipt,
  type SelectionAccess, type SelectionCandidate, type SelectionRecovery, type SelectionSource } from "@/lib/discovery-selection";

const button = "min-h-11 rounded-lg border border-sage-border bg-white px-3 py-2 text-sm hover:bg-sage-surface disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent";
const input = "min-h-11 min-w-0 w-full rounded-lg border border-sage-border bg-white p-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent";
const panel = "min-w-0 space-y-4 rounded-xl border border-sage-border bg-white p-4 sm:p-5";
type Draft = { assessmentId: string; structureChoice: string; rationale: string; overrides: Partial<Record<ScientificKey, CellChoice>> };
const emptyDraft = (): Draft => ({ assessmentId: "", structureChoice: "", rationale: "", overrides: {} });
const structureId = (d: Draft) => d.structureChoice === "none" ? null : d.structureChoice;
const evidenceKey = (r: CellChoice["evidence_refs"][number]) => `${r.table}:${r.row_id}`;
async function abandonOnAbort<T>(work: () => Promise<T>, signal: AbortSignal): Promise<T> {
  if (signal.aborted) throw new Error("Private verification interrupted");
  let stop!: () => void;
  const aborted = new Promise<never>((_, reject) => { stop = () => reject(new Error("Private verification interrupted")); });
  signal.addEventListener("abort", stop, { once: true });
  try { return await Promise.race([work(), aborted]); }
  finally { signal.removeEventListener("abort", stop); }
}
function inventory(m: SelectionCandidate, d: Draft) {
  return d.assessmentId && d.structureChoice ? selectedInventory(m, d.assessmentId, structureId(d)) : null;
}
function choicesFor(context: ContextReceipt | null, drafts: Record<string, Draft>): MaterialChoice[] | null {
  if (!context) return null;
  const choices: MaterialChoice[] = []; let count = 0;
  for (const m of context.context.materials) {
    const d = drafts[m.descriptor.id] ?? emptyDraft(), inv = inventory(m, d);
    if (!inv || !d.rationale.trim() || Array.from(d.rationale).length > 2000 || d.rationale.includes("\0")) return null;
    count += inv.results.length;
    const cells = SCIENTIFIC_KEYS.map(k => d.overrides[k] ?? inventoryCell(k, inv.results));
    for (const c of cells) {
      const results = inv.results.filter(r => r.property_key === c.property_key), quantified = results.filter(r => r.quantity.relation !== "unreported");
      if (results.length > 8 || !selectionCode(c.reason_code) || c.evidence_refs.length > 20) return null;
      if (["not_computed", "not_applicable", "conflicted"].includes(c.availability) && !c.evidence_refs.length) return null;
      if (["not_computed", "not_applicable"].includes(c.availability) && quantified.length) return null;
      if (c.availability === "conflicted" && (quantified.length < 2 || new Set(quantified.map(r => r.component_key)).size !== 1)) return null;
    }
    choices.push({ material_id: m.descriptor.id, assessment_id: d.assessmentId, structure_id: structureId(d), rationale: d.rationale, cells });
  }
  return count <= 100 ? choices : null;
}

/** No local/session storage. Only opaque original-request pins survive an
 * uncertain write inside this mounted page, and only the original actor can see them. */
export function DiscoverySelectionWorkbench() {
  const [access, setAccess] = useState<SelectionAccess | null>(null);
  const [packageId, setPackageId] = useState(""), [file, setFile] = useState<File | null>(null), [fileEpoch, setFileEpoch] = useState(0);
  const [source, setSource] = useState<SelectionSource | null>(null), [context, setContext] = useState<ContextReceipt | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({}), [prepared, setPrepared] = useState<PreparedSelection | null>(null);
  const [rehearsal, setRehearsal] = useState<RegistrationReceipt | null>(null), [receipt, setReceipt] = useState<RegistrationReceipt | null>(null);
  const [recovery, setRecovery] = useState<SelectionRecovery | null>(null), [unresolved, setUnresolved] = useState(false);
  const [busy, setBusy] = useState(false), [message, setMessage] = useState(""), [expanded, setExpanded] = useState<string | null>(null);
  const mounted = useRef(true), epoch = useRef(0), inFlight = useRef(false), controller = useRef<AbortController | null>(null);
  const retained = useRef<SelectionRecovery | null>(null), detailTrigger = useRef<HTMLButtonElement | null>(null), heading = useRef<HTMLHeadingElement | null>(null);
  const locked = busy || unresolved || !access;
  function clearPreview() { setPrepared(null); setRehearsal(null); setExpanded(null); setReceipt(null); }
  function clearInputs() {
    setPackageId(""); setFile(null); setFileEpoch(n => n + 1); setSource(null); setContext(null); setDrafts({}); clearPreview();
  }
  function clearPrivate() {
    epoch.current++; controller.current?.abort(); inFlight.current = false; setBusy(false); clearInputs(); setAccess(null);
    setRecovery(null); setUnresolved(retained.current !== null);
  }
  function begin() {
    if (inFlight.current) return null;
    inFlight.current = true; setBusy(true); setMessage("");
    const generation = ++epoch.current, next = new AbortController(); controller.current?.abort(); controller.current = next;
    const timer = window.setTimeout(() => next.abort(), 55_000);
    return { signal: next.signal, active: () => mounted.current && epoch.current === generation,
      live: () => mounted.current && epoch.current === generation && !next.signal.aborted,
      finish: () => { window.clearTimeout(timer); if (mounted.current && epoch.current === generation) { inFlight.current = false; setBusy(false); } } };
  }
  async function fresh(signal: AbortSignal, original?: SelectionAccess) {
    const current = parseSelectionAccess(await getSelectionAccess(signal));
    if (original && (current.actor_user_id !== original.actor_user_id || current.actor_grant_id !== original.actor_grant_id)) throw new ApiError(401, null, "Access changed");
    return current;
  }
  function failed(error: unknown) {
    clearPreview();
    if (error instanceof ApiError && [401, 403].includes(error.status)) {
      clearPrivate(); setMessage("Curator access changed. Private files and results were cleared. Refresh access to continue.");
    } else setMessage(SELECTION_FAILURE);
  }
  async function refresh() {
    if (inFlight.current) return;
    clearPrivate(); const call = begin()!;
    try {
      const current = await fresh(call.signal); if (!call.live()) return; setAccess(current);
      if (retained.current) {
        if (retained.current.actorId === current.actor_user_id) setRecovery(retained.current);
        else setMessage("An unresolved registration belongs to another account. Sign in as the original account; new registrations remain locked here.");
      }
    } catch (error) { if (call.active()) failed(error); } finally { call.finish(); }
  }
  useEffect(() => {
    mounted.current = true; void refresh();
    const clear = () => { clearPrivate(); setMessage("Session or page context changed. Private drafts were cleared. Refresh curator access."); };
    const unsubscribe = onAuthChange(clear);
    const warn = (event: BeforeUnloadEvent) => { if (retained.current) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("pagehide", clear); window.addEventListener("beforeunload", warn);
    return () => { mounted.current = false; epoch.current++; controller.current?.abort(); unsubscribe(); window.removeEventListener("pagehide", clear); window.removeEventListener("beforeunload", warn); };
    // Admission happens on mount and explicit actions, never on file selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => { if (prepared || receipt) heading.current?.focus({ preventScroll: true }); }, [prepared, receipt]);
  function edit(id: string, patch: Partial<Draft>, changedContext = false) {
    if (locked || inFlight.current) return;
    clearPreview(); setMessage(""); setDrafts(previous => ({ ...previous, [id]: {
      ...(previous[id] ?? emptyDraft()), ...(changedContext ? { rationale: "", overrides: {} } : {}), ...patch,
    } }));
  }
  async function inspect() {
    if (locked || !file || !selectionUUID(packageId) || file.size <= 0 || file.size > BUNDLE_LIMIT) return;
    const call = begin(); if (!call) return;
    setSource(null); setContext(null); setDrafts({}); clearPreview();
    try {
      const current = await fresh(call.signal, access!); if (!call.live()) return;
      // File.arrayBuffer and crypto are not cancellable; race the deadline and
      // check the generation again after every async boundary before upload.
      const original = await abandonOnAbort(() => selectionSourceFromFile(file, packageId), call.signal);
      if (!call.live()) return;
      const raw = await getSelectionContext(original, call.signal); if (!call.live()) return;
      const value = await abandonOnAbort(() => parseSelectionContext(raw, current, original), call.signal); if (!call.live()) return;
      setSource(original); setContext(value); setAccess(current);
      setDrafts(Object.fromEntries(value.context.materials.map(m => [m.descriptor.id, emptyDraft()])));
    } catch (error) { if (call.active()) failed(error); } finally { call.finish(); }
  }
  async function compile() {
    const choices = choicesFor(context, drafts);
    if (locked || !choices || !source || !context) return;
    const call = begin(); if (!call) return; clearPreview();
    try {
      const current = await fresh(call.signal, access!); if (!call.live()) return;
      const request = { source, expected_context_sha256: context.context_sha256, request_key: `browser-discovery:${crypto.randomUUID()}`, choices };
      const raw = await prepareSelection(request, call.signal); if (!call.live()) return;
      const value = await abandonOnAbort(() => parsePreparedSelection(raw, current, context, request), call.signal); if (!call.live()) return;
      setPrepared(value); setAccess(current);
    } catch (error) { if (call.active()) failed(error); } finally { call.finish(); }
  }
  async function register(commit: boolean) {
    if (locked || !prepared || commit && !rehearsal) return;
    const call = begin(); if (!call) return;
    const original = prepared, locator = recoveryFor(original); let submitted = false;
    if (!commit) setRehearsal(null);
    try {
      const current = await fresh(call.signal, access!); if (!call.live()) return;
      if (current.actor_user_id !== original.actor_user_id || current.actor_grant_id !== original.actor_grant_id) throw new ApiError(401, null, "Access changed");
      if (commit) { retained.current = locator; setRecovery(locator); setUnresolved(true); submitted = true; }
      const raw = await registerSelection(commit ? original.commit_json : original.preview_json, call.signal);
      if (!call.live()) return;
      const value = parseRegistrationReceipt(raw, locator, commit);
      if (commit) {
        clearInputs(); retained.current = null; setRecovery(null); setUnresolved(false); setReceipt(value);
        setMessage("Exact registration confirmed. This receipt does not approve science, ML training or public publication.");
      } else { setRehearsal(value); setMessage("Native registration rehearsal verified. No registration was committed."); }
    } catch (error) {
      if (!call.active()) return;
      if (!submitted) failed(error);
      else {
        clearInputs();
        if (error instanceof ApiError && [401, 403].includes(error.status)) clearPrivate();
        setMessage("Registration outcome is unknown. Private drafts were cleared. Check the original request; an error does not prove rollback. No write is retried automatically.");
      }
    } finally { call.finish(); }
  }
  async function recover() {
    if (!recovery || inFlight.current) return;
    const original = recovery, call = begin()!;
    try {
      const current = await fresh(call.signal); if (!call.live()) return;
      if (current.actor_user_id !== original.actorId) throw new ApiError(401, null, "Recovery account changed");
      const raw = await getSelectionOutcome(original, call.signal); if (!call.live()) return;
      const value = parseRegistrationReceipt(raw, original, true, true);
      clearInputs(); retained.current = null; setRecovery(null); setUnresolved(false); setReceipt(value); setAccess(current);
      setMessage("Original registration recovered. Historical durability does not establish current publication eligibility.");
    } catch (error) {
      if (!call.active()) return;
      if (error instanceof ApiError && [401, 403].includes(error.status)) { clearPrivate(); setMessage("Access changed. Refresh under the original account to recover its request."); }
      else setMessage(error instanceof ApiError && error.status === 404
        ? "No original outcome was visible in this snapshot. The write may still be in flight; no rollback or safe retry is inferred."
        : "The original outcome remains unverified. No new write was sent.");
    } finally { call.finish(); }
  }
  const choices = choicesFor(context, drafts);
  const detail = prepared?.payload.rows.find(r => r.material.row_id === expanded);
  return <div className="min-w-0 space-y-5">
    <header className="space-y-3"><h2 className="text-xl font-semibold">Discovery selection</h2>
      <p className="text-sm text-sage-muted">Curator workbench · one explicit representative state and research action per material, with all alternative assessments retained.</p>
      <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">RPS is a frozen research-priority score, not superconductivity probability. Registration is not scientific acceptance, ML training approval or public publication.</p>
      <p className="text-sm">{SCIENTIFIC_DISCLAIMER}</p>
      <p className="text-sm text-sage-muted">Compare policy scores only within the same frozen campaign, budget, policy and release, and within the same eligible role / rank group. No score is recomputed here.</p>
      <button className={button} disabled={busy} onClick={() => void refresh()}>Refresh curator access</button>
      {access && <p className="text-sm">Current curator access verified. Frozen context quantities are not current scientific acceptance.</p>}
    </header>
    <div aria-live="polite">{busy && <p role="status">Verifying the exact private operation…</p>}{message && <p role="alert" className="rounded-lg border border-sage-border p-3 text-sm">{message}</p>}</div>
    {recovery && <section className={panel} aria-label="Original registration recovery">
      <h3 className="font-semibold">Original registration request</h3>
      <p className="text-sm">Keep this page open. Navigation or reload loses this in-memory locator. Retain these references in your approved private operation record; keep the original source package separately.</p>
      <pre className="overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(recovery, null, 2)}</pre>
      <button className={button} disabled={busy} onClick={() => void recover()}>Check original outcome</button>
      <p className="text-sm">Read only, under the original account. No automatic retry, replacement request key or rollback inference.</p>
    </section>}
    <section className={panel} aria-label="Frozen distribution source">
      <h3 className="font-semibold">1. Inspect a frozen distribution</h3>
      <label className="block text-sm">Distribution package ID<input className={input} value={packageId} maxLength={36} disabled={locked} onChange={e => {
        if (!locked && !inFlight.current) { setPackageId(e.target.value); setSource(null); setContext(null); setDrafts({}); clearPreview(); setMessage(""); }
      }} /></label>
      <label className="block text-sm">Original public-bundle JSON file<input key={fileEpoch} className={input} type="file" accept="application/json,.json" disabled={locked} onChange={e => {
        if (!locked && !inFlight.current) { setFile(e.target.files?.[0] ?? null); setSource(null); setContext(null); setDrafts({}); clearPreview(); setMessage(""); }
      }} /></label>
      <p className="text-sm text-sage-muted">Select the original canonical UTF-8 file, up to 16 MiB. Choosing a file does not upload it. Inspect sends its exact text to the existing private API; no URL or local server path is fetched.</p>
      <button className={button} disabled={locked || !selectionUUID(packageId) || !file || file.size <= 0 || file.size > BUNDLE_LIMIT} onClick={() => void inspect()}>Inspect frozen distribution</button>
      {source && <p className="break-all text-xs">Original file SHA-256: {source.expected_public_bundle_text_sha256}</p>}
    </section>
    {context && <section className="space-y-4" aria-label="Explicit representative choices">
      <h3 className="text-lg font-semibold">2. Choose representatives</h3>
      <p className="text-sm">Choose both a state / action assessment and a structure for every material. No highest-score default is applied. Changing either clears the previous rationale and availability declarations.</p>
      <details className={panel}><summary className="cursor-pointer text-sm">Frozen campaign and context pins</summary><pre className="overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify({ ...context.context, materials: undefined, context_sha256: context.context_sha256 }, null, 2)}</pre></details>
      {context.context.materials.map(m => {
        const d = drafts[m.descriptor.id] ?? emptyDraft(), inv = inventory(m, d);
        return <section key={m.descriptor.id} className={panel} aria-label={`Representative ${m.descriptor.id}`}>
          <h4 className="font-semibold">{m.assessments[0].assessment.formula} · {m.descriptor.id}</h4>
          <p className="break-all text-xs text-sage-muted">Actual material: {m.material.row_id}. RPS descriptor IDs are not native state or structure IDs.</p>
          <label className="block text-sm">State and action assessment<select className={input} value={d.assessmentId} disabled={locked} onChange={e => edit(m.descriptor.id, { assessmentId: e.target.value }, true)}>
            <option value="">Choose an assessment explicitly</option>
            {m.assessments.map(a => <option key={a.reference.id} value={a.reference.id}>{a.reference.id} · {a.assessment.state_summary} · {a.assessment.action_summary} · RPS {a.assessment.result.score_display?.toLocaleString("en-US") ?? "Unranked"}</option>)}
          </select></label>
          <label className="block text-sm">Structure binding<select className={input} value={d.structureChoice} disabled={locked} onChange={e => edit(m.descriptor.id, { structureChoice: e.target.value }, true)}>
            <option value="">Choose a structure binding explicitly</option>
            {m.structures.map(s => <option key={s.reference?.row_id ?? "none"} value={s.reference?.row_id ?? "none"}>{s.reference ? `${s.structure_kind.replaceAll("_", " ")} · ${s.reference.row_id}` : "No structure selected — unbound events only"}</option>)}
          </select></label>
          <label className="block text-sm">Selection rationale<textarea className={input} rows={3} maxLength={4000} disabled={locked || !inv} value={d.rationale} onChange={e => edit(m.descriptor.id, { rationale: e.target.value })} /></label>
          <p className="text-xs text-sage-muted">Required, up to 2,000 Unicode characters. Explain why this state and action represents the material in this campaign; do not paste private source text.</p>
          <details className="space-y-3"><summary className="min-h-11 cursor-pointer py-2 text-sm">All frozen policy assessments ({m.assessments.length.toLocaleString("en-US")})</summary>{m.assessments.map(a => <PolicyDetails key={a.reference.id} assessment={a.assessment} />)}</details>
          {inv && <div className="space-y-3">
            <p className="break-all text-sm">Selected native state: {inv.assessment.state.row_id} · {inv.results.length.toLocaleString("en-US")} matching results. All matching results are retained; numeric values cannot be edited here.</p>
            <p className="text-sm text-sage-muted">Current event type, scientific reviews and provenance are resolved in the compiled preview, not inferred from this inventory. At most 8 results per field and 100 overall can be projected; excess results require a separately reviewed upstream package, not hidden exclusions.</p>
            {SCIENTIFIC_KEYS.map(k => {
              const cell = d.overrides[k] ?? inventoryCell(k, inv.results), results = inv.results.filter(r => r.property_key === k), quantified = results.filter(r => r.quantity.relation !== "unreported");
              const conflictPossible = quantified.length >= 2 && new Set(quantified.map(r => r.component_key)).size === 1;
              return <details key={k} className="rounded-lg border border-sage-border p-3">
                <summary className="min-h-11 cursor-pointer py-2 text-sm font-medium">{SCIENTIFIC_FIELDS[k].label} · {AVAILABILITY_LABELS[cell.availability]} · {results.length.toLocaleString("en-US")} results</summary>
                <div className="space-y-3 pt-2">
                  {results.length === 0 && <p className="text-sm">No matching registered result. Missing data is not zero or evidence against superconductivity.</p>}
                  {results.map(r => <div key={r.reference.row_id} className="space-y-1 text-sm"><p>{r.component_key} · {scientificQuantity(r.quantity)} · {r.event.knowledge_origin}</p><details><summary className="cursor-pointer">Exact inventory result pins</summary><pre className="overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(r, null, 2)}</pre></details></div>)}
                  <label className="block text-sm">{SCIENTIFIC_FIELDS[k].label} availability declaration<select className={input} disabled={locked} value={d.overrides[k]?.availability ?? "inventory"} onChange={e => {
                    const overrides = { ...d.overrides };
                    if (e.target.value === "inventory") delete overrides[k];
                    else overrides[k] = { property_key: k, availability: e.target.value as CellChoice["availability"], reason_code: "", evidence_refs: [] };
                    edit(m.descriptor.id, { overrides });
                  }}><option value="inventory">Use registered inventory ({AVAILABILITY_LABELS[inventoryCell(k, inv.results).availability]})</option>
                    <option value="not_computed" disabled={!!quantified.length || !inv.evidence.length}>Not computed — explicit evidence required</option>
                    <option value="not_applicable" disabled={!!quantified.length || !inv.evidence.length}>Not applicable — explicit evidence required</option>
                    <option value="conflicted" disabled={!conflictPossible || !inv.evidence.length}>Conflicted — same-component evidence required</option>
                  </select></label>
                  {d.overrides[k] && <fieldset disabled={locked} className="space-y-3"><legend className="text-sm">Explicit declaration evidence</legend>
                    <p className="text-xs text-sage-muted">A declaration is not an accepted scientific review. Family labels alone do not establish applicability. Choose up to 20 context-matched references.</p>
                    <label className="block text-sm">{SCIENTIFIC_FIELDS[k].label} reason code<input className={input} value={cell.reason_code} maxLength={160} onChange={e => edit(m.descriptor.id, { overrides: { ...d.overrides, [k]: { ...cell, reason_code: e.target.value } } })} /></label>
                    <p className="text-xs text-sage-muted">Use a lowercase code starting with a letter, with letters, digits or underscores.</p>
                    {inv.evidence.map(e => <label key={evidenceKey(e.reference)} className="flex min-h-11 items-start gap-2 break-all text-sm"><input type="checkbox" className="mt-1" checked={cell.evidence_refs.some(r => evidenceKey(r) === evidenceKey(e.reference))} onChange={event => {
                      const refs = cell.evidence_refs.filter(r => evidenceKey(r) !== evidenceKey(e.reference));
                      if (event.target.checked) refs.push(e.reference);
                      refs.sort((a, b) => evidenceKey(a) < evidenceKey(b) ? -1 : 1);
                      edit(m.descriptor.id, { overrides: { ...d.overrides, [k]: { ...cell, evidence_refs: refs } } });
                    }} />{e.reference.table} · {e.reference.row_id} · SHA-256 {e.reference.row_sha256}</label>)}
                  </fieldset>}
                </div>
              </details>;
            })}
          </div>}
        </section>;
      })}
      {!choices && <p className="text-sm">Complete every explicit choice, rationale and declaration within the projection limits before compiling.</p>}
      <button className={button} disabled={locked || !choices} onClick={() => void compile()}>Compile scientific preview</button>
    </section>}
    {prepared && <section className={panel} aria-label="Compiled scientific preview">
      <h3 ref={heading} tabIndex={-1} className="text-lg font-semibold">3. Inspect the complete scientific preview</h3>
      <p className="text-sm">Prepared only; no registration performed. Unreviewed scientific results may appear in this private preview. They do not meet the public scientific-acceptance requirement.</p>
      <pre className="overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify({ request_key: prepared.request_key, request_sha256: prepared.request_sha256, payload_sha256: prepared.payload_sha256, selection_sha256: prepared.selection_sha256 }, null, 2)}</pre>
      <div role="region" aria-label="Prepared materials" tabIndex={0} className="overflow-x-auto"><table className="w-full min-w-[750px] text-left text-sm">
        <caption className="sr-only">Explicit prepared representatives, frozen scores and scientific result coverage</caption>
        <thead><tr>{["Material", "State / action", "RPS", "Scientific results", "Alternatives", "Inspect"].map(h => <th key={h} scope="col" className="p-2">{h}</th>)}</tr></thead>
        <tbody>{prepared.payload.rows.map(r => <tr key={r.material.row_id} className="border-t border-sage-border"><th scope="row" className="p-2">{r.assessment.formula}</th><td className="p-2">{r.assessment.state_summary} / {r.assessment.action_summary}</td><td className="p-2">{r.assessment.result.score_display?.toLocaleString("en-US") ?? "Unranked"}</td><td className="p-2">{r.cells.reduce((n, c) => n + c.observations.length, 0).toLocaleString("en-US")} recorded; {r.cells.reduce((n, c) => n + c.observations.filter(o => o.scientific_scope_accepted).length, 0).toLocaleString("en-US")} scope accepted</td><td className="p-2">{r.alternatives.length.toLocaleString("en-US")}</td><td className="p-2"><button className={button} aria-expanded={expanded === r.material.row_id} aria-controls={expanded === r.material.row_id ? "prepared-material-details" : undefined} onClick={e => { detailTrigger.current = e.currentTarget; setExpanded(r.material.row_id); }}>Inspect {r.assessment.formula}</button></td></tr>)}</tbody>
      </table></div>
      {detail && <MaterialDetails row={detail} prepared close={() => { setExpanded(null); detailTrigger.current?.focus(); }} />}
      <div className="space-y-3 border-t border-sage-border pt-4"><h4 className="font-semibold">4. Rehearse, then register this exact preview</h4>
        <p className="text-sm">The native rehearsal verifies the original command without committing. Its provisional record ID is not the final registration ID. Editing any choice invalidates this preview and rehearsal.</p>
        <button className={button} disabled={locked} onClick={() => void register(false)}>Run registration rehearsal</button>
        {rehearsal && <p className="text-sm">Native rehearsal verified for the exact request, payload and selection hashes.</p>}
        <button className={`${button} ml-2`} disabled={locked || !rehearsal} onClick={() => void register(true)}>Register exact preview</button>
      </div>
    </section>}
    {receipt && <section className={panel} aria-label="Verified registration receipt"><h3 ref={heading} tabIndex={-1} className="font-semibold">Registration receipt</h3><pre className="overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(receipt, null, 2)}</pre><p className="text-sm">Durable registration only. Public release still requires independent scientific and publication checks; historical recovery is not a current authorization check.</p></section>}
    <p className="text-sm text-sage-muted">Scientific adjudication is a separate task in <Link className="text-accent-deep underline" href="/dashboard/research/review">Scientific evidence</Link>. This workbench does not execute calculations, change scores or publish a Discovery record.</p>
  </div>;
}
