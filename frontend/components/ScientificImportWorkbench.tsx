"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { ApiError, scientificImportAccess, scientificImportBinding, scientificImportOutcome, scientificImportSubmit } from "@/lib/api";
import { onAuthChange } from "@/lib/auth-session";
import { ImportInputError, importHash, importMaterialId, knownImportAccess, knownImportBinding, knownImportReceipt, prepareImportRequest, readImportManifest,
  type ImportAccess, type ImportBinding, type ImportManifest, type ImportReceipt, type ImportRecovery, type ImportRequest } from "@/lib/scientific-imports";

const button = "rounded border border-sage-border bg-white px-3 py-2 text-sm text-accent-deep hover:bg-sage-surface disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2";
const input = "min-w-0 w-full rounded border border-sage-border bg-white p-2 text-sm";
const panel = "min-w-0 space-y-3 rounded-lg border border-sage-border bg-white p-4";
const statusLabel = { success_pending: "Pending scientific review", quarantined: "Quarantined — no canonical result rows", failed: "Technical failure recorded", outcome_unknown: "Durable start — terminal outcome unknown" };
type Draft = { body: ImportRequest; receipt: ImportReceipt; access: ImportAccess };
const number = (value: number | null | undefined) => value == null ? "Not reported" : value.toLocaleString("en-US") + " ms";

