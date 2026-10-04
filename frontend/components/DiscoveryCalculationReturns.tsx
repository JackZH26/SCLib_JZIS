"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, discoveryCalculationCapabilities, discoveryCalculationCommit, discoveryCalculationContext, discoveryCalculationDetail, discoveryCalculationFile, discoveryCalculationOutcome, discoveryCalculationPage, discoveryCalculationPreview } from "@/lib/api";
import { onAuthChange } from "@/lib/auth-session";
import { CALCULATION_REQUEST_VERSION, calculationByteSha, calculationRecovery, knownCalculationCapabilities, knownCalculationContext, knownCalculationPage, knownCalculationPreview, knownCalculationReading, knownCalculationReceipt, knownCalculationRecovery, prepareCalculationUpload, type CalculationCapabilities, type CalculationContext, type CalculationEntry, type CalculationFile, type CalculationPage, type CalculationReading, type CalculationRecovery, type CalculationRequest, type CalculationUpload } from "@/lib/discovery-calculations";
import type { DesignCapabilities, DesignEntry } from "@/lib/discovery-designs";
import { expressionCanonical, expressionSha } from "@/lib/source-expressions";

const input = "mt-1 block min-h-11 w-full min-w-0 rounded-lg border border-sage-border bg-white px-3 py-2 text-sm text-sage-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent";
const button = "min-h-11 rounded-lg border border-sage-border bg-white px-3 py-2 text-sm text-sage-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50";
const primary = "min-h-11 rounded-lg bg-accent-deep px-4 py-2 text-sm font-medium text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50";
const panel = "min-w-0 space-y-3 rounded-lg border border-sage-border p-3 sm:p-4";
const readable = (text: string) => text.replaceAll("_", " ");
const statusLabel: Record<string, string> = { initialization_only: "Initialization only", incomplete: "Run incomplete", scf_not_converged: "Electronic convergence not reached", ionic_not_converged: "Ionic convergence not reached", scf_reported_converged: "Electronic convergence reported", relaxation_reported_converged: "Relaxation convergence reported" };
type Props = { capabilities: DesignCapabilities; entry: DesignEntry | null; disabled?: boolean; invalidationKey?: number; saveRecovery?: CalculationRecovery | null; onSaveDispatched: (pins: CalculationRecovery) => void; onSaveResolved: (pins: CalculationRecovery) => void; onScopeInvalid?: (error: ApiError) => void };
type Prepared = { upload: CalculationUpload; reading: CalculationReading; recovery: CalculationRecovery };
function Reading({ reading }: { reading: CalculationReading }) {
  const report = reading.report;
  if (!report) return <p className="text-sm text-amber-800">Original files and quantities are withheld: {reading.eligibility.reason_codes.map(readable).join("; ")}</p>;
  return <section aria-label="Native calculation reading" className={`${panel} bg-sage-surface`}>
    <h4 className="font-medium">{statusLabel[report.status]}</h4><p className="text-xs text-sage-muted">{report.engine.name} {report.engine.version} · server reading of the original input, XML, stdout and UPF files</p>
    <dl className="grid min-w-0 gap-3 text-sm sm:grid-cols-2">{([["Total energy", report.observations.total_energy], ["Fermi energy", report.observations.fermi_energy], ["Valence electron count", report.observations.valence_electrons]] as const).map(([label, q]) => <div key={label} className="min-w-0"><dt className="text-sage-muted">{label}</dt><dd className="break-words font-medium [overflow-wrap:anywhere]">{q ? <span title={`Original XML token: ${q.raw}`}>{q.value.toLocaleString("en-US", { maximumSignificantDigits: 12, notation: q.value !== 0 && Math.abs(q.value) < 0.000001 ? "scientific" : "standard" })} {q.unit}</span> : "Not reported for this run"}</dd></div>)}<div><dt className="text-sage-muted">Electronic iterations</dt><dd>{report.convergence.scf_steps.toLocaleString("en-US")}</dd></div></dl>
    <p className="text-xs leading-5 text-sage-muted">Convergence refers to this run. Basis and k-point convergence, material stability and Tc remain unestablished. Total energy includes the selected smearing contribution; it is not formation or hull energy.</p>
    <details className="text-xs"><summary className="cursor-pointer">Inspect method, geometry, native units and file checks</summary><pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-white p-3">{reading.reportText}</pre></details>
  </section>;
}
async function bounded<T>(call: () => Promise<T>, controller: AbortController) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try { return await Promise.race([call(), new Promise<never>((_, reject) => { timer = setTimeout(() => { controller.abort(); reject(new Error("Calculation request timed out")); }, 25000); })]); }
  finally { if (timer) clearTimeout(timer); }
}
export function DiscoveryCalculationReturns(props: Props) {
  return <Workspace key={JSON.stringify([props.capabilities.actor_user_id, props.capabilities.session_version, props.capabilities.curator_grant_id])} {...props} />;
}
function Workspace({ capabilities: access, entry, disabled = false, invalidationKey = 0, saveRecovery = null, onSaveDispatched, onSaveResolved, onScopeInvalid }: Props) {
  const initial = knownCalculationRecovery(saveRecovery) && saveRecovery.actorId === access.actor_user_id ? structuredClone(saveRecovery) : null;
  const [cap, setCap] = useState<CalculationCapabilities | null>(null), [context, setContext] = useState<CalculationContext | null>(null), [busy, setBusy] = useState(false), [message, setMessage] = useState("");
  const [sources, setSources] = useState<{ role: CalculationFile["role"]; file: File }[]>([]), [fileEpoch, setFileEpoch] = useState(0);
  const [findings, setFindings] = useState(""), [decision, setDecision] = useState<CalculationRequest["decision"] | "">(""), [reason, setReason] = useState(""), [unknowns, setUnknowns] = useState(""), [linked, setLinked] = useState(false);
  const [prepared, setPrepared] = useState<Prepared | null>(null), [saved, setSaved] = useState<CalculationEntry | null>(null), [page, setPage] = useState<CalculationPage | null>(null), [reading, setReading] = useState<CalculationReading | null>(null), [recovery, setRecovery] = useState<CalculationRecovery | null>(initial);
  const mounted = useRef(false), sequence = useRef(0), controller = useRef<AbortController | null>(null), inFlight = useRef(false), pending = useRef<CalculationRecovery | null>(initial), previousDraft = useRef(invalidationKey), previousEntry = useRef(entry?.record_sha256 ?? null);
  const downloadUrls = useRef(new Set<string>());
  const [downloadReady, setDownloadReady] = useState<{ url: string; name: string; receiptId: string; ordinal: number } | null>(null);
  function releaseDownloads() { for (const url of downloadUrls.current) URL.revokeObjectURL(url); downloadUrls.current.clear(); }
  function clearDownload() { releaseDownloads(); setDownloadReady(null); }
  const locked = disabled || busy || recovery !== null;
  const currentEntry = entry?.is_head && entry.status === "proposed" && entry.eligibility.eligible && entry.design.next_action.kind === "calculation";
  function clearDraft() { setSources([]); setFileEpoch(n => n + 1); setFindings(""); setDecision(""); setReason(""); setUnknowns(""); setLinked(false); setPrepared(null); }
  function clear() { clearDownload(); ++sequence.current; controller.current?.abort(); inFlight.current = false; setCap(null); setContext(null); setReading(null); setPage(null); setSaved(null); clearDraft(); setRecovery(pending.current); setBusy(false); }
  function begin() { const id = ++sequence.current; controller.current?.abort(); const c = new AbortController(); controller.current = c; inFlight.current = true; setBusy(true); return { signal: c.signal, active: () => mounted.current && sequence.current === id, run: <T,>(call: () => Promise<T>) => bounded(call, c) }; }
  function finish() { inFlight.current = false; setBusy(false); }
  function fail(error: unknown) {
    finish(); clearDownload(); setPrepared(null); setReading(null); setSaved(null); setPage(null); setContext(null);
    if (error instanceof ApiError && [401, 403].includes(error.status)) { pending.current = null; clear(); setMessage("Research access or session changed. Private files and notes have been cleared."); }
    else if (error instanceof ApiError && error.status === 404) setMessage("Calculation returns are not available in this research scope.");
    else if (error instanceof ApiError && error.status === 409) setMessage("The research plan or source changed. Reload the saved plan before continuing.");
    else if (error instanceof ApiError && [400, 413, 415, 422].includes(error.status)) setMessage("These files could not be read within the supported QE input and output scope. Check the original files and size limits, then refresh calculation access.");
    else setMessage("The calculation response could not be verified. Refresh calculation access before continuing.");
    if (error instanceof ApiError && [401, 403, 409].includes(error.status)) onScopeInvalid?.(error);
  }
  async function refresh() {
    if (disabled || inFlight.current) return;
    const e = entry ? structuredClone(entry) : null, op = begin(); clearDownload(); setCap(null); setContext(null); setReading(null); setPage(null); setPrepared(null); setSaved(null); setMessage("");
    try {
      const next = knownCalculationCapabilities(await op.run(() => discoveryCalculationCapabilities(op.signal)), access);
      if (!op.active()) return; if (!next) throw new Error("Invalid calculation capabilities");
      let ctx = null;
      if (e && !pending.current) { ctx = await knownCalculationContext(await op.run(() => discoveryCalculationContext(e.design_id, op.signal)), e); if (!op.active()) return; if (!ctx) throw new Error("Invalid calculation context"); }
      setCap(next); setContext(ctx); finish();
    } catch (error) { if (op.active()) fail(error); }
  }
  useEffect(() => {
    mounted.current = true; void refresh();
    const hide = () => { clear(); setMessage("Private files, readings and notes cleared after leaving this page. Refresh calculation access to continue."); };
    const visibility = () => { if (document.visibilityState === "hidden") hide(); };
    const unsubscribe = onAuthChange(() => { pending.current = null; clear(); });
    window.addEventListener("pagehide", hide); document.addEventListener("visibilitychange", visibility);
    return () => { releaseDownloads(); mounted.current = false; ++sequence.current; controller.current?.abort(); unsubscribe(); window.removeEventListener("pagehide", hide); document.removeEventListener("visibilitychange", visibility); };
    // Identity changes remount this workspace; only the parent retains unknown-save hashes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (previousDraft.current === invalidationKey && previousEntry.current === (entry?.record_sha256 ?? null)) return;
    previousDraft.current = invalidationKey; previousEntry.current = entry?.record_sha256 ?? null;
    if (pending.current) return;
    clear(); setMessage("Proposal scope changed. Refresh calculation access before selecting files.");
    // Draft changes invalidate a file preview; they never repeat an upload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invalidationKey, entry?.record_sha256]);
  function edit(change: () => void) { if (locked || pending.current) return; change(); setPrepared(null); setSaved(null); setMessage(""); }
  async function preview(event: FormEvent) {
    event.preventDefault(); if (!cap || !context?.eligibility.eligible || !currentEntry || locked || inFlight.current || !linked || !decision) return;
    const c = structuredClone(cap), design = structuredClone(context.design), selected = [...sources], op = begin(); clearDownload(); setPrepared(null); setSaved(null); setReading(null); setMessage("");
    try {
      const upload = await op.run(() => prepareCalculationUpload({ version: CALCULATION_REQUEST_VERSION, request_key: `calculation:${crypto.randomUUID()}`, design, association: "researcher_linked_unverified", findings: findings.trim(), decision, reason: reason.trim(), unknowns: unknowns.split(/\r?\n/).map(s => s.trim()).filter(Boolean) }, selected));
      if (!op.active()) return;
      const ref = { actorId: c.actor_user_id, requestKey: upload.request.request_key, requestSha: await expressionSha(expressionCanonical(upload.request)), design };
      if (!op.active()) return;
      const result = await knownCalculationPreview(await op.run(() => discoveryCalculationPreview(upload, op.signal)), c, ref);
      if (!op.active()) return; if (!result) throw new Error("Invalid native preview");
      if (result.receipt.replayed) { clearDraft(); setSaved(result); } else setPrepared({ upload, reading: result, recovery: calculationRecovery(result.receipt, c.actor_user_id) });
      finish();
    } catch (error) { if (op.active()) { if (!(error instanceof ApiError) && error instanceof Error && /Choose one|selected file changed/.test(error.message)) { finish(); setMessage(error.message); } else fail(error); } }
  }
  function recorded(result: CalculationEntry) { const pins = pending.current; pending.current = null; if (pins) onSaveResolved(structuredClone(pins)); clearDraft(); setRecovery(null); setSaved(result); setReading(null); setPage(null); finish(); setMessage("Original files and your decision are saved privately. Load the saved reading to reconstruct the result from retained files."); }
  async function save() {
    if (!cap || !prepared || locked || inFlight.current || pending.current) return;
    const c = structuredClone(cap), selected = prepared, op = begin(); pending.current = selected.recovery; setRecovery(selected.recovery); onSaveDispatched(structuredClone(selected.recovery)); setMessage("");
    try { const result = await knownCalculationReceipt(await op.run(() => discoveryCalculationCommit(selected.upload, selected.recovery.previewSha, op.signal)), c, selected.recovery, "commit"); if (!op.active()) return; if (!result) throw new Error("Invalid save"); recorded(result); }
    catch (error) {
      if (!op.active()) return;
      if (error instanceof ApiError && [400, 401, 403, 409, 413, 415, 422].includes(error.status)) { const pins = pending.current; pending.current = null; if (pins) onSaveResolved(pins); setRecovery(null); fail(error); }
      else { clearDraft(); setReading(null); setPage(null); setRecovery(selected.recovery); finish(); setMessage("Save outcome is unknown. Check the original request; the upload will not be repeated."); }
    }
  }
  async function checkOutcome() {
    if (!cap || !recovery || disabled || inFlight.current) return;
    const c = structuredClone(cap), pins = structuredClone(recovery), op = begin();
    try { const result = await knownCalculationReceipt(await op.run(() => discoveryCalculationOutcome(pins.requestKey, pins.requestSha, op.signal)), c, pins, "outcome"); if (!op.active()) return; if (!result) throw new Error("Invalid outcome"); recorded(result); }
    catch (error) { if (!op.active()) return; if (error instanceof ApiError && [401, 403].includes(error.status)) fail(error); else { finish(); setMessage("The original save remains unverified. Keep this page open; no upload or write was retried."); } }
  }
  async function loadPage(offset = 0) {
    const id = entry?.design_id ?? saved?.receipt.design.design_id;
    if (!cap || !id || locked || inFlight.current) return;
    const c = structuredClone(cap), op = begin(); clearDownload(); setPage(null); setReading(null); setPrepared(null); setMessage("");
    try { const result = await knownCalculationPage(await op.run(() => discoveryCalculationPage(id, offset, op.signal)), c, id, offset); if (!op.active()) return; if (!result) throw new Error("Invalid history"); setPage(result); finish(); } catch (error) { if (op.active()) fail(error); }
  }
  async function inspect(selected: CalculationEntry) {
    if (!cap || locked || inFlight.current) return;
    const c = structuredClone(cap), chosen = structuredClone(selected), op = begin(); clearDownload(); setReading(null); setPrepared(null); setMessage("");
    try { const result = await knownCalculationReading(await op.run(() => discoveryCalculationDetail(chosen.receipt.receipt_id, op.signal)), c, chosen); if (!op.active()) return; if (!result) throw new Error("Invalid retained reading"); setReading(result); finish(); } catch (error) { if (op.active()) fail(error); }
  }
  async function download(ordinal: number) {
    if (!reading?.eligibility.eligible || !reading.report || locked || inFlight.current) return;
    const chosen = structuredClone(reading), f = chosen.request.files[ordinal]; if (!f) return;
    const op = begin(); clearDownload(); setMessage("");
    try {
      const bytes = await op.run(() => discoveryCalculationFile(chosen.receipt.receipt_id, ordinal, f.size_bytes, op.signal));
      if (!op.active()) return; const hash = await calculationByteSha(bytes); if (!op.active()) return; if (hash !== f.sha256) throw new Error("Original byte mismatch");
      const url = URL.createObjectURL(new Blob([new Uint8Array(bytes)], { type: "application/octet-stream" })); downloadUrls.current.add(url); setDownloadReady({ url, name: f.name, receiptId: chosen.receipt.receipt_id, ordinal }); finish(); setMessage(`Verified ${f.name}; size and SHA-256 match the saved original. Use “Save verified file” to download it.`);
    } catch (error) { if (op.active()) fail(error); }
  }
  return <div className="min-w-0 space-y-4" aria-label="Private calculation returns">
    <header className="space-y-2"><h3 className="text-lg font-semibold">Calculation results</h3><p className="max-w-3xl text-sm leading-6 text-sage-muted">Bring original calculation files back to this research question, then record what they change about the next step.</p></header>
    <div className="flex flex-wrap gap-3"><button type="button" className={button} disabled={disabled || busy} onClick={() => void refresh()}>Refresh calculation access</button>{cap && <button type="button" className={button} disabled={locked || !(entry || saved)} onClick={() => void loadPage()}>Load calculation history</button>}{busy && <p role="status" className="self-center text-sm text-sage-muted">Reading exact calculation scope…</p>}</div>
    {context && <p className="break-words text-sm [overflow-wrap:anywhere]"><strong>Research question:</strong> {context.next_action.question}</p>}
    {message && <p role="status" className="rounded-lg bg-sage-surface p-3 text-sm">{message}</p>}
    {recovery && <section className={panel} aria-label="Original calculation save recovery"><h4 className="font-medium">Check the original save</h4><p className="text-sm text-sage-muted">Only the original request identity is retained. Keep this page open until its outcome is known.</p><button type="button" className={button} disabled={!cap || disabled || busy} onClick={() => void checkOutcome()}>Check original calculation request</button></section>}
    {context && !context.eligibility.eligible && <p className="text-sm text-amber-800">New returns are unavailable: {context.eligibility.reason_codes.map(readable).join("; ")}</p>}
    {cap && context?.eligibility.eligible && currentEntry && !recovery && <details open={!prepared && !saved && !page && !reading} className={panel}><summary className="cursor-pointer text-sm font-medium">Return calculation files</summary><form aria-label="Return original calculation files" onSubmit={preview} className="space-y-4">
      <fieldset disabled={locked} className="min-w-0 space-y-4"><legend className="mb-2 text-sm font-medium">Original files</legend>
        <p className="text-xs leading-5 text-sage-muted">PWSCF 7.5, QEXSD 25.05.21, scalar PBE, non-spin-polarized SCF or fixed-cell relaxation in the supported SCLib input format. Input up to 1 MiB; each other file up to 8 MiB. Files are sent to the private server only when you preview.</p>
        <div key={fileEpoch} className="grid min-w-0 gap-3 sm:grid-cols-2">{([["input", "QE input (.in)"], ["xml", "QE XML output"], ["stdout", "QE stdout log"], ["upf", "Original UPF files (1–8)"]] as const).map(([role, label]) => <label key={role} className="min-w-0 text-sm">{label}<input type="file" multiple={role === "upf"} className={`${input} text-xs file:mr-2 file:rounded file:border-0 file:bg-sage-surface file:px-2 file:py-1`} onChange={e => { const files = Array.from(e.target.files ?? []); edit(() => setSources(previous => [...previous.filter(s => s.role !== role), ...files.map(file => ({ role, file }))])); }} /></label>)}</div>
        <label className="block text-sm">Findings<textarea className={input} rows={3} maxLength={4000} required value={findings} onChange={e => edit(() => setFindings(e.target.value))} /></label>
        <div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">Research decision<select className={input} required value={decision} onChange={e => edit(() => setDecision(e.target.value as typeof decision))}><option value="">Choose a decision</option><option value="continue">Continue</option><option value="stop">Stop</option><option value="redirect">Redirect</option></select></label><label className="text-sm">Reason for this decision<textarea className={input} rows={2} maxLength={2000} required value={reason} onChange={e => edit(() => setReason(e.target.value))} /></label></div>
        <label className="block text-sm">Remaining unknowns (one per line, up to 16)<textarea className={input} rows={3} maxLength={16016} value={unknowns} onChange={e => edit(() => setUnknowns(e.target.value))} /></label>
        <label className="flex items-start gap-2 text-sm leading-5"><input type="checkbox" checked={linked} className="mt-1 h-4 w-4 shrink-0 accent-[color:var(--accent,#3A7D5C)]" onChange={e => edit(() => setLinked(e.target.checked))} /><span>I am associating these files with this question. This association and the original execution have not been independently verified.</span></label>
        <button type="submit" className={primary} disabled={!linked || !decision}>Preview calculation return</button>
      </fieldset>
    </form></details>}
    {prepared && !recovery && <section className={panel} aria-label="Exact calculation preview"><Reading reading={prepared.reading} /><p className="text-sm">Decision: <strong>{readable(prepared.upload.request.decision)}</strong> — {prepared.upload.request.reason}</p><p className="text-xs text-sage-muted">Saving retains {prepared.upload.request.files.length} original files and this decision in your private plan history.</p><details className="text-xs"><summary className="cursor-pointer">Inspect exact request and file fingerprints</summary><pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-all">{prepared.reading.receipt.request_canonical_json}</pre></details><button type="button" className={primary} disabled={locked} onClick={() => void save()}>Save original files and decision</button></section>}
    {saved && <section className={panel} aria-label="Saved calculation receipt"><h4 className="font-medium">Saved calculation return</h4><p className="text-sm">{readable(saved.request.decision)} · {saved.request.files.length} original files</p><button type="button" className={button} disabled={locked} onClick={() => void inspect(saved)}>Read saved calculation</button><details className="text-xs"><summary className="cursor-pointer">Inspect immutable receipt</summary><pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-all">{saved.receipt.receipt_canonical_json}</pre></details></section>}
    {page && <section className={panel} aria-label="Calculation return history"><h4 className="font-medium">Saved returns ({page.total.toLocaleString("en-US")})</h4>{!page.entries.length && <p className="text-sm text-sage-muted">No saved calculation returns in this window.</p>}<ul className="divide-y divide-sage-border">{page.entries.map(item => <li key={item.receipt.receipt_id} className="flex min-w-0 flex-col items-start justify-between gap-3 py-3 sm:flex-row"><div className="min-w-0 flex-1"><p className="text-sm font-medium">{readable(item.request.decision)} · {item.request.files.length} files</p><p className="break-words text-sm [overflow-wrap:anywhere]">{item.request.reason}</p>{!item.eligibility.eligible && <p className="text-xs text-amber-800">{item.eligibility.reason_codes.map(readable).join("; ")}</p>}</div><button type="button" className={button} disabled={locked} onClick={() => void inspect(item)}>Inspect return</button></li>)}</ul><div className="flex flex-wrap gap-2"><button type="button" className={button} disabled={locked || page.offset === 0} onClick={() => void loadPage(Math.max(0, page.offset - 8))}>Previous returns</button><button type="button" className={button} disabled={locked || page.offset + page.entries.length >= page.total || page.offset >= 1000} onClick={() => void loadPage(page.offset + 8)}>Next returns</button></div></section>}
    {reading && <section className={panel} aria-label="Saved calculation detail"><Reading reading={reading} /><div className="space-y-2 break-words text-sm [overflow-wrap:anywhere]"><p><strong>Findings:</strong> {reading.request.findings}</p><p><strong>Decision:</strong> {readable(reading.request.decision)} — {reading.request.reason}</p>{reading.request.unknowns.length > 0 && <details><summary className="cursor-pointer">Remaining unknowns ({reading.request.unknowns.length})</summary><ul className="mt-2 list-inside list-disc">{reading.request.unknowns.map(s => <li key={s}>{s}</li>)}</ul></details>}</div>{reading.report && reading.eligibility.eligible && <div className="space-y-2"><h4 className="text-sm font-medium">Retained original files</h4><ul className="space-y-2">{reading.request.files.map((f, i) => <li key={`${f.role}:${f.name}`} className="flex min-w-0 flex-col items-start justify-between gap-2 text-sm sm:flex-row sm:items-center"><span className="min-w-0 flex-1 break-all">{f.name} <span className="text-xs text-sage-muted">({f.size_bytes.toLocaleString("en-US")} bytes)</span></span>{downloadReady?.receiptId === reading.receipt.receipt_id && downloadReady.ordinal === i && !locked ? <a href={downloadReady.url} download={downloadReady.name} aria-label={`Save verified ${f.role === "upf" ? f.name : f.role}`} className={`${button} inline-flex items-center`} onClick={() => setMessage(`Download requested for ${f.name}. The saved bytes were verified before this link was created.`)}>Save verified file</a> : <button type="button" aria-label={`Prepare download ${f.role === "upf" ? f.name : f.role}`} className={button} disabled={locked} onClick={() => void download(i)}>Prepare download</button>}</li>)}</ul></div>}</section>}
  </div>;
}
