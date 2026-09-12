"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import { onAuthChange } from "@/lib/auth-session";
import { MlRunEvidencePanel } from "./MlRunEvidencePanel";
import { importDigest } from "@/lib/scientific-imports";
import { checkRun, commitRun, getRunAccess, inspectRunContext, inspectRunPlan, parseRunAccess, parseRunContext,
  parseRunInspection, parseRunReadiness, parseRunResult, previewRun, recoverRun, runHash, runIntent, runKey,
  validPlanRef, validRunBudget, validSubmissionRef, validRunEvidenceText, runEvidenceDigest,
  type PlanRef, type RunActor, type RunContext, type RunDecisionInput, type RunInput, type RunInspection, type RunKind,
  type RunPlan, type RunPlanInput, type RunReadiness, type RunRecovery, type RunResult, type SubmissionRef } from "@/lib/ml-use-runs";

const button = "rounded border border-sage-border bg-white px-3 py-2 text-sm text-accent-deep hover:bg-sage-surface disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2";
const field = "min-w-0 w-full rounded border border-sage-border bg-white p-2 text-sm";
const panel = "min-w-0 space-y-3 rounded-lg border border-sage-border bg-white p-4";
const emptySubmission: SubmissionRef = { submission_id: "", submission_sha256: "", inventory_sha256: "" };
const emptyPlan: PlanRef = { plan_id: "", plan_sha256: "" };
type Draft = { input: RunInput; result: RunResult; recovery: RunRecovery };
const labels = { unreviewed: "Not reviewed", conditional_approval_recorded: "Conditional approval recorded", denied: "Denied",
  revoked: "Revoked", expired: "Expired", approver_unavailable: "Original approver unavailable", evidence_unavailable: "Review evidence unavailable" };
const numeric = (v: string) => /^[1-9]\d{0,15}$/.test(v) && Number.isSafeInteger(Number(v));

function Metadata({ value }: { value: RunContext | RunPlan }) {
  return <div className="space-y-3">
    <dl className="grid min-w-0 gap-x-4 gap-y-1 break-all text-xs sm:grid-cols-[12rem_1fr]">
      {([["submission_id", "Submission"], ["submission_sha256", "Submission hash"], ["inventory_sha256", "Inventory hash"],
        ["prepared_sha256", "Prepared input hash"], ["task_sha256", "Task hash"], ["config_sha256", "Configuration hash"],
        ["package_sha256", "Dataset package hash"], ["implementation_sha256", "Selected source hash"], ["runtime_sha256", "Observed host hash"]] as const).map(([key, label]) =>
        <div key={key} className="contents"><dt className="font-semibold">{label}</dt><dd className="font-mono">{value[key]}</dd></div>)}
    </dl>
    <p className="text-sm">Private CPU baseline evaluation only. Source and host hashes are observations, not installed-dependency, loaded-code or execution-image attestation.</p>
    <details><summary>Recorded source and host documents</summary>
      <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all text-xs">{value.implementation_json}{"\n"}{value.runtime_json}</pre></details>
  </div>;
}

