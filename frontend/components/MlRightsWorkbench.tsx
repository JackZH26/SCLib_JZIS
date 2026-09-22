"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import { onAuthChange } from "@/lib/auth-session";
import { importDigest } from "@/lib/scientific-imports";
import { commitMlRights, getMlRightsAccess, inspectMlRights, ML_RIGHTS_BASES, ML_RIGHTS_PURPOSE, mlRightsHash, mlRightsIntent, mlRightsKey,
  parseMlRightsAccess, parseMlRightsPage, parseMlRightsResult, previewMlRights, recoverMlRights, validMlRightsQuery,
  type MlRightsActor, type MlRightsInput, type MlRightsPage, type MlRightsQuery, type MlRightsRecovery, type MlRightsResource, type MlRightsResult } from "@/lib/ml-use-rights";

const button = "rounded border border-sage-border bg-white px-3 py-2 text-sm text-accent-deep hover:bg-sage-surface disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2";
const field = "min-w-0 w-full rounded border border-sage-border bg-white p-2 text-sm";
const panel = "min-w-0 space-y-3 rounded-lg border border-sage-border bg-white p-4";
const emptyQuery = { submission_id: "", submission_sha256: "", inventory_sha256: "" };
type Draft = { input: MlRightsInput; result: MlRightsResult; recovery: MlRightsRecovery };
const statusLabels = { unreviewed: "Unreviewed", allow_recorded: "Allow recorded", denied: "Denied", revoked: "Revoked", expired: "Expired", reviewer_unavailable: "Reviewer unavailable" };

