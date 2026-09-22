"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import { onAuthChange } from "@/lib/auth-session";
import { importCanonical, importDigest } from "@/lib/scientific-imports";
import { commitPilotDecision, getPilotAccess, inspectPilot, parsePilotAccess, parsePilotInspection, parsePilotResult,
  pilotHash, pilotIntent, pilotKey, pilotReason, preparePilotFiles, previewPilotDecision, recoverPilotDecision, validPilotRef,
  type PilotActor, type PilotChoice, type PilotFiles, type PilotInput, type PilotInspection, type PilotRecovery, type PilotRef, type PilotResult } from "@/lib/ml-pilot-participation";

const button = "rounded border border-sage-border bg-white px-3 py-2 text-sm text-accent-deep hover:bg-sage-surface disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2";
const field = "min-w-0 w-full rounded border border-sage-border bg-white p-2 text-sm";
const panel = "min-w-0 space-y-3 rounded-lg border border-sage-border bg-white p-4";
const emptyRef = { registration_id: "", registration_sha256: "" };
type Draft = { input: PilotInput; files: PilotFiles | null; recovery: PilotRecovery; result: PilotResult };

export function MlPilotParticipationWorkbench() {
  const [access, setAccess] = useState<PilotActor | null>(null), [query, setQuery] = useState<PilotRef>(emptyRef);
  const [page, setPage] = useState<PilotInspection | null>(null), [choice, setChoice] = useState<"" | PilotChoice>(""), [reason, setReason] = useState("");
  const [selection, setSelection] = useState<File | null>(null), [protocol, setProtocol] = useState<File | null>(null), [fileEpoch, setFileEpoch] = useState(0);
  const [reviewed, setReviewed] = useState(false), [draft, setDraft] = useState<Draft | null>(null), [receipt, setReceipt] = useState<PilotResult | null>(null);
  const [busy, setBusy] = useState(false), [unresolved, setUnresolved] = useState(false), [message, setMessage] = useState<string | null>(null);
  const [recovery, setRecovery] = useState<PilotRecovery | null>(null), [manualKey, setManualKey] = useState(""), [manualHash, setManualHash] = useState("");
  const serial = useRef(0), mounted = useRef(true), working = useRef(false), controller = useRef<AbortController | null>(null);
  const identity = useRef<string | null>(null), retained = useRef<PilotRecovery | null>(null), heading = useRef<HTMLHeadingElement | null>(null);
  const locked = busy || unresolved, self = page?.participants.find(row => row.binding.user_id === access?.actor_user_id);
  const canAccept = !!page?.current_bound_roles_available && page.current_registration_document_policy;
  const validChoice = !!self && !!choice && self.head?.decision !== choice && (choice !== "withdraw" || self.head?.decision === "accept")
    && (choice !== "accept" || canAccept && selection !== null && protocol !== null);
  const validFields = validChoice && pilotReason(reason);
  function clearFiles() { setSelection(null); setProtocol(null); setFileEpoch(value => value + 1); }
  function clearDecision() { clearFiles(); setChoice(""); setReason(""); setReviewed(false); setDraft(null); setReceipt(null); }
  function clearPrivate() {
    serial.current++; controller.current?.abort(); working.current = false; setBusy(false); setAccess(null); identity.current = null;
    setQuery(emptyRef); setPage(null); clearDecision(); setRecovery(null); setManualKey(""); setManualHash(""); setUnresolved(retained.current !== null);
  }
  function begin() {
    working.current = true; setBusy(true); setMessage(null); const version = ++serial.current;
    controller.current?.abort(); const next = new AbortController(); controller.current = next;
    return { signal: next.signal, active: () => mounted.current && serial.current === version,
      finish: () => { if (mounted.current && serial.current === version) { working.current = false; setBusy(false); } } };
  }
  function fail(error: unknown) {
    setPage(null); clearDecision();
    if (error instanceof ApiError && [401, 403].includes(error.status)) {
      clearPrivate(); setMessage("Account access changed. Private details were cleared. Refresh access under the original account.");
    } else setMessage(error instanceof ApiError && error.status === 404
      ? "The exact invitation or private feature is unavailable. No successful operation is inferred."
      : "The exact response, documents or current state could not be verified. Reinspect the invitation before continuing.");
  }
  async function current(signal: AbortSignal) {
    const value = parsePilotAccess(await getPilotAccess(signal));
    if (identity.current !== null && value.actor_user_id !== identity.current) throw new ApiError(401, null, "Session changed");
    return value;
  }
  async function refresh() {
    if (working.current) return; const call = begin(); setAccess(null); setQuery(emptyRef); setPage(null); clearDecision();
    setRecovery(null); setManualKey(""); setManualHash("");
    try {
      const actor = await current(call.signal); if (!call.active()) return;
      identity.current = actor.actor_user_id; setAccess(actor);
      const original = retained.current; setRecovery(original?.actorId === actor.actor_user_id ? original : null);
      if (original) setMessage(original.actorId === actor.actor_user_id ? "Recover the original outcome before making another decision."
        : "An unresolved operation belongs to another account. Return to its original account to recover it.");
    } catch (error) { if (call.active()) fail(error); } finally { call.finish(); }
  }
  useEffect(() => {
    mounted.current = true; void refresh(); const stop = onAuthChange(() => { clearPrivate(); setMessage("Session changed. Refresh account access before continuing."); });
    return () => { mounted.current = false; serial.current++; controller.current?.abort(); working.current = false; stop(); };
    // No automatic decisions, polling, or browser-persisted private data.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => { if (page) { heading.current?.focus({ preventScroll: true }); heading.current?.scrollIntoView({ block: "start" }); } }, [page]);
  useEffect(() => {
    if (!unresolved) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn); return () => window.removeEventListener("beforeunload", warn);
  }, [unresolved]);
  async function load() {
    if (working.current || unresolved || !access || !validPilotRef(query)) return;
    const call = begin(), ref = { ...query }; setPage(null); clearDecision();
    try {
      const actor = await current(call.signal); if (!call.active()) return;
      const value = await parsePilotInspection(await inspectPilot(ref, call.signal), actor, ref);
      if (!call.active()) return; setAccess(actor); setPage(value);
    } catch (error) { if (call.active()) fail(error); } finally { call.finish(); }
  }
  function edit() { setDraft(null); setReceipt(null); setReviewed(false); setMessage(null); }
  async function preview() {
    if (working.current || unresolved || !access || !page || !self || !choice || !validFields || !reviewed) return;
    const call = begin(), ref = { registration_id: page.registration.id, registration_sha256: page.registration.record_sha256 };
    setDraft(null); setReceipt(null);
    try {
      const actor = await current(call.signal); if (!call.active()) return;
      const latest = await parsePilotInspection(await inspectPilot(ref, call.signal), actor, ref); if (!call.active()) return;
      const member = latest.participants.find(row => row.binding.user_id === actor.actor_user_id);
      if (importCanonical(member ?? null) !== importCanonical(self) || latest.current_bound_roles_available !== page.current_bound_roles_available
        || latest.current_registration_document_policy !== page.current_registration_document_policy) {
        clearDecision(); setPage(latest); setMessage("The current participation or role state changed. Review the refreshed state and choose again."); return;
      }
      const files = choice === "accept" ? await preparePilotFiles(latest.registration, selection!, protocol!, call.signal) : null;
      if (!call.active()) return;
      const input: PilotInput = { participant_id: self.binding.id, participant_sha256: self.binding.record_sha256, registration_sha256: ref.registration_sha256,
        request_key: "ml-pilot:" + crypto.randomUUID(), decision: choice, reason_code: reason,
        supersedes_id: self.head?.id ?? null, supersedes_sha256: self.head?.record_sha256 ?? null };
      const recovery = { actorId: actor.actor_user_id, requestKey: input.request_key, intentSha256: await importDigest(pilotIntent(input, actor.actor_user_id)) };
      if (!call.active()) return;
      const result = await parsePilotResult(await previewPilotDecision(input, actor.actor_user_id, files, call.signal), recovery, false, input);
      if (!call.active()) return; setAccess(actor); setDraft({ input, files, recovery, result });
    } catch (error) { if (call.active()) fail(error); } finally { call.finish(); }
  }
  function acceptReceipt(result: PilotResult) {
    setPage(null); clearDecision(); setReceipt(result); retained.current = null; setRecovery(null); setUnresolved(false); setManualKey(""); setManualHash("");
    setMessage("Historical participation receipt verified. Reinspect the invitation for current readiness. No scientific approval or ML authorization is granted.");
  }
  async function commit() {
    if (working.current || unresolved || !draft || !access || draft.recovery.actorId !== access.actor_user_id) return;
    const call = begin(), original = draft; let sent = false;
    try {
      await current(call.signal); if (!call.active()) return;
      // Retain only recovery references once a write may have been sent. Never
      // retain uploaded documents for a retry or send a replacement request key.
      retained.current = original.recovery; setRecovery(original.recovery); setUnresolved(true); setDraft(null); clearFiles(); sent = true;
      const value = await parsePilotResult(await commitPilotDecision(original.input, original.recovery.actorId, original.files, original.recovery.intentSha256, call.signal), original.recovery, true, original.input);
      if (call.active()) acceptReceipt(value);
    } catch (error) {
      if (!call.active()) return;
      if (!sent || error instanceof ApiError && [401, 403].includes(error.status)) fail(error);
      else { setPage(null); clearDecision(); setMessage("Commit outcome is unknown. Check the original key and hash. No automatic retry is sent; a missing receipt is not proof of rollback."); }
    } finally { call.finish(); }
  }
  async function recover(manual = false) {
    if (working.current || !access || manual && unresolved) return;
    const original = manual ? { actorId: access.actor_user_id, requestKey: manualKey, intentSha256: manualHash } : recovery;
    if (!original || !pilotKey(original.requestKey) || !pilotHash(original.intentSha256)) return;
    const call = begin(); retained.current = original; setRecovery(original); setUnresolved(true); setPage(null); clearDecision();
    try {
      const actor = await current(call.signal); if (!call.active()) return;
      if (actor.actor_user_id !== original.actorId) throw new ApiError(401, null, "Recovery account changed");
      const value = await parsePilotResult(await recoverPilotDecision(original, call.signal), original, true);
      if (!call.active()) return; if (!value.replayed) throw new Error("Invalid recovery"); setAccess(actor); acceptReceipt(value);
    } catch (error) {
      if (!call.active()) return;
      if (error instanceof ApiError && [401, 403].includes(error.status)) fail(error);
      else setMessage(error instanceof ApiError && error.status === 404 ? "No outcome was observed in this snapshot. The original commit may still be in flight; no rollback is inferred."
        : "Outcome remains unknown. Retain the original request key and intent hash; no new write was sent.");
    } finally { call.finish(); }
  }
  return <div className="min-w-0 space-y-5">
    <header className="space-y-3"><h2 className="text-xl font-semibold">ML pilot participation</h2>
      <p className="text-sm">Inspect an exact private preregistration and record your own agreement to its protocol and assigned roles.</p>
      <p className="rounded border border-amber-200 bg-amber-50 p-3 text-sm">Participation is not scientific review completion, source permission, proof of reviewer independence, or permission to train a model.</p>
      <button className={button} disabled={busy} onClick={() => void refresh()}>Refresh account access</button>
      {access && <p className="break-all text-xs">Signed-in account: {access.actor_user_id}. This check grants no reviewer role.</p>}
    </header>
    <div aria-live="polite">{busy && <p role="status">Checking the exact private operation…</p>}{message && <p role="alert" className={panel}>{message}</p>}</div>
    {recovery && <section className={panel} aria-label="Unresolved participation operation"><h3 className="font-semibold">Original operation</h3>
      <p className="text-sm">Keep these references in an approved private record before leaving. This page does not persist files or recovery references in browser storage. After reloading, use manual recovery under the original account.</p>
      <dl className="break-all text-sm"><dt>Original account</dt><dd>{recovery.actorId}</dd><dt>Original request key</dt><dd>{recovery.requestKey}</dd><dt>Intent SHA-256</dt><dd>{recovery.intentSha256}</dd></dl>
      <button className={button} disabled={busy || !access} onClick={() => void recover()}>Check original outcome</button>
    </section>}
    <section className={panel} aria-label="Exact pilot invitation"><h3 className="font-semibold">Exact private invitation</h3>
      <p className="text-sm">Obtain both references and any required original files through your approved private handoff. No public directory or document download is provided.</p>
      {([["registration_id", "Registration UUID"], ["registration_sha256", "Registration record SHA-256"]] as const).map(([name, label]) =>
        <label key={name} className="block text-sm">{label}<input className={field} autoComplete="off" spellCheck={false} maxLength={64} value={query[name]} disabled={locked || !access}
          onChange={event => { setQuery({ ...query, [name]: event.target.value }); setPage(null); clearDecision(); setMessage(null); }} /></label>)}
      <button className={button} disabled={locked || !access || !validPilotRef(query)} onClick={() => void load()}>Inspect invitation</button>
    </section>
    {page && <section className={panel} aria-label="Current pilot participation"><h3 ref={heading} tabIndex={-1} className="scroll-mt-24 font-semibold focus-visible:outline focus-visible:outline-2">Current account participation</h3>
      <p>{page.accepted_account_count.toLocaleString("en-US")} of {page.participant_count.toLocaleString("en-US")} accounts currently accept the protocol.</p>
      <p>Account-participation readiness: <strong>{page.ready_for_prospective_review ? "Ready" : "Not ready"}</strong>. This is a snapshot, not scientific acceptance.</p>
      <p className="text-sm">Bound accounts and roles: {page.current_bound_roles_available ? "Currently available" : "Unavailable"}. Document-check policy: {page.current_registration_document_policy ? "Current" : "Historical; new acceptance unavailable"}.</p>
      <p className="text-sm">{page.owner ? "Registrar view: all bound accounts. You cannot decide for another account." : "Participant view: only your binding and decision are disclosed. Other accounts’ records remain private."}</p>
      <details><summary>Registration and original file references</summary><dl className="break-all text-sm"><dt>Registered at (UTC)</dt><dd>{page.registration.created_at}</dd>
        <dt>Selection file SHA-256</dt><dd>{page.registration.selection_file_sha256}</dd><dt>Protocol file SHA-256</dt><dd>{page.registration.protocol_file_sha256}</dd>
        <dt>Logical selection SHA-256</dt><dd>{page.registration.selection_sha256}</dd><dt>Document-check version</dt><dd>{page.registration_document_check_version}</dd></dl></details>
      <ul className="space-y-2">{page.participants.map(row => <li key={row.binding.id} className="rounded border border-sage-border p-3 text-sm">
        <p className="break-all">Account: {row.binding.user_id}</p><p>Roles: {row.binding.roles.join(", ")}. Current decision: {row.head?.decision ?? "No decision"}.</p>
        <details><summary>Exact binding and predecessor</summary><pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(row, null, 2)}</pre></details>
      </li>)}</ul>
    </section>}
    {self && <section className={panel} aria-label="Own participation decision"><h3 className="font-semibold">Your protocol participation</h3>
      <p className="text-sm">Acceptance confirms only your participation in this exact protocol. Decline and withdrawal need no source upload and remain available after reviewer-role revocation, while your account remains active.</p>
      <label className="block text-sm">Participation decision<select className={field} value={choice} disabled={locked} onChange={event => { setChoice(event.target.value as typeof choice); setReason(""); clearFiles(); edit(); }}>
        <option value="">Choose a decision</option><option value="accept" disabled={!canAccept || self.head?.decision === "accept"}>Accept exact protocol</option>
        <option value="decline" disabled={self.head?.decision === "decline"}>Decline participation</option><option value="withdraw" disabled={self.head?.decision !== "accept"}>Withdraw current acceptance</option></select></label>
      <label className="block text-sm">Reason code<input className={field} value={reason} autoComplete="off" spellCheck={false} maxLength={160} disabled={locked || !choice}
        onChange={event => { setReason(event.target.value); edit(); }} /><span className="text-xs">Start with a lowercase letter; use lowercase letters, digits and underscores only. Do not include names, source text or sensitive details.</span></label>
      {choice === "accept" && <div key={fileEpoch} className="space-y-3"><p className="text-sm">Supply the two original files, each at most 8 MiB. The browser checks raw file hashes before upload; the server independently validates the exact documents. Do not resave or reconstruct them.</p>
        <label className="block text-sm">Original selection file<input className={field} type="file" disabled={locked} onChange={event => { setSelection(event.target.files?.[0] ?? null); edit(); }} /></label>
        <label className="block text-sm">Original protocol file<input className={field} type="file" disabled={locked} onChange={event => { setProtocol(event.target.files?.[0] ?? null); edit(); }} /></label>
        <p className="text-xs">Original files are submitted only for acceptance preview and explicit commit. The registry does not retain their bytes or grant access to them.</p>
      </div>}
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={reviewed} disabled={locked || !validFields} onChange={event => { setReviewed(event.target.checked); setDraft(null); }} />
        <span>I reviewed my exact role, decision and predecessor. For acceptance, I read the original protocol and agree to participate; this does not attest to scientific results or source rights.</span></label>
      <button className={button} disabled={locked || !validFields || !reviewed} onClick={() => void preview()}>Preview participation decision</button>
    </section>}
    {draft && <section className={panel} aria-label="Participation preview"><h3 className="font-semibold">Review before committing</h3>
      <p className="text-sm">Rollback-only preview: no new decision committed. Verify your account, decision, reason, exact binding and predecessor. Keep the key and hash privately for recovery.</p>
      <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(draft.result.intent, null, 2)}</pre>
      <p className="break-all font-mono text-xs">Intent SHA-256: {draft.recovery.intentSha256}</p>
      <button className={button} disabled={locked} onClick={() => void commit()}>Commit exact participation preview</button>
    </section>}
    {receipt && <section className={panel} aria-label="Historical participation receipt"><h3 className="font-semibold">Historical participation receipt</h3>
      <p>Decision: {receipt.intent.decision}. {receipt.replayed ? "Recovered existing record." : "New record committed."}</p>
      <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(receipt.decision, null, 2)}</pre>
      <p className="text-sm">This receipt is not current readiness. It remains historical after later decisions, role revocation or policy changes.</p>
    </section>}
    <section className={panel} aria-label="Manual participation recovery"><h3 className="font-semibold">Recover an earlier operation</h3>
      <p className="text-sm">Sign in as the original participant. Use the original participation request key and intent hash, not the registrar’s key. This is a private read and does not require source files or an active reviewer grant.</p>
      <label className="block text-sm">Recovery request key<input className={field} maxLength={120} autoComplete="off" spellCheck={false} value={manualKey} disabled={locked || !access} onChange={event => setManualKey(event.target.value)} /></label>
      <label className="block text-sm">Recovery intent SHA-256<input className={field} maxLength={64} autoComplete="off" spellCheck={false} value={manualHash} disabled={locked || !access} onChange={event => setManualHash(event.target.value)} /></label>
      <button className={button} disabled={locked || !access || !pilotKey(manualKey) || !pilotHash(manualHash)} onClick={() => void recover(true)}>Recover historical participation</button>
    </section>
  </div>;
}
