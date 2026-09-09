"use client";

import { useEffect, useRef, useState } from "react";

import { ApiError, sourceLifecycleHistory, sourceLifecycleImpact, sourceTaskCapabilities, sourceTaskCommit, sourceTaskExecutionOutcome,
  sourceTaskHistory, sourceTaskPreview, sourceTaskRequestOutcome } from "@/lib/api";
import { onAuthChange } from "@/lib/auth-session";
import { knownLifecycleHistory, knownSourceImpact, knownTaskCapabilities, knownTaskHistory, knownTaskOperation, knownTaskPreview,
  knownTaskReceipt, sourceId, TASK_VERSION, taskKey, taskOperationSha256, taskUuid,
  type LifecycleEvent, type LifecycleHistory, type SourceImpact, type TaskCapabilities, type TaskHistory, type TaskOperation, type TaskPreview, type TaskReceipt } from "@/lib/source-tasks";

const button = "rounded border border-sage-border bg-white px-3 py-2 text-sm text-accent-deep hover:bg-sage-surface disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2";
const input = "min-w-0 w-full rounded border border-sage-border bg-white p-2 text-sm";
const panel = "min-w-0 space-y-3 rounded-lg border border-sage-border bg-white p-4";
const label = (value: string) => value.replaceAll("_", " ");
const number = (value: number) => value.toLocaleString("en-US");
type Draft = { operation: TaskOperation; preview: TaskPreview };
type Recovery = { operation: "enqueue"; key: string; actorId: string } | { operation: "execute"; key: string; requestId: string; actorId: string };
type Phase = "idle" | "loading" | "previewing" | "ready" | "committing" | "unknown" | "checking" | "committed";
function boundedCall<T>(call: () => Promise<T>, controller: AbortController): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => controller.abort(), 30_000);
    const abort = () => { cleanup(); reject(new Error("Source operation interrupted")); };
    function cleanup() { window.clearTimeout(timer); controller.signal.removeEventListener("abort", abort); }
    controller.signal.addEventListener("abort", abort, { once: true });
    if (controller.signal.aborted) { abort(); return; }
    try { call().then(value => { cleanup(); resolve(value); }, error => { cleanup(); reject(error); }); }
    catch (error) { cleanup(); reject(error); }
  });
}

