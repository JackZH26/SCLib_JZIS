"use client";

import { useEffect, useRef, useState } from "react";

import { ApiError, scientificAdjudicationCommit, scientificAdjudicationContext, scientificAdjudicationOutcome, scientificAdjudicationPreview } from "@/lib/api";
import { onAuthChange } from "@/lib/auth-session";
import { ScientificReviewDossier } from "@/components/ScientificReviewDossier";
import { reviewNumber, type ReviewQueueItem } from "@/lib/scientific-review";
import { currentScope, knownAdjudicationContext, knownAdjudicationPreview, knownAdjudicationReceipt, knownAdjudicationRequest,
  REVIEW_CHECKS, REVIEW_LIMITATIONS, REVIEW_PROFILES, REVIEW_REASONS,
  type AdjudicationContext, type AdjudicationPreview, type AdjudicationReceipt, type AdjudicationRequest,
  type AdjudicationTarget, type CheckValue, type ReviewDecision, type ReviewProfile, type ReviewScope } from "@/lib/scientific-review-decision";

const button = "rounded border border-sage-border bg-white px-3 py-2 text-sm text-accent-deep hover:bg-sage-surface focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50";
const input = "min-w-0 w-full rounded border border-sage-border bg-white p-2 text-sm";
const label = (value: string) => value.replaceAll("_", " ");
type Phase = "loading" | "editing" | "previewing" | "preview_ready" | "committing" | "outcome_unknown" | "checking" | "committed" | "unavailable";
type Confirmations = { profile: ReviewProfile | ""; checks: Record<typeof REVIEW_CHECKS[number], CheckValue>;
  artifacts: string[]; inspected: boolean; resolves: boolean };
