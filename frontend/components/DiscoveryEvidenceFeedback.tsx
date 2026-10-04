"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import Link from "@/components/AppLink";
import { ApiError, discoveryDesignDetail, discoveryFeedbackCapabilities, discoveryFeedbackCommit, discoveryFeedbackContext, discoveryFeedbackOutcome, discoveryFeedbackPage, discoveryFeedbackPreview } from "@/lib/api";
import { onAuthChange } from "@/lib/auth-session";
import { FEEDBACK_REQUEST_VERSION, feedbackChildFromDetail, feedbackDesignPin, feedbackRecordHref, knownFeedbackCapabilities, knownFeedbackContext, knownFeedbackPage, knownFeedbackReceipt, knownFeedbackRecovery, knownFeedbackRequest, type FeedbackCapabilities, type FeedbackChildPin, type FeedbackContext, type FeedbackDecision, type FeedbackDesignPin, type FeedbackEntry, type FeedbackPage, type FeedbackPin, type FeedbackProjection, type FeedbackReceipt, type FeedbackRecovery, type FeedbackRequest } from "@/lib/discovery-feedback";
import { designId, knownDesignDetail, type DesignCapabilities, type DesignEntry } from "@/lib/discovery-designs";
import { retainedHc2, retainedRecordText } from "@/lib/material-retained-record";
import { expressionCanonical, expressionSha } from "@/lib/source-expressions";

