"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, discoveryConditionBatchCapabilities, discoveryConditionBatchCommit, discoveryConditionBatchDetail, discoveryConditionBatchManifest, discoveryConditionBatchOutcome, discoveryConditionBatchPage, discoveryConditionBatchPreview } from "@/lib/api";
import { onAuthChange } from "@/lib/auth-session";
import { CONDITION_BATCH_REQUEST_VERSION, knownConditionBatchCapabilities, knownConditionBatchDetail, knownConditionBatchManifest, knownConditionBatchOutcome, knownConditionBatchPage, knownConditionBatchReceipt, knownConditionBatchRequest, knownConditionBatchSaveRecovery, type ConditionBatchCapabilities, type ConditionBatchChild, type ConditionBatchDetail, type ConditionBatchExpected, type ConditionBatchPage, type ConditionBatchReceipt, type ConditionBatchRecovery, type ConditionBatchSaveRecovery, type ConditionBatchScenario } from "@/lib/discovery-condition-batches";
import type { ConditionSweepManifest } from "@/lib/discovery-condition-sweep";
import type { DesignCapabilities, ResearchDesign } from "@/lib/discovery-designs";
import { expressionCanonical, expressionSha, parseExpressionJson } from "@/lib/source-expressions";

const button = "min-h-11 rounded-lg border border-sage-border bg-white px-3 py-2 text-sm text-sage-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50";
const primary = "min-h-11 rounded-lg bg-accent-deep px-4 py-2 text-sm font-medium text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50";
const panel = "min-w-0 space-y-3 rounded-lg border border-sage-border p-3 sm:p-4";
type Props = { capabilities: DesignCapabilities; generated: ConditionSweepManifest | null; disabled?: boolean; invalidationKey?: number; saveRecovery?: ConditionBatchSaveRecovery | null; onSaveDispatched?: (recovery: ConditionBatchSaveRecovery) => void; onSaveResolved?: (recovery: ConditionBatchSaveRecovery) => void; onOpenChild: (child: ConditionBatchChild) => void; onScopeInvalid?: (error: ApiError) => void };
type Prepared = { expected: ConditionBatchExpected & { recovery: ConditionBatchRecovery }; receipt: ConditionBatchReceipt };
function label(conditions: ResearchDesign["target_conditions"]) {
  const p = conditions.pressure;
  return `${p.kind === "ambient" ? "Ambient target" : p.kind === "specified" ? `${p.raw_gpa} GPa target` : "Pressure unspecified"} · ${conditions.temperature_k === null ? "Temperature unspecified" : `${conditions.temperature_k} K target`}`;
}
function child(receipt: ConditionBatchReceipt): ConditionBatchChild | null { return receipt.child ? { design_id: receipt.child.design_id, revision_id: receipt.child.receipt_id, record_sha256: receipt.child.receipt_sha256 } : null; }
async function bounded<T>(call: () => Promise<T>, controller: AbortController) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try { return await Promise.race([call(), new Promise<never>((_, reject) => { timer = setTimeout(() => { controller.abort(); reject(new Error("Private batch request timed out")); }, 25000); })]); }
  finally { if (timer) clearTimeout(timer); }
}
/** Actor scope remounts; an already-sent save is recoverable through parent-held hashes. */
export function DiscoveryConditionBatchWorkspace(props: Props) {
  const identity = JSON.stringify({ actor: props.capabilities.actor_user_id, session: props.capabilities.session_version, grant: props.capabilities.curator_grant_id });
  return <Workspace key={identity} {...props} />;
}
function Workspace({ capabilities: design, generated, disabled = false, invalidationKey = 0, saveRecovery = null, onSaveDispatched, onSaveResolved, onOpenChild, onScopeInvalid }: Props) {
  const initialRecovery = knownConditionBatchSaveRecovery(saveRecovery) && saveRecovery.actorId === design.actor_user_id ? structuredClone(saveRecovery) : null;
  const [cap, setCap] = useState<ConditionBatchCapabilities | null>(null), [busy, setBusy] = useState(false), [message, setMessage] = useState("");
  const [page, setPage] = useState<ConditionBatchPage | null>(null), [detail, setDetail] = useState<ConditionBatchDetail | null>(null);
  const [artifact, setArtifact] = useState<{ text: string; fileSha: string; manifest: ConditionSweepManifest } | null>(null);
  const [prepared, setPrepared] = useState<Prepared | null>(null), [saved, setSaved] = useState<ConditionBatchReceipt | null>(null), [recovery, setRecovery] = useState<ConditionBatchSaveRecovery | null>(initialRecovery);
  const mounted = useRef(false), sequence = useRef(0), controller = useRef<AbortController | null>(null), inFlight = useRef(false);
  const commitIdentity = useRef<ConditionBatchSaveRecovery | null>(initialRecovery), previousDraft = useRef(invalidationKey), previousGeneration = useRef(generated?.manifest_sha256 ?? null);
  const locked = disabled || busy || recovery !== null;
  function clear() { ++sequence.current; controller.current?.abort(); inFlight.current = false; setCap(null); setPage(null); setDetail(null); setArtifact(null); setPrepared(null); setSaved(null); setRecovery(commitIdentity.current); setBusy(false); }
  function begin() { const id = ++sequence.current; controller.current?.abort(); const c = new AbortController(); controller.current = c; inFlight.current = true; setBusy(true); return { signal: c.signal, active: () => mounted.current && id === sequence.current, run: <T,>(call: () => Promise<T>) => bounded(call, c) }; }
  function finish() { inFlight.current = false; setBusy(false); }
  function fail(error: unknown) {
    finish(); setPrepared(null); setPage(null); setDetail(null); setArtifact(null); setSaved(null);
    if (error instanceof ApiError && [401, 403].includes(error.status)) { clear(); setMessage("Batch access or session changed. Private batch information has been cleared."); }
    else if (error instanceof ApiError && error.status === 409) setMessage("The parent, source or access changed. Reload the batch before preparing another preview.");
    else if (error instanceof ApiError && error.status === 404) setMessage("Durable condition batches are unavailable. The local condition planner remains available.");
    else setMessage("The batch response could not be verified. Reload access and the exact batch before continuing.");
    if (error instanceof ApiError && [401, 403, 409].includes(error.status)) onScopeInvalid?.(error);
  }
  async function refresh() {
    if (disabled || inFlight.current) return;
    const current = structuredClone(design), op = begin(); setCap(null); setPrepared(null); setPage(null); setDetail(null); setArtifact(null); setSaved(null); setMessage("");
    try { const next = knownConditionBatchCapabilities(await op.run(() => discoveryConditionBatchCapabilities(op.signal)), current); if (!op.active()) return; if (!next) throw new Error("Invalid batch capabilities"); setCap(next); finish(); }
    catch (error) { if (op.active()) fail(error); }
  }
  useEffect(() => {
    mounted.current = true; void refresh();
    const hide = () => { clear(); setMessage("Private batches and prepared operations cleared after leaving this page. Refresh batch access to continue."); };
    const visibility = () => { if (document.visibilityState === "hidden") hide(); };
    const unsubscribe = onAuthChange(() => { commitIdentity.current = null; clear(); setMessage("Session changed. Refresh batch access to continue."); });
    window.addEventListener("pagehide", hide); document.addEventListener("visibilitychange", visibility);
    return () => { mounted.current = false; ++sequence.current; controller.current?.abort(); unsubscribe(); window.removeEventListener("pagehide", hide); document.removeEventListener("visibilitychange", visibility); };
    // The keyed parent owns the current actor and exact generation snapshot.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (previousDraft.current === invalidationKey && previousGeneration.current === (generated?.manifest_sha256 ?? null)) return;
    previousDraft.current = invalidationKey; previousGeneration.current = generated?.manifest_sha256 ?? null;
    if (commitIdentity.current) return;
    ++sequence.current; controller.current?.abort(); finish(); setPrepared(null); setSaved(null); setRecovery(null); setMessage("Draft changed. Prepare a fresh batch operation preview before saving.");
    // Draft edits invalidate prepared operations without repeating access reads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invalidationKey, generated?.manifest_sha256]);
  async function loadPage(offset = 0) {
    if (!cap || locked || inFlight.current) return; const current = structuredClone(cap), native = structuredClone(design), op = begin(); setPrepared(null); setPage(null); setDetail(null); setArtifact(null); setMessage("");
    try { const next = await knownConditionBatchPage(await op.run(() => discoveryConditionBatchPage(offset, op.signal)), current, native, offset); if (!op.active()) return; if (!next) throw new Error("Invalid batch page"); setPage(next); finish(); }
    catch (error) { if (op.active()) fail(error); }
  }
  async function inspect(batchId: string, offset = 0) {
    if (!cap || locked || inFlight.current) return; const current = structuredClone(cap), native = structuredClone(design), op = begin(); setPrepared(null); setDetail(null); setArtifact(null); setMessage("");
    try {
      const raw = await op.run(() => discoveryConditionBatchDetail(batchId, offset, op.signal));
      const first = await knownConditionBatchDetail(raw, current, native, batchId, offset); if (!op.active()) return; if (!first) throw new Error("Invalid batch detail");
      const text = await op.run(() => discoveryConditionBatchManifest(batchId, op.signal)), manifest = await knownConditionBatchManifest(text, first.entry); if (!op.active()) return; if (!manifest) throw new Error("Invalid original manifest");
      const next = await knownConditionBatchDetail(raw, current, native, batchId, offset, manifest); if (!op.active()) return; if (!next) throw new Error("Scenario differs from original manifest");
      const fileSha = await expressionSha(text); if (!op.active()) return;
      setDetail(next); setArtifact({ text, fileSha, manifest }); finish();
    } catch (error) { if (op.active()) fail(error); }
  }
  async function preview(expected: ConditionBatchExpected) {
    if (!cap || locked || inFlight.current || !knownConditionBatchRequest(expected.request)) return;
    const detached = structuredClone(expected), current = structuredClone(cap), native = structuredClone(design), op = begin(); setPrepared(null); setSaved(null); setMessage("");
    try {
      const ref: ConditionBatchRecovery = { actorId: current.actor_user_id, requestKey: detached.request.request_key, requestSha: await expressionSha(expressionCanonical(detached.request)), previewSha: "", receiptSha: "", receiptId: "" };
      if (!op.active()) return;
      const next = await knownConditionBatchReceipt(await op.run(() => discoveryConditionBatchPreview(detached.request, op.signal)), current, native, { ...detached, recovery: ref }, "preview");
      if (!op.active()) return; if (!next) throw new Error("Invalid batch preview");
      if (next.replayed) setSaved(next); else setPrepared({ expected: { ...detached, recovery: { ...ref, previewSha: next.preview_sha256, receiptSha: next.receipt_sha256, receiptId: next.receipt_id } }, receipt: next }); finish();
    } catch (error) { if (op.active()) fail(error); }
  }
  function previewRetention() {
    if (!generated || locked) return;
    try { const manifest = structuredClone(generated), input = parseExpressionJson(manifest.input_canonical_json) as { axes: import("@/lib/discovery-condition-sweep").ConditionSweepAxes };
      void preview({ manifest, request: { version: CONDITION_BATCH_REQUEST_VERSION, request_key: `condition-batch:${crypto.randomUUID()}`, operation: "retain_batch", payload: { parent: manifest.parent, axes: input.axes, expected_input_sha256: manifest.input_sha256, expected_manifest_sha256: manifest.manifest_sha256 } } });
    } catch { setMessage("The generated manifest could not be read. Generate the sweep again before previewing retention."); }
  }
  function previewChild(scenario: ConditionBatchScenario) {
    if (!detail || !artifact || !detail.entry.eligibility.eligible || scenario.child || locked) return;
    void preview({ batch: detail.entry, scenario, manifest: artifact.manifest, request: { version: CONDITION_BATCH_REQUEST_VERSION, request_key: `condition-child:${crypto.randomUUID()}`, operation: "propose_candidate_child", payload: { batch: { id: detail.entry.id, record_sha256: detail.entry.record_sha256, manifest_sha256: detail.entry.manifest_sha256 }, candidate_sha256: scenario.candidate_sha256 } } });
  }
  function recorded(next: ConditionBatchReceipt) { const pins = commitIdentity.current; commitIdentity.current = null; if (pins) onSaveResolved?.(structuredClone(pins)); setPrepared(null); setRecovery(null); setSaved(next); setPage(null); setDetail(null); setArtifact(null); finish(); setMessage(next.child ? "The candidate child and its batch link were saved together. Open its design history to continue." : "The original generation artifact was retained in your private batch history."); }
  async function save() {
    if (!cap || !prepared || locked || inFlight.current) return; const selected = structuredClone(prepared), current = structuredClone(cap), native = structuredClone(design), op = begin(); setPrepared(null); setMessage("");
    const pins: ConditionBatchSaveRecovery = { ...selected.expected.recovery, inputSha: selected.receipt.input_sha256 };
    commitIdentity.current = pins; onSaveDispatched?.(structuredClone(pins));
    try { const next = await knownConditionBatchReceipt(await op.run(() => discoveryConditionBatchCommit(selected.expected.request, selected.expected.recovery.previewSha, op.signal)), current, native, selected.expected, "commit"); if (!op.active()) return; if (!next) throw new Error("Invalid save receipt"); recorded(next); }
    catch (error) {
      if (!op.active()) return;
      setPage(null); setDetail(null); setArtifact(null); setSaved(null); setRecovery(pins); finish(); setMessage("Save outcome is unverified. Check the original request with GET; no write will be retried.");
      if (error instanceof ApiError && [401, 403, 409].includes(error.status)) fail(error);
    }
  }
  async function checkOutcome() {
    if (!cap || !recovery || disabled || inFlight.current) return; const pins = structuredClone(recovery), current = structuredClone(cap), native = structuredClone(design), op = begin();
    try { const next = await knownConditionBatchOutcome(await op.run(() => discoveryConditionBatchOutcome(pins.requestKey, pins.requestSha, op.signal)), current, native, pins); if (!op.active()) return; if (!next) throw new Error("Invalid original outcome"); recorded(next); }
    catch (error) { if (!op.active()) return; if (error instanceof ApiError && [401, 403].includes(error.status)) fail(error); else { finish(); setMessage("The original outcome remains unverified. No rollback or failed save is inferred; no write was retried."); } }
  }
  function download(checksum = false) {
    if (!artifact || !detail || locked) return; let url: string | null = null;
    const name = `sclib-condition-batch-${detail.entry.manifest_sha256.slice(0, 12)}.json`;
    try { url = URL.createObjectURL(new Blob([checksum ? `${artifact.fileSha}  ${name}\n` : artifact.text], { type: checksum ? "text/plain;charset=utf-8" : "application/json;charset=utf-8" })); const a = document.createElement("a"); a.href = url; a.download = checksum ? `${name}.sha256` : name; document.body.appendChild(a); a.click(); a.remove(); setMessage(checksum ? "The file checksum covers the exact exported UTF-8 bytes, including the original manifest body checksum field." : "The exact retained manifest bytes were exported."); }
    catch { setMessage("The browser could not start the download. The verified retained artifact remains available here."); }
    finally { if (url) setTimeout(() => URL.revokeObjectURL(url!), 1000); }
  }
  return <section className="min-w-0 space-y-4" aria-label="Private condition batches">
    <header className="space-y-2"><h3 className="text-lg font-semibold">Condition batch history</h3><p className="text-sm leading-6 text-sage-muted">Retain the exact generation artifact and connect individual scenarios to native research-design histories. Requested conditions remain proposals.</p></header>
    <div className="flex flex-wrap gap-2"><button type="button" className={button} disabled={disabled || busy} onClick={() => void refresh()}>Refresh batch access</button>{cap && <button type="button" className={button} disabled={locked} onClick={() => void loadPage()}>Load saved batches</button>}</div>
    {busy && <p role="status" className="text-sm text-sage-muted">Verifying private batch scope…</p>}
    {message && <p role="status" className="break-words text-sm [overflow-wrap:anywhere]">{message}</p>}
    {cap && generated && <div className={`${panel} bg-sage-surface`} aria-label="Generated batch retention"><h4 className="font-medium">Generated sweep · {generated.scenarios.length} scenarios</h4><p className="text-xs text-sage-muted">Parent revision {generated.parent.revision} · original generation flags preserved.</p><button type="button" className={button} disabled={locked} onClick={previewRetention}>Preview batch retention</button></div>}
    {cap && recovery && <section className={panel} aria-label="Original batch save recovery"><h4 className="font-medium">Original save recovery</h4><p className="break-all text-xs text-sage-muted">Request key: {recovery.requestKey}</p><button type="button" className={button} disabled={disabled || busy} onClick={() => void checkOutcome()}>Check original batch request</button></section>}
    {page && <section className={panel} aria-label="Saved condition batches"><h4 className="font-medium">Saved batches ({page.total})</h4>{page.entries.length === 0 && <p className="text-sm text-sage-muted">No retained batches in this window. Generate a sweep from an eligible saved design to begin.</p>}<ul className="divide-y divide-sage-border">{page.entries.map(e => <li key={e.id} className="flex flex-wrap items-start justify-between gap-3 py-3"><div className="min-w-0 space-y-1"><p className="text-sm">Parent revision {e.parent.revision} · {e.scenario_total} scenarios</p><p className="break-all text-xs text-sage-muted">Batch {e.id}</p><p className="text-xs text-sage-muted">{e.eligibility.eligible ? "Available for child proposals" : e.eligibility.reason_codes.map(r => r.replaceAll("_", " ")).join(" · ")}</p></div><button type="button" className={button} disabled={locked} onClick={() => void inspect(e.id)}>Inspect batch</button></li>)}</ul><div className="flex flex-wrap gap-2"><button type="button" className={button} disabled={locked || page.offset === 0} onClick={() => void loadPage(Math.max(0, page.offset - 8))}>Previous batches</button><button type="button" className={button} disabled={locked || page.offset + page.entries.length >= page.total || page.offset + 8 > 1000} onClick={() => void loadPage(page.offset + 8)}>Next batches</button></div></section>}
    {detail && artifact && <section className={panel} aria-label="Retained batch scenarios"><h4 className="font-medium">Retained scenarios ({detail.scenario_total})</h4><div className="flex flex-wrap gap-2"><button type="button" className={button} disabled={locked} onClick={() => download()}>Export exact manifest</button><button type="button" className={button} disabled={locked} onClick={() => download(true)}>Export file checksum</button></div><p className="break-all text-xs text-sage-muted">Manifest body SHA-256: {detail.entry.manifest_sha256}</p>{!detail.entry.eligibility.eligible && <p className="text-sm text-amber-800">Child proposals are held: {detail.entry.eligibility.reason_codes.map(r => r.replaceAll("_", " ")).join(" · ")}. The original artifact remains inspectable.</p>}
      <div role="region" aria-label="Retained scenario window" tabIndex={0} className="min-w-0 max-w-full overflow-x-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"><table role="table" className="block w-full min-w-0 text-left text-sm sm:table"><thead role="rowgroup" className="sr-only text-xs text-sage-muted sm:not-sr-only sm:table-header-group"><tr role="row"><th role="columnheader" className="py-2 pr-3">Requested conditions</th><th role="columnheader" className="py-2 pr-3">Proposed next action</th><th role="columnheader" className="py-2">Design history</th></tr></thead><tbody role="rowgroup" className="block divide-y divide-sage-border sm:table-row-group">{detail.scenarios.map(s => <tr role="row" key={s.candidate_id} className="block py-3 sm:table-row sm:py-0"><td role="cell" className="block break-words align-top [overflow-wrap:anywhere] sm:table-cell sm:py-3 sm:pr-3"><span className="mb-1 block text-xs text-sage-muted sm:hidden" aria-hidden="true">Requested conditions</span>{label(s.conditions)}</td><td role="cell" className="mt-3 block break-words align-top [overflow-wrap:anywhere] sm:mt-0 sm:table-cell sm:max-w-64 sm:py-3 sm:pr-3"><span className="mb-1 block text-xs text-sage-muted sm:hidden" aria-hidden="true">Proposed next action</span>{s.proposal.next_action.question}</td><td role="cell" className="mt-3 block align-top sm:mt-0 sm:table-cell sm:py-3">{s.child ? <button type="button" className={`${button} w-full sm:w-auto`} disabled={locked} aria-label={`Open child history for ${label(s.conditions)}`} onClick={() => onOpenChild(structuredClone(s.child!))}>Open child history</button> : <button type="button" className={`${button} w-full sm:w-auto`} disabled={locked || !detail.entry.eligibility.eligible} aria-label={`Preview child for ${label(s.conditions)}`} onClick={() => previewChild(s)}>Preview child</button>}</td></tr>)}</tbody></table></div>
      <div className="flex flex-wrap items-center gap-2 text-xs"><button type="button" className={button} disabled={locked || detail.offset === 0} onClick={() => void inspect(detail.entry.id, Math.max(0, detail.offset - 8))}>Previous retained scenarios</button><span>{detail.offset + 1}–{Math.min(detail.offset + 8, detail.scenario_total)} of {detail.scenario_total}</span><button type="button" className={button} disabled={locked || detail.offset + 8 >= detail.scenario_total} onClick={() => void inspect(detail.entry.id, detail.offset + 8)}>Next retained scenarios</button></div><details className="text-xs"><summary className="cursor-pointer">Inspect original artifact and receipt</summary><pre tabIndex={0} className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-sage-surface p-3">{artifact.text}</pre><pre tabIndex={0} className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-sage-surface p-3">{detail.entry.receipt.receipt_canonical_json}</pre></details>
    </section>}
    {prepared && <section className={`${panel} border-accent-deep`} aria-label="Exact batch operation preview"><h4 className="font-medium">{prepared.receipt.child ? "Candidate child preview" : "Batch retention preview"}</h4><p className="text-sm">{prepared.receipt.child ? "Save the exact candidate proposal and batch link together." : "Retain this exact generation artifact in your private history."}</p><details className="text-xs"><summary className="cursor-pointer">Inspect exact request and preview</summary><pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-sage-surface p-3">{prepared.receipt.request_canonical_json}</pre><pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-sage-surface p-3">{prepared.receipt.preview_canonical_json}</pre></details><button type="button" className={primary} disabled={locked} onClick={() => void save()}>{prepared.receipt.child ? "Save candidate child" : "Retain private batch"}</button></section>}
    {saved && <section className={panel} aria-label="Saved batch operation receipt"><h4 className="font-medium">{saved.child ? "Recorded candidate child" : "Recorded batch retention"}</h4><p className="break-all text-xs text-sage-muted">Batch {saved.batch_id}</p>{saved.child ? <button type="button" className={button} disabled={locked} onClick={() => onOpenChild(child(saved)!)}>Open saved child history</button> : <button type="button" className={button} disabled={locked} onClick={() => void inspect(saved.batch_id)}>Inspect retained batch</button>}<details className="text-xs"><summary className="cursor-pointer">Inspect immutable batch receipt</summary><pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-sage-surface p-3">{saved.receipt_canonical_json}</pre></details></section>}
  </section>;
}
