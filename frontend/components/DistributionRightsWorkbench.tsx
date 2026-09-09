"use client";

import { useEffect, useRef, useState } from "react";

import { ApiError, distributionRightsAccess, distributionRightsContext, distributionRightsOutcome, distributionRightsPage, distributionRightsPrepare } from "@/lib/api";
import { onAuthChange } from "@/lib/auth-session";
import { knownRightsAccess, knownRightsContext, knownRightsPage, knownRightsResult, RIGHTS_LICENSES, rightsCode, rightsUuid,
  type RightsAccess, type RightsContext, type RightsDependency, type RightsInput, type RightsPage, type RightsRecovery, type RightsResult } from "@/lib/distribution-rights";

const button = "rounded border border-sage-border bg-white px-3 py-2 text-sm text-accent-deep hover:bg-sage-surface disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2";
const input = "min-w-0 w-full rounded border border-sage-border bg-white p-2 text-sm";
const panel = "min-w-0 space-y-3 rounded-lg border border-sage-border bg-white p-4";
type Draft = { request: RightsInput; result: RightsResult; context: RightsContext; recovery: RightsRecovery };

export function DistributionRightsWorkbench() {
  const [access, setAccess] = useState<RightsAccess | null>(null);
  const [packageId, setPackageId] = useState("");
  const [page, setPage] = useState<RightsPage | null>(null);
  const [context, setContext] = useState<RightsContext | null>(null);
  const [decision, setDecision] = useState<"" | "allow" | "revoke">("");
  const [license, setLicense] = useState("");
  const [basis, setBasis] = useState("");
  const [reason, setReason] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [receipt, setReceipt] = useState<RightsResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [unresolved, setUnresolved] = useState(false);
  const [recovery, setRecovery] = useState<RightsRecovery | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const seq = useRef(0), controller = useRef<AbortController | null>(null), mounted = useRef(true);
  const actor = useRef<string | null>(null), pending = useRef<Draft | null>(null), writing = useRef(false);
  // Only an opaque original-account locator survives an auth notification.
  const retained = useRef<RightsRecovery | null>(null);
  const decisionHeading = useRef<HTMLHeadingElement | null>(null);
  const locked = busy || unresolved;
  function clearEvidence() { setPage(null); setContext(null); setDraft(null); setReceipt(null); }
  function begin() {
    const version = ++seq.current; controller.current?.abort();
    const next = new AbortController(); controller.current = next;
    const timer = window.setTimeout(() => next.abort(), 30_000);
    return { signal: next.signal, active: () => mounted.current && seq.current === version,
      finish: () => { window.clearTimeout(timer); if (mounted.current && seq.current === version) setBusy(false); } };
  }
  function clearPrivate() {
    seq.current += 1; controller.current?.abort(); clearEvidence(); setAccess(null); actor.current = null;
    setPackageId(""); setDecision(""); setLicense(""); setBasis(""); setReason("");
    pending.current = null; writing.current = false; setRecovery(null); setBusy(false);
    setUnresolved(retained.current !== null);
  }
  function fail(error: unknown) {
    clearEvidence(); setMessage(error instanceof ApiError && [401, 403].includes(error.status)
      ? "Reviewer access is unavailable. Private data has been cleared. Refresh access to continue."
      : "The response could not be verified. Inspect the exact package again; no success is inferred.");
    if (error instanceof ApiError && [401, 403].includes(error.status)) clearPrivate();
  }
  async function checkAccess(signal: AbortSignal) {
    const value = knownRightsAccess(await distributionRightsAccess(signal));
    if (!value) throw new Error("Invalid reviewer access response");
    if (actor.current !== null && actor.current !== value.actor_user_id) throw new ApiError(401, null, "Session changed");
    return value;
  }
  async function refresh() {
    if (busy) return;
    const call = begin(); setBusy(true); setMessage(null); clearEvidence(); setAccess(null);
    try {
      const value = await checkAccess(call.signal); if (!call.active()) return;
      actor.current = value.actor_user_id; setAccess(value);
      const previous = retained.current;
      setRecovery(previous?.actorId === value.actor_user_id ? previous : null);
      if (previous) setMessage(previous.actorId === value.actor_user_id
        ? "An earlier commit outcome is unknown. Check its original receipt before starting another decision."
        : "An unresolved operation belongs to another account. Return to its original account to recover it.");
    } catch (error) { if (call.active()) fail(error); }
    finally { call.finish(); }
  }
  useEffect(() => {
    mounted.current = true; void refresh();
    const stop = onAuthChange(() => { clearPrivate(); setMessage("Session changed. Private data has been cleared. Refresh reviewer access before continuing."); });
    return () => { mounted.current = false; seq.current += 1; controller.current?.abort(); stop(); };
    // Access is rechecked on every explicit observation; no automatic writes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (!unresolved) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn); return () => window.removeEventListener("beforeunload", warn);
  }, [unresolved]);
  useEffect(() => {
    if (!context) return;
    decisionHeading.current?.focus({ preventScroll: true });
    decisionHeading.current?.scrollIntoView?.({ block: "start" });
  }, [context]);
  function edit() { setDraft(null); setReceipt(null); setMessage(null); }
  async function load(after: string | null = null) {
    if (locked || !rightsUuid(packageId) || !access) return;
    const call = begin(), inventory = after === null ? undefined : page?.inventory_sha256;
    setBusy(true); setContext(null); edit();
    try {
      const current = await checkAccess(call.signal); if (!call.active()) return;
      const value = knownRightsPage(await distributionRightsPage(packageId, after, inventory, call.signal), current, packageId, after, inventory);
      if (!call.active()) return; if (!value) throw new Error("Invalid dependency page");
      setAccess(current); setPage(value);
    } catch (error) { if (call.active()) fail(error); }
    finally { call.finish(); }
  }
  async function inspect(selected: RightsDependency) {
    if (locked || !page) return;
    const call = begin(); setBusy(true); setContext(null); edit(); setDecision(""); setLicense(""); setBasis(""); setReason("");
    try {
      const current = await checkAccess(call.signal); if (!call.active()) return;
      const value = knownRightsContext(await distributionRightsContext(page.package_id, selected.dependency_id, call.signal), current, page, selected);
      if (!call.active()) return; if (!value) throw new Error("Invalid dependency context");
      setAccess(current); setContext(value);
    } catch (error) { if (call.active()) fail(error); }
    finally { call.finish(); }
  }
  async function preview() {
    if (locked || !context || !access || !decision || !license || !rightsCode(basis) || !rightsCode(reason)) return;
    const call = begin(); setBusy(true); edit();
    const request: RightsInput = { request_key: "rights:" + crypto.randomUUID(), decision, license_code: license, basis_code: basis, reason_code: reason,
      expected_package_sha256: context.package_record_sha256, expected_inventory_sha256: context.inventory_sha256,
      expected_dependency_row_sha256: context.dependency.row_sha256, expected_head_id: context.head?.id ?? null, expected_head_sha256: context.head?.record_sha256 ?? null };
    const ref: RightsRecovery = { actorId: access.actor_user_id, packageId: context.package_id, dependencyId: context.dependency.dependency_id,
      requestKey: request.request_key, intentSha256: "" };
    try {
      const value = await knownRightsResult(await distributionRightsPrepare(ref.packageId, ref.dependencyId, { ...request, dry_run: true }, call.signal),
        { ...ref, committed: false, request, grantId: access.actor_grant_id, publicBundleSha256: context.public_bundle_sha256 });
      if (!call.active()) return; if (!value) throw new Error("Invalid rights preview");
      setDraft({ request, result: value, context, recovery: { ...ref, intentSha256: value.intent_sha256 } });
    } catch (error) { if (call.active()) fail(error); }
    finally { call.finish(); }
  }
  function accept(value: RightsResult) {
    clearEvidence(); setReceipt(value); setRecovery(null); setUnresolved(false); pending.current = null; retained.current = null;
    setMessage("A committed historical permission receipt was verified. It does not establish current publication eligibility, legal validity or ML training approval.");
  }
  async function commit(retry = false) {
    const original = retry ? pending.current : draft;
    if (busy || writing.current || !original || !access || original.recovery.actorId !== access.actor_user_id || (!retry && unresolved)) return;
    writing.current = true; pending.current = original; retained.current = original.recovery;
    setRecovery(original.recovery); setUnresolved(true); setBusy(true); setMessage(null);
    const call = begin();
    try {
      const value = await knownRightsResult(await distributionRightsPrepare(original.recovery.packageId, original.recovery.dependencyId,
        { ...original.request, dry_run: false, expected_intent_sha256: original.result.intent_sha256 }, call.signal),
        { ...original.recovery, committed: true, request: original.request, grantId: original.result.intent.actor_grant_id,
          publicBundleSha256: original.context.public_bundle_sha256 });
      if (!call.active()) return; if (!value) throw new Error("Invalid committed receipt"); accept(value);
    } catch (error) {
      if (!call.active()) return; clearEvidence();
      if (error instanceof ApiError && [401, 403].includes(error.status)) { clearPrivate(); setMessage("Session or reviewer access changed. Refresh access to recover the original account's receipt."); }
      else setMessage("Commit outcome is unknown. Check the original receipt; absence is not proof of rollback. No write is retried automatically.");
    } finally { writing.current = false; call.finish(); }
  }
  async function recover() {
    if (busy || !recovery) return;
    const original = recovery, call = begin(); setBusy(true); setMessage(null);
    try {
      const current = await checkAccess(call.signal); if (!call.active()) return;
      if (current.actor_user_id !== original.actorId) throw new ApiError(401, null, "Recovery account changed");
      const value = await knownRightsResult(await distributionRightsOutcome(original, call.signal), { ...original, committed: true });
      if (!call.active()) return; if (!value || !value.replayed) throw new Error("Invalid historical outcome"); setAccess(current); accept(value);
    } catch (error) {
      if (!call.active()) return;
      if (error instanceof ApiError && [401, 403].includes(error.status)) { clearPrivate(); setMessage("Reviewer access changed. Private recovery data has been cleared; refresh under the original account."); }
      else setMessage(error instanceof ApiError && error.status === 404
        ? "No receipt was observed in this snapshot. The original commit may still be in flight; no rollback is inferred."
        : "Outcome remains unknown. Keep the original request key; no new write was sent.");
    } finally { call.finish(); }
  }
  return <div className="min-w-0 space-y-5">
    <header className="space-y-3">
      <h2 className="text-xl font-semibold text-sage-ink">Distribution rights</h2>
      <p className="text-sm text-sage-muted">Review one source dependency of an already registered RPS package. Every decision is scoped to its exact stored version.</p>
      <p className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">A rights statement is not legal verification, package publication, scientific acceptance or ML training approval. Confirm lawful permission through your approved review process.</p>
      <button className={button} disabled={busy} onClick={() => void refresh()}>Refresh reviewer access</button>
    </header>
    <div aria-live="polite">{busy && <p role="status">Checking the exact private operation…</p>}{message && <p role="alert" className="rounded border border-sage-border p-3 text-sm">{message}</p>}</div>
    {recovery && <section className={panel} aria-label="Unresolved rights operation">
      <h3 className="font-semibold">Original operation</h3><p className="break-all font-mono text-sm">{recovery.requestKey}</p>
      <p className="text-sm">Keep this page open. Navigation or reload loses the in-memory recovery and retry details. Retain the original references in your approved private operation record.</p>
      <details><summary className="cursor-pointer text-sm">Original recovery references</summary><dl className="space-y-2 break-all text-sm">
        <dt>Account ID</dt><dd className="font-mono">{recovery.actorId}</dd><dt>Package ID</dt><dd className="font-mono">{recovery.packageId}</dd>
        <dt>Dependency ID</dt><dd className="font-mono">{recovery.dependencyId}</dd><dt>Intent SHA-256</dt><dd className="font-mono">{recovery.intentSha256}</dd></dl></details>
      <button className={button} disabled={busy} onClick={() => void recover()}>Check original outcome</button>
      {pending.current && <><p className="text-sm">An explicit retry may perform the original write if it was not committed. It reuses the identical key, decision and preview pin.</p>
        <button className={button} disabled={busy || !access} onClick={() => void commit(true)}>Retry exact original commit</button></>}
    </section>}
    <section className={panel} aria-label="Registered package">
      <label className="block text-sm">Package UUID<input className={input} value={packageId} disabled={locked || !access} onChange={e => { setPackageId(e.target.value); clearEvidence(); edit(); }} /></label>
      <button className={button} disabled={locked || !access || !rightsUuid(packageId)} onClick={() => void load()}>Load dependencies</button>
      {page && <><p className="text-sm">{page.dependency_count.toLocaleString("en-US")} registered dependencies. This page contains compact identifiers only.</p>
        <ul className="space-y-2">{page.dependencies.map(item => <li key={item.dependency_id} className="min-w-0 rounded border border-sage-border p-3 text-sm">
          <p className="break-all">{item.table} · {item.row_id}</p><p className="break-all font-mono text-xs text-sage-muted">{item.dependency_id}</p>
          <button className={button} disabled={locked} onClick={() => void inspect(item)}>Inspect dependency</button>
        </li>)}</ul>{page.next_after && <button className={button} disabled={locked} onClick={() => void load(page.next_after)}>Next dependencies</button>}</>}
    </section>
    {context && <section className={panel} aria-label="Exact rights decision">
      <h3 ref={decisionHeading} tabIndex={-1} className="scroll-mt-24 font-semibold focus-visible:outline focus-visible:outline-2">Exact dependency</h3><p className="break-all text-sm">{context.dependency.table} · {context.dependency.row_id}</p>
      <p className="text-sm">Permission head: {context.head?.decision ?? "No recorded decision"}. This is not current publication approval.</p>
      <details><summary className="cursor-pointer text-sm">Version pins</summary><dl className="space-y-2 break-all text-sm"><dt>Inventory SHA-256</dt><dd className="font-mono">{context.inventory_sha256}</dd>
        <dt>Dependency row SHA-256</dt><dd className="font-mono">{context.dependency.row_sha256}</dd><dt>Predecessor</dt><dd>{context.head?.id ?? "None"}</dd></dl></details>
      <label className="block text-sm">Decision<select className={input} value={decision} disabled={locked} onChange={e => { const value = e.target.value as typeof decision; setDecision(value); setLicense(value === "revoke" ? context.head?.license_code ?? "" : ""); edit(); }}>
        <option value="">Choose a decision</option><option value="allow">Record scoped permission</option><option value="revoke" disabled={!context.head}>Revoke predecessor permission</option></select></label>
      <label className="block text-sm">License or permission basis<select className={input} value={license} disabled={locked || decision === "revoke"} onChange={e => { setLicense(e.target.value); edit(); }}>
        <option value="">Choose the reviewed basis</option>{RIGHTS_LICENSES.map(value => <option key={value}>{value}</option>)}</select></label>
      {decision === "revoke" && <p className="text-sm">Revocation inherits the predecessor's rights document; it does not issue a new permission.</p>}
      <label className="block text-sm">Basis code<input className={input} value={basis} maxLength={160} disabled={locked} onChange={e => { setBasis(e.target.value); edit(); }} /></label>
      <label className="block text-sm">Reason code<input className={input} value={reason} maxLength={160} disabled={locked} onChange={e => { setReason(e.target.value); edit(); }} /></label>
      <p className="text-sm text-sage-muted">Use approved opaque codes (lowercase letters, digits and underscores). Do not paste source text, credentials or personal review details.</p>
      <button className={button} disabled={locked || !decision || !license || !rightsCode(basis) || !rightsCode(reason)} onClick={() => void preview()}>Preview rights decision</button>
    </section>}
    {draft && <section className={panel} aria-label="Rights preview">
      <h3 className="font-semibold">Review before committing</h3><p className="text-sm">Decision: {draft.request.decision}. No new permission has been committed by this preview.</p>
      <p className="break-all font-mono text-sm">{draft.result.intent_sha256}</p>
      <details><summary className="cursor-pointer text-sm">Fixed rights document{draft.request.decision === "revoke" ? " (inherited)" : ""}</summary>
        <pre className="whitespace-pre-wrap break-all text-sm">{JSON.stringify(draft.result.rights_document, null, 2)}</pre></details>
      <button className={button} disabled={locked} onClick={() => void commit()}>Commit exact preview</button>
    </section>}
    {receipt && <section className={panel} aria-label="Historical permission receipt"><h3 className="font-semibold">Committed historical receipt</h3>
      <p className="text-sm">Decision: {receipt.intent.decision}. {receipt.replayed ? "Recovered existing record." : "New record committed."}</p>
      <dl className="space-y-2 break-all text-sm"><dt>Permission ID</dt><dd className="font-mono">{receipt.permission!.id}</dd><dt>Rights artifact ID</dt><dd className="font-mono">{receipt.artifact!.id}</dd>
        <dt>Intent SHA-256</dt><dd className="font-mono">{receipt.intent_sha256}</dd><dt>Original request key</dt><dd className="font-mono">{receipt.intent.request_key}</dd></dl>
      <p className="text-sm">Canonical rights bytes are retained in immutable permission history. A live artifact can later change; this receipt is not a fresh authorization check.</p>
    </section>}
  </div>;
}
