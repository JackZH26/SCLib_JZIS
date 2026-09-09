"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import { onAuthChange } from "@/lib/auth-session";
import { MaterialDetails } from "@/components/ScientificDiscoveryMatrix";
import { SCIENTIFIC_DISCLAIMER } from "@/lib/discovery-scientific";
import { selectionCode, selectionUUID } from "@/lib/discovery-selection";
import { GOVERNANCE_FAILURE, getCurrentInspection, getGovernanceHeader, getGovernanceOutcome, getOperatorAccess, getReviewPage,
  governanceCanonical, parseCurrentInspection, parseGovernanceHeader, parseGovernanceReceipt, parseOperatorAccess, parseReviewPage,
  postGovernance, prepareGovernanceDraft, readProjectionRights, roleGrant, verifyCompleteHistory,
  type CurrentInspection, type GovernanceDraft, type GovernanceHeader, type GovernanceReceipt, type GovernanceRecovery,
  type GovernanceReview, type OperatorAccess, type ProjectionRight } from "@/lib/discovery-governance";

const button = "min-h-11 rounded-lg border border-sage-border bg-white px-3 py-2 text-sm hover:bg-sage-surface disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent";
const input = "min-h-11 min-w-0 w-full rounded-lg border border-sage-border bg-white p-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent";
const panel = "min-w-0 space-y-4 rounded-xl border border-sage-border bg-white p-4 sm:p-5";
function Pins({ title, value }: { title: string; value: unknown }) {
  return <details className="rounded-lg border border-sage-border p-3"><summary className="min-h-11 cursor-pointer py-2 text-sm">{title}</summary><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(value, null, 2)}</pre></details>;
}
async function withAbort<T>(work: () => Promise<T>, signal: AbortSignal) {
  if (signal.aborted) throw new Error(GOVERNANCE_FAILURE);
  let stop!: () => void;
  const aborted = new Promise<never>((_, reject) => { stop = () => reject(new Error(GOVERNANCE_FAILURE)); });
  signal.addEventListener("abort", stop, { once: true });
  try { return await Promise.race([work(), aborted]); } finally { signal.removeEventListener("abort", stop); }
}
export function DiscoveryGovernanceWorkbench() {
  const [access, setAccess] = useState<OperatorAccess | null>(null), [packageId, setPackageId] = useState("");
  const [header, setHeader] = useState<GovernanceHeader | null>(null), [reviews, setReviews] = useState<GovernanceReview[]>([]);
  const [nextAfter, setNextAfter] = useState<string | null>(null), [historyComplete, setHistoryComplete] = useState(false);
  const [current, setCurrent] = useState<CurrentInspection | null>(null), [expanded, setExpanded] = useState<string | null>(null);
  const [decision, setDecision] = useState<GovernanceDraft["decision"] | "">(""), [reason, setReason] = useState(""), [reviewId, setReviewId] = useState("");
  const [representativeApproved, setRepresentativeApproved] = useState(false), [disclosureApproved, setDisclosureApproved] = useState(false);
  const [rightsFile, setRightsFile] = useState<File | null>(null), [fileEpoch, setFileEpoch] = useState(0), [rights, setRights] = useState<ProjectionRight[] | null>(null);
  const [draft, setDraft] = useState<GovernanceDraft | null>(null), [rehearsal, setRehearsal] = useState<GovernanceReceipt | null>(null);
  const [receipt, setReceipt] = useState<{ result: GovernanceReceipt; original: GovernanceRecovery } | null>(null);
  const [recovery, setRecovery] = useState<GovernanceRecovery | null>(null), [unresolved, setUnresolved] = useState(false);
  const [busy, setBusy] = useState(false), [message, setMessage] = useState("");
  const mounted = useRef(true), epoch = useRef(0), flight = useRef(false), controller = useRef<AbortController | null>(null);
  const retained = useRef<GovernanceRecovery | null>(null), heading = useRef<HTMLHeadingElement | null>(null), detailTrigger = useRef<HTMLButtonElement | null>(null);
  const locked = busy || unresolved || !access;
  function clearPreview() { setDraft(null); setRehearsal(null); setReceipt(null); }
  function clearDecision() {
    setDecision(""); setReason(""); setReviewId(""); setRepresentativeApproved(false); setDisclosureApproved(false);
    setRights(null); setRightsFile(null); setFileEpoch(n => n + 1); clearPreview();
  }
  function clearWork() {
    setHeader(null); setReviews([]); setNextAfter(null); setHistoryComplete(false); setCurrent(null); setExpanded(null); clearDecision();
  }
  function clearPrivate() {
    epoch.current++; controller.current?.abort(); flight.current = false; setBusy(false); setAccess(null); setPackageId(""); clearWork();
    setRecovery(null); setUnresolved(retained.current !== null);
  }
  function begin() {
    if (flight.current) return null;
    flight.current = true; setBusy(true); setMessage(""); const generation = ++epoch.current, next = new AbortController();
    controller.current?.abort(); controller.current = next;
    const timer = window.setTimeout(() => next.abort(), 55_000);
    return { signal: next.signal, active: () => mounted.current && epoch.current === generation,
      live: () => mounted.current && epoch.current === generation && !next.signal.aborted,
      finish: () => { window.clearTimeout(timer); if (mounted.current && epoch.current === generation) { flight.current = false; setBusy(false); } } };
  }
  async function fresh(signal: AbortSignal, original?: OperatorAccess) {
    const result = parseOperatorAccess(await getOperatorAccess(signal));
    if (original && (original.actor_user_id !== result.actor_user_id || governanceCanonical(original.grants) !== governanceCanonical(result.grants))) throw new ApiError(401, null, "Access changed");
    return result;
  }
  function failed(error: unknown) {
    clearWork();
    if (error instanceof ApiError && [401, 403].includes(error.status)) {
      clearPrivate(); setMessage("Operator access changed. Private history, scientific content and draft decisions were cleared. Refresh access.");
    } else setMessage(GOVERNANCE_FAILURE);
  }
  async function refreshAccess() {
    if (flight.current) return; clearPrivate(); const call = begin()!;
    try {
      const a = await fresh(call.signal); if (!call.live()) return; setAccess(a);
      if (retained.current) {
        if (a.actor_user_id === retained.current.actorId) setRecovery(retained.current);
        else setMessage("An unresolved operation belongs to another account. Sign in as the original account; new writes remain locked here.");
      }
    } catch (error) { if (call.active()) failed(error); } finally { call.finish(); }
  }
  useEffect(() => {
    mounted.current = true; void refreshAccess();
    const clear = () => { clearPrivate(); setMessage("Session or page context changed. Private data was cleared. Refresh operator access."); };
    const unsubscribe = onAuthChange(clear);
    const warn = (event: BeforeUnloadEvent) => { if (retained.current) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("pagehide", clear); window.addEventListener("beforeunload", warn);
    return () => { mounted.current = false; epoch.current++; controller.current?.abort(); unsubscribe(); window.removeEventListener("pagehide", clear); window.removeEventListener("beforeunload", warn); };
    // Initial admission only; all workbench requests are explicit thereafter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (draft || receipt) { heading.current?.focus({ preventScroll: true }); heading.current?.scrollIntoView?.({ block: "start" }); }
  }, [draft, receipt]);
  async function inspect() {
    if (locked || !selectionUUID(packageId)) return;
    const call = begin(); if (!call) return; clearWork();
    try {
      const a = await fresh(call.signal, access!); if (!call.live()) return;
      const h = parseGovernanceHeader(await getGovernanceHeader(packageId, call.signal), a, packageId); if (!call.live()) return;
      const page = parseReviewPage(await getReviewPage(h, null, call.signal), a, h, null); if (!call.live()) return;
      if (page.next_after === null) await withAbort(() => verifyCompleteHistory(h, page.reviews), call.signal);
      if (!call.live()) return;
      setAccess(a); setHeader(h); setReviews(page.reviews); setNextAfter(page.next_after); setHistoryComplete(page.next_after === null);
    } catch (error) { if (call.active()) failed(error); } finally { call.finish(); }
  }
  async function nextPage() {
    if (locked || !header || !nextAfter) return;
    const call = begin(); if (!call) return; clearPreview();
    try {
      const a = await fresh(call.signal, access!); if (!call.live()) return;
      const page = parseReviewPage(await getReviewPage(header, nextAfter, call.signal), a, header, nextAfter); if (!call.live()) return;
      const combined = [...reviews, ...page.reviews];
      if (new Set(combined.map(r => r.id)).size !== combined.length || combined.length > header.review_count) throw new Error(GOVERNANCE_FAILURE);
      if (page.next_after === null) await withAbort(() => verifyCompleteHistory(header, combined), call.signal);
      if (!call.live()) return;
      setReviews(combined); setNextAfter(page.next_after); setHistoryComplete(page.next_after === null);
    } catch (error) { if (call.active()) failed(error); } finally { call.finish(); }
  }
  async function unchanged(a: OperatorAccess, h: GovernanceHeader, signal: AbortSignal) {
    const latest = parseGovernanceHeader(await getGovernanceHeader(h.package.id, signal), a, h.package.id);
    if (latest.history_sha256 !== h.history_sha256) throw new ApiError(409, null, "History changed");
  }
  async function inspectCurrent() {
    if (locked || !header) return;
    const call = begin(); if (!call) return;
    let historyChecked = false;
    setCurrent(null); setExpanded(null); clearDecision();
    try {
      const a = await fresh(call.signal, access!); if (!call.live()) return;
      await unchanged(a, header, call.signal); if (!call.live()) return;
      historyChecked = true;
      const raw = await getCurrentInspection(header.package.id, call.signal); if (!call.live()) return;
      const value = await withAbort(() => parseCurrentInspection(raw, header), call.signal); if (!call.live()) return;
      setCurrent(value);
    } catch (error) {
      if (!call.active()) return;
      if (!historyChecked || error instanceof ApiError && [401, 403].includes(error.status)) failed(error);
      else setMessage("Current scientific inspection is unavailable or changed. Scientific content was cleared. Recorded metadata remains historical only; protective rejection or withdrawal can still be considered.");
    } finally { call.finish(); }
  }
  function edit(change: () => void) { if (locked || flight.current) return; clearPreview(); setMessage(""); change(); }
  async function inspectRights() {
    if (locked || !current || !rightsFile || decision !== "approve") return;
    const call = begin(); if (!call) return; setRights(null); setRepresentativeApproved(false); setDisclosureApproved(false); clearPreview();
    try {
      const result = await withAbort(() => readProjectionRights(rightsFile, current.rights_targets), call.signal);
      if (call.live()) setRights(result);
    } catch { if (call.active()) setMessage("The rights file must contain exactly every target, sorted uniquely, with an explicit permitted license and basis code. No rights were inferred or uploaded."); }
    finally { call.finish(); }
  }
  const chosenReview = reviews.find(r => r.id === reviewId) ?? null;
  const independent = !!access && !!header && access.actor_user_id !== header.package.actor_user_id;
  const canReview = independent && !!access && !!roleGrant(access, "reviewer");
  const canAct = independent && !!access && !!roleGrant(access, "publisher");
  const positive = decision === "approve" || decision === "publish";
  const canPreview = !!header && selectionCode(reason) && !!decision && (!positive || !!current && historyComplete)
    && (decision === "approve" ? canReview && !!rights && representativeApproved && disclosureApproved
      : decision === "reject" ? canReview : canAct && !!chosenReview && chosenReview.decision === "approve" && chosenReview.actor_user_id !== access!.actor_user_id
        && (decision === "withdraw" ? !header.has_withdrawal : !header.has_rejection && !header.has_withdrawal && header.actions.length === 0
          && !!current?.payload.rows.some(r => r.cells.some(c => c.observations.some(o => o.scientific_scope_accepted)))));
  async function preview() {
    if (locked || !canPreview || !header || !decision) return;
    const call = begin(); if (!call) return; clearPreview();
    try {
      const a = await fresh(call.signal, access!); if (!call.live()) return;
      await unchanged(a, header, call.signal); if (!call.live()) return;
      const next = await withAbort(() => prepareGovernanceDraft({ access: a, header, decision, reasonCode: reason, rights: rights ?? [],
        representativeApproved, disclosureApproved, review: chosenReview, current, historyComplete, requestKey: `browser-governance:${crypto.randomUUID()}` }), call.signal);
      if (!call.live()) return;
      const raw = await postGovernance(next, false, call.signal); if (!call.live()) return;
      const verified = parseGovernanceReceipt(raw, next.recovery, false); setDraft(next); setRehearsal(verified);
    } catch (error) { if (call.active()) failed(error); } finally { call.finish(); }
  }
  async function commit() {
    if (locked || !draft || !rehearsal || !header) return;
    const call = begin(); if (!call) return; const original = draft; let submitted = false;
    try {
      const a = await fresh(call.signal, access!); if (!call.live()) return;
      if (roleGrant(a, original.recovery.operation === "review" ? "reviewer" : "publisher") !== original.grantId) throw new ApiError(401, null, "Grant changed");
      await unchanged(a, header, call.signal); if (!call.live()) return;
      retained.current = original.recovery; setRecovery(original.recovery); setUnresolved(true); submitted = true;
      const raw = await postGovernance(original, true, call.signal); if (!call.live()) return;
      const result = parseGovernanceReceipt(raw, original.recovery, true);
      clearWork(); retained.current = null; setRecovery(null); setUnresolved(false); setReceipt({ result, original: original.recovery });
      setMessage("Exact governance operation committed. Inspect the recorded history again; this receipt is not a current scientific or public authorization.");
    } catch (error) {
      if (!call.active()) return;
      if (!submitted) failed(error);
      else {
        clearWork(); setPackageId("");
        if (error instanceof ApiError && [401, 403].includes(error.status)) clearPrivate();
        setMessage("Operation outcome is unknown. Private drafts were cleared. Check the original request; an error or absent receipt does not prove rollback. No write is retried automatically.");
      }
    } finally { call.finish(); }
  }
  async function recover() {
    if (flight.current || !recovery) return;
    const original = recovery, call = begin()!;
    try {
      const a = await fresh(call.signal); if (!call.live()) return;
      if (a.actor_user_id !== original.actorId || !roleGrant(a, original.operation === "review" ? "reviewer" : "publisher")) throw new ApiError(401, null, "Original role required");
      const raw = await getGovernanceOutcome(original, call.signal); if (!call.live()) return;
      const result = parseGovernanceReceipt(raw, original, true, true);
      clearWork(); retained.current = null; setRecovery(null); setUnresolved(false); setReceipt({ result, original }); setAccess(a);
      setMessage("Original operation recovered. Historical durability does not establish current publication eligibility.");
    } catch (error) {
      if (!call.active()) return;
      if (error instanceof ApiError && [401, 403].includes(error.status)) failed(error);
      else setMessage(error instanceof ApiError && error.status === 404 ? "No original outcome was visible in this snapshot. The write may still be in flight; no rollback or safe retry is inferred." : "The original outcome remains unverified. No write was sent.");
    } finally { call.finish(); }
  }
  const detail = current?.payload.rows.find(r => r.material.row_id === expanded);
  return <div className="min-w-0 space-y-5">
    <header className="space-y-3"><h2 className="text-xl font-semibold">Discovery governance</h2>
      <p className="text-sm text-sage-muted">Independent disclosure review and publication actions for an exact registered scientific projection.</p>
      <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">Recorded history is not current publication eligibility. Any rejection continues to hold the package; a later approval does not override it. Withdrawal is not a reversible visibility toggle.</p>
      <p className="text-sm">{SCIENTIFIC_DISCLAIMER}</p><button className={button} disabled={busy} onClick={() => void refreshAccess()}>Refresh operator access</button>
      {access && <p className="text-sm">Current explicit roles: {access.grants.map(g => g.role).join(", ")}. Package-specific account separation is still required.</p>}
    </header>
    <div aria-live="polite">{busy && <p role="status">Verifying the exact governance operation…</p>}{message && <p role="alert" className="rounded-lg border border-sage-border p-3 text-sm">{message}</p>}</div>
    {recovery && <section className={panel} aria-label="Original governance recovery"><h3 className="font-semibold">Original operation request</h3>
      <p className="text-sm">Keep this page open. Navigation or reload loses this in-memory locator. Retain these opaque references in your approved private operation record; no private draft is saved in browser storage.</p>
      <pre className="overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(recovery, null, 2)}</pre>
      <button className={button} disabled={busy} onClick={() => void recover()}>Check original outcome</button><p className="text-sm">Read only. Same-account regrant may recover; no new request key, automatic retry or rollback inference.</p>
    </section>}
    <section className={panel} aria-label="Inspect registered projection"><h3 className="font-semibold">1. Inspect recorded governance</h3>
      <label className="block text-sm">Projection package ID<input className={input} value={packageId} maxLength={36} disabled={locked} onChange={e => edit(() => { setPackageId(e.target.value); clearWork(); })} /></label>
      <button className={button} disabled={locked || !selectionUUID(packageId)} onClick={() => void inspect()}>Inspect governance history</button>
      <p className="text-sm text-sage-muted">Use a registered projection package ID, not its original distribution package ID. History does not load retained scientific or rights text.</p>
    </section>
    {header && <section className={panel} aria-label="Recorded governance history"><h3 className="font-semibold">Recorded package and decisions</h3>
      <p className="text-sm">{header.review_count.toLocaleString("en-US")} recorded reviews · {header.rejection_count.toLocaleString("en-US")} rejections · {header.has_withdrawal ? "Withdrawal recorded" : "No withdrawal recorded"}. Current publication eligibility: not checked.</p>
      <Pins title="Exact package and historical author pins" value={header.package} />
      <p className="break-all text-xs">History SHA-256: {header.history_sha256}</p>
      <h4 className="font-medium">Complete recorded action inventory</h4>
      {header.actions.length === 0 ? <p className="text-sm">No publish or withdraw action recorded.</p> : header.actions.map(a => <Pins key={a.id} title={`${a.kind} · ${new Date(a.created_at).toLocaleString("en-US", { timeZone: "UTC" })} UTC`} value={a} />)}
      <h4 className="font-medium">Review history · {reviews.length.toLocaleString("en-US")} of {header.review_count.toLocaleString("en-US")} loaded</h4>
      <p className="text-sm text-sage-muted">Chronological append-only records, not a latest-approval head. Account and grant IDs below describe the historical record; they do not assert that those grants remain active.</p>
      {reviews.map(r => <Pins key={r.id} title={`${r.decision} · ${r.id} · ${new Date(r.created_at).toLocaleString("en-US", { timeZone: "UTC" })} UTC`} value={r} />)}
      {nextAfter && <button className={button} disabled={locked} onClick={() => void nextPage()}>Load next review page</button>}
      <p className="text-sm">{historyComplete ? "Complete recorded history verified for this snapshot." : "History is partial. Positive decisions require the complete pinned history."}</p>
      <button className={button} disabled={locked} onClick={() => void inspectCurrent()}>Inspect current scientific content</button>
      <p className="text-sm text-sage-muted">Scientific content is checked separately. A source hold may make it unavailable while these historical references remain readable for protective decisions.</p>
    </section>}
    {current && <section className={panel} aria-label="Current scientific inspection"><h3 className="font-semibold">Current reconstruction at the last read</h3>
      <p className="text-sm">Inspect every selected state, scientific cell and alternative action before a positive decision. This read is not ongoing authorization, scientific approval or ML admission. Compare policy scores only within the same frozen campaign, budget, policy, release and eligible role / rank group.</p>
      <div className="flex flex-wrap gap-2">{current.payload.rows.map(r => <button key={r.material.row_id} className={button} aria-expanded={expanded === r.material.row_id} onClick={e => { detailTrigger.current = e.currentTarget; setExpanded(r.material.row_id); }}>Inspect {r.assessment.formula}</button>)}</div>
      {detail && <MaterialDetails row={detail} prepared close={() => { setExpanded(null); detailTrigger.current?.focus(); }} />}
      <Pins title={`Complete new-scope rights targets (${current.rights_targets.length.toLocaleString("en-US")})`} value={current.rights_targets} />
    </section>}
    {header && <section className={panel} aria-label="Explicit governance decision"><h3 className="font-semibold">2. Prepare an independent decision</h3>
      <label className="block text-sm">Operation<select className={input} disabled={locked} value={decision} onChange={e => edit(() => { clearDecision(); setDecision(e.target.value as typeof decision); })}>
        <option value="">Choose an operation explicitly</option><option value="approve" disabled={!canReview}>Approve selection and disclosure</option><option value="reject" disabled={!canReview}>Reject this projection</option>
        <option value="publish" disabled={!canAct}>Publish using an exact approved review</option><option value="withdraw" disabled={!canAct}>Withdraw using an exact approved review</option>
      </select></label>
      <p className="text-sm text-sage-muted">Review requires an account distinct from the curator. Publication and withdrawal require a third account distinct from curator and selected reviewer. Legacy admin flags do not grant these roles.</p>
      {(decision === "reject" || decision === "withdraw") && <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm">This creates a durable protective record. The present model has no rejection override or withdrawal reversal. It does not require current positive source eligibility.</p>}
      {(decision === "publish" || decision === "withdraw") && <label className="block text-sm">Exact approved review<select className={input} value={reviewId} disabled={locked} onChange={e => edit(() => setReviewId(e.target.value))}>
        <option value="">Choose a recorded approval explicitly</option>{reviews.filter(r => r.decision === "approve").map(r => <option key={r.id} value={r.id} disabled={r.actor_user_id === access?.actor_user_id}>{r.id} · historical reviewer {r.actor_user_id}</option>)}
      </select></label>}
      {decision === "approve" && <div className="space-y-3">
        <p className="text-sm">New scope: discovery_scientific_projection. Old RPS distribution permissions are not automatically inherited. Rights assertions are human decisions, not scientific evidence or software-generated legal conclusions.</p>
        <label className="block text-sm">Complete rights JSON file<input key={fileEpoch} type="file" className={input} accept="application/json,.json" disabled={locked || !current} onChange={e => edit(() => { setRightsFile(e.target.files?.[0] ?? null); setRights(null); setRepresentativeApproved(false); setDisclosureApproved(false); })} /></label>
        <p className="text-sm text-sage-muted">A UTF-8 JSON array, up to 8 MiB, with every target in dependency_id order. Each row needs dependency_id, row_sha256, license_code and basis_code. No license or permission is selected by default. Choosing or checking the file does not upload it.</p>
        <p className="text-xs text-sage-muted">Permitted license codes: CC0-1.0, CC-BY-4.0, CC-BY-SA-4.0, permission-on-file.</p>
        <button className={button} disabled={locked || !current || !rightsFile} onClick={() => void inspectRights()}>Check complete rights file locally</button>
        {rights && <Pins title={`${rights.length.toLocaleString("en-US")} of ${current!.rights_targets.length.toLocaleString("en-US")} explicit rights assertions checked`} value={rights} />}
        <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" disabled={locked || !rights} checked={representativeApproved} onChange={e => edit(() => setRepresentativeApproved(e.target.checked))} />I approve this exact representative selection.</label>
        <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" disabled={locked || !rights} checked={disclosureApproved} onChange={e => edit(() => setDisclosureApproved(e.target.checked))} />I approve disclosure under the complete new-scope rights assertions.</label>
      </div>}
      <label className="block text-sm">Decision reason code<input className={input} disabled={locked || !decision} value={reason} maxLength={160} onChange={e => edit(() => setReason(e.target.value))} /></label>
      <p className="text-xs text-sage-muted">Use a lowercase code starting with a letter, with letters, digits or underscores. Do not paste private source text.</p>
      {positive && (!current || !historyComplete) && <p className="text-sm">Load the complete pinned history and inspect current scientific content before a positive decision.</p>}
      {decision === "publish" && (header.has_rejection || header.has_withdrawal) && <p className="text-sm">This recorded rejection or withdrawal prevents publication; another approval cannot clear it.</p>}
      <button className={button} disabled={locked || !canPreview} onClick={() => void preview()}>Run decision rehearsal</button>
    </section>}
    {draft && rehearsal && <section className={panel} aria-label="Native governance rehearsal"><h3 ref={heading} tabIndex={-1} className="scroll-mt-24 font-semibold">3. Native rehearsal verified · {draft.decision}</h3>
      <p className="text-sm">No commit was performed. Inspect the exact command and original-request references. Editing any decision invalidates this rehearsal. Its provisional record ID need not equal the final committed ID.</p>
      <Pins title="Exact command reviewed in the native rehearsal" value={JSON.parse(draft.previewJSON)} /><Pins title="Original request pins" value={draft.recovery} />
      <button className={button} disabled={locked} onClick={() => void commit()}>Commit exact decision</button>
    </section>}
    {receipt && <section className={panel} aria-label="Verified governance receipt"><h3 ref={heading} tabIndex={-1} className="scroll-mt-24 font-semibold">Exact operation receipt</h3>
      <p className="text-sm">Outer transaction commit verified. The native inner committed flag is not the durability boundary. Scientific and public eligibility require separate current checks.</p>
      <Pins title="Recorded result and original operation locator" value={receipt} />
    </section>}
    <p className="text-sm text-sage-muted">Representative preparation remains in <Link className="text-accent-deep underline" href="/dashboard/research/discovery">Discovery selection</Link>; per-property scientific adjudication remains in <Link className="text-accent-deep underline" href="/dashboard/research/review">Scientific evidence</Link>.</p>
  </div>;
}