function blank(): Confirmations {
  return { profile: "", checks: { source_match: "unresolved", quantity_and_units: "unresolved", state_association: "unresolved", method_and_scope: "unresolved" },
    artifacts: [], inspected: false, resolves: false };
}
function boundedOperation<T>(operation: () => Promise<T>, controller: AbortController): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = window.setTimeout(() => controller.abort(), 30_000);
    const abort = () => { cleanup(); reject(new Error("Review request interrupted")); };
    function cleanup() { window.clearTimeout(timer); controller.signal.removeEventListener("abort", abort); }
    controller.signal.addEventListener("abort", abort, { once: true });
    if (controller.signal.aborted) { abort(); return; }
    // Attach both handlers even if the transport ignores abort: late responses
    // cannot settle this operation again or become unhandled rejections.
    try {
      operation().then(value => { cleanup(); resolve(value); }, error => { cleanup(); reject(error); });
    } catch (error) { cleanup(); reject(error); }
  });
}
interface Props {
  selected: ReviewQueueItem[];
  onInvalidate: (recoverable: boolean) => void;
  onBusyChange: (busy: boolean) => void;
  onRecovered?: () => void;
}
export function ScientificReviewDecisionPanel({ selected, onInvalidate, onBusyChange, onRecovered }: Props) {
  const [context, setContext] = useState<AdjudicationContext | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [scope, setScope] = useState<ReviewScope>("extraction_fidelity");
  const [decision, setDecision] = useState<ReviewDecision>("request_clarification");
  const [reason, setReason] = useState("insufficient_evidence");
  const [rationale, setRationale] = useState("");
  const [confirmations, setConfirmations] = useState<Record<string, Confirmations>>({});
  const [preview, setPreview] = useState<AdjudicationPreview | null>(null);
  const [receipt, setReceipt] = useState<AdjudicationReceipt | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const sequence = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const pending = useRef<{ request: AdjudicationRequest; preview: AdjudicationPreview } | null>(null);
  const mounted = useRef(true);
  const identity = useRef<{ user: string; grant: string | null } | null>(null);
  const callbacks = useRef({ onInvalidate, onBusyChange, onRecovered });
  callbacks.current = { onInvalidate, onBusyChange, onRecovered };
  const selectedKey = selected.map(item => [item.property_id, item.event_id, item.event_revision].join(":")).join("|");

  function begin() {
    const version = ++sequence.current;
    controller.current?.abort();
    const next = new AbortController(); controller.current = next;
    return { signal: next.signal, active: () => mounted.current && version === sequence.current,
      run: <T,>(operation: () => Promise<T>) => boundedOperation(operation, next) };
  }
  function clearDraft() {
    setRationale(""); setConfirmations({}); setPreview(null); pending.current = null;
  }
  function refuse(error: unknown) {
    setContext(null); clearDraft(); setReceipt(null); setPhase("unavailable");
    const conflict = error instanceof ApiError && error.status === 409;
    setMessage(conflict ? "The subject, review head or preview changed. All prior evidence and selections have been cleared. Refresh access and review again."
      : "Review access or evidence could not be checked. All prior evidence and selections have been cleared. Refresh access to continue.");
    callbacks.current.onInvalidate(false);
  }
  async function loadContext(keepReceipt = false) {
    const request = begin();
    setContext(null); clearDraft(); setMessage(null); setPhase("loading");
    if (!keepReceipt) setReceipt(null);
    try {
      const value = knownAdjudicationContext(await request.run(() => scientificAdjudicationContext(selected.map(item => item.property_id), request.signal)), selected);
      if (!request.active()) return;
      if (!value) throw new Error("Invalid action context");
      if (identity.current && (identity.current.user !== value.actor_user_id || identity.current.grant !== value.actor_grant_id))
        throw new ApiError(401, null, "Review session changed");
      identity.current = { user: value.actor_user_id, grant: value.actor_grant_id };
      setContext(value); setPhase(keepReceipt ? "committed" : "editing");
    } catch (error) { if (request.active()) refuse(error); }
  }
  useEffect(() => {
    mounted.current = true;
    void loadContext();
    const unsubscribe = onAuthChange(() => {
      sequence.current += 1; controller.current?.abort();
      setContext(null); clearDraft(); setReceipt(null); setPhase("unavailable");
      callbacks.current.onInvalidate(false);
    });
    return () => {
      mounted.current = false; sequence.current += 1; controller.current?.abort(); unsubscribe();
      callbacks.current.onBusyChange(false);
    };
    // Explicit identity changes restart context; no request survives a selection change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedKey]);
  useEffect(() => {
    onBusyChange(["committing", "outcome_unknown", "checking"].includes(phase));
  }, [phase, onBusyChange]);
  useEffect(() => {
    if (!["committing", "outcome_unknown", "checking"].includes(phase)) return;
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      // Browsers supply their own confirmation wording. No source data is persisted.
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, [phase]);

  function edit(change: () => void) {
    sequence.current += 1; controller.current?.abort();
    setPreview(null); setReceipt(null); pending.current = null; setMessage(null); setPhase("editing"); change();
  }
  function update(property: string, change: Partial<Confirmations>) {
    edit(() => setConfirmations(current => ({ ...current, [property]: { ...(current[property] ?? blank()), ...change } })));
  }
  function makeRequest(): AdjudicationRequest | null {
    if (!context) return null;
    const items = context.targets.map(target => {
      const flags = confirmations[target.property_id] ?? blank();
      const chosen = flags.profile;
      if (!chosen) return null;
      const previous = currentScope(target, scope);
      const fidelity = currentScope(target, "extraction_fidelity");
      return { decision_id: crypto.randomUUID(), subject_id: target.subject_id, property_id: target.property_id, scope,
        profile_version: chosen, expected_subject_sha256: target.subject_sha256, expected_previous_decision_id: previous.decision_id,
        expected_impact_sha256: target.impact_sha256, decision, reason_code: reason, rationale,
        proposition: REVIEW_PROFILES[chosen].proposition, limitations: [...REVIEW_LIMITATIONS], checks: flags.checks,
        evidence_refs: target.required_artifacts.filter(ref => flags.artifacts.includes(ref.artifact_id)),
        source_inspection_attested: flags.inspected,
        resolves_decision_id: decision === "accept" && flags.resolves ? previous.decision_id : null,
        extraction_decision_id: scope === "scientific_result" && decision === "accept" ? fidelity.decision_id : null };
    });
    return knownAdjudicationRequest({ version: "scientific-result-adjudication/1.0.0", request_key: "review:" + crypto.randomUUID(), items }, context);
  }
  async function preparePreview() {
    let payload: AdjudicationRequest | null;
    try { payload = makeRequest(); } catch { payload = null; }
    if (!payload || !context) {
      setMessage("Complete every selected profile, provide a 20–2000 character rationale, and explicitly confirm each required check and source for acceptance. Unsupported or held targets cannot be silently omitted. The complete request is limited to 200 evidence references and 128 KiB.");
      return;
    }
    const request = begin(); setPhase("previewing"); setPreview(null); pending.current = null; setMessage(null);
    try {
      const value = knownAdjudicationPreview(await request.run(() => scientificAdjudicationPreview(payload, request.signal)), payload, context);
      if (!request.active()) return;
      if (!value) throw new Error("Invalid preview");
      pending.current = { request: payload, preview: value };
      setPreview(value); setPhase("preview_ready");
    } catch (error) { if (request.active()) refuse(error); }
  }
  async function commit() {
    const captured = pending.current;
    if (!captured || phase !== "preview_ready") return;
    const request = begin(); setPhase("committing"); setMessage(null);
    try {
      const value = knownAdjudicationReceipt(await request.run(() => scientificAdjudicationCommit(captured.request, captured.preview.preview_sha256, request.signal)),
        captured.request, captured.preview);
      if (!request.active()) return;
      if (!value) throw new Error("Unverifiable commit outcome");
      setReceipt(value); setPreview(null);
      await loadContext(true);
    } catch (error) {
      if (!request.active()) return;
      if (error instanceof ApiError && [400, 401, 403, 409, 422].includes(error.status)) { refuse(error); return; }
      // An abort/timeout or malformed response is NOT proof the write rolled back.
      setContext(null); setPreview(null); setConfirmations({}); setRationale(""); setPhase("outcome_unknown");
      setMessage("Commit outcome is unknown. No automatic retry was sent. Keep this page open and use Check outcome; the request key is retained only in memory.");
      callbacks.current.onInvalidate(true);
    }
  }
  async function checkOutcome() {
    const captured = pending.current;
    if (!captured) return;
    const request = begin(); setPhase("checking"); setMessage(null);
    try {
      const value = knownAdjudicationReceipt(await request.run(() => scientificAdjudicationOutcome(captured.request.request_key, request.signal)), captured.request, captured.preview);
      if (!request.active()) return;
      if (!value) throw new Error("Unverifiable receipt");
      setReceipt(value); callbacks.current.onRecovered?.(); await loadContext(true);
    } catch (error) {
      if (!request.active()) return;
      if (error instanceof ApiError && [401, 403].includes(error.status)) { refuse(error); return; }
      setPhase("outcome_unknown"); setMessage(error instanceof ApiError && error.status === 404
        ? "No receipt was returned for this request yet. This is not proof that the original request cannot still complete. Do not submit a new request."
        : "The outcome could not be verified. No write was retried. You may check this same request again.");
    }
  }
  const busy = ["loading", "previewing", "committing", "outcome_unknown", "checking", "unavailable"].includes(phase);
  return <section className="min-w-0 space-y-4 rounded-lg border border-sage-border bg-white p-4" aria-labelledby="adjudication-heading">
    <h3 id="adjudication-heading" className="font-semibold">Exact-property review</h3>
    <p className="text-sm text-sage-muted">Only the explicitly selected results are included. Review decisions do not alter original values, attest upstream execution, authorize publication or admit ML training data.</p>
    <p className="text-sm text-amber-950">Extraction fidelity asks whether the retained result matches its source. Scientific result review is a separate, limited sampled-frequency proposition—not a full-zone stability assessment. Unknown pressure, temperature and method remain unknown; an extraction run does not become DFPT.</p>
    {["committing", "outcome_unknown", "checking"].includes(phase) && <p className="text-sm text-amber-950">Keep this page open until the original request outcome is verified. Do not navigate away or submit a replacement request. Recovery information is held only in memory; a browser warning cannot guarantee recovery after leaving.</p>}
    {message && <p role="alert" className="rounded bg-amber-50 p-3 text-sm text-amber-950">{message}</p>}
    {["loading", "previewing", "committing", "checking"].includes(phase) && <p role="status" className="text-sm">{phase === "loading" ? "Checking exact review context…" : phase === "previewing" ? "Rehearsing the complete proposed request without mutation…" : phase === "committing" ? "Submitting the reviewed request. Its outcome must be confirmed…" : "Checking the original request without another write…"}</p>}
    {phase === "outcome_unknown" && <div className="space-y-2"><p className="break-all font-mono text-xs">Request key: {pending.current?.request.request_key}</p><button className={button} onClick={() => void checkOutcome()}>Check outcome</button></div>}
    {receipt && <section className="rounded border border-sage-border p-3" aria-labelledby="receipt-heading">
      <h4 id="receipt-heading" className="font-semibold">Committed review receipt · historical record</h4>
      <p className="break-all text-xs">Request {receipt.request_id} · {receipt.replayed ? "Existing receipt returned" : "New receipt recorded"}</p>
      <p className="text-sm">This receipt is not a current scientific-approval badge. Current status is checked separately below.</p>
      <ul className="mt-2 space-y-1 text-xs">{receipt.items.map(item => <li className="break-all" key={item.decision_id}>{item.property_id} · {label(item.scope)} · {label(item.decision)} · decision {item.decision_id}</li>)}</ul>
    </section>}
    {context && <>
      <p className="text-xs">{reviewNumber(context.targets.length)} explicitly selected results. At most 50 evidence references per result, 200 per request and 128 KiB total. {context.can_review ? "A current explicit reviewer grant was checked; the server checks it again before commit." : "Inspection only: no current reviewer grant permits these writes."}</p>
      <fieldset disabled={busy || !context.can_review} className="space-y-4">
        <legend className="sr-only">Proposed review decision</legend>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm">Review scope<select className={input} value={scope} onChange={event => edit(() => { setScope(event.target.value as ReviewScope); setConfirmations({}); })}>
            <option value="extraction_fidelity">Extraction fidelity</option><option value="scientific_result">Scientific result</option>
          </select></label>
          <label className="text-sm">Decision<select className={input} value={decision} onChange={event => edit(() => { const chosen = event.target.value as ReviewDecision; setDecision(chosen); setReason(REVIEW_REASONS[chosen][0]); setConfirmations({}); })}>
            <option value="request_clarification">Request clarification</option><option value="reject">Reject</option><option value="accept">Accept within selected scope</option>
          </select></label>
          <label className="text-sm">Reason<select className={input} value={reason} onChange={event => edit(() => setReason(event.target.value))}>{REVIEW_REASONS[decision].map(code => <option key={code} value={code}>{label(code)}</option>)}</select></label>
        </div>
        <label className="block text-sm">Shared rationale (20–2000 characters; private reviewer-authored content)
          <textarea className={input} rows={4} maxLength={4000} value={rationale} onChange={event => edit(() => setRationale(event.target.value))} />
        </label>
        <p className="text-xs">The same scope, decision, reason and rationale apply to every listed item. Profiles, evidence references and confirmations are selected separately for each result. No target is silently dropped.</p>
        {context.targets.map(target => {
          const flags = confirmations[target.property_id] ?? blank();
          const profiles = target.available_profiles.filter(p => REVIEW_PROFILES[p].scope === scope);
          const previous = currentScope(target, scope);
          return <fieldset key={target.property_id} className="min-w-0 space-y-3 rounded border border-sage-border p-3">
            <legend className="max-w-full break-all px-1 text-sm font-medium">Result {target.property_id}</legend>
            <p className="break-all text-xs">Subject {target.subject_id} · SHA-256 {target.subject_sha256}</p>
            <details open className="min-w-0">
              <summary className="mb-3 cursor-pointer text-sm font-medium">Evidence captured with this review subject</summary>
              <p className="mb-3 text-xs">These typed fields and source locators came with this exact review context in one server read snapshot. A separately opened browsing detail is not substituted for this evidence. Commit rechecks the subject and dependencies.</p>
              <ScientificReviewDossier value={target.dossier} idPrefix={"review-" + target.property_id} />
            </details>
            <ul className="text-xs">{target.status.scopes.map(status => <li key={status.scope}>{label(status.scope)}: {label(status.effective_status)}{status.scientific_scope_accepted ? " (limited scientific-scope acceptance; not ML or publication authorization)" : ""}
              {status.reason_codes.length > 0 && <span> · {status.reason_codes.map(label).join("; ")}</span>}</li>)}</ul>
            <label className="block min-w-0 break-words text-sm">Profile for {target.property_id}<select className={input} value={flags.profile} onChange={event => update(target.property_id, { ...blank(), profile: event.target.value as ReviewProfile | "" })}>
              <option value="">Choose an explicitly available profile</option>{profiles.map(p => <option value={p} key={p}>{p}</option>)}
            </select></label>
            {!profiles.length && <p className="text-sm text-amber-950">This target has no supported profile for the selected scope. Remove it explicitly or choose another scope; it cannot be omitted during submission.</p>}
            {target.reason_codes.length > 0 && <p className="text-xs text-amber-950">Context warnings: {target.reason_codes.map(label).join("; ")}</p>}
            {scope === "scientific_result" && decision === "accept" && currentScope(target, "extraction_fidelity").effective_status !== "accepted"
              && <p className="text-sm text-amber-950">A current accepted extraction-fidelity decision is required before scientific-scope acceptance.</p>}
            <div className="grid gap-2 sm:grid-cols-2">{REVIEW_CHECKS.map(check => <label key={check} className="min-w-0 break-words text-sm">{label(check)} · {target.property_id}
              <select className={input} value={flags.checks[check]} onChange={event => update(target.property_id, { checks: { ...flags.checks, [check]: event.target.value as CheckValue } })}>
                <option value="unresolved">Unresolved</option><option value="satisfied">Satisfied after review</option><option value="not_applicable">Not applicable</option>
              </select>
            </label>)}</div>
            <details><summary className="cursor-pointer text-sm">Required retained artifact references ({target.required_artifacts.length})</summary>
              <p className="my-2 text-xs">Select only evidence you inspected through authorized access. No raw source text or download is provided here. These confirmations are reviewer declarations, not new disclosure rights.</p>
              {target.required_artifacts.map(ref => <label key={ref.artifact_id} className="my-2 flex min-w-0 items-start gap-2 text-xs">
                <input className="mt-1" type="checkbox" checked={flags.artifacts.includes(ref.artifact_id)} onChange={event => update(target.property_id,
                  { artifacts: event.target.checked ? [...flags.artifacts, ref.artifact_id] : flags.artifacts.filter(id => id !== ref.artifact_id) })} />
                <span className="break-all">I inspected artifact {ref.artifact_id}<br />SHA-256 {ref.bytes_sha256}</span>
              </label>)}
            </details>
            <label className="flex items-start gap-2 text-sm"><input className="mt-1" type="checkbox" checked={flags.inspected} onChange={event => update(target.property_id, { inspected: event.target.checked })} />I attest that I inspected the cited sources for result {target.property_id}.</label>
            {decision === "accept" && ["reject", "request_clarification"].includes(previous.decision ?? "") && <label className="flex items-start gap-2 text-sm">
              <input className="mt-1" type="checkbox" checked={flags.resolves} onChange={event => update(target.property_id, { resolves: event.target.checked })} />
              I explicitly resolve previous decision {previous.decision_id}. The server must verify a different reviewer and the exact current head.
            </label>}
            <Impact target={target} />
          </fieldset>;
        })}
        <ul className="list-inside list-disc text-xs">{REVIEW_LIMITATIONS.map(value => <li key={value}>{label(value)}</li>)}</ul>
        <button className={button} onClick={() => void preparePreview()}>Preview complete request</button>
      </fieldset>
    </>}
    {preview && <section className="space-y-3 rounded border border-amber-200 bg-amber-50 p-3" aria-labelledby="preview-heading">
      <h4 id="preview-heading" className="font-semibold">Exact request preview · no database mutation</h4>
      <p className="text-sm">Review every item and the bounded relationship inventories above. Committing records these scope-limited decisions only; it does not change original values or automatically publish or train anything.</p>
      <p className="break-all text-xs">Request SHA-256: {preview.request_sha256}<br />Preview SHA-256: {preview.preview_sha256}</p>
      <ol className="list-inside list-decimal text-xs">{preview.items.map(item => <li className="break-all" key={item.decision_id}>{item.property_id} · {label(item.scope)} · {label(item.decision)} · {item.profile_version}<br />Decision ID {item.decision_id}</li>)}</ol>
      <button className={button} disabled={phase !== "preview_ready"} onClick={() => void commit()}>Commit exactly these {preview.items.length} decisions</button>
    </section>}
  </section>;
}

function Impact({ target }: { target: AdjudicationTarget }) {
  return <details className="text-xs"><summary className="cursor-pointer">Bounded relationships for {target.property_id}</summary>
    <p className="my-2">Relation inventory only, not predicted effects. Included: {target.impact.scope.map(label).join("; ")}. Unsupported: {target.impact.unsupported_scopes.map(label).join("; ") || "None declared; no global completeness inferred"}.</p>
    <p className="break-all">Impact SHA-256: {target.impact_sha256}</p>
    <p>{reviewNumber(target.impact.items.length)} declared relationships; no automatic refresh or publication is performed.</p>
    <ul className="mt-2 space-y-1">{target.impact.items.map((item, index) => <li key={index} className="break-all">{item.table}: {item.row_id} · {label(item.relation)} via {item.via_table}: {item.via_id}</li>)}</ul>
  </details>;
}
