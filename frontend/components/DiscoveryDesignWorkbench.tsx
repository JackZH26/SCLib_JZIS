"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import Link from "@/components/AppLink";
import { useDashboardUser } from "@/components/dashboard/user-context";
import { ApiError, discoveryDesignCapabilities, discoveryDesignCommit, discoveryDesignContext, discoveryDesignDetail, discoveryDesignOutcome, discoveryDesignPage, discoveryDesignPreview } from "@/lib/api";
import { onAuthChange } from "@/lib/auth-session";
import { expressionCanonical, expressionSha } from "@/lib/source-expressions";
import { DESIGN_MAX_BYTES, DESIGN_MODIFICATIONS, DESIGN_PAIRING, DESIGN_REQUEST_VERSION, emptyResearchDesign, knownDesignCapabilities, knownDesignContext, knownDesignDetail, knownDesignPage, knownDesignReceipt, knownDesignRequest,
  type DesignBaseline, type DesignCapabilities, type DesignContext, type DesignDetail, type DesignEntry, type DesignPage, type DesignParent, type DesignReceipt, type DesignRecovery, type DesignRequest, type ResearchDesign } from "@/lib/discovery-designs";

const input = "mt-1 block min-h-11 w-full min-w-0 rounded-lg border border-sage-border bg-white px-3 py-2 text-sm text-sage-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent";
const button = "min-h-11 rounded-lg border border-sage-border bg-white px-3 py-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50";
const primary = "min-h-11 rounded-lg bg-accent-deep px-4 py-2 text-sm font-medium text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50";
const section = "min-w-0 space-y-3 rounded-xl border border-sage-border bg-white p-4 sm:p-5";
function readable(text: string) { return text.replaceAll("_", " "); }
async function bounded<T>(call: () => Promise<T>, controller: AbortController) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try { return await Promise.race([call(), new Promise<never>((_, reject) => { timer = setTimeout(() => { controller.abort(); reject(new Error("Private request timed out")); }, 25000); })]); }
  finally { if (timer) clearTimeout(timer); }
}
function BaselineView({ context }: { context: Pick<DesignContext, "projection" | "eligibility"> }) {
  const p = context.projection;
  if (!p) return <p className="text-sm text-amber-800">Source reference withheld: {context.eligibility.reason_codes.map(readable).join(" · ")}</p>;
  if (p.kind === "unanchored") return <p className="text-sm text-sage-muted">Unanchored hypothesis. No source values or material associations are established.</p>;
  return <div role="region" className="space-y-2 break-words text-sm [overflow-wrap:anywhere]" aria-label="Baseline reference">
    <p><strong>Source reference:</strong> {p.formula ?? "Formula unavailable"} · {p.knowledge_origin ?? "Origin unresolved"}</p>
    <p className="text-xs text-sage-muted">Source pressure: {p.pressure_gpa === null ? "not supplied" : `${p.pressure_gpa} GPa`} · source temperature: {p.temperature_k === null ? "not supplied" : `${p.temperature_k} K`}</p>
    {p.values.map(v => <p key={v.field_id}>{readable(v.field_id)}: {v.value} {v.unit} · {readable(v.relation)}</p>)}
    <details className="text-xs"><summary className="cursor-pointer">Inspect baseline pins</summary><dl className="mt-2 space-y-2 break-all">{(["material_id", "property_id", "event_id", "state_id", "producer_run_id", "source_snapshot_sha256"] as const).map(k => <div key={k}><dt className="text-sage-muted">{readable(k)}</dt><dd>{p[k] ?? "Unestablished"}</dd></div>)}</dl></details>
    <p className="text-xs text-sage-muted">These results describe the original reference. A proposed modification does not inherit them.</p>
  </div>;
}