export function ScientificImportWorkbench() {
  const [access, setAccess] = useState<ImportAccess | null>(null);
  const [materialId, setMaterialId] = useState("");
  const [binding, setBinding] = useState<ImportBinding | null>(null);
  const [manifestFile, setManifestFile] = useState<File | null>(null);
  const [manifestPin, setManifestPin] = useState("");
  const [manifest, setManifest] = useState<ImportManifest | null>(null);
  const [files, setFiles] = useState<Record<string, File>>({});
  const [forceFile, setForceFile] = useState<File | null>(null);
  const [forceName, setForceName] = useState("");
  const [forcePin, setForcePin] = useState("");
  const [fileEpoch, setFileEpoch] = useState(0);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [receipt, setReceipt] = useState<ImportReceipt | null>(null);
  const [busy, setBusy] = useState(false);
  const [unresolved, setUnresolved] = useState(false);
  const [recovery, setRecovery] = useState<ImportRecovery | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const seq = useRef(0), mounted = useRef(true), controller = useRef<AbortController | null>(null), writing = useRef(false);
  const retained = useRef<ImportRecovery | null>(null), heading = useRef<HTMLHeadingElement | null>(null);
  const locked = busy || unresolved || !access;
  function begin() {
    const generation = ++seq.current; controller.current?.abort(); const next = new AbortController(); controller.current = next;
    const timer = window.setTimeout(() => next.abort(), 55_000);
    return { signal: next.signal, active: () => mounted.current && seq.current === generation,
      finish: () => { window.clearTimeout(timer); if (mounted.current && seq.current === generation) setBusy(false); } };
  }
  function clearFiles() {
    setManifestFile(null); setManifestPin(""); setManifest(null); setFiles({}); setForceFile(null); setForceName(""); setForcePin("");
    setFileEpoch(n => n + 1); setDraft(null);
  }
  function clearPrivate() {
    seq.current++; controller.current?.abort(); clearFiles(); setBinding(null); setMaterialId(""); setReceipt(null); setAccess(null);
    setRecovery(null); setUnresolved(retained.current !== null); setBusy(false); writing.current = false;
  }
  function edit() { setDraft(null); setReceipt(null); setMessage(null); }
  async function checkAccess(signal: AbortSignal) {
    const current = knownImportAccess(await scientificImportAccess(signal));
    if (!current) throw new Error("Unverified access"); return current;
  }
  function failed(error: unknown) {
    setDraft(null); setReceipt(null);
    if (error instanceof ApiError && [401, 403].includes(error.status)) {
      clearPrivate(); setMessage("Curator access or session changed. Private files and results have been cleared. Refresh access to continue.");
    } else setMessage(error instanceof ImportInputError ? error.message : "The operation could not be verified. No success is inferred; inspect the inputs and preview again.");
  }
  async function refresh() {
    if (busy) return;
    clearPrivate(); const call = begin(); setBusy(true); setMessage(null);
    try {
      const current = await checkAccess(call.signal); if (!call.active()) return; setAccess(current);
      if (retained.current) {
        if (retained.current.actorId === current.actor_user_id) setRecovery(retained.current);
        else setMessage("An unresolved import belongs to another account. Sign in as the original account to recover it; new imports remain locked here.");
      }
    } catch (error) { if (call.active()) failed(error); } finally { call.finish(); }
  }
  useEffect(() => {
    mounted.current = true; void refresh();
    const unsubscribe = onAuthChange(() => { clearPrivate(); setMessage("Session changed. Local files and private results were cleared. Refresh curator access."); });
    return () => { mounted.current = false; seq.current++; controller.current?.abort(); unsubscribe(); };
    // Initial access only; file selection does not upload or run a parser.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (retained.current) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", warn); return () => window.removeEventListener("beforeunload", warn);
  }, []);
  useEffect(() => { if (draft || receipt) { heading.current?.focus(); heading.current?.scrollIntoView({ block: "start" }); } }, [draft, receipt]);
  async function inspectMaterial() {
    if (locked || !importMaterialId(materialId)) return;
    const original = access!, call = begin(); setBusy(true); setBinding(null); edit();
    try {
      const current = await checkAccess(call.signal); if (!call.active()) return;
      if (current.actor_user_id !== original.actor_user_id || current.actor_grant_id !== original.actor_grant_id) throw new ApiError(401, null, "Access changed");
      const result = knownImportBinding(await scientificImportBinding(materialId, call.signal), materialId);
      if (!call.active()) return; if (!result) throw new Error("Unverified material binding"); setAccess(current); setBinding(result);
    } catch (error) { if (call.active()) failed(error); } finally { call.finish(); }
  }
  async function loadManifest() {
    if (locked || !manifestFile) return;
    const call = begin(); setBusy(true); setManifest(null); setFiles({}); edit();
    try {
      const value = await readImportManifest(manifestFile, manifestPin);
      if (!call.active() || call.signal.aborted) return; setManifest(value);
    } catch (error) { if (call.active()) failed(error); } finally { call.finish(); }
  }
  async function preview() {
    if (locked || !binding || !manifest) return;
    const original = access!, call = begin(); setBusy(true); edit();
    try {
      const current = await checkAccess(call.signal); if (!call.active()) return;
      if (current.actor_user_id !== original.actor_user_id || current.actor_grant_id !== original.actor_grant_id) throw new ApiError(401, null, "Access changed");
      const body = await prepareImportRequest({ manifest, manifestSha256: manifestPin, binding, files, forceFile, forceName, forceSha256: forcePin,
        compilerSha256: current.compiler_sha256, requestKey: "browser-import:" + crypto.randomUUID() });
      if (!call.active() || call.signal.aborted) return;
      const value = knownImportReceipt(await scientificImportSubmit(body, call.signal), { mode: "preview", requestSha256: body.expected_request_sha256, grantId: current.actor_grant_id });
      if (!call.active()) return; if (!value) throw new Error("Unverified preview"); setAccess(current); setDraft({ body, receipt: value, access: current });
    } catch (error) { if (call.active()) failed(error); } finally { call.finish(); }
  }
  function accept(value: ImportReceipt) {
    setReceipt(value); setDraft(null);
    if (value.status === "outcome_unknown") {
      setUnresolved(true); setMessage("A durable start exists, but its terminal outcome is unknown. Check again explicitly; this read does not resume parsing.");
    } else { retained.current = null; setRecovery(null); setUnresolved(false); setMessage(null); }
  }
  async function commit() {
    if (locked || !draft || writing.current) return;
    writing.current = true; const original = draft, call = begin(); setBusy(true); setMessage(null);
    let submitted = false;
    try {
      const current = await checkAccess(call.signal); if (!call.active()) return;
      if (current.actor_user_id !== original.access.actor_user_id || current.actor_grant_id !== original.access.actor_grant_id) throw new ApiError(401, null, "Access changed");
      if (current.compiler_sha256 !== original.access.compiler_sha256) throw new ImportInputError("The server parser version changed. Prepare a new preview; no commit was sent.");
      const ref = { actorId: current.actor_user_id, requestKey: original.body.request_key, requestSha256: original.body.expected_request_sha256 };
      retained.current = ref; setRecovery(ref); setUnresolved(true); submitted = true;
      const value = knownImportReceipt(await scientificImportSubmit({ ...original.body, dry_run: false }, call.signal),
        { mode: "commit", requestSha256: ref.requestSha256, grantId: original.access.actor_grant_id });
      if (!call.active()) return; if (!value) throw new Error("Unverified import acknowledgement");
      clearFiles(); setBinding(null); setMaterialId(""); accept(value);
    } catch (error) {
      if (!call.active()) return;
      if (!submitted) failed(error);
      else {
        clearFiles(); setBinding(null); setMaterialId(""); setReceipt(null);
        if (error instanceof ApiError && [401, 403].includes(error.status)) { clearPrivate(); setMessage("Access changed during submission. Refresh under the original account to check its outcome."); }
        else setMessage("Import outcome is unknown. Check the original request; an error or absent receipt does not prove rollback. No upload is retried automatically.");
      }
    } finally { writing.current = false; call.finish(); }
  }
  async function recover() {
    if (busy || !recovery) return;
    const original = recovery, call = begin(); setBusy(true); setMessage(null);
    try {
      const current = await checkAccess(call.signal); if (!call.active()) return;
      if (current.actor_user_id !== original.actorId) throw new ApiError(401, null, "Recovery account changed");
      const value = knownImportReceipt(await scientificImportOutcome(original, call.signal), { mode: "outcome", requestSha256: original.requestSha256 });
      if (!call.active()) return; if (!value || !value.replayed) throw new Error("Unverified original outcome"); setAccess(current); accept(value);
    } catch (error) {
      if (!call.active()) return;
      if (error instanceof ApiError && [401, 403].includes(error.status)) { clearPrivate(); setMessage("Curator access changed. Refresh under the original account; private recovery data was cleared."); }
      else setMessage(error instanceof ApiError && error.status === 404
        ? "No attempt was observed in this snapshot. The original request may still be in flight; no rollback or safe retry is inferred."
        : "The original outcome remains unverified. No new upload or write was sent.");
    } finally { call.finish(); }
  }
  const displayed = draft?.receipt ?? receipt;
  return <div className="min-w-0 space-y-5">
    <header className="space-y-3"><h2 className="text-xl font-semibold text-sage-ink">Scientific imports</h2>
      <p className="text-sm text-sage-muted">Private, bounded QE matdyn file import. Select existing local bytes, preview the exact package and explicitly retain pending evidence.</p>
      <p className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">This does not run a calculation, approve science or admit ML training data. A minimum over supplied q-points is not full-Brillouin-zone stability or evidence of superconductivity.</p>
      <button className={button} disabled={busy} onClick={() => void refresh()}>Refresh curator access</button></header>
    <div aria-live="polite">{busy && <p role="status">Checking the exact private import…</p>}{message && <p role="alert" className="rounded border border-sage-border p-3 text-sm">{message}</p>}</div>
    {recovery && <section className={panel} aria-label="Unresolved import">
      <h3 className="font-semibold">Original import request</h3><p className="text-sm">Keep this page open. Navigation or reload loses this in-memory recovery locator. Retain the references in your approved private operation record; keep the original source package separately.</p>
      <dl className="space-y-1 break-all text-xs"><dt>Original account</dt><dd className="font-mono">{recovery.actorId}</dd><dt>Request key</dt><dd className="font-mono">{recovery.requestKey}</dd><dt>Package SHA-256</dt><dd className="font-mono">{recovery.requestSha256}</dd></dl>
      <button className={button} disabled={busy} onClick={() => void recover()}>Check original outcome</button><p className="text-sm">Read only. This does not retry the upload, resume a worker or record a failure.</p>
    </section>}
    <section className={panel} aria-label="Existing material binding">
      <h3 className="font-semibold">1. Inspect an existing material</h3>
      <label className="block text-sm">Material ID<input className={input} maxLength={100} value={materialId} disabled={locked} onChange={e => { if (!locked) { setMaterialId(e.target.value); setBinding(null); edit(); } }} /></label>
      <button className={button} disabled={locked || !importMaterialId(materialId)} onClick={() => void inspectMaterial()}>Inspect material</button>
      {binding && <><p className="break-all text-sm">Current formula: {binding.material_formula}. Formula agreement alone does not establish phase or sample identity.</p>
        <p className="break-all font-mono text-xs">Material row SHA-256: {binding.material_row_sha256}</p></>}
    </section>
    <section className={panel} aria-label="Local source package">
      <h3 className="font-semibold">2. Select the existing source package</h3>
      <p className="text-sm">Use the canonical UTF-8 manifest from the package workflow (up to 64 KiB, no formatting or trailing newline). Supply its SHA-256 from an independent trusted record; copying a hash from an untrusted replacement does not authenticate it. Files are never opened by a URL or program path.</p>
      <label className="block text-sm">Canonical manifest file<input key={"manifest-" + fileEpoch} className={input} type="file" accept=".json,application/json" disabled={locked} onChange={e => { if (!locked) { setManifestFile(e.target.files?.[0] ?? null); setManifest(null); setFiles({}); edit(); } }} /></label>
      <label className="block text-sm">Independent manifest SHA-256<input className={input} maxLength={64} value={manifestPin} disabled={locked} onChange={e => { if (!locked) { setManifestPin(e.target.value); setManifest(null); setFiles({}); edit(); } }} /></label>
      <button className={button} disabled={locked || !manifestFile || !importHash(manifestPin)} onClick={() => void loadManifest()}>Load local manifest</button>
      <p className="text-sm text-sage-muted">Loading the manifest reads only local bytes. Preview is the first explicit source upload.</p>
      {manifest && <><p className="break-all text-sm">Declared source formula: {manifest.context.material_formula ?? "Not reported"}; geometry: {manifest.context.geometry_scope}. These are unreviewed declarations.</p>
        <p className="text-sm">Select each logical file below. Physical filenames may differ; actual sizes and SHA-256 must match. Original files: 4 MiB each, 8 MiB combined including the manifest.</p>
        <ul className="space-y-3">{manifest.files.map(entry => <li key={entry.logical_name} className="min-w-0 space-y-2 rounded border border-sage-border p-3">
          <p className="break-all text-sm">{entry.role} · {entry.logical_name} · {entry.size_bytes.toLocaleString("en-US")} bytes</p><p className="break-all font-mono text-xs">{entry.sha256}</p>
          <label className="block text-sm">Source file: {entry.logical_name}<input key={entry.logical_name + fileEpoch} className={input} type="file" disabled={locked} onChange={e => { if (!locked) {
            const selected = e.target.files?.[0]; setFiles(old => { const next = { ...old }; if (selected) next[entry.logical_name] = selected; else delete next[entry.logical_name]; return next; }); edit();
          } }} /></label></li>)}</ul></>}
      <label className="block text-sm">Force-constant file (optional)<input key={"force-" + fileEpoch} className={input} type="file" disabled={locked} onChange={e => { if (!locked) { setForceFile(e.target.files?.[0] ?? null); edit(); } }} /></label>
      <label className="block text-sm">Force-constant logical name<input className={input} maxLength={120} value={forceName} disabled={locked} onChange={e => { if (!locked) { setForceName(e.target.value); edit(); } }} /></label>
      <label className="block text-sm">Independent force-constant SHA-256<input className={input} maxLength={64} value={forcePin} disabled={locked} onChange={e => { if (!locked) { setForcePin(e.target.value); edit(); } }} /></label>
      <p className="text-sm">Optional FC: up to 8 MiB, with the exact logical flfrc name from the program input and an independent hash. Leave all three FC fields empty if unavailable; missing validated coordinates produce quarantine, never formula-derived coordinates.</p>
      <button className={button} disabled={locked || !binding || !manifest} onClick={() => void preview()}>Preview pending import</button>
    </section>
    {displayed && <section className={panel} aria-label={draft ? "Import preview" : "Import receipt"}>
      <h3 ref={heading} tabIndex={-1} className="scroll-mt-24 font-semibold focus-visible:outline focus-visible:outline-2">{draft ? "Review before importing" : "Durable import receipt"}</h3>
      <p className="text-sm">{statusLabel[displayed.status]}</p>
      <p className="text-sm">{draft ? "Rollback-only preview: proposed IDs are not evidence of saved records." : "This is an import history receipt, not a fresh scientific, source-rights or ML approval."}</p>
      <dl className="space-y-1 break-all text-xs"><dt>Package SHA-256</dt><dd className="font-mono">{displayed.requestSha256}</dd>
        {!draft && <><dt>Attempt ID</dt><dd className="font-mono">{displayed.attemptId}</dd></>}
        <dt>Parser-worker wall time</dt><dd>{number(displayed.costs?.import_wall_ms)}</dd><dt>Parser-worker CPU time</dt><dd>{number(displayed.costs?.import_cpu_ms)}</dd></dl>
      <p className="text-sm">Calculation wall time, CPU time and monetary cost: not reported, not zero. No raw native report is rendered here.</p>
      {displayed.reasons.length > 0 && <ul className="list-disc space-y-1 pl-5 text-sm">{displayed.reasons.map(reason => <li className="break-all" key={reason}>{reason.replaceAll("_", " ")}</li>)}</ul>}
      {draft && <button className={button} disabled={locked} onClick={() => void commit()}>Commit exact preview</button>}
      {!draft && displayed.rowIds && <><p className="break-all text-sm">Pending property ID: <span className="font-mono">{displayed.rowIds.property}</span></p>
        <Link className="text-sm text-accent-deep underline" href="/dashboard/research/review">Open scientific evidence workbench</Link>
        <p className="text-sm">Locate the actual property ID above in the private evidence inventory. Import does not approve or publish it.</p></>}
    </section>}
  </div>;
}
