"use client";

import { useEffect, useRef, useState } from "react";
import { onAuthChange } from "@/lib/auth-session";
import { parseRunEvidence, parseRunEvidencePurge, purgeRunEvidence, readRunEvidence, validRunEvidenceRef,
  type RunEvidence, type RunEvidenceRef } from "@/lib/ml-use-runs";

const empty: RunEvidenceRef = { decision_id: "", decision_sha256: "" };
const button = "rounded border border-sage-border px-3 py-2 text-sm disabled:opacity-50 focus-visible:outline focus-visible:outline-2";

/** Separate from approver admission so an original author can withdraw text after role revocation. */
export function MlRunEvidencePanel({ disabled = false }: { disabled?: boolean }) {
  const [opened, setOpened] = useState(false);
  const [ref, setRef] = useState<RunEvidenceRef>(empty), [document, setDocument] = useState<RunEvidence | null>(null);
  const [confirm, setConfirm] = useState(false), [busy, setBusy] = useState(false), [unknown, setUnknown] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const serial = useRef(0), active = useRef(false), controller = useRef<AbortController | null>(null);
  // An uncertain purge retains only exact non-content references in memory. No retry is automatic.
  const pending = useRef<RunEvidenceRef | null>(null);
  useEffect(() => {
    const stop = onAuthChange(() => {
      serial.current++; controller.current?.abort(); active.current = false; setBusy(false); setRef(empty);
      setDocument(null); setConfirm(false); setUnknown(false); setOpened(false); pending.current = null;
      setMessage("Session changed. Private evidence was cleared. Any earlier purge outcome remains unknown; recover its exact references under the original account.");
    });
    return () => { serial.current++; controller.current?.abort(); stop(); };
  }, []);
  function edit(value: RunEvidenceRef) { setRef(value); setDocument(null); setConfirm(false); setMessage(null); }
  async function operate(purge: boolean, retry = false) {
    const target = retry ? pending.current : ref;
    if (active.current || disabled || !target || !validRunEvidenceRef(target) || purge && !retry && !confirm || unknown && !retry) return;
    const original = { ...target }, version = ++serial.current;
    active.current = true; setBusy(true); setDocument(null); setMessage(null); setConfirm(false);
    controller.current?.abort(); const abort = new AbortController(); controller.current = abort;
    if (purge) { pending.current = original; setUnknown(true); }
    try {
      if (purge) {
        const value = parseRunEvidencePurge(await purgeRunEvidence(original, abort.signal), original);
        if (serial.current !== version) return;
        pending.current = null; setUnknown(false);
        setMessage(`Private text purge verified${value.replayed ? " (existing receipt)" : ""}. The immutable approval and purge receipt remain; backup deletion is not established. Reload plan/readiness status before relying on it.`);
      } else {
        const value = await parseRunEvidence(await readRunEvidence(original, abort.signal), original);
        if (serial.current === version) setDocument(value);
      }
    } catch {
      if (serial.current !== version) return;
      setMessage(purge ? "Purge outcome is unknown. Keep the exact decision references. Only an explicit identical retry can confirm the retained purge receipt; no rollback is inferred."
        : "Private evidence is unavailable or could not be verified. The original author needs current exact review memberships and unexpired retained text.");
    } finally { if (serial.current === version) { active.current = false; setBusy(false); } }
  }
  const locked = disabled || busy || unknown;
  return <section className="min-w-0 space-y-3 rounded-lg border border-sage-border bg-white p-4" aria-label="Private review evidence">
    <h3 className="font-semibold">Private review evidence</h3>
    {!opened ? <button className={button} disabled={disabled} onClick={() => setOpened(true)}>Manage private review evidence</button> : <>
    <p className="text-sm">Use the decision UUID and record hash from your historical approval receipt. Only its original author can read or request purge. Purge remains available to that verified administrator after review-role removal. It removes the live text irreversibly, not the approval history or backups.</p>
    {([["decision_id", "Evidence decision UUID"], ["decision_sha256", "Evidence decision record SHA-256"]] as const).map(([key, label]) =>
      <label className="block text-sm" key={key}>{label}<input className="w-full min-w-0 rounded border border-sage-border p-2" value={ref[key]} maxLength={64} autoComplete="off" spellCheck={false} disabled={locked}
        onChange={e => edit({ ...ref, [key]: e.target.value })} /></label>)}
    <button className={button} disabled={locked || !validRunEvidenceRef(ref)} onClick={() => void operate(false)}>Read exact private review</button>
    {document && <div className="space-y-2 text-sm">
      <p>Access expiry (UTC): {document.access_expires_at}. Bytes: {document.size_bytes.toLocaleString("en-US")}.</p>
      <p className="break-all font-mono text-xs">Content SHA-256: {document.content_sha256}</p>
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all text-xs">{document.text}</pre>
      <button className={button} onClick={() => setDocument(null)}>Clear displayed text</button>
    </div>}
    <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={confirm} disabled={locked || !validRunEvidenceRef(ref)} onChange={e => setConfirm(e.target.checked)} />
      <span>I request irreversible removal of the private review text for this exact decision. Its history remains and the approval will no longer have available evidence.</span></label>
    <div className="flex flex-wrap gap-2"><button className={button} disabled={locked || !confirm || !validRunEvidenceRef(ref)} onClick={() => void operate(true)}>Purge exact private review</button>
    {unknown && <button className={button} disabled={disabled || busy} onClick={() => void operate(true, true)}>Retry identical evidence purge</button>}
    <button className={button} disabled={busy || unknown} onClick={() => { edit(empty); setOpened(false); }}>Close and clear evidence panel</button>
    </div>
    </>}
    <div aria-live="polite">{busy && <p role="status">Checking private review evidence…</p>}{message && <p role="alert" className="text-sm">{message}</p>}</div>
  </section>;
}