export function DiscoveryDesignWorkbench({ initialMaterialId = "", initialPropertyId = "" }: { initialMaterialId?: string; initialPropertyId?: string }) {
  const { user } = useDashboardUser();
  const [access, setAccess] = useState<DesignCapabilities | null>(null), [busy, setBusy] = useState(false), [message, setMessage] = useState("");
  const [kind, setKind] = useState<DesignBaseline["kind"]>(initialPropertyId ? "native_property" : initialMaterialId ? "retained_result" : "unanchored");
  const [material, setMaterial] = useState(initialMaterialId), [property, setProperty] = useState(initialPropertyId), [index, setIndex] = useState("0");
  const [context, setContext] = useState<DesignContext | null>(null), [form, setForm] = useState<ResearchDesign>(emptyResearchDesign), [parent, setParent] = useState<DesignParent>(null);
  const [page, setPage] = useState<DesignPage | null>(null), [detail, setDetail] = useState<DesignDetail | null>(null), [editing, setEditing] = useState<DesignEntry | null>(null);
  const [prepared, setPrepared] = useState<{ request: DesignRequest; receipt: DesignReceipt; recovery: DesignRecovery } | null>(null), [saved, setSaved] = useState<DesignReceipt | null>(null), [recovery, setRecovery] = useState<DesignRecovery | null>(null);
  const [withdrawReason, setWithdrawReason] = useState("");
  const mounted = useRef(false), sequence = useRef(0), controller = useRef<AbortController | null>(null), retained = useRef<DesignRecovery | null>(null), previousActor = useRef<string | null>(null);
  const cap = access?.actor_user_id === user.id ? access : null, locked = busy || recovery !== null;
  function clearProposal() { setContext(null); setForm(emptyResearchDesign()); setParent(null); setEditing(null); setPrepared(null); setSaved(null); setWithdrawReason(""); }
  function clearPrivate() { ++sequence.current; controller.current?.abort(); setAccess(null); setPage(null); setDetail(null); clearProposal(); setRecovery(null); setBusy(false); }
  function begin() { const id = ++sequence.current; controller.current?.abort(); const c = new AbortController(); controller.current = c; return { signal: c.signal, active: () => mounted.current && sequence.current === id, run: <T,>(call: () => Promise<T>) => bounded(call, c) }; }
  function fail(error: unknown) {
    setBusy(false); setPrepared(null); setContext(null); setPage(null); setDetail(null); setSaved(null);
    if (error instanceof ApiError && [401, 403].includes(error.status)) { clearPrivate(); retained.current = null; setMessage("Research access or session changed. Private information has been cleared."); }
    else if (error instanceof ApiError && error.status === 404) setMessage("This research-design interface or exact record is unavailable. No scientific absence was inferred.");
    else if (error instanceof ApiError && error.status === 409) setMessage("The source, design head or access changed. Reload before preparing another preview.");
    else setMessage("This response could not be verified. Reload access and the exact reference before continuing.");
  }
  async function refresh() {
    if (busy) return; const op = begin(); setAccess(null); setContext(null); setPage(null); setDetail(null); setPrepared(null); setSaved(null); setBusy(true); setMessage("");
    try { const next = knownDesignCapabilities(await op.run(() => discoveryDesignCapabilities(op.signal)), user.id); if (!op.active()) return; if (!next) throw new Error("Invalid capability"); setAccess(next); setBusy(false); if (retained.current?.actorId === user.id) { setRecovery(retained.current); setMessage("The original save needs an outcome check. No write will be retried."); } }
    catch (error) { if (op.active()) fail(error); }
  }
  useEffect(() => {
    if (previousActor.current !== null && previousActor.current !== user.id) { setKind("unanchored"); setMaterial(""); setProperty(""); setIndex("0"); }
    previousActor.current = user.id;
    mounted.current = true; retained.current = null; clearPrivate(); void refresh();
    const unsubscribe = onAuthChange(() => { retained.current = null; clearPrivate(); setKind("unanchored"); setMaterial(""); setProperty(""); setIndex("0"); setMessage("Session changed. Private information has been cleared; refresh access."); });
    const hide = () => { clearPrivate(); setKind("unanchored"); setMaterial(""); setProperty(""); setIndex("0"); setMessage("Private source values and drafts cleared after leaving this page. Refresh access to continue."); };
    const visibility = () => { if (document.visibilityState === "hidden") hide(); };
    document.addEventListener("visibilitychange", visibility); window.addEventListener("pagehide", hide);
    return () => { unsubscribe(); mounted.current = false; ++sequence.current; controller.current?.abort(); document.removeEventListener("visibilitychange", visibility); window.removeEventListener("pagehide", hide); };
    // The authenticated user owns every source view and draft.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user.id]);
  function edit(next: ResearchDesign) { setForm(next); setPrepared(null); setSaved(null); setMessage(""); }
  function selectorEdit(update: () => void) { update(); setContext(null); setPrepared(null); setSaved(null); }
  async function loadContext() {
    if (!cap || locked) return; const current = cap, op = begin(); setContext(null); setPrepared(null); setBusy(true); setMessage("");
    const expected = { kind, material_id: kind === "unanchored" ? null : material, record_index: kind === "retained_result" && /^\d{1,4}$/.test(index) ? Number(index) : null, property_id: kind === "native_property" ? property : null };
    try { const next = await knownDesignContext(await op.run(() => discoveryDesignContext(kind, expected.material_id ?? "", expected.record_index, expected.property_id, op.signal)), current, expected); if (!op.active()) return; if (!next) throw new Error("Invalid context"); setContext(next); setBusy(false); }
    catch (error) { if (op.active()) fail(error); }
  }
  async function loadPage(offset = 0) {
    if (!cap || locked) return; const current = cap, op = begin(); setPage(null); setDetail(null); setBusy(true); setMessage("");
    try { const next = await knownDesignPage(await op.run(() => discoveryDesignPage(offset, op.signal)), current, offset); if (!op.active()) return; if (!next) throw new Error("Invalid page"); setPage(next); setBusy(false); }
    catch (error) { if (op.active()) fail(error); }
  }
  async function inspect(entry: DesignEntry) {
    if (!cap || locked) return; const current = cap, op = begin(); setDetail(null); setPrepared(null); setBusy(true); setMessage("");
    try { const next = await knownDesignDetail(await op.run(() => discoveryDesignDetail(entry.design_id, op.signal)), current, entry.design_id); if (!op.active()) return; if (!next) throw new Error("Invalid history"); setDetail(next); setBusy(false); }
    catch (error) { if (op.active()) fail(error); }
  }
  function useDesign(entry: DesignEntry, fork = false) {
    if (locked || entry.status === "withdrawn") return;
    setKind(entry.baseline.kind); setMaterial(entry.baseline.material_id ?? ""); setProperty(entry.baseline.property_id ?? ""); setIndex(String(entry.baseline.record_index ?? 0));
    setForm(structuredClone(entry.design)); setParent(fork ? { design_id: entry.design_id, revision_id: entry.id, record_sha256: entry.record_sha256 } : entry.parent); setEditing(fork ? null : entry); setContext(null); setPrepared(null); setSaved(null);
    setMessage("Proposal copied. Reload its exact baseline before previewing; source values are not inherited.");
  }
  async function previewRequest(request: DesignRequest) {
    if (!cap || locked) return;
    if (!knownDesignRequest(request)) { setMessage("Complete the host, modification, hypothesis, prerequisites and at least two distinct outcomes with different decisions."); return; }
    const canonical = expressionCanonical(request);
    if (new TextEncoder().encode(canonical).length > DESIGN_MAX_BYTES) { setMessage("This design exceeds the supported request size. Shorten the proposal before previewing."); return; }
    const snapshot = JSON.parse(canonical) as DesignRequest, current = cap, op = begin(); setPrepared(null); setSaved(null); setBusy(true); setMessage("");
    try {
      const ref = { actorId: current.actor_user_id, requestKey: snapshot.request_key, requestSha: await expressionSha(canonical), previewSha: "", receiptSha: "", receiptId: "" };
      if (!op.active()) return;
      const next = await knownDesignReceipt(await op.run(() => discoveryDesignPreview(snapshot, op.signal)), current, ref, "preview");
      if (!op.active()) return; if (!next) throw new Error("Invalid preview");
      if (next.replayed) setSaved(next); else setPrepared({ request: snapshot, receipt: next, recovery: { ...ref, previewSha: next.preview_sha256, receiptSha: next.receipt_sha256, receiptId: next.receipt_id } }); setBusy(false);
    } catch (error) { if (op.active()) fail(error); }
  }
  function propose(event: FormEvent) {
    event.preventDefault(); if (!context?.eligibility.eligible || locked) return;
    const common = { baseline: context.baseline, design: form, parent };
    void previewRequest(editing ? { version: DESIGN_REQUEST_VERSION, request_key: `discovery-design:${crypto.randomUUID()}`, operation: "revise", payload: { ...common, design_id: editing.design_id, predecessor: { id: editing.id, record_sha256: editing.record_sha256 } } }
      : { version: DESIGN_REQUEST_VERSION, request_key: `discovery-design:${crypto.randomUUID()}`, operation: "propose", payload: common });
  }
  async function save() {
    if (!cap || !prepared || locked) return; const current = cap, selected = prepared, op = begin(); retained.current = selected.recovery; setBusy(true); setMessage("");
    try { const next = await knownDesignReceipt(await op.run(() => discoveryDesignCommit(selected.request, selected.recovery.previewSha, op.signal)), current, selected.recovery, "commit"); if (!op.active()) return; if (!next) throw new Error("Invalid save"); retained.current = null; setRecovery(null); clearProposal(); setDetail(null); setPage(null); setSaved(next); setBusy(false); setMessage("Saved to your private research-design history. Load saved designs to inspect its current source scope."); }
    catch (error) {
      if (!op.active()) return;
      if (error instanceof ApiError && [400, 401, 403, 409, 413, 415, 422].includes(error.status)) { retained.current = null; setRecovery(null); fail(error); }
      else { clearProposal(); setPage(null); setDetail(null); setRecovery(selected.recovery); setBusy(false); setMessage("Save outcome is unknown. Check the original request with GET; no write will be retried."); }
    }
  }
  async function checkOutcome() {
    if (!cap || !recovery || busy) return; const current = cap, ref = recovery, op = begin(); setBusy(true);
    try { const next = await knownDesignReceipt(await op.run(() => discoveryDesignOutcome(ref.requestKey, ref.requestSha, op.signal)), current, ref, "outcome"); if (!op.active()) return; if (!next) throw new Error("Invalid outcome"); retained.current = null; setRecovery(null); setSaved(next); setBusy(false); setMessage("The original save is recorded. No new write was sent."); }
    catch (error) { if (!op.active()) return; if (error instanceof ApiError && [401, 403].includes(error.status)) fail(error); else { setBusy(false); setMessage("The original outcome remains unverified. No failed save or rollback is inferred; no write was retried."); } }
  }
  const head = detail?.entries[0];
  return <div className="min-w-0 space-y-5">
    <header className="space-y-2"><p className="text-xs font-medium uppercase tracking-wide text-accent-deep">Private research workspace</p><h2 className="text-2xl font-semibold">Discovery research designs</h2><p className="max-w-3xl text-sm leading-6 text-sage-muted">Keep a host, explicit modifications and requested conditions together. Record the next action and how its observable outcomes change your decision.</p><p className="text-xs text-sage-muted">Saved designs are proposals. Source results, stable-host status and calculation or experiment outcomes require separate evidence.</p></header>
    <div className="flex flex-wrap items-center gap-3"><button className={button} disabled={busy} onClick={() => void refresh()}>Refresh access</button>{cap && <button className={button} disabled={locked} onClick={() => void loadPage()}>Load saved designs</button>}{busy && <p role="status" className="text-sm text-sage-muted">Loading exact research scope…</p>}<Link className="text-sm text-accent-deep underline" href="/discovery">Public Discovery</Link></div>
    {message && <p role="status" className="rounded-lg border border-sage-border bg-sage-surface p-3 text-sm">{message}</p>}
    {cap && recovery && <section className={section} aria-label="Original design save recovery"><h3 className="font-semibold">Original save recovery</h3><p className="text-sm text-sage-muted">Keep this page open until the outcome is known.</p><button className={button} disabled={busy} onClick={() => void checkOutcome()}>Check original request</button><p className="break-all text-xs text-sage-muted">Request key: {recovery.requestKey}</p></section>}
    {cap && !recovery && <>
      {page && <section className={section} aria-label="Saved research designs"><h3 className="font-semibold">Saved designs <span className="font-normal text-sage-muted">({page.entries.length} of {page.total})</span></h3>{!page.entries.length && <p className="text-sm text-sage-muted">No saved designs in this window. Outline a hypothesis below.</p>}<ul className="divide-y divide-sage-border">{page.entries.map(e => <li key={e.id} className="flex flex-wrap items-start justify-between gap-3 py-3"><div className="min-w-0"><p className="break-words font-medium">{e.design.host_label} → {e.design.state_label}</p><p className="text-xs text-sage-muted">Revision {e.revision} · {e.status} · {readable(e.design.next_action.kind)}</p>{!e.eligibility.eligible && <p className="text-xs text-amber-800">{e.eligibility.reason_codes.map(readable).join(" · ")}</p>}</div><button className={button} disabled={locked} onClick={() => void inspect(e)}>Inspect history</button></li>)}</ul><div className="flex flex-wrap gap-2"><button className={button} disabled={locked || page.offset === 0} onClick={() => void loadPage(Math.max(0, page.offset - 8))}>Previous window</button><button className={button} disabled={locked || page.offset + page.entries.length >= page.total} onClick={() => void loadPage(page.offset + 8)}>Next window</button></div></section>}
      {detail && head && <section className={section} aria-label="Research design history"><h3 className="font-semibold">Design history</h3><p className="text-xs text-sage-muted">Latest {detail.entries.length} of {detail.revision_total} immutable revisions. Links describe proposed modifications of a research design.</p><BaselineView context={head} /><div className="flex flex-wrap gap-2"><button className={button} disabled={locked || head.status === "withdrawn"} onClick={() => useDesign(head)}>Revise current proposal</button><button className={button} disabled={locked || head.status === "withdrawn"} onClick={() => useDesign(head, true)}>Start linked proposal</button></div><ol className="divide-y divide-sage-border">{detail.entries.map(e => <li key={e.id} className="space-y-2 py-3"><p className="text-sm font-medium">Revision {e.revision} · {e.operation} · {e.is_head ? "current head" : "historical"}</p><p className="break-words text-sm">{e.design.hypothesis}</p><details className="text-xs"><summary className="cursor-pointer">Inspect exact proposal and pins</summary><pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-sage-surface p-3">{e.receipt.receipt_canonical_json}</pre></details></li>)}</ol>{head.status !== "withdrawn" && <div className="space-y-3 border-t border-sage-border pt-3"><label className="block text-sm">Withdrawal reason<textarea className={input} maxLength={2000} value={withdrawReason} disabled={locked} onChange={e => { setWithdrawReason(e.target.value); setPrepared(null); }} /></label><button className={button} disabled={locked || !withdrawReason.trim()} onClick={() => void previewRequest({ version: DESIGN_REQUEST_VERSION, request_key: `discovery-design:${crypto.randomUUID()}`, operation: "withdraw", payload: { design_id: head.design_id, predecessor: { id: head.id, record_sha256: head.record_sha256 }, reason: withdrawReason.trim() } })}>Preview withdrawal</button></div>}</section>}
      <section className={section} aria-label="Design baseline selection"><div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold">1. Source baseline</h3><button className={button} disabled={locked} onClick={() => { clearProposal(); setKind("unanchored"); setMaterial(""); setProperty(""); setIndex("0"); }}>New independent proposal</button></div><div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">Baseline type<select className={input} value={kind} disabled={locked} onChange={e => selectorEdit(() => setKind(e.target.value as DesignBaseline["kind"]))}><option value="unanchored">Unanchored hypothesis</option><option value="retained_result">Retained catalogue result</option><option value="native_property">Native scientific property</option></select></label>{kind !== "unanchored" && <label className="text-sm">Exact material ID<input className={input} maxLength={100} value={material} disabled={locked} onChange={e => selectorEdit(() => setMaterial(e.target.value))} /></label>}{kind === "retained_result" && <label className="text-sm">Retained record index<input className={input} inputMode="numeric" value={index} disabled={locked} onChange={e => selectorEdit(() => setIndex(e.target.value))} /></label>}{kind === "native_property" && <label className="text-sm">Exact property ID<input className={input} maxLength={36} value={property} disabled={locked} onChange={e => selectorEdit(() => setProperty(e.target.value))} /></label>}</div><button className={button} disabled={locked} onClick={() => void loadContext()}>Load exact baseline</button>{context && <BaselineView context={context} />}</section>
      <form onSubmit={propose} noValidate aria-label="Persistent research design" className={section}>
        <h3 className="font-semibold">2. {editing ? "Revise the current proposal" : parent ? "Outline a linked proposal" : "Outline a research proposal"}</h3>{parent && <p className="break-all text-xs text-sage-muted">Proposed modification of design {parent.design_id} · exact revision {parent.revision_id}. This link does not establish material genealogy.</p>}
        <fieldset disabled={locked} className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">Host label<input className={input} required maxLength={500} value={form.host_label} onChange={e => edit({ ...form, host_label: e.target.value })} /></label><label className="text-sm">Proposed state label<input className={input} required maxLength={500} value={form.state_label} onChange={e => edit({ ...form, state_label: e.target.value })} /></label></div>
          <fieldset className="space-y-3"><legend className="text-sm font-medium">Explicit modifications</legend>{form.modifications.map((m, i) => <div key={i} className="grid gap-3 border-t border-sage-border pt-3 sm:grid-cols-2"><label className="text-sm">Modification {i + 1}<select className={input} value={m.kind} onChange={e => edit({ ...form, modifications: form.modifications.map((item, j) => j === i ? { ...item, kind: e.target.value as typeof m.kind } : item) })}>{DESIGN_MODIFICATIONS.map(k => <option key={k} value={k}>{readable(k)}</option>)}</select></label><label className="text-sm">Parameters {i + 1}<textarea className={input} rows={2} maxLength={2000} value={m.parameters} placeholder="Species, site, amount, units and reference" onChange={e => edit({ ...form, modifications: form.modifications.map((item, j) => j === i ? { ...item, parameters: e.target.value } : item) })} /></label><button type="button" className={`${button} w-fit`} disabled={form.modifications.length === 1} onClick={() => edit({ ...form, modifications: form.modifications.filter((_, j) => j !== i) })}>Remove modification {i + 1}</button></div>)}<button type="button" className={button} disabled={form.modifications.length >= 8} onClick={() => edit({ ...form, modifications: [...form.modifications, { kind: "doping", parameters: "" }] })}>Add modification</button></fieldset>
          <div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">Requested pressure<select className={input} value={form.target_conditions.pressure.kind} onChange={e => edit({ ...form, target_conditions: { ...form.target_conditions, pressure: { kind: e.target.value as "ambient" | "specified" | "unspecified", raw_gpa: null } } })}><option value="unspecified">Unspecified target</option><option value="ambient">Ambient target, approximately 1 atm</option><option value="specified">Specified target in GPa</option></select></label>{form.target_conditions.pressure.kind === "specified" && <label className="text-sm">Requested pressure (GPa)<input className={input} inputMode="decimal" value={form.target_conditions.pressure.raw_gpa ?? ""} onChange={e => edit({ ...form, target_conditions: { ...form.target_conditions, pressure: { kind: "specified", raw_gpa: e.target.value } } })} /></label>}<label className="text-sm">Requested temperature (K, optional)<input className={input} inputMode="decimal" value={form.target_conditions.temperature_k ?? ""} onChange={e => edit({ ...form, target_conditions: { ...form.target_conditions, temperature_k: e.target.value || null } })} /></label><label className="text-sm">Pairing hypothesis<select className={input} value={form.pairing_hypothesis} onChange={e => edit({ ...form, pairing_hypothesis: e.target.value as ResearchDesign["pairing_hypothesis"] })}>{DESIGN_PAIRING.map(k => <option key={k} value={k}>{readable(k)}</option>)}</select></label></div>
          <label className="block text-sm">Research hypothesis<textarea className={input} rows={3} maxLength={4000} value={form.hypothesis} onChange={e => edit({ ...form, hypothesis: e.target.value })} /></label>
          <div className="space-y-3 border-t border-sage-border pt-4"><h4 className="font-medium">3. Decision-changing next action</h4><label className="block text-sm">Action type<select className={input} value={form.next_action.kind} onChange={e => edit({ ...form, next_action: { ...form.next_action, kind: e.target.value as ResearchDesign["next_action"]["kind"] } })}><option value="source_review">Source review</option><option value="calculation">Calculation proposal</option><option value="experiment">Experiment proposal</option></select></label><label className="block text-sm">Question this action tests<textarea className={input} rows={2} maxLength={2000} value={form.next_action.question} onChange={e => edit({ ...form, next_action: { ...form.next_action, question: e.target.value } })} /></label><label className="block text-sm">Prerequisites (one per line)<textarea className={input} rows={3} value={form.next_action.prerequisites.join("\n")} maxLength={16016} onChange={e => edit({ ...form, next_action: { ...form.next_action, prerequisites: e.target.value.split(/\r?\n/) } })} /></label>{form.next_action.outcomes.map((o, i) => <div key={i} className="grid gap-3 border-t border-sage-border pt-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]"><label className="text-sm">Observable outcome {i + 1}<textarea className={input} rows={2} maxLength={1000} value={o.observation} onChange={e => edit({ ...form, next_action: { ...form.next_action, outcomes: form.next_action.outcomes.map((item, j) => j === i ? { ...item, observation: e.target.value } : item) } })} /></label><label className="text-sm">Decision for outcome {i + 1}<select className={input} value={o.decision} onChange={e => edit({ ...form, next_action: { ...form.next_action, outcomes: form.next_action.outcomes.map((item, j) => j === i ? { ...item, decision: e.target.value as typeof o.decision } : item) } })}><option value="continue">Continue</option><option value="stop">Stop</option><option value="redirect">Redirect</option></select></label></div>)}<p className="text-xs text-sage-muted">Outcomes must be distinguishable and lead to at least two different decisions. They are anticipated observations, not completed results.</p></div>
          <details className="border-t border-sage-border pt-3"><summary className="cursor-pointer text-sm font-medium">Estimated resource bounds</summary><p className="mt-2 text-xs text-sage-muted">Unknown budgets remain unknown. No calculation is submitted.</p><div className="mt-3 grid gap-3 sm:grid-cols-2">{form.next_action.budget.map((b, i) => <label key={b.resource} className="text-sm">{readable(b.resource)} ({b.unit})<input className={input} inputMode="decimal" placeholder="Unknown" maxLength={80} value={b.raw_upper ?? ""} onChange={e => edit({ ...form, next_action: { ...form.next_action, budget: form.next_action.budget.map((item, j) => j === i ? { ...item, status: e.target.value ? "estimated" : "unknown", raw_upper: e.target.value || null } : item) } })} /></label>)}</div></details>
          <button type="submit" className={primary} disabled={!context?.eligibility.eligible}>Preview private proposal</button><p className="text-xs text-sage-muted">{!context?.eligibility.eligible && "Load a current baseline first. "}Preview checks the exact proposal without retaining a write.</p>
        </fieldset>
      </form>
      {prepared && <section className={`${section} border-accent-deep`} aria-label="Exact design preview"><h3 className="font-semibold">Exact private preview</h3><p className="text-sm">{prepared.request.operation} · revision {prepared.receipt.revision}</p><p className="text-xs text-sage-muted">Save appends this exact proposal to your private history.</p><details><summary className="cursor-pointer text-sm">Inspect exact operation</summary><pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-sage-surface p-3 text-xs">{prepared.receipt.request_canonical_json}</pre></details><button className={primary} disabled={locked} onClick={() => void save()}>Save private proposal</button></section>}
    </>}
    {saved && <section className={section} aria-label="Saved design receipt"><h3 className="font-semibold">Recorded private proposal</h3><p className="text-sm">Revision {saved.revision} · {saved.status}</p><p className="break-all text-xs text-sage-muted">Design ID: {saved.design_id}</p><details><summary className="cursor-pointer text-sm">Inspect immutable receipt</summary><pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-sage-surface p-3 text-xs">{saved.receipt_canonical_json}</pre></details></section>}
  </div>;
}