export function MlRightsWorkbench() {
  const [access, setAccess] = useState<MlRightsActor | null>(null), [query, setQuery] = useState<MlRightsQuery>(emptyQuery);
  const [page, setPage] = useState<MlRightsPage | null>(null), [selected, setSelected] = useState<MlRightsResource | null>(null);
  const [choice, setChoice] = useState<"" | MlRightsInput["decision"]>(""), [basis, setBasis] = useState("");
  const [evidence, setEvidence] = useState(""), [expiry, setExpiry] = useState(""), [reviewed, setReviewed] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null), [receipt, setReceipt] = useState<MlRightsResult | null>(null);
  const [busy, setBusy] = useState(false), [unresolved, setUnresolved] = useState(false), [message, setMessage] = useState<string | null>(null);
  const [recovery, setRecovery] = useState<MlRightsRecovery | null>(null), [manualKey, setManualKey] = useState(""), [manualHash, setManualHash] = useState("");
  const serial = useRef(0), mounted = useRef(true), working = useRef(false), controller = useRef<AbortController | null>(null);
  const identity = useRef<string | null>(null), retained = useRef<MlRightsRecovery | null>(null), pending = useRef<Draft | null>(null);
  const heading = useRef<HTMLHeadingElement | null>(null);
  const locked = busy || unresolved;
  function clearDecision() { setSelected(null); setDraft(null); setReceipt(null); setChoice(""); setBasis(""); setEvidence(""); setExpiry(""); setReviewed(false); }
  function clearPrivate() {
    serial.current++; controller.current?.abort(); working.current = false; setBusy(false); setAccess(null); identity.current = null;
    setQuery(emptyQuery); setPage(null); clearDecision(); pending.current = null; setRecovery(null); setManualKey(""); setManualHash("");
    setUnresolved(retained.current !== null);
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
      clearPrivate(); setMessage("Reviewer access changed. Private details were cleared. Refresh access under the original account.");
    } else setMessage(error instanceof ApiError && error.status === 404
      ? "The exact private resource or feature is unavailable. No permission or successful operation is inferred."
      : "The response could not be verified. Reload the exact inventory; no success is inferred.");
  }
  async function current(signal: AbortSignal) {
    const value = parseMlRightsAccess(await getMlRightsAccess(signal));
    if (identity.current !== null && identity.current !== value.actor_user_id) throw new ApiError(401, null, "Session changed");
    return value;
  }
  async function refresh() {
    if (working.current) return; const call = begin(); setAccess(null); setPage(null); clearDecision();
    try {
      const value = await current(call.signal); if (!call.active()) return;
      identity.current = value.actor_user_id; setAccess(value);
      const original = retained.current; setRecovery(original?.actorId === value.actor_user_id ? original : null);
      if (original) setMessage(original.actorId === value.actor_user_id ? "Recover the original outcome before making another decision."
        : "An unresolved operation belongs to another account. Return to its original account to recover it.");
    } catch (e) { if (call.active()) fail(e); } finally { call.finish(); }
  }
  useEffect(() => {
    mounted.current = true; void refresh(); const stop = onAuthChange(() => { clearPrivate(); setMessage("Session changed. Refresh reviewer access before continuing."); });
    // React Strict Mode replays mount effects. Retire both the old request and
    // its synchronous busy guard, so the next setup can perform fresh admission.
    return () => { mounted.current = false; serial.current++; controller.current?.abort(); working.current = false; stop(); };
    // No automatic writes, polling or browser-persisted private drafts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => { if (selected) { heading.current?.focus({ preventScroll: true }); heading.current?.scrollIntoView({ block: "start" }); } }, [selected]);
  useEffect(() => {
    if (!unresolved) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn); return () => window.removeEventListener("beforeunload", warn);
  }, [unresolved]);
  async function load(after: string | null = null) {
    if (working.current || unresolved || !access || !validMlRightsQuery(query)) return;
    const call = begin(), request = { ...query, after }, previous = after ? page ?? undefined : undefined;
    setPage(null); clearDecision();
    try {
      const actor = await current(call.signal); if (!call.active()) return;
      const value = await parseMlRightsPage(await inspectMlRights(request, call.signal), actor, request, previous);
      if (!call.active()) return; setAccess(actor); setPage(value);
    } catch (e) { if (call.active()) fail(e); } finally { call.finish(); }
  }
  function edit() { setDraft(null); setReceipt(null); setReviewed(false); setMessage(null); }
  const validFields = !!choice && (ML_RIGHTS_BASES as readonly string[]).includes(basis) && (evidence === "" || mlRightsHash(evidence))
    && (choice === "allow" ? mlRightsHash(evidence) && /^[1-9]\d{0,15}$/.test(expiry) && Number.isSafeInteger(Number(expiry))
      && Number(expiry) > Date.now() / 1000 && !!page && Number(expiry) <= Date.parse(page.input_access_expires_at) / 1000 : true)
    && (choice !== "revoke" || selected?.head?.decision === "allow");
  async function preview() {
    if (working.current || unresolved || !access || !selected || !page || !validFields || !reviewed || !choice) return;
    const call = begin(); setDraft(null); setReceipt(null);
    try {
      const actor = await current(call.signal); if (!call.active()) return;
      if (actor.reviewer_grant_id !== page.reviewer_grant_id || actor.curator_grant_id !== page.curator_grant_id) throw new Error("Membership changed");
      const input: MlRightsInput = { submission_id: page.submission_id, submission_sha256: page.submission_sha256, inventory_sha256: page.inventory_sha256,
        resource_id: selected.resource_id, reviewer_grant_id: actor.reviewer_grant_id, curator_grant_id: actor.curator_grant_id,
        purpose: ML_RIGHTS_PURPOSE, request_key: "ml-rights:" + crypto.randomUUID(), decision: choice, basis_code: basis as MlRightsInput["basis_code"],
        evidence_sha256: evidence || null, expires_epoch: choice === "allow" ? Number(expiry) : null,
        supersedes_id: selected.head?.id ?? null, supersedes_sha256: selected.head?.record_sha256 ?? null };
      const recovery = { actorId: actor.actor_user_id, requestKey: input.request_key, intentSha256: await importDigest(mlRightsIntent(input, actor.actor_user_id)) };
      if (!call.active()) return;
      const result = await parseMlRightsResult(await previewMlRights(input, call.signal), recovery, false, input);
      if (!call.active()) return; setAccess(actor); setDraft({ input, recovery, result });
    } catch (e) { if (call.active()) fail(e); } finally { call.finish(); }
  }
  function accept(result: MlRightsResult) {
    setPage(null); clearDecision(); setReceipt(result); pending.current = null; retained.current = null; setRecovery(null); setUnresolved(false);
    setManualKey(""); setManualHash(""); setMessage("Historical decision verified. This receipt is not current permission, legal verification, scientific acceptance or authorization to run ML.");
  }
  async function commit(retry = false) {
    const original = retry ? pending.current : draft;
    if (working.current || !original || !access || original.recovery.actorId !== access.actor_user_id || (!retry && unresolved)) return;
    const call = begin(); pending.current = original; retained.current = original.recovery; setRecovery(original.recovery); setUnresolved(true);
    try {
      const result = await parseMlRightsResult(await commitMlRights(original.input, original.recovery.intentSha256, call.signal), original.recovery, true, original.input);
      if (call.active()) accept(result);
    } catch (e) {
      if (!call.active()) return; setPage(null); clearDecision();
      if (e instanceof ApiError && [401, 403].includes(e.status)) fail(e);
      else setMessage("Commit outcome is unknown. Recover the original key and hash. No write is retried automatically; a missing receipt is not proof of rollback.");
    } finally { call.finish(); }
  }
  async function recover(manual = false) {
    if (working.current || !access || manual && unresolved) return;
    const original = manual ? { actorId: access.actor_user_id, requestKey: manualKey, intentSha256: manualHash } : recovery;
    if (!original || !mlRightsKey(original.requestKey) || !mlRightsHash(original.intentSha256)) return;
    const call = begin(); retained.current = original; setRecovery(original); setUnresolved(true); setPage(null); clearDecision();
    try {
      const actor = await current(call.signal); if (!call.active()) return;
      if (actor.actor_user_id !== original.actorId) throw new ApiError(401, null, "Recovery account changed");
      const value = await parseMlRightsResult(await recoverMlRights(original, call.signal), original, true);
      if (!call.active()) return; if (!value.replayed) throw new Error("Invalid recovery"); setAccess(actor); accept(value);
    } catch (e) {
      if (!call.active()) return;
      if (e instanceof ApiError && [401, 403].includes(e.status)) fail(e);
      else setMessage(e instanceof ApiError && e.status === 404 ? "No outcome was observed in this snapshot. The original commit may still be in flight; no rollback is inferred."
        : "Outcome remains unknown. Retain the original request key and intent hash; no new write was sent.");
    } finally { call.finish(); }
  }
  return <div className="min-w-0 space-y-5">
    <header className="space-y-3"><h2 className="text-xl font-semibold">ML source rights</h2>
      <p className="text-sm">Independent review of one exact resource, inventory and private baseline request. Public RPS permissions do not substitute for ML permissions.</p>
      <p className="rounded border border-amber-200 bg-amber-50 p-3 text-sm">No training or run approval is granted here. A document hash is not legal verification. Keep the reviewed evidence resolvable in your approved access-controlled record.</p>
      <button className={button} disabled={busy} onClick={() => void refresh()}>Refresh reviewer access</button>
      {access && <p className="break-all text-xs">Reviewer account: {access.actor_user_id}. Explicit curator and ML rights memberships checked.</p>}
    </header>
    <div aria-live="polite">{busy && <p role="status">Checking the exact private operation…</p>}{message && <p role="alert" className={panel}>{message}</p>}</div>
    {recovery && <section className={panel} aria-label="Unresolved ML rights operation">
      <h3 className="font-semibold">Original operation</h3><p className="text-sm">Keep these references in your approved private record before leaving. Reloading loses the in-memory draft; manual recovery below uses the original account, key and hash.</p>
      <dl className="break-all text-sm"><dt>Original account</dt><dd>{recovery.actorId}</dd><dt>Original request key</dt><dd>{recovery.requestKey}</dd><dt>Intent SHA-256</dt><dd>{recovery.intentSha256}</dd></dl>
      <button className={button} disabled={busy || !access} onClick={() => void recover()}>Check original outcome</button>
      {pending.current && <><p className="text-sm">Explicit retry may perform the original write if it was not committed. The exact decision, key and preview hash are unchanged.</p>
        <button className={button} disabled={busy || !access} onClick={() => void commit(true)}>Retry exact original commit</button></>}
    </section>}
    <section className={panel} aria-label="Exact ML inventory">
      <h3 className="font-semibold">Exact private submission</h3><p className="text-sm">Obtain all three references through the approved private handoff. No global submission directory or source download is provided.</p>
      {([["submission_id", "Submission UUID"], ["submission_sha256", "Submission record SHA-256"], ["inventory_sha256", "Inventory SHA-256"]] as const).map(([key, label]) =>
        <label key={key} className="block text-sm">{label}<input className={field} autoComplete="off" spellCheck={false} maxLength={64} value={query[key]} disabled={locked || !access}
          onChange={e => { setQuery({ ...query, [key]: e.target.value }); setPage(null); clearDecision(); }} /></label>)}
      <button className={button} disabled={locked || !access || !validMlRightsQuery(query)} onClick={() => void load()}>Inspect inventory</button>
      {page && <><p className="text-sm">{page.resource_count.toLocaleString("en-US")} exact resources; showing {page.resources.length.toLocaleString("en-US")}. Heads may change between reads. Counts are not independent scientific support.</p>
        <p className="text-sm">Original input expiry (UTC): {page.input_access_expires_at}. Withdrawal remains possible after input expiry or purge.</p>
        <div className="overflow-x-auto"><table className="w-full text-left text-sm"><caption className="sr-only">Exact ML permission resources</caption>
          <thead><tr><th scope="col">Kind / identity</th><th scope="col">Recorded status</th><th scope="col">Review</th></tr></thead>
          <tbody>{page.resources.map((row, i) => <tr key={row.resource_id} className="border-t border-sage-border">
            <th scope="row" className="max-w-xs break-all p-2 font-normal">{row.kind === "row" ? `${row.entry.table} · ${row.entry.row_id}` : `Artifact · ${row.entry.sha256}`}</th>
            <td className="p-2">{statusLabels[row.recorded_permission_status]}</td><td className="p-2"><button className={button} disabled={locked} onClick={() => { clearDecision(); setSelected(row); }}>Review resource {i + 1}</button></td>
          </tr>)}</tbody></table></div>
        {page.next_after && <button className={button} disabled={locked} onClick={() => void load(page.next_after)}>Next resources</button>}
        <p className="text-sm">Allow recorded does not establish current source validity or permission to execute a run. The owner's separate live check must reconstruct and recheck the full retained input.</p>
      </>}
    </section>
    {selected && <section className={panel} aria-label="Exact ML rights decision">
      <h3 ref={heading} tabIndex={-1} className="scroll-mt-24 font-semibold focus-visible:outline focus-visible:outline-2">Review exact resource</h3><p className="break-all font-mono text-xs">{selected.resource_id}</p>
      <p className="text-sm">Purpose: private baseline evaluation only. Each representation remains distinct; a subject-membership hash is not a standalone row checksum.</p>
      <details><summary>Exact metadata, representations and origins</summary><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(selected.entry, null, 2)}</pre></details>
      <p className="break-all text-sm">Predecessor: {selected.head?.id ?? "None"}. Status at inspection: {statusLabels[selected.recorded_permission_status]}.</p>
      {selected.head && <details><summary>Historical predecessor decision</summary><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(selected.head, null, 2)}</pre></details>}
      <label className="block text-sm">Decision<select className={field} value={choice} disabled={locked} onChange={e => { setChoice(e.target.value as typeof choice); setBasis(""); setEvidence(""); setExpiry(""); edit(); }}>
        <option value="">Choose a decision</option><option value="allow">Record scoped allow</option><option value="deny">Record denial</option><option value="revoke" disabled={selected.head?.decision !== "allow"}>Revoke exact allow</option></select></label>
      <label className="block text-sm">Documented basis<select className={field} value={basis} disabled={locked || !choice} onChange={e => { setBasis(e.target.value); edit(); }}>
        <option value="">Choose the reviewed basis</option>{(choice === "allow" ? ML_RIGHTS_BASES.slice(0, 3) : ML_RIGHTS_BASES.slice(3)).map(value => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}</select></label>
      <label className="block text-sm">Evidence document SHA-256{choice !== "allow" && " (optional)"}<input className={field} maxLength={64} autoComplete="off" spellCheck={false} value={evidence} disabled={locked} onChange={e => { setEvidence(e.target.value); edit(); }} /></label>
      {choice === "allow" && <label className="block text-sm">Allow expiry (UTC Unix seconds)<input className={field} inputMode="numeric" maxLength={16} value={expiry} disabled={locked} onChange={e => { setExpiry(e.target.value); edit(); }} />
        <span className="text-xs">Explicitly choose a future expiry no later than the original input expiry. The database clock is authoritative.</span></label>}
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={reviewed} disabled={locked || !validFields} onChange={e => { setReviewed(e.target.checked); setDraft(null); }} />
        <span>I independently reviewed this exact resource and decision. For an allow, I inspected the documented permission and retained its resolvable evidence. This declaration is not software verification of legal validity.</span></label>
      <button className={button} disabled={locked || !validFields || !reviewed} onClick={() => void preview()}>Preview ML rights decision</button>
    </section>}
    {draft && <section className={panel} aria-label="ML rights preview"><h3 className="font-semibold">Review before committing</h3>
      <p className="text-sm">Rollback-only preview: no new decision committed. Review the account, grants, resource, purpose, evidence, expiry and exact predecessor.</p>
      <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(draft.result.intent, null, 2)}</pre>
      <p className="break-all font-mono text-xs">Intent SHA-256: {draft.recovery.intentSha256}</p>
      <button className={button} disabled={locked} onClick={() => void commit()}>Commit exact ML preview</button>
    </section>}
    {receipt && <section className={panel} aria-label="Historical ML rights receipt"><h3 className="font-semibold">Historical decision receipt</h3>
      <p>Decision: {receipt.intent.decision}. {receipt.replayed ? "Recovered existing record." : "New record committed."}</p>
      <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(receipt.decision, null, 2)}</pre>
      <p className="text-sm">Reinspect the inventory for subsequent review. This historical receipt remains historical after expiry, revocation or membership changes.</p>
    </section>}
    <section className={panel} aria-label="Manual ML rights recovery"><h3 className="font-semibold">Recover an earlier operation</h3>
      <p className="text-sm">Sign in as the original reviewer. Use the rights decision key and intent hash, not the owner's submission key. This performs a private read only.</p>
      <label className="block text-sm">Recovery request key<input className={field} maxLength={120} autoComplete="off" spellCheck={false} value={manualKey} disabled={locked || !access} onChange={e => setManualKey(e.target.value)} /></label>
      <label className="block text-sm">Recovery intent SHA-256<input className={field} maxLength={64} autoComplete="off" spellCheck={false} value={manualHash} disabled={locked || !access} onChange={e => setManualHash(e.target.value)} /></label>
      <button className={button} disabled={locked || !access || !mlRightsKey(manualKey) || !mlRightsHash(manualHash)} onClick={() => void recover(true)}>Recover historical decision</button>
    </section>
  </div>;
}