const input = "mt-1 block min-h-11 w-full min-w-0 rounded-lg border border-sage-border bg-white px-3 py-2 text-sm text-sage-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent";
const button = "min-h-11 rounded-lg border border-sage-border bg-white px-3 py-2 text-sm text-sage-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50";
const primary = "min-h-11 rounded-lg bg-accent-deep px-4 py-2 text-sm font-medium text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50";
const panel = "min-w-0 space-y-3 rounded-lg border border-sage-border p-3 sm:p-4";
export type FeedbackProposalSelection = { feedback: FeedbackPin; design: FeedbackDesignPin };
type Props = { capabilities: DesignCapabilities; entry: DesignEntry | null; disabled?: boolean; invalidationKey?: number; saveRecovery?: FeedbackRecovery | null; followUpSelection?: FeedbackProposalSelection | null; savedChild?: FeedbackChildPin | null; onSaveDispatched?: (recovery: FeedbackRecovery) => void; onSaveResolved?: (recovery: FeedbackRecovery) => void; onStartLinkedProposal: (selection: FeedbackProposalSelection) => void; onFollowUpLinked?: () => void; onOpenChild: (child: FeedbackChildPin) => void; onScopeInvalid?: (error: ApiError) => void };
type Prepared = { request: FeedbackRequest; receipt: FeedbackReceipt; recovery: FeedbackRecovery };
const readable = (value: string) => value.replaceAll("_", " ");
function valueText(value: unknown): string | null { return typeof value === "number" && Number.isFinite(value) ? String(value) : retainedRecordText(value, 2000); }
function EvidenceReading({ projection, canonicalText }: { projection: FeedbackProjection; canonicalText: string }) {
  const r = projection.record, tc = r.scientific_values?.tc_kelvin;
  const tcValue = tc ? valueText(tc.raw_value) : valueText(r.tc_kelvin);
  const tcUnits = tc ? [tc.input_unit, tc.raw_unit].map(valueText).filter((v): v is string => v !== null) : [];
  const hc2 = retainedHc2(r);
  const criteria: [string, unknown][] = [["Retained Tc type", r.tc_type], ["Retained Tc definition", r.tc_definition], ["Reported criterion", r.tc_criterion], ["Criterion alias", r.criterion]];
  const hc2Context: [string, unknown][] = [["Hc2 conditions", r.hc2_conditions], ["Hc2 direction", r.hc2_direction], ["Field orientation", r.field_orientation], ["Magnetic field orientation", r.magnetic_field_orientation]];
  const longHc2Token = !r.scientific_values?.hc2_tesla && typeof r.hc2_tesla === "string" && Array.from(r.hc2_tesla).length > 500 ? valueText(r.hc2_tesla) : null;
  const withheldHc2Unit = projection.withheld_fields.includes("hc2_tesla_unit");
  const details: [string, unknown][] = [["Knowledge origin", r.knowledge_origin], ["Retained evidence type", r.evidence_type], ["Retained measurement", r.measurement], ["Retained measurement method", r.measurement_method], ["Retained method statement", r.method_statement], ["Pressure (API field: GPa)", r.pressure_gpa], ["Pressure status", r.pressure_status], ["Pressure kind", r.pressure_kind], ["Pressure conditions", r.pressure_conditions]];
  return <section className={`${panel} bg-sage-surface`} aria-label="Existing retained evidence reading">
    <div className="space-y-1"><h4 className="font-medium">{projection.formula || "Existing material record"}</h4><p className="break-words text-xs text-sage-muted">Material {projection.material_id} · retained record index {projection.record_index.toLocaleString("en-US")}</p><div className="flex flex-wrap gap-x-4 gap-y-1 text-sm"><Link className="text-accent-deep underline" href={feedbackRecordHref(projection.material_id, projection.record_index)!}>Open exact retained record</Link>{typeof r.paper_id === "string" && /^[A-Za-z0-9._:-]{1,100}$/.test(r.paper_id) && <Link className="text-accent-deep underline" href={`/paper/${encodeURIComponent(r.paper_id)}`}>Open source paper</Link>}</div>{valueText(r.id) && <p className="break-all text-xs text-sage-muted">Source record ID: {valueText(r.id)}</p>}</div>
    <dl className="grid min-w-0 gap-3 text-sm sm:grid-cols-2">
      <div className="min-w-0"><dt className="text-sage-muted">{tc ? "Retained Tc source token" : "Retained Tc (API field: K)"}</dt><dd className="break-words font-medium [overflow-wrap:anywhere]">{tcValue ?? "Not available"}{tcUnits.length > 0 && <span className="block text-xs font-normal">Stored units: {tcUnits.join(" · ")}</span>}</dd></div>
      {criteria.map(([label, raw]) => { const text = valueText(raw); return text === null ? null : <div key={label} className="min-w-0"><dt className="text-sage-muted">{label}</dt><dd className="break-words [overflow-wrap:anywhere]">{text}</dd></div>; })}
      {details.map(([label, raw]) => { const text = valueText(raw); return text === null ? null : <div key={label} className="min-w-0"><dt className="text-sage-muted">{label}</dt><dd className="break-words [overflow-wrap:anywhere]">{text}</dd></div>; })}
      <div className="min-w-0"><dt className="text-sage-muted">Retained Hc2</dt><dd className="break-words [overflow-wrap:anywhere]">{hc2 ? <><span className="font-medium">{hc2.value}{!withheldHc2Unit && hc2.displayUnit ? ` ${hc2.displayUnit}` : ""}</span>{hc2.units.map(u => <p key={u.key} className="text-xs">{u.label}: {u.value}</p>)}{(withheldHc2Unit || hc2.unitMetadataUnresolved) && <p className="text-xs">Unit metadata unresolved</p>}</> : longHc2Token ?? "Not available"}{(hc2 || longHc2Token) && hc2Context.map(([label, raw]) => { const text = valueText(raw); return text === null ? null : <p key={label} className="text-xs">{label}: {text}</p>; })}</dd></div>
    </dl>
    <p className="text-xs leading-5 text-sage-muted">These are existing source-record readings. Sharing a row does not establish a joint measurement, Hc2(0), a probe method or equivalence to the proposed sample, phase or state.</p>
    {projection.withheld_fields.length > 0 && <details className="text-xs"><summary className="cursor-pointer">Withheld source fields ({projection.withheld_fields.length})</summary><ul className="mt-2 max-h-40 overflow-auto break-all">{projection.withheld_fields.map(k => <li key={k}>{k}: invalid or exceeds the reading bound</li>)}</ul></details>}
    <details className="text-xs"><summary className="cursor-pointer">Inspect exact evidence projection and original value tokens</summary><pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-white p-3">{canonicalText}</pre></details>
  </section>;
}
async function bounded<T>(call: () => Promise<T>, controller: AbortController) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try { return await Promise.race([call(), new Promise<never>((_, reject) => { timer = setTimeout(() => { controller.abort(); reject(new Error("Private evidence request timed out")); }, 25000); })]); }
  finally { if (timer) clearTimeout(timer); }
}
export function DiscoveryEvidenceFeedback(props: Props) {
  const identity = JSON.stringify({ actor: props.capabilities.actor_user_id, session: props.capabilities.session_version, grant: props.capabilities.curator_grant_id });
  return <Workspace key={identity} {...props} />;
}
function Workspace({ capabilities: designAccess, entry, disabled = false, invalidationKey = 0, saveRecovery = null, followUpSelection = null, savedChild = null, onSaveDispatched, onSaveResolved, onStartLinkedProposal, onFollowUpLinked, onOpenChild, onScopeInvalid }: Props) {
  const initialRecovery = knownFeedbackRecovery(saveRecovery) && saveRecovery.actorId === designAccess.actor_user_id ? structuredClone(saveRecovery) : null;
  const [cap, setCap] = useState<FeedbackCapabilities | null>(null), [design, setDesign] = useState<FeedbackDesignPin | null>(null), [busy, setBusy] = useState(false), [message, setMessage] = useState("");
  const [material, setMaterial] = useState(entry?.baseline.material_id ?? ""), [index, setIndex] = useState(String(entry?.baseline.record_index ?? 0));
  const [context, setContext] = useState<FeedbackContext | null>(null), [page, setPage] = useState<FeedbackPage | null>(null);
  const [findings, setFindings] = useState(""), [decision, setDecision] = useState<FeedbackDecision | "">(""), [reason, setReason] = useState(""), [unknowns, setUnknowns] = useState("");
  const [prepared, setPrepared] = useState<Prepared | null>(null), [saved, setSaved] = useState<FeedbackReceipt | null>(null), [recovery, setRecovery] = useState<FeedbackRecovery | null>(initialRecovery);
  const [existingChildId, setExistingChildId] = useState(""), [loadedChild, setLoadedChild] = useState<FeedbackChildPin | null>(null);
  const mounted = useRef(false), sequence = useRef(0), controller = useRef<AbortController | null>(null), inFlight = useRef(false), commitIdentity = useRef<FeedbackRecovery | null>(initialRecovery), previousDraft = useRef(invalidationKey), previousEntry = useRef(entry?.record_sha256 ?? null);
  const previousFeedback = useRef(followUpSelection?.feedback.id ?? null);
  const locked = disabled || busy || recovery !== null;
  const childForLink = existingChildId.trim() ? loadedChild : savedChild;
  const currentEntry = entry?.is_head && entry.status === "proposed" && entry.eligibility.eligible && entry.baseline.kind === "retained_result" && entry.design.next_action.kind === "source_review";
  function clear() { ++sequence.current; controller.current?.abort(); inFlight.current = false; setCap(null); setDesign(null); setContext(null); setPage(null); setPrepared(null); setSaved(null); setLoadedChild(null); setExistingChildId(""); setFindings(""); setReason(""); setUnknowns(""); setDecision(""); setMaterial(""); setIndex("0"); setRecovery(commitIdentity.current); setBusy(false); }
  function begin() { const id = ++sequence.current; controller.current?.abort(); const c = new AbortController(); controller.current = c; inFlight.current = true; setBusy(true); return { signal: c.signal, active: () => mounted.current && id === sequence.current, run: <T,>(call: () => Promise<T>) => bounded(call, c) }; }
  function finish() { inFlight.current = false; setBusy(false); }
  function fail(error: unknown) {
    finish(); setPrepared(null); setContext(null); setPage(null); setSaved(null); setLoadedChild(null);
    if (error instanceof ApiError && [401, 403].includes(error.status)) { clear(); setMessage("Evidence access or session changed. Private readings and notes have been cleared."); }
    else if (error instanceof ApiError && error.status === 409) setMessage("The design, evidence source or linked child changed. Reload the exact evidence and history before continuing.");
    else if (error instanceof ApiError && error.status === 404) setMessage("Evidence returns are unavailable for this research scope.");
    else setMessage("The evidence response could not be verified. Refresh access and reload the exact source before continuing.");
    if (error instanceof ApiError && [401, 403, 409].includes(error.status)) onScopeInvalid?.(error);
  }
  async function refresh() {
    if (disabled || inFlight.current) return; const access = structuredClone(designAccess), selected = entry ? structuredClone(entry) : null, op = begin(); setCap(null); setDesign(null); setContext(null); setPage(null); setPrepared(null); setSaved(null); setLoadedChild(null); setMessage("");
    try { const next = knownFeedbackCapabilities(await op.run(() => discoveryFeedbackCapabilities(op.signal)), access); if (!op.active()) return; if (!next) throw new Error("Invalid feedback capabilities"); const pin = selected ? await feedbackDesignPin(selected) : null; if (!op.active()) return; setCap(next); setDesign(pin); finish(); }
    catch (error) { if (op.active()) fail(error); }
  }
  useEffect(() => {
    mounted.current = true; void refresh();
    const hide = () => { clear(); setMessage("Private evidence readings and prepared operations cleared after leaving this page. Refresh evidence access to continue."); };
    const visibility = () => { if (document.visibilityState === "hidden") hide(); };
    const unsubscribe = onAuthChange(() => { commitIdentity.current = null; clear(); setMessage("Session changed. Refresh evidence access to continue."); });
    window.addEventListener("pagehide", hide); document.addEventListener("visibilitychange", visibility);
    return () => { mounted.current = false; ++sequence.current; controller.current?.abort(); inFlight.current = false; unsubscribe(); window.removeEventListener("pagehide", hide); document.removeEventListener("visibilitychange", visibility); };
    // The keyed parent owns actor scope; no private notes survive a session remount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (previousDraft.current === invalidationKey && previousEntry.current === (entry?.record_sha256 ?? null)) return;
    const changed = previousEntry.current !== (entry?.record_sha256 ?? null); previousDraft.current = invalidationKey; previousEntry.current = entry?.record_sha256 ?? null;
    if (commitIdentity.current) return; ++sequence.current; controller.current?.abort(); finish(); setPrepared(null); setSaved(null); setContext(null); setMessage("Proposal scope changed. Reload evidence before preparing another return.");
    setLoadedChild(null);
    if (changed) { setExistingChildId(""); setPage(null); setFindings(""); setReason(""); setUnknowns(""); setDecision(""); setMaterial(entry?.baseline.material_id ?? ""); setIndex(String(entry?.baseline.record_index ?? 0)); setDesign(null); setCap(null); }
    // Parent draft mutations invalidate pending previews without silently repeating reads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invalidationKey, entry?.record_sha256]);
  useEffect(() => {
    if (previousFeedback.current === (followUpSelection?.feedback.id ?? null)) return;
    previousFeedback.current = followUpSelection?.feedback.id ?? null;
    if (commitIdentity.current) return; ++sequence.current; controller.current?.abort(); finish(); setPrepared(null); setLoadedChild(null); setExistingChildId("");
    // A different immutable return requires a separately verified child and fresh preview.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [followUpSelection?.feedback.id]);
  function edit(setter: () => void, selector = false) { if (locked || commitIdentity.current) return; setter(); setPrepared(null); setSaved(null); setMessage(""); if (selector) setContext(null); }
  async function loadContext() {
    if (!cap || !design || !currentEntry || locked || inFlight.current) return;
    if (!material.trim() || material.trim().length > 100 || !/^\d{1,4}$/.test(index) || Number(index) > 4999) { setMessage("Enter an exact material ID and a retained record index from 0 to 4999."); return; }
    const expected = { design: structuredClone(design), materialId: material.trim(), recordIndex: Number(index) }, current = structuredClone(cap), op = begin(); setContext(null); setPrepared(null); setSaved(null); setMessage("");
    try { const next = await knownFeedbackContext(await op.run(() => discoveryFeedbackContext(expected.design, expected.materialId, expected.recordIndex, op.signal)), current, expected); if (!op.active()) return; if (!next) throw new Error("Invalid evidence context"); setContext(next); finish(); }
    catch (error) { if (op.active()) fail(error); }
  }
  async function loadPage(offset = 0) {
    if (!cap || !design || locked || inFlight.current) return; const current = structuredClone(cap), id = design.design_id, op = begin(); setPage(null); setPrepared(null); setMessage("");
    try { const next = await knownFeedbackPage(await op.run(() => discoveryFeedbackPage(id, offset, op.signal)), current, id, offset); if (!op.active()) return; if (!next) throw new Error("Invalid feedback history"); setPage(next); finish(); }
    catch (error) { if (op.active()) fail(error); }
  }
  async function preview(request: FeedbackRequest, selectedDesign: FeedbackDesignPin) {
    if (!cap || locked || inFlight.current || !knownFeedbackRequest(request)) { setMessage("Supply bounded findings, an explicit decision and its reason. Keep unknowns distinct, with at most 16 lines."); return; }
    const detached = structuredClone(request), current = structuredClone(cap), pin = structuredClone(selectedDesign), op = begin(); setPrepared(null); setSaved(null); setMessage("");
    try {
      const ref = { actorId: current.actor_user_id, requestKey: detached.request_key, requestSha: await expressionSha(expressionCanonical(detached)), design: pin, operation: detached.operation, feedback: detached.operation === "link_follow_up" ? detached.payload.feedback : null, child: detached.operation === "link_follow_up" ? detached.payload.child : null };
      if (!op.active()) return; const next = await knownFeedbackReceipt(await op.run(() => discoveryFeedbackPreview(detached, op.signal)), current, ref, "preview"); if (!op.active()) return; if (!next) throw new Error("Invalid evidence preview");
      if (next.replayed) setSaved(next); else setPrepared({ request: detached, receipt: next, recovery: { ...ref, previewSha: next.preview_sha256, receiptSha: next.receipt_sha256, receiptId: next.receipt_id } }); finish();
    } catch (error) { if (op.active()) fail(error); }
  }
  function returnEvidence(event: FormEvent) {
    event.preventDefault(); if (!context?.eligibility.eligible || !currentEntry || locked) return;
    if (!decision) { setMessage("Choose your actual researcher decision before previewing the return."); return; }
    void preview({ version: FEEDBACK_REQUEST_VERSION, request_key: `discovery-evidence:${crypto.randomUUID()}`, operation: "return_evidence", payload: { design: context.design, evidence: context.evidence, findings: findings.trim(), decision, reason: reason.trim(), unknowns: unknowns.split(/\r?\n/).map(s => s.trim()).filter(Boolean) } }, context.design);
  }
  function recorded(next: FeedbackReceipt) { const pins = commitIdentity.current; commitIdentity.current = null; if (pins) onSaveResolved?.(structuredClone(pins)); if (next.operation === "link_follow_up") onFollowUpLinked?.(); setPrepared(null); setRecovery(null); setSaved(next); setPage(null); finish(); setMessage(next.operation === "link_follow_up" ? "The saved child is durably linked to this exact evidence return. No execution or source value was created." : "Your source-record association and researcher decision were saved. Load return history to inspect currentness or start a linked proposal."); }
  async function save() {
    if (!cap || !prepared || locked || inFlight.current) return; const selected = structuredClone(prepared), current = structuredClone(cap), op = begin(); setPrepared(null); setMessage("");
    commitIdentity.current = selected.recovery; onSaveDispatched?.(structuredClone(selected.recovery));
    try { const next = await knownFeedbackReceipt(await op.run(() => discoveryFeedbackCommit(selected.request, selected.recovery.previewSha, op.signal)), current, selected.recovery, "commit"); if (!op.active()) return; if (!next) throw new Error("Invalid feedback save receipt"); recorded(next); }
    catch (error) { if (!op.active()) return; if (error instanceof ApiError && [400, 401, 403, 409, 413, 415, 422].includes(error.status)) { commitIdentity.current = null; onSaveResolved?.(structuredClone(selected.recovery)); setRecovery(null); fail(error); } else { setContext(null); setPage(null); setSaved(null); setRecovery(selected.recovery); finish(); setMessage("Save outcome is unverified. Check the original request with GET; no write will be retried."); } }
  }
  async function checkOutcome() {
    if (!cap || !recovery || disabled || inFlight.current) return; const pins = structuredClone(recovery), current = structuredClone(cap), op = begin();
    try { const next = await knownFeedbackReceipt(await op.run(() => discoveryFeedbackOutcome(pins.requestKey, pins.requestSha, op.signal)), current, pins, "outcome"); if (!op.active()) return; if (!next) throw new Error("Invalid original evidence outcome"); recorded(next); }
    catch (error) { if (!op.active()) return; if (error instanceof ApiError && [401, 403].includes(error.status)) fail(error); else { finish(); setMessage("The original outcome remains unverified. No rollback or failed save is inferred; no write was retried."); } }
  }
  function startLinked(e: FeedbackEntry) { if (locked || !currentEntry || !e.eligibility.eligible || !design || expressionCanonical(e.design) !== expressionCanonical(design)) return; onStartLinkedProposal({ feedback: { id: e.id, record_sha256: e.record_sha256 }, design: structuredClone(e.design) }); }
  async function loadSavedChild() {
    if (!cap || !followUpSelection || locked || inFlight.current) return;
    const id = existingChildId.trim(); if (!designId(id)) { setMessage("Enter the exact saved child design ID."); return; }
    const parent = structuredClone(followUpSelection.design), access = structuredClone(designAccess), op = begin(); setLoadedChild(null); setPrepared(null); setSaved(null); setMessage("");
    try { const detail = await knownDesignDetail(await op.run(() => discoveryDesignDetail(id, op.signal)), access, id); if (!op.active()) return; const child = detail ? feedbackChildFromDetail(detail, parent) : null;
      if (!child) { finish(); setMessage("This design is not a verified current eligible initial child of the selected exact parent. No link was prepared."); return; }
      setLoadedChild(child); finish(); setMessage("Existing initial child verified against the exact parent and current source scope. Preview its link before saving.");
    } catch (error) { if (op.active()) fail(error); }
  }
  function previewLink() { if (!followUpSelection || !childForLink || locked) return; void preview({ version: FEEDBACK_REQUEST_VERSION, request_key: `discovery-follow-up:${crypto.randomUUID()}`, operation: "link_follow_up", payload: { feedback: structuredClone(followUpSelection.feedback), child: structuredClone(childForLink) } }, followUpSelection.design); }
  return <section className="min-w-0 space-y-4" aria-label="Discovery evidence returns">
    <header className="space-y-2"><h3 className="text-lg font-semibold">Return evidence</h3><p className="text-sm leading-6 text-sage-muted">Compare the saved action with an existing retained source record, then record your decision and remaining unknowns.</p><p className="text-xs text-sage-muted">Existing archival evidence only. Cross-material references are allowed; physical relevance to the proposed sample, phase or state remains unestablished.</p></header>
    <div className="flex flex-wrap gap-2"><button type="button" className={button} disabled={disabled || busy} onClick={() => void refresh()}>Refresh evidence access</button>{cap && design && <button type="button" className={button} disabled={locked} onClick={() => void loadPage()}>Load return history</button>}</div>
    {busy && <p role="status" className="text-sm text-sage-muted">Verifying exact evidence scope…</p>}{message && <p role="status" className="break-words text-sm [overflow-wrap:anywhere]">{message}</p>}
    {cap && recovery && <section className={panel} aria-label="Original evidence save recovery"><h4 className="font-medium">Original save recovery</h4><p className="break-all text-xs text-sage-muted">Request key: {recovery.requestKey}</p><button type="button" className={button} disabled={disabled || busy} onClick={() => void checkOutcome()}>Check original evidence request</button></section>}
    {cap && !recovery && entry && design && <>
      <section className={panel} aria-label="Pinned research action"><h4 className="font-medium">Saved action: {readable(entry.design.next_action.kind)}</h4><p className="break-words text-sm [overflow-wrap:anywhere]">{entry.design.next_action.question}</p><p className="text-xs text-sage-muted">Anticipated outcomes in this immutable proposal:</p><ol className="space-y-2 text-sm">{entry.design.next_action.outcomes.map((o, i) => <li key={i} className="break-words [overflow-wrap:anywhere]">{i + 1}. {o.observation} <span className="text-sage-muted">→ {readable(o.decision)}</span></li>)}</ol><details className="text-xs"><summary className="cursor-pointer">Inspect exact design and action pins</summary><pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-sage-surface p-3">{expressionCanonical(design)}</pre></details></section>
      {!currentEntry ? <p className="text-sm text-sage-muted">Evidence returns require a current eligible retained-result design with a source-review action. Saved history remains readable below.</p> : <form onSubmit={returnEvidence} noValidate className={panel} aria-label="Return existing evidence"><fieldset disabled={locked} className="min-w-0 space-y-3"><legend className="mb-2 font-medium">Existing evidence selector</legend><div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">Evidence material ID<input className={input} maxLength={100} value={material} onChange={e => edit(() => setMaterial(e.target.value), true)} /></label><label className="text-sm">Evidence retained record index<input className={input} inputMode="numeric" value={index} onChange={e => edit(() => setIndex(e.target.value), true)} /></label></div><button type="button" className={button} onClick={() => void loadContext()}>Load exact evidence</button>{context && (context.projection ? <EvidenceReading projection={context.projection} canonicalText={context.projection_canonical_json!} /> : <p className="text-sm text-amber-800">Source readings withheld: {context.eligibility.reason_codes.map(readable).join(" · ")}</p>)}<label className="block text-sm">Findings from this source review<textarea className={input} rows={3} maxLength={4000} value={findings} onChange={e => edit(() => setFindings(e.target.value))} /></label><div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">Actual researcher decision<select className={input} value={decision} onChange={e => edit(() => setDecision(e.target.value as FeedbackDecision | ""))}><option value="">Choose a decision</option><option value="continue">Continue</option><option value="stop">Stop</option><option value="redirect">Redirect</option></select></label><label className="text-sm">Reason for this decision<textarea className={input} rows={2} maxLength={2000} value={reason} onChange={e => edit(() => setReason(e.target.value))} /></label></div><label className="block text-sm">Remaining unknowns (one per line)<textarea className={input} rows={3} maxLength={16016} value={unknowns} onChange={e => edit(() => setUnknowns(e.target.value))} /></label><button type="submit" className={primary} disabled={!context?.eligibility.eligible}>Preview evidence return</button></fieldset></form>}
    </>}
    {page && <section className={panel} aria-label="Saved evidence return history"><h4 className="font-medium">Evidence returns ({page.total.toLocaleString("en-US")})</h4>{page.entries.length === 0 ? <p className="text-sm text-sage-muted">No evidence returns in this window.</p> : <div className="max-h-[36rem] space-y-4 overflow-y-auto">{page.entries.map(e => <article key={e.id} className="min-w-0 space-y-2 border-t border-sage-border pt-3"><p className="text-sm font-medium">Researcher decision: {readable(e.decision)}</p><p className="break-words text-sm [overflow-wrap:anywhere]">{e.findings}</p><p className="break-words text-sm [overflow-wrap:anywhere]">Reason: {e.reason}</p>{e.unknowns.length > 0 && <details className="text-sm"><summary className="cursor-pointer">Remaining unknowns ({e.unknowns.length})</summary><ul className="mt-2 space-y-1">{e.unknowns.map((u, i) => <li key={i} className="break-words [overflow-wrap:anywhere]">{u}</li>)}</ul></details>}<p className={`text-xs ${e.eligibility.eligible ? "text-sage-muted" : "text-amber-800"}`}>{e.eligibility.eligible ? "Current design and source pins; physical association unestablished" : `Historical return; current readings withheld: ${e.eligibility.reason_codes.map(readable).join(" · ")}`}</p><p className="break-words text-xs text-sage-muted">Evidence material {e.evidence.material_id} · retained record index {e.evidence.record_index.toLocaleString("en-US")}</p><Link className="text-sm text-accent-deep underline" href={feedbackRecordHref(e.evidence.material_id, e.evidence.record_index)!}>Open exact retained record</Link>{e.projection && <details className="text-sm"><summary className="cursor-pointer">Inspect retained evidence readings</summary><div className="mt-2"><EvidenceReading projection={e.projection} canonicalText={e.projection_canonical_json!} /></div></details>}<details className="text-xs"><summary className="cursor-pointer">Inspect immutable return receipt</summary><pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-sage-surface p-3">{e.receipt.receipt_canonical_json}</pre></details><button type="button" className={button} disabled={locked || !currentEntry || !e.eligibility.eligible || !design || expressionCanonical(e.design) !== expressionCanonical(design)} onClick={() => startLinked(e)}>Start proposal from return</button>{e.follow_ups.map(link => <div key={link.id} className="space-y-1"><p className="break-all text-xs text-sage-muted">Linked child {link.child.design_id} · {link.eligibility.eligible ? "current eligible initial proposal" : link.eligibility.reason_codes.map(readable).join(" · ")}</p><button type="button" className={button} disabled={locked} onClick={() => onOpenChild(structuredClone(link.child))}>Open linked child</button></div>)}</article>)}</div>}<div className="flex flex-wrap gap-2"><button type="button" className={button} disabled={locked || page.offset === 0} onClick={() => void loadPage(Math.max(0, page.offset - 8))}>Previous returns</button><button type="button" className={button} disabled={locked || page.offset + page.entries.length >= page.total || page.offset + 8 > 1000} onClick={() => void loadPage(page.offset + 8)}>Next returns</button></div></section>}
    {followUpSelection && <section className={panel} aria-label="Evidence follow-up association"><h4 className="font-medium">Link the saved follow-up</h4><p className="break-all text-xs text-sage-muted">Evidence return {followUpSelection.feedback.id}</p><p className="text-sm text-sage-muted">Save a new initial linked proposal or load an existing initial child by ID. Both paths require an exact parent, a fresh preview and an explicit association save.</p><div className="space-y-3"><h5 className="text-sm font-medium">Link an existing saved initial child</h5><label className="block text-sm">Existing child design ID<input className={input} maxLength={36} value={existingChildId} disabled={locked} onChange={e => edit(() => { setExistingChildId(e.target.value); setLoadedChild(null); })} /></label><button type="button" className={button} disabled={locked || !cap || !existingChildId.trim()} onClick={() => void loadSavedChild()}>Load saved child</button></div>{childForLink ? <><p className="break-all text-xs text-sage-muted">Verified saved initial child: {childForLink.design_id}</p><details className="text-xs"><summary className="cursor-pointer">Inspect exact saved child pins</summary><pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-sage-surface p-3">{expressionCanonical(childForLink)}</pre></details><button type="button" className={button} disabled={locked || !cap} onClick={previewLink}>Preview follow-up link</button></> : <p className="text-xs text-sage-muted">Save a new initial child or load an existing one. A later revision or changed parent cannot be linked.</p>}</section>}
    {prepared && <section className={`${panel} border-accent-deep`} aria-label="Exact evidence preview"><h4 className="font-medium">Exact private preview</h4><p className="text-sm">{prepared.request.operation === "return_evidence" ? "Existing evidence association and researcher decision" : "Existing return to saved initial child association"}</p><details className="text-sm"><summary className="cursor-pointer">Inspect exact evidence operation</summary><pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-sage-surface p-3 text-xs">{prepared.receipt.request_canonical_json}</pre></details><button type="button" className={primary} disabled={locked} onClick={() => void save()}>Save evidence association</button></section>}
    {saved && <section className={panel} aria-label="Saved evidence receipt"><h4 className="font-medium">Recorded private association</h4><p className="break-all text-xs text-sage-muted">Evidence return: {saved.feedback_id}</p><details className="text-sm"><summary className="cursor-pointer">Inspect recorded association receipt</summary><pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-sage-surface p-3 text-xs">{saved.receipt_canonical_json}</pre></details></section>}
  </section>;
}