export function MlRunsWorkbench() {
  const [kind, setKind] = useState<RunKind>("plan"), [access, setAccess] = useState<RunActor | null>(null);
  const [submission, setSubmission] = useState<SubmissionRef>(emptySubmission), [planRef, setPlanRef] = useState<PlanRef>(emptyPlan);
  const [context, setContext] = useState<RunContext | null>(null), [inspection, setInspection] = useState<RunInspection | null>(null);
  const [knownPlan, setKnownPlan] = useState<RunPlan | null>(null), [readiness, setReadiness] = useState<RunReadiness | null>(null);
  const [cpu, setCpu] = useState(""), [wall, setWall] = useState(""), [memory, setMemory] = useState("");
  const [choice, setChoice] = useState<"" | RunDecisionInput["decision"]>(""), [reason, setReason] = useState("");
  const [evidence, setEvidence] = useState(""), [expiry, setExpiry] = useState(""), [confirmed, setConfirmed] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null), [receipt, setReceipt] = useState<RunResult | null>(null);
  const [busy, setBusy] = useState(false), [unresolved, setUnresolved] = useState(false), [message, setMessage] = useState<string | null>(null);
  const [recovery, setRecovery] = useState<RunRecovery | null>(null), [manualKey, setManualKey] = useState(""), [manualHash, setManualHash] = useState("");
  const serial = useRef(0), working = useRef(false), mounted = useRef(true), controller = useRef<AbortController | null>(null);
  const identity = useRef<string | null>(null), pending = useRef<Draft | null>(null), retained = useRef<RunRecovery | null>(null);
  const heading = useRef<HTMLHeadingElement | null>(null);
  const locked = busy || unresolved;
  function clearViews() { setContext(null); setInspection(null); setReadiness(null); setKnownPlan(null); setDraft(null); setReceipt(null); setConfirmed(false); }
  function clearPrivate() {
    serial.current++; controller.current?.abort(); working.current = false; setBusy(false); setAccess(null); identity.current = null;
    clearViews(); setSubmission(emptySubmission); setPlanRef(emptyPlan); setCpu(""); setWall(""); setMemory(""); setChoice(""); setReason("");
    setEvidence(""); setExpiry(""); pending.current = null; setRecovery(null); setManualKey(""); setManualHash(""); setUnresolved(retained.current !== null);
  }
  function begin() {
    working.current = true; setBusy(true); setMessage(null); const version = ++serial.current;
    controller.current?.abort(); const next = new AbortController(); controller.current = next;
    return { signal: next.signal, active: () => mounted.current && serial.current === version,
      finish: () => { if (mounted.current && serial.current === version) { working.current = false; setBusy(false); } } };
  }
  function fail(error: unknown) {
    clearViews();
    if (error instanceof ApiError && [401, 403].includes(error.status)) {
      clearPrivate(); setMessage("Access changed. Private details were cleared. Refresh access under the original account.");
    } else setMessage(error instanceof ApiError && error.status === 404
      ? "The exact private record or retained input is unavailable. No successful operation or execution permission is inferred."
      : "The response could not be verified. Reload the exact context; no success or execution permission is inferred.");
  }
  async function current(signal: AbortSignal) {
    const actor = parseRunAccess(await getRunAccess(kind, signal), kind);
    if (identity.current !== null && actor.actor_user_id !== identity.current) throw new ApiError(401, null, "Session changed");
    return actor;
  }
  async function refresh() {
    if (working.current) return; const call = begin(); setAccess(null); clearViews();
    try {
      const actor = await current(call.signal); if (!call.active()) return;
      identity.current = actor.actor_user_id; setAccess(actor);
      const original = retained.current; setRecovery(original?.actorId === actor.actor_user_id && original.kind === kind ? original : null);
      if (original) setMessage(original.actorId === actor.actor_user_id ? "Recover the original outcome before making another change."
        : "An unresolved operation belongs to another account. Return to its original account to recover it.");
    } catch (e) { if (call.active()) fail(e); } finally { call.finish(); }
  }
  useEffect(() => {
    mounted.current = true; void refresh();
    const stop = onAuthChange(() => { clearPrivate(); setMessage("Session changed. Refresh access before continuing."); });
    return () => { mounted.current = false; serial.current++; controller.current?.abort(); working.current = false; stop(); };
    // Role selection checks access, never starts a write or readiness worker.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind]);
  useEffect(() => { if (context || inspection) { heading.current?.focus({ preventScroll: true }); heading.current?.scrollIntoView({ block: "start" }); } }, [context, inspection]);
  useEffect(() => { if (!unresolved) return; const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn); return () => window.removeEventListener("beforeunload", warn); }, [unresolved]);
  function edit() { setDraft(null); setReceipt(null); setReadiness(null); setConfirmed(false); setMessage(null); }
  async function load() {
    if (working.current || unresolved || !access || (kind === "plan" ? !validSubmissionRef(submission) : !validPlanRef(planRef))) return;
    const call = begin(), query = { ...submission }, target = { ...planRef }; clearViews(); setChoice(""); setReason(""); setEvidence(""); setExpiry("");
    try {
      const actor = await current(call.signal); if (!call.active()) return;
      if (kind === "plan") {
        const value = await parseRunContext(await inspectRunContext(query, call.signal), actor, query);
        if (!call.active()) return; setContext(value);
      } else {
        const value = await parseRunInspection(await inspectRunPlan(target, call.signal), actor, target);
        if (!call.active()) return; setInspection(value);
      }
      setAccess(actor);
    } catch (e) { if (call.active()) fail(e); } finally { call.finish(); }
  }
  const budget = { cpu_seconds: Number(cpu), wall_seconds: Number(wall), memory_mib: Number(memory) };
  const validBudget = numeric(cpu) && numeric(wall) && numeric(memory) && validRunBudget(budget);
  const validDecision = !!choice && /^[a-z][a-z0-9_]{0,159}$/.test(reason)
    && (choice !== "revoke" || inspection?.head?.decision === "approve")
    && (choice !== "approve" || validRunEvidenceText(evidence) && numeric(expiry) && Number(expiry) > Date.now() / 1000
      && !!inspection && Number(expiry) <= Date.parse(inspection.input_access_expires_at) / 1000);
  const valid = kind === "plan" ? !!context && validBudget : !!inspection && validDecision;
  async function preview() {
    if (working.current || unresolved || !access || !valid || !confirmed) return;
    const call = begin(); setDraft(null); setReceipt(null); setReadiness(null);
    try {
      const actor = await current(call.signal); if (!call.active()) return;
      if (actor.role_grant_id !== access.role_grant_id || actor.curator_grant_id !== access.curator_grant_id) throw new Error("Membership changed");
      const requestKey = "ml-run:" + crypto.randomUUID(); let input: RunInput;
      if (kind === "plan" && context) {
        if (actor.role_grant_id !== context.requester_grant_id || actor.curator_grant_id !== context.curator_grant_id) throw new Error("Context changed");
        input = { submission_id: context.submission_id, submission_sha256: context.submission_sha256, inventory_sha256: context.inventory_sha256,
          prepared_sha256: context.prepared_sha256, task_sha256: context.task_sha256, config_sha256: context.config_sha256, package_sha256: context.package_sha256,
          implementation_sha256: context.implementation_sha256, runtime_sha256: context.runtime_sha256, requester_grant_id: actor.role_grant_id,
          curator_grant_id: actor.curator_grant_id, request_key: requestKey, ...budget } as RunPlanInput;
      } else if (inspection && choice) input = { plan_id: inspection.plan.id, plan_sha256: inspection.plan.record_sha256,
        approver_grant_id: actor.role_grant_id, curator_grant_id: actor.curator_grant_id, request_key: requestKey, decision: choice,
        reason_code: reason, evidence_sha256: choice === "approve" ? await runEvidenceDigest(evidence) : null,
        evidence_text: choice === "approve" ? evidence : null, expires_epoch: choice === "approve" ? Number(expiry) : null,
        supersedes_id: inspection.head?.id ?? null, supersedes_sha256: inspection.head?.record_sha256 ?? null } as RunDecisionInput;
      else throw new Error("Context unavailable");
      const ref: RunRecovery = { kind, actorId: actor.actor_user_id, requestKey, intentSha256: await importDigest(runIntent(kind, input, actor.actor_user_id)) };
      if (!call.active()) return;
      const result = await parseRunResult(await previewRun(kind, input, call.signal), ref, false, input);
      if (call.active()) { setAccess(actor); setDraft({ input, result, recovery: ref }); }
    } catch (e) { if (call.active()) fail(e); } finally { call.finish(); }
  }
  function accept(result: RunResult) {
    clearViews(); setEvidence(""); setReceipt(result); pending.current = null; retained.current = null; setRecovery(null); setUnresolved(false); setManualKey(""); setManualHash("");
    if (result.kind === "plan" && result.record) {
      const plan = result.record as RunPlan; setKnownPlan(plan); setPlanRef({ plan_id: plan.id, plan_sha256: plan.record_sha256 });
    }
    setMessage("Historical record verified. This is not current source permission, scientific acceptance or authorization to execute. No model was started.");
  }
  async function commit(retry = false) {
    const original = retry ? pending.current : draft;
    if (working.current || !original || !access || original.recovery.actorId !== access.actor_user_id || original.recovery.kind !== kind || !retry && unresolved) return;
    const call = begin(); pending.current = original; retained.current = original.recovery; setRecovery(original.recovery); setUnresolved(true);
    try {
      const result = await parseRunResult(await commitRun(kind, original.input, original.recovery.intentSha256, call.signal), original.recovery, true, original.input);
      if (call.active()) accept(result);
    } catch (e) { if (!call.active()) return; clearViews();
      if (e instanceof ApiError && [401, 403].includes(e.status)) fail(e);
      else setMessage("Commit outcome is unknown. Recover the original key and hash. No automatic retry is made; a missing receipt is not proof of rollback.");
    } finally { call.finish(); }
  }
  async function recover(manual = false) {
    if (working.current || !access || manual && unresolved) return;
    const original: RunRecovery | null = manual ? { kind, actorId: access.actor_user_id, requestKey: manualKey, intentSha256: manualHash } : recovery;
    if (!original || !runKey(original.requestKey) || !runHash(original.intentSha256)) return;
    const call = begin(); retained.current = original; setRecovery(original); setUnresolved(true); clearViews();
    try {
      const actor = await current(call.signal); if (!call.active()) return;
      if (actor.actor_user_id !== original.actorId || actor.kind !== original.kind) throw new ApiError(401, null, "Recovery identity changed");
      const result = await parseRunResult(await recoverRun(original, call.signal), original, true);
      if (!call.active()) return; if (!result.replayed) throw new Error("Invalid recovery"); setAccess(actor); accept(result);
    } catch (e) { if (!call.active()) return;
      if (e instanceof ApiError && [401, 403].includes(e.status)) fail(e);
      else setMessage(e instanceof ApiError && e.status === 404 ? "No outcome was observed in this snapshot. The original transaction may still be in flight; no rollback is inferred."
        : "Outcome remains unknown. Retain the original references; no new write was sent.");
    } finally { call.finish(); }
  }
  async function check() {
    if (working.current || unresolved || !access || kind !== "plan" || !validPlanRef(planRef)) return;
    const call = begin(), query = { ...planRef }, plan = knownPlan ?? undefined; setReadiness(null);
    try {
      const actor = await current(call.signal); if (!call.active()) return;
      const result = await parseRunReadiness(await checkRun(query, call.signal), actor, query, plan);
      if (call.active()) { setAccess(actor); setReadiness(result); }
    } catch (e) { if (call.active()) fail(e); } finally { call.finish(); }
  }
  return <div className="min-w-0 space-y-5">
    <header className="space-y-3"><h2 className="text-xl font-semibold">ML run plans</h2>
      <p className="text-sm">Request an exact private baseline plan, obtain independent conditional review, and check current prerequisites.</p>
      <p className="rounded border border-amber-200 bg-amber-50 p-3 text-sm">Execution remains disabled. A recorded approval is not source permission, scientific acceptance, reserved resources or a licence to train. No model starts from this page.</p>
      <label className="block text-sm">Workflow role<select className={field} value={kind} disabled={locked} onChange={e => { clearPrivate(); setKind(e.target.value as RunKind); }}>
        <option value="plan">Request a run plan</option><option value="decision">Independent run approval</option></select></label>
      <p className="text-xs">Selecting a role checks existing access; it does not grant membership. Reviewers must use a different account from the original requester.</p>
      <button className={button} disabled={busy} onClick={() => void refresh()}>Refresh workflow access</button>
      {access && <p className="break-all text-xs">Current account: {access.actor_user_id}. Explicit curator and {kind === "plan" ? "requester" : "run approver"} memberships checked.</p>}
    </header>
    <div aria-live="polite">{busy && <p role="status">Checking the exact private operation…</p>}{message && <p role="alert" className={panel}>{message}</p>}</div>
    {recovery && <section className={panel} aria-label="Unresolved run operation"><h3 className="font-semibold">Original operation</h3>
      <p className="text-sm">Keep these references in your approved private log. Reloading loses the draft. Recovery requires the original account and operation type.</p>
      <dl className="break-all text-sm"><dt>Operation type</dt><dd>{recovery.kind}</dd><dt>Original account</dt><dd>{recovery.actorId}</dd>
        <dt>Original request key</dt><dd>{recovery.requestKey}</dd><dt>Original intent SHA-256</dt><dd>{recovery.intentSha256}</dd></dl>
      <button className={button} disabled={busy || !access} onClick={() => void recover()}>Check original run outcome</button>
      {pending.current && <button className={button} disabled={busy || !access} onClick={() => void commit(true)}>Retry identical original run write</button>}
    </section>}
    {kind === "plan" && <section className={panel} aria-label="Owner submission context"><h3 className="font-semibold">Exact retained submission</h3>
      <p className="text-sm">Use the original private submission handoff. No global directory or source download is provided.</p>
      {([["submission_id", "Submission UUID"], ["submission_sha256", "Submission record SHA-256"], ["inventory_sha256", "Inventory SHA-256"]] as const).map(([key, label]) =>
        <label key={key} className="block text-sm">{label}<input className={field} value={submission[key]} maxLength={64} spellCheck={false} autoComplete="off" disabled={locked || !access}
          onChange={e => { setSubmission({ ...submission, [key]: e.target.value }); clearViews(); }} /></label>)}
      <button className={button} disabled={locked || !access || !validSubmissionRef(submission)} onClick={() => void load()}>Load run context</button>
    </section>}
    <section className={panel} aria-label="Exact run plan reference"><h3 className="font-semibold">Exact run plan</h3>
      <p className="text-sm">{kind === "plan" ? "Check a newly recorded plan or enter your exact earlier plan reference." : "Obtain the immutable plan ID and hash through the approved independent handoff."}</p>
      {([["plan_id", "Run plan UUID"], ["plan_sha256", "Run plan record SHA-256"]] as const).map(([key, label]) =>
        <label key={key} className="block text-sm">{label}<input className={field} value={planRef[key]} maxLength={64} spellCheck={false} autoComplete="off" disabled={locked || !access}
          onChange={e => { setPlanRef({ ...planRef, [key]: e.target.value }); setInspection(null); setKnownPlan(null); edit(); }} /></label>)}
      <button className={button} disabled={locked || !access || !validPlanRef(planRef)} onClick={() => void (kind === "plan" ? check() : load())}>
        {kind === "plan" ? "Check current run readiness" : "Inspect exact run plan"}</button>
      {kind === "plan" && <p className="text-xs">This explicit check reconstructs retained inputs and rereads current permissions. It can take up to 95 seconds. It does not fit a model or create an execution permit.</p>}
    </section>
    {(context || inspection) && <section className={panel} aria-label="Run contract details">
      <h3 ref={heading} tabIndex={-1} className="scroll-mt-24 font-semibold focus-visible:outline focus-visible:outline-2">{context ? "Review exact run inputs" : "Review independent run contract"}</h3>
      <Metadata value={context ?? inspection!.plan} />
      <p className="text-sm">Original input expiry (UTC): {context?.input_access_expires_at ?? inspection!.input_access_expires_at}</p>
      {context ? <><p className="text-sm">Explicitly request a single-process CPU budget. These limits are not a reservation or proof the future environment can satisfy the plan.</p>
        {([[cpu, setCpu, "CPU budget (seconds)", "1–1800"], [wall, setWall, "Wall-time budget (seconds)", "1–1800, at least CPU budget"],
          [memory, setMemory, "Memory budget (MiB)", "128–4096"]] as const).map(([value, setter, label, help]) =>
          <label key={label} className="block text-sm">{label}<input className={field} value={value} inputMode="numeric" maxLength={4} disabled={locked}
            onChange={e => { setter(e.target.value); edit(); }} /><span className="text-xs">{help}</span></label>)}
      </> : <><p className="text-sm">Requested budget: {inspection!.plan.cpu_seconds.toLocaleString("en-US")} CPU seconds / {inspection!.plan.wall_seconds.toLocaleString("en-US")} wall seconds / {inspection!.plan.memory_mib.toLocaleString("en-US")} MiB.</p>
        <p className="text-sm">Review head at inspection: {labels[inspection!.recorded_approval_status]}. This is not a live readiness check.</p>
        {inspection!.head && <details><summary>Exact historical predecessor</summary><pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(inspection!.head, null, 2)}</pre></details>}
        <label className="block text-sm">Review decision<select className={field} value={choice} disabled={locked} onChange={e => { setChoice(e.target.value as typeof choice); setEvidence(""); setExpiry(""); edit(); }}>
          <option value="">Choose a decision</option><option value="approve">Record conditional approval</option><option value="deny">Record denial</option>
          <option value="revoke" disabled={inspection!.head?.decision !== "approve"}>Revoke exact approval</option></select></label>
        <label className="block text-sm">Review reason code<input className={field} value={reason} maxLength={160} autoComplete="off" spellCheck={false} disabled={locked} onChange={e => { setReason(e.target.value); edit(); }} />
          <span className="text-xs">Use an approved opaque lowercase code. Do not paste source text or credentials.</span></label>
        {choice === "approve" && <label className="block text-sm">Private run-review text<textarea className={field} value={evidence} rows={5} maxLength={8192} autoComplete="off" spellCheck={false} disabled={locked} onChange={e => { setEvidence(e.target.value); edit(); }} />
          <span className="text-xs">{new TextEncoder().encode(evidence).length.toLocaleString("en-US")} / 8,192 UTF-8 bytes. The exact text is hashed automatically and retained privately on commit. Do not paste credentials, paper contents or unnecessary personal data. Access ends at the original input expiry; stored bytes require explicit purge. Approval alone is not scientific acceptance.</span></label>}
        {choice === "approve" && <label className="block text-sm">Approval expiry (UTC Unix seconds)<input className={field} value={expiry} inputMode="numeric" maxLength={16} disabled={locked} onChange={e => { setExpiry(e.target.value); edit(); }} />
          <span className="text-xs">Choose an explicit future expiry within original input retention. The database clock is authoritative.</span></label>}
      </>}
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={confirmed} disabled={locked || !valid} onChange={e => { setConfirmed(e.target.checked); setDraft(null); }} />
        <span>{context ? "I reviewed these exact inputs, requested budget and execution limits." : "I independently reviewed this exact plan, budget and decision. For approval, I consent to storing this private review text until explicitly purged. This does not establish source rights or scientific acceptance."}</span></label>
      <button className={button} disabled={locked || !valid || !confirmed} onClick={() => void preview()}>{context ? "Preview run plan" : "Preview run decision"}</button>
    </section>}
    {draft && <section className={panel} aria-label="Exact run preview"><h3 className="font-semibold">Review before committing</h3>
      <p className="text-sm">Rollback-only preview. No new record was committed. Confirm exact inputs, account, grants, budget and any predecessor/expiry.</p>
      <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(draft.result.intent, null, 2)}</pre>
      <p className="break-all font-mono text-xs">Intent SHA-256: {draft.recovery.intentSha256}</p>
      <button className={button} disabled={locked} onClick={() => void commit()}>Commit exact run preview</button>
    </section>}
    {receipt && <section className={panel} aria-label="Historical run receipt"><h3 className="font-semibold">Historical run receipt</h3>
      <p className="text-sm">{receipt.kind === "plan" ? "Requested plan" : "Conditional review"}: {receipt.replayed ? "recovered existing record" : "new record committed"}. This is not current execution permission.</p>
      {receipt.kind === "plan" && receipt.record && <Metadata value={receipt.record as RunPlan} />}
      <details><summary>Exact historical record and handoff references</summary><pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(receipt.record, null, 2)}</pre></details>
    </section>}
    {readiness && <section className={panel} aria-label="Current run readiness"><h3 className="font-semibold">Current snapshot — execution disabled</h3>
      <p className="text-sm">Observed at UTC Unix seconds {readiness.observed_epoch}. This snapshot is not a permission lease; state can change immediately afterward.</p>
      <dl className="grid gap-2 text-sm sm:grid-cols-2"><dt>Independent plan review</dt><dd>{labels[readiness.approval_status]}</dd>
        <dt>Recorded source permissions</dt><dd>{readiness.source_coverage.status_counts.allow_recorded.toLocaleString("en-US")} / {readiness.source_coverage.resource_count.toLocaleString("en-US")} resources allowed</dd>
        <dt>Current source validity</dt><dd>{readiness.source_coverage.current_source_validity_passed ? "No hold observed" : "Held or changed"}</dd>
        <dt>Combined source-permission gate</dt><dd>{readiness.source_coverage.source_permission_granted ? "Satisfied in this snapshot only" : "Not satisfied"}</dd>
        <dt>Selected implementation / host fingerprints</dt><dd>{readiness.fingerprints_match.implementation ? "Source matches" : "Source changed"} / {readiness.fingerprints_match.runtime ? "Host matches" : "Host changed"}</dd></dl>
      <h4 className="font-semibold">Remaining execution blockers</h4><ul className="list-disc space-y-1 pl-5 text-sm">{readiness.blockers.map(value => <li key={value}>{value.replaceAll("_", " ")}</li>)}</ul>
      <details><summary>Source coverage and first blocked resources</summary><pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(readiness.source_coverage, null, 2)}</pre></details>
    </section>}
    {kind === "decision" && <MlRunEvidencePanel disabled={locked} />}
    <section className={panel} aria-label="Manual run recovery"><h3 className="font-semibold">Recover an earlier operation</h3>
      <p className="text-sm">Use the original {kind === "plan" ? "plan" : "run decision"} key and intent hash under its original account. This private read does not grant or execute anything. Drafts are not saved in browser storage.</p>
      <label className="block text-sm">Recovery request key<input className={field} value={manualKey} maxLength={120} autoComplete="off" spellCheck={false} disabled={locked || !access} onChange={e => setManualKey(e.target.value)} /></label>
      <label className="block text-sm">Recovery intent SHA-256<input className={field} value={manualHash} maxLength={64} autoComplete="off" spellCheck={false} disabled={locked || !access} onChange={e => setManualHash(e.target.value)} /></label>
      <button className={button} disabled={locked || !access || !runKey(manualKey) || !runHash(manualHash)} onClick={() => void recover(true)}>Recover historical run record</button>
    </section>
  </div>;
}