export function SourceTaskWorkbench() {
  const [access, setAccess] = useState<TaskCapabilities | null>(null);
  const [kind, setKind] = useState<"paper" | "work">("paper");
  const [source, setSource] = useState("");
  const [lifecycle, setLifecycle] = useState<LifecycleHistory | null>(null);
  const [selected, setSelected] = useState<LifecycleEvent | null>(null);
  const [impact, setImpact] = useState<SourceImpact | null>(null);
  const [requestId, setRequestId] = useState("");
  const [lookupKey, setLookupKey] = useState("");
  const [executionKey, setExecutionKey] = useState("");
  const [history, setHistory] = useState<TaskHistory | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [receipt, setReceipt] = useState<TaskReceipt | null>(null);
  const [recovery, setRecovery] = useState<Recovery | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const seq = useRef(0), controller = useRef<AbortController | null>(null);
  const mounted = useRef(true), identity = useRef<string | null>(null), pending = useRef<Draft | null>(null);
  // No source payload or hashes survive an auth notification. Only this opaque
  // recovery locator remains in memory, and only its original actor can use it.
  const retainedRecovery = useRef<Recovery | null>(null);
  const busy = ["loading", "previewing", "committing", "checking"].includes(phase);
  const locked = busy || recovery !== null;

  function clearEvidence() { setLifecycle(null); setSelected(null); setImpact(null); setHistory(null); setDraft(null); setReceipt(null); }
  function begin() {
    const version = ++seq.current; controller.current?.abort();
    const next = new AbortController(); controller.current = next;
    return { signal: next.signal, active: () => mounted.current && seq.current === version,
      run: <T,>(call: () => Promise<T>) => boundedCall(call, next) };
  }
  function clearPrivate() {
    seq.current += 1; controller.current?.abort(); clearEvidence(); setAccess(null); setSource("");
    setRequestId(""); setLookupKey(""); setExecutionKey(""); setRecovery(null); pending.current = null;
    identity.current = null; setPhase("idle");
  }
  function fail(error: unknown) {
    clearEvidence(); setAccess(null); setPhase("idle");
    if (error instanceof ApiError && [401, 403].includes(error.status)) {
      clearPrivate(); setMessage("Session or curator access is unavailable. Private data has been cleared. Refresh access to continue.");
    } else setMessage(error instanceof ApiError && error.status === 404
      ? "Not found in this observation. This does not prove that a previous operation rolled back."
      : error instanceof ApiError && error.status === 409
        ? "The exact source, inventory, task head or preview changed. Prior evidence has been cleared. Inspect again before preparing a new operation."
        : "The response could not be verified. Private evidence has been cleared; no success is inferred.");
  }
  async function checkAccess(call: ReturnType<typeof begin>) {
    const current = knownTaskCapabilities(await call.run(() => sourceTaskCapabilities(call.signal)));
    if (!current) throw new Error("Invalid source task capabilities");
    if (identity.current !== null && identity.current !== current.actor_user_id) throw new ApiError(401, null, "Session changed");
    if (call.active()) { identity.current = current.actor_user_id; setAccess(current); }
    return current;
  }
  async function refresh() {
    const call = begin(); clearEvidence(); setAccess(null); setMessage(null); setPhase("loading");
    try {
      const current = await checkAccess(call); if (!call.active()) return;
      const saved = retainedRecovery.current;
      if (saved && saved.actorId === current.actor_user_id) { setRecovery(saved); setPhase("unknown"); setMessage("An earlier commit outcome is unknown. Check its original key before preparing another write."); }
      else { setRecovery(null); setPhase("idle"); }
    } catch (error) { if (call.active()) fail(error); }
  }
  useEffect(() => {
    mounted.current = true; void refresh();
    const unsubscribe = onAuthChange(() => { clearPrivate(); setMessage("Session changed. Private data has been cleared. Refresh access before any inspection or recovery."); });
    return () => { mounted.current = false; seq.current += 1; controller.current?.abort(); unsubscribe(); };
    // Initial access check; subsequent checks are explicit and actor-bound.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (phase !== "committing" && retainedRecovery.current === null) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [phase, recovery]);
  function edit() { clearEvidence(); setPhase("idle"); setMessage(null); }
  async function inspectSource(before: number | null = null) {
    if (!(kind === "paper" ? sourceId(source) : taskUuid(source))) return;
    const call = begin(); clearEvidence(); setMessage(null); setPhase("loading");
    try {
      await checkAccess(call); if (!call.active()) return;
      const value = knownLifecycleHistory(await call.run(() => sourceLifecycleHistory(kind, source, before, call.signal)), kind, source);
      if (!call.active()) return; if (!value) throw new Error("Invalid source history");
      setLifecycle(value); setPhase("idle");
    } catch (error) { if (call.active()) fail(error); }
  }
  async function inspectImpact(event: LifecycleEvent) {
    const call = begin(); setImpact(null); setDraft(null); setReceipt(null); setSelected(event); setMessage(null); setPhase("loading");
    try {
      await checkAccess(call); if (!call.active()) return;
      const value = knownSourceImpact(await call.run(() => sourceLifecycleImpact(event.id, event.record_sha256, call.signal)), event);
      if (!call.active()) return; if (!value) throw new Error("Invalid source impact");
      setImpact(value); setPhase("idle");
    } catch (error) { if (call.active()) fail(error); }
  }
  async function inspectTask(id = requestId) {
    if (!taskUuid(id)) return;
    const call = begin(); setHistory(null); setDraft(null); setReceipt(null); setImpact(null); setMessage(null); setPhase("loading");
    try {
      await checkAccess(call); if (!call.active()) return;
      const value = knownTaskHistory(await call.run(() => sourceTaskHistory(id, call.signal)), id);
      if (!call.active()) return; if (!value) throw new Error("Invalid task history");
      setRequestId(id); setHistory(value); setPhase("idle");
    } catch (error) { if (call.active()) fail(error); }
  }
  async function preview(operation: TaskOperation) {
    const validated = knownTaskOperation(operation); if (!validated) return;
    const call = begin(); setDraft(null); setReceipt(null); setMessage(null); setPhase("previewing");
    try {
      const current = await checkAccess(call); if (!call.active()) return;
      const sha = await taskOperationSha256(validated); if (!call.active()) return;
      const value = knownTaskPreview(await call.run(() => sourceTaskPreview(validated, call.signal)), validated, current, sha);
      if (!call.active()) return; if (!value) throw new Error("Invalid task preview");
      setDraft({ operation: validated, preview: value }); setPhase("ready");
    } catch (error) { if (call.active()) fail(error); }
  }
  async function commit() {
    if (!draft || !access || phase !== "ready" || pending.current !== null) return;
    const original = draft, actor = access.actor_user_id;
    const reference: Recovery = original.operation.operation === "enqueue"
      ? { operation: "enqueue", key: original.operation.request_key, actorId: actor }
      : { operation: "execute", key: original.operation.execution_key, requestId: original.operation.request_id, actorId: actor };
    pending.current = original; retainedRecovery.current = reference;
    const call = begin(); setPhase("committing"); setMessage(null);
    try {
      const operationSha = await taskOperationSha256(original.operation); if (!call.active()) return;
      if (operationSha !== original.preview.operation_sha256) throw new Error("Changed operation binding");
      const value = knownTaskReceipt(await call.run(() => sourceTaskCommit(original.operation, original.preview.preview_sha256, call.signal)),
        { actorId: actor, operation: original.operation, operationSha, preview: original.preview });
      if (!call.active()) return; if (!value) throw new Error("Invalid committed receipt");
      acceptReceipt(value);
    } catch (error) {
      if (!call.active()) return;
      clearEvidence(); setRecovery(reference); setPhase("unknown");
      if (error instanceof ApiError && [401, 403].includes(error.status)) { clearPrivate(); setMessage("Session or curator access changed. Private data has been cleared. Refresh access to recover the original operation for its original account."); }
      else setMessage("Commit outcome is unknown. No rollback or failure is inferred. Check the original operation key; do not send another write.");
    }
  }
  function acceptReceipt(value: TaskReceipt) {
    clearEvidence(); setReceipt(value); setRequestId(value.request.id); setRecovery(null); setDraft(null);
    pending.current = null; retainedRecovery.current = null; setPhase("committed");
    setMessage("A committed historical receipt was verified. It does not establish current cache readiness or complete propagation.");
  }
  async function checkOutcome(reference?: Recovery) {
    const ref = reference ?? recovery; if (!ref) return;
    const call = begin(); setReceipt(null); setDraft(null); setMessage(null); setPhase("checking");
    try {
      const current = await checkAccess(call); if (!call.active()) return;
      if (current.actor_user_id !== ref.actorId) throw new ApiError(401, null, "Recovery actor changed");
      const raw = await call.run(() => ref.operation === "enqueue" ? sourceTaskRequestOutcome(ref.key, call.signal)
        : sourceTaskExecutionOutcome(ref.requestId, ref.key, call.signal));
      if (!call.active()) return;
      const original = recovery ? pending.current : null;
      const operationSha = original ? await taskOperationSha256(original.operation) : undefined;
      if (!call.active()) return;
      const value = knownTaskReceipt(raw, { actorId: current.actor_user_id, ...(ref.operation === "enqueue"
        ? { requestKey: ref.key } : { requestId: ref.requestId, executionKey: ref.key }),
        ...(original ? { operation: original.operation, operationSha, preview: original.preview } : {}) });
      if (!value) throw new Error("Invalid recovery receipt"); acceptReceipt(value);
    } catch (error) {
      if (!call.active()) return;
      if (error instanceof ApiError && [401, 403].includes(error.status)) { clearPrivate(); setMessage("Session or curator access is unavailable. Private recovery data has been cleared."); }
      else if (recovery) { setPhase("unknown"); setMessage(error instanceof ApiError && error.status === 404
        ? "Not found now. The commit may still be in flight; absence is not proof of rollback. The original key is retained. Check again without submitting another write."
        : "Outcome remains unknown. The original key is retained. Check again without submitting another write."); }
      else fail(error);
    }
  }
  const head = history?.attempts.at(-1);
  const executable = history && (!head || head.status === "retryable_failure" && head.attempt_number < 5);
  return <div className="min-w-0 space-y-5">
    <header className="space-y-3">
      <h2 className="text-xl font-semibold text-sage-ink">Source-change tasks</h2>
      <p className="text-sm text-sage-muted">Private curator workflow: inspect a source revision, enqueue an exact impact inventory, then explicitly invalidate the Timeline cache.</p>
      <p className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">Invalidation only. This does not rebuild the Timeline, refresh all dependencies, invalidate external caches, reinstate a source, approve science or authorize ML training. No automatic retries are scheduled.</p>
      <button className={button} disabled={busy || recovery !== null} onClick={() => void refresh()}>Refresh curator access</button>
    </header>
    <div aria-live="polite">{busy && <p role="status">{phase === "committing" ? "Submitting the exact previewed operation…" : "Checking the bounded private snapshot…"}</p>}
      {message && <p role="alert" className="rounded border border-sage-border p-3 text-sm">{message}</p>}</div>
    {access && <p className="text-xs text-sage-muted">Current curator access verified. Historical receipt grants are not current permissions.</p>}
    {recovery && <section className={panel} aria-labelledby="recovery-heading">
      <h3 id="recovery-heading" className="font-semibold">Recover unknown commit</h3>
      <p className="break-all font-mono text-xs">Original {recovery.operation === "enqueue" ? "request" : "execution"} key: {recovery.key}</p>
      <p className="text-sm">Keep this tab open until the outcome is recovered. This page does not persist recovery across reloads or guarantee protection against in-app navigation.</p>
      <button className={button} disabled={busy} onClick={() => void checkOutcome()}>Check original outcome</button>
    </section>}
    {access && !recovery && <>
      <section className={panel} aria-labelledby="source-heading">
        <h3 id="source-heading" className="font-semibold">1. Inspect source lifecycle</h3>
        <div className="grid gap-3 sm:grid-cols-[10rem_1fr]">
          <label className="text-sm">Source type<select className={input} value={kind} disabled={locked} onChange={event => { edit(); setKind(event.target.value as "paper" | "work"); setSource(""); }}><option value="paper">Paper ID</option><option value="work">Work UUID</option></select></label>
          <label className="text-sm">Source identifier<input className={input} value={source} maxLength={100} disabled={locked} onChange={event => { edit(); setSource(event.target.value); }} placeholder={kind === "paper" ? "Exact paper_id" : "Canonical Work UUID"} /></label>
        </div>
        <button className={button} disabled={locked || !(kind === "paper" ? sourceId(source) : taskUuid(source))} onClick={() => void inspectSource()}>Inspect source</button>
        {lifecycle && <div className="space-y-2 text-sm">
          <p>Bibliographic status: {lifecycle.status ?? "Not reported"}. Lifecycle hold: {lifecycle.lifecycle_review_required ? "Review required" : "No lifecycle hold observed"}.</p>
          <p className="text-xs text-sage-muted">Historical events, newest first. Only the current head can produce a new exact impact preview.</p>
          {lifecycle.events.length === 0 ? <p>No lifecycle events were returned. No task can be inferred or enqueued.</p> : <ul className="space-y-2">{lifecycle.events.map(event => <li key={event.id}>
            <button className={button + " w-full text-left"} disabled={locked || event.id !== lifecycle.head?.id} aria-pressed={selected?.id === event.id} onClick={() => void inspectImpact(event)}>
              <span className="block">Inspect impact · revision {number(event.revision)} · {label(event.observed_status)}</span><span className="block break-all font-mono text-xs">{event.id}</span>
            </button></li>)}</ul>}
          <button className={button} disabled={locked || lifecycle.next_before_revision === null} onClick={() => void inspectSource(lifecycle.next_before_revision)}>Older events</button>
        </div>}
        {impact && <div className="space-y-2 rounded border border-sage-border p-3 text-sm">
          <h4 className="font-semibold">Exact declared impact</h4><p>{number(impact.node_count)} relationship nodes in this database snapshot. This is not a scientific dependency proof or global total.</p>
          <ul>{Object.entries(impact.counts).map(([name, count]) => <li key={name}>{label(name)}: {number(count)}</li>)}</ul>
          <details><summary>Scope and exclusions</summary><p className="mt-2 font-medium">Covered relationships</p><ul className="list-disc pl-5">{impact.supported_scopes.map(scope => <li key={scope}>{label(scope)}</li>)}</ul><p className="mt-2 font-medium">Not covered</p><ul className="list-disc pl-5">{impact.unsupported_scopes.map(scope => <li key={scope}>{label(scope)}</li>)}</ul></details>
          <p className="break-all font-mono text-xs">Inventory SHA-256: {impact.inventory_sha256}</p>
          <button className={button} disabled={locked} onClick={() => void preview({ version: TASK_VERSION, operation: "enqueue", request_key: "source-ui-" + crypto.randomUUID(), event_id: impact.event.id, expected_event_sha256: impact.event.record_sha256, expected_inventory_sha256: impact.inventory_sha256 })}>Preview enqueue</button>
        </div>}
      </section>
      <section className={panel} aria-labelledby="task-heading">
        <h3 id="task-heading" className="font-semibold">2. Inspect task or recover a known key</h3>
        <p className="text-xs text-sage-muted">Receipt recovery is read-only and actor-scoped; task history requires current research-operator access. A 404 means not found now, never proof that an earlier write rolled back.</p>
        <label className="block text-sm">Request key<input className={input} value={lookupKey} maxLength={160} disabled={locked} onChange={event => { edit(); setLookupKey(event.target.value); }} /></label>
        <button className={button} disabled={locked || !taskKey(lookupKey)} onClick={() => void checkOutcome({ operation: "enqueue", key: lookupKey, actorId: access.actor_user_id })}>Find request outcome</button>
        <label className="block text-sm">Task request UUID<input className={input} value={requestId} maxLength={36} disabled={locked} onChange={event => { edit(); setRequestId(event.target.value); }} /></label>
        <button className={button} disabled={locked || !taskUuid(requestId)} onClick={() => void inspectTask()}>Load task history</button>
        <label className="block text-sm">Execution key<input className={input} value={executionKey} maxLength={160} disabled={locked} onChange={event => { edit(); setExecutionKey(event.target.value); }} /></label>
        <button className={button} disabled={locked || !taskUuid(requestId) || !taskKey(executionKey)} onClick={() => void checkOutcome({ operation: "execute", requestId, key: executionKey, actorId: access.actor_user_id })}>Find execution outcome</button>
        {history && <div className="space-y-2 rounded border border-sage-border p-3 text-sm">
          <h4 className="font-semibold">Immutable task history</h4><p>Stored state: {label(history.stored_state)}. Attempts: {number(history.attempts.length)} of 5.</p>
          <p className="break-all font-mono text-xs">Request SHA-256: {history.request.record_sha256}</p>
          <ol className="list-inside list-decimal">{history.attempts.map(row => <li key={row.id}>{label(row.status)} · {label(row.outcome_code)}</li>)}</ol>
          <button className={button} disabled={locked || !executable} onClick={() => void preview({ version: TASK_VERSION, operation: "execute", request_id: history.request.id,
            expected_request_sha256: history.request.record_sha256, execution_key: "source-ui-" + crypto.randomUUID(), expected_predecessor_id: head?.id ?? null, expected_predecessor_sha256: head?.record_sha256 ?? null })}>Preview execution</button>
          {!executable && <p>No further execution is available for this terminal task. Success remains a historical invalidation receipt, not current cache readiness.</p>}
        </div>}
      </section>
    </>}
    {draft && <section className={panel} aria-labelledby="preview-heading">
      <h3 id="preview-heading" className="font-semibold">3. Confirm exact {draft.operation.operation} preview</h3>
      <p className="text-sm">Predicted stored outcome: {label(draft.preview.predicted_status)}{draft.preview.predicted_outcome_code ? " · " + label(draft.preview.predicted_outcome_code) : ""}. Preview changed no database state.</p>
      <p className="text-sm">{draft.preview.replayed ? "This exact operation already has a historical receipt. Confirmation will replay it without another invalidation." : "Commit records only this scoped operation. A blocked or obsolete outcome will not invalidate the cache."}</p>
      <p className="break-all font-mono text-xs">Original operation key: {draft.operation.operation === "enqueue" ? draft.operation.request_key : draft.operation.execution_key}</p>
      <p className="text-xs text-sage-muted">Keep this key before leaving the page. Recovery references are held only in this tab, not saved across reloads. In-app navigation is not guaranteed to be blocked.</p>
      <p className="break-all font-mono text-xs">Preview SHA-256: {draft.preview.preview_sha256}</p>
      <button className={button} disabled={phase !== "ready"} onClick={() => void commit()}>Commit exact preview</button>
    </section>}
    {receipt && <section className={panel} aria-labelledby="receipt-heading">
      <h3 id="receipt-heading" className="font-semibold">Committed historical receipt</h3>
      <p className="text-sm">{receipt.operation === "enqueue" ? "Task enqueue recorded." : "Execution recorded: " + label(receipt.attempt!.status) + " · " + label(receipt.attempt!.outcome_code) + "."} {receipt.replayed ? "Exact replay; no new execution." : "New receipt."}</p>
      <p className="break-all font-mono text-xs">Request UUID: {receipt.request.id}</p>
      <p className="text-sm">Timeline rebuilt: no. Complete propagation: no. Scientific and ML approval: none.</p>
      {receipt.attempt?.status === "succeeded" && <p className="text-sm">Invalidation was acknowledged in that transaction. Cache state present: {receipt.attempt.state_present ? "yes" : "no"}; changed: {receipt.attempt.state_changed ? "yes" : "no"}. It may have been rebuilt or changed since.</p>}
      <button className={button} disabled={locked} onClick={() => void inspectTask(receipt.request.id)}>Inspect recorded task</button>
    </section>}
    <p className="text-xs text-sage-muted">Private operator workflow. The browser validates response structure and exact operation pins, not source files, scientific correctness or live distributed-system state. Nothing is stored in browser storage.</p>
  </div>;
}
