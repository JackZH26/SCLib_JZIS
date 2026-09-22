"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import { onAuthChange } from "@/lib/auth-session";
import { pilotHash, pilotKey, pilotReason } from "@/lib/ml-pilot-participation";
import { parseEvidenceSnapshot, prepareEvidence, type EvidenceSnapshot } from "@/lib/ml-pilot-evidence";
import { preparePilotQualityReport, type PilotQualityReport } from "@/lib/ml-pilot-quality";
import { MlPilotQualityReport } from "@/components/MlPilotQualityReport";
import { checkReviewCoverage, checkReviewDocuments, commitReview, DECLARATION_HASH, DECLARATION_VERSION, getReviewWording, inspectReview,
  parseReviewCoverage, parseReviewInspection, parseReviewPreflight, parseReviewResult, parseReviewWording, prepareReviewDocuments, previewReview, recoverReview,
  REVIEW_FILES, sendReviewEvidence, validReviewRef, type ReviewAction, type ReviewBasis, type ReviewControl, type ReviewDocuments, type ReviewDocumentSet,
  type ReviewCoverage, type ReviewRecord, type ReviewRecovery, type ReviewRef, type ReviewResult, type ReviewWording } from "@/lib/ml-pilot-reviews";

const button = "rounded border border-sage-border bg-white px-3 py-2 text-sm text-accent-deep hover:bg-sage-surface disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2";
const field = "min-w-0 w-full rounded border border-sage-border bg-white p-2 text-sm";
const panel = "min-w-0 space-y-3 rounded-lg border border-sage-border bg-white p-4";
const emptyRef = { participant_id: "", participant_sha256: "", registration_sha256: "" };
const fileLabels = { selection: "Original selection file", protocol: "Original protocol file", reviews: "Original review log", conclusion: "Original conclusion file" };
type Draft = { controls: ReviewControl; action: ReviewAction; documents: ReviewDocuments | null; basis: ReviewBasis;
  predecessor: ReviewRecord | null; result: ReviewResult; recovery: ReviewRecovery };

function Basis({ value }: { value: ReviewBasis }) {
  return <div className="space-y-3 text-sm" aria-label="Exact review scope">
    <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2"><div><dt>Selected candidate events</dt><dd>{value.selected_candidates.toLocaleString("en-US")}</dd></div>
      <div><dt>Complete log records, including revisions</dt><dd>{value.review_record_count.toLocaleString("en-US")}</dd></div>
      <div><dt>Your review records</dt><dd>{value.own_review_record_count.toLocaleString("en-US")}</dd></div>
      <div><dt>You are the recorded conclusion author</dt><dd>{value.conclusion_author_is_current_account ? "Yes" : "No"}</dd></div>
      <div><dt>Document conclusion, not approval</dt><dd>{value.recorded_recommendation}</dd></div></dl>
    <p>Counts include all revisions and failures; they are not counts of independent materials or evidence of review quality.
      {value.conclusion_author_is_current_account ? " Your declaration also covers the exact conclusion and its field-specific recommendations." : " Your declaration covers your own review contributions, not endorsement as the conclusion author."}</p>
    <details><summary>Exact document and contribution hashes</summary><pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(value, null, 2)}</pre></details>
    <p className="text-xs">The canary hash is declared only. Context, source permissions, human independence and scientific correctness are not verified here.</p>
  </div>;
}

export function MlPilotReviewWorkbench() {
  const [wording, setWording] = useState<ReviewWording | null>(null), [query, setQuery] = useState<ReviewRef>(emptyRef);
  const [head, setHead] = useState<ReviewRecord | null | undefined>(undefined), [action, setAction] = useState<"" | ReviewAction>(""), [reason, setReason] = useState("");
  const [files, setFiles] = useState<Partial<ReviewDocumentSet>>({}), [fileEpoch, setFileEpoch] = useState(0);
  const [documents, setDocuments] = useState<ReviewDocuments | null>(null), [scope, setScope] = useState<ReviewBasis | null>(null);
  const [coverage, setCoverage] = useState<ReviewCoverage | null>(null);
  const [canaryFile, setCanaryFile] = useState<File | null>(null), [contextFiles, setContextFiles] = useState<File[]>([]);
  const [evidenceEpoch, setEvidenceEpoch] = useState(0);
  const [evidence, setEvidence] = useState<EvidenceSnapshot | null>(null);
  const [quality, setQuality] = useState<PilotQualityReport | null>(null);
  const [consent, setConsent] = useState(false), [confirmed, setConfirmed] = useState(false), [draft, setDraft] = useState<Draft | null>(null);
  const [receipt, setReceipt] = useState<ReviewResult | null>(null), [message, setMessage] = useState<string | null>(null), [busy, setBusy] = useState(false);
  const [unresolved, setUnresolved] = useState(false), [recovery, setRecovery] = useState<ReviewRecovery | null>(null), [manualKey, setManualKey] = useState(""), [manualHash, setManualHash] = useState("");
  const serial = useRef(0), mounted = useRef(true), working = useRef(false), controller = useRef<AbortController | null>(null), identity = useRef<string | null>(null);
  const retained = useRef<ReviewRecovery | null>(null), heading = useRef<HTMLHeadingElement | null>(null), previewHeading = useRef<HTMLHeadingElement | null>(null), receiptHeading = useRef<HTMLHeadingElement | null>(null);
  const locked = busy || unresolved, completeFiles = REVIEW_FILES.every(k => !!files[k]);
  const canPreview = !!wording && head !== undefined && !!action && pilotReason(reason) && !!scope && (action === "withdraw" ? head?.action === "attest" : documents !== null);
  function invalidate() { setConsent(false); setConfirmed(false); setDraft(null); setReceipt(null); setCoverage(null); setEvidence(null); setQuality(null); setMessage(null); }
  function clearEvidenceFiles() { setCanaryFile(null); setContextFiles([]); setEvidenceEpoch(n => n + 1); }
  function clearDocuments() { setFiles({}); setFileEpoch(n => n + 1); setDocuments(null); setScope(null); setCoverage(null); setEvidence(null); setQuality(null); clearEvidenceFiles(); }
  function clearChoice() { setAction(""); setReason(""); clearDocuments(); invalidate(); }
  function clearPrivate() {
    serial.current++; controller.current?.abort(); working.current = false; setBusy(false); identity.current = null; setWording(null);
    setQuery(emptyRef); setHead(undefined); clearChoice(); setRecovery(null); setManualKey(""); setManualHash(""); setUnresolved(retained.current !== null);
  }
  function begin() {
    working.current = true; setBusy(true); setMessage(null); const epoch = ++serial.current;
    controller.current?.abort(); const c = new AbortController(); controller.current = c;
    return { signal: c.signal, active: () => mounted.current && epoch === serial.current,
      finish: () => { if (mounted.current && epoch === serial.current) { working.current = false; setBusy(false); } } };
  }
  function fail(error: unknown) {
    setHead(undefined); clearChoice();
    if (error instanceof ApiError && [401, 403].includes(error.status)) { clearPrivate(); setMessage("Account access changed. Private review details were cleared. Return to the original account for recovery."); }
    else setMessage(error instanceof ApiError && error.status === 404 ? "The exact account binding or private feature is unavailable. No successful operation is inferred."
      : "The exact documents, response or current state could not be verified. Inspect again before continuing; no scientific acceptance is inferred.");
  }
  async function current(signal: AbortSignal) {
    const v = await parseReviewWording(await getReviewWording(signal));
    if (identity.current !== null && v.actor_user_id !== identity.current) throw new ApiError(401, null, "Session changed"); return v;
  }
  async function refresh() {
    if (working.current) return; const call = begin(); setWording(null); setQuery(emptyRef); setHead(undefined); clearChoice(); setRecovery(null); setManualKey(""); setManualHash("");
    try {
      const v = await current(call.signal); if (!call.active()) return; identity.current = v.actor_user_id; setWording(v);
      const original = retained.current; setRecovery(original?.actorId === v.actor_user_id ? original : null);
      if (original) setMessage(original.actorId === v.actor_user_id ? "Recover the original outcome before making another declaration." : "An unresolved operation belongs to another account. Return to its original account to recover it.");
    } catch (error) { if (call.active()) fail(error); } finally { call.finish(); }
  }
  useEffect(() => {
    mounted.current = true; void refresh(); const stop = onAuthChange(() => { clearPrivate(); setMessage("Session changed. Refresh access before continuing."); });
    return () => { mounted.current = false; serial.current++; controller.current?.abort(); working.current = false; stop(); };
    // No automatic declarations, retries, polling or persisted private input.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => { if (head !== undefined) { heading.current?.focus({ preventScroll: true }); heading.current?.scrollIntoView({ block: "start" }); } }, [head]);
  useEffect(() => { if (draft) { previewHeading.current?.focus({ preventScroll: true }); previewHeading.current?.scrollIntoView({ block: "start" }); } }, [draft]);
  useEffect(() => { if (receipt) { receiptHeading.current?.focus({ preventScroll: true }); receiptHeading.current?.scrollIntoView({ block: "start" }); } }, [receipt]);
  useEffect(() => { if (!unresolved) return; const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn); return () => window.removeEventListener("beforeunload", warn); }, [unresolved]);
  async function inspect() {
    if (working.current || unresolved || !wording || !validReviewRef(query)) return; const call = begin(), ref = { ...query }; setHead(undefined); clearChoice();
    try { const actor = await current(call.signal); if (!call.active()) return;
      const value = await parseReviewInspection(await inspectReview(ref, call.signal), actor.actor_user_id, ref); if (call.active()) { setWording(actor); setHead(value); }
    } catch (error) { if (call.active()) fail(error); } finally { call.finish(); }
  }
  async function check() {
    if (working.current || unresolved || !wording || head === undefined || action !== "attest" || !completeFiles) return;
    const call = begin(), ref = { ...query }; invalidate(); setScope(null); setDocuments(null); clearEvidenceFiles();
    try { const actor = await current(call.signal); if (!call.active()) return;
      const originals = await prepareReviewDocuments(files as ReviewDocumentSet, call.signal); if (!call.active()) return;
      const value = parseReviewPreflight(await checkReviewDocuments(ref, originals, call.signal), actor.actor_user_id, ref, originals);
      if (call.active()) { setWording(actor); setDocuments(originals); setScope(value); setMessage("Original documents checked for your account. No declaration has been recorded. Review your complete scope and the exact wording below."); }
    } catch (error) { if (call.active()) fail(error); } finally { call.finish(); }
  }
  async function preview() {
    if (working.current || unresolved || !canPreview || !consent || !wording || !scope || !action || head === undefined) return;
    const call = begin(), ref = { ...query }; setDraft(null); setConfirmed(false);
    try {
      const actor = await current(call.signal); if (!call.active()) return;
      const latest = await parseReviewInspection(await inspectReview(ref, call.signal), actor.actor_user_id, ref); if (!call.active()) return;
      if ((latest?.record_sha256 ?? null) !== (head?.record_sha256 ?? null)) { clearChoice(); setHead(latest); setMessage("Your declaration history changed. Review the refreshed predecessor and choose again."); return; }
      const controls: ReviewControl = { ...ref, request_key: "ml-review:" + crypto.randomUUID(), reason_code: reason,
        supersedes_id: head?.id ?? null, supersedes_sha256: head?.record_sha256 ?? null, declaration_version: DECLARATION_VERSION,
        declaration_sha256: DECLARATION_HASH, declaration_acknowledged: true };
      const result = await parseReviewResult(await previewReview(action, controls, documents, call.signal), { actorId: actor.actor_user_id, requestKey: controls.request_key }, false,
        { controls, action, basis: scope, predecessor: head }); if (!call.active()) return;
      setDraft({ controls, action, documents, basis: scope, predecessor: head, result, recovery: { actorId: actor.actor_user_id, requestKey: controls.request_key, intentSha256: result.intent_sha256 } });
    } catch (error) { if (call.active()) fail(error); } finally { call.finish(); }
  }
  async function checkCoverage() {
    if (working.current || unresolved || !wording || !documents || !scope || action !== "attest") return;
    const call = begin(), ref = { ...query }; invalidate();
    try {
      const actor = await current(call.signal); if (!call.active()) return;
      const value = parseReviewCoverage(await checkReviewCoverage(ref, documents, call.signal), actor.actor_user_id, ref, scope);
      if (call.active()) setCoverage(value);
    } catch (error) { if (call.active()) fail(error); } finally { call.finish(); }
  }
  async function checkEvidence() {
    if (working.current || unresolved || !wording || !scope || !documents || !completeFiles || !canaryFile || action !== "attest") return;
    const call = begin(), ref = { ...query }; invalidate();
    try {
      const actor = await current(call.signal); if (!call.active()) return;
      const upload = await prepareEvidence(ref, scope, files as ReviewDocumentSet, canaryFile, contextFiles, call.signal); if (!call.active()) return;
      const value = parseEvidenceSnapshot(await sendReviewEvidence(ref, upload.body, call.signal), actor.actor_user_id, ref, scope, upload);
      if (call.active()) { setEvidence(value); setCoverage(value.account); }
    } catch (error) { if (call.active()) fail(error); } finally { call.finish(); }
  }
  async function showQuality() {
    if (working.current || unresolved || !wording || !scope || !evidence || !canaryFile || !files.conclusion || action !== "attest") return;
    const call = begin(); setQuality(null); setConsent(false); setConfirmed(false); setDraft(null); setReceipt(null);
    try {
      await current(call.signal); if (!call.active()) return;
      const value = await preparePilotQualityReport(canaryFile, files.conclusion, scope, evidence, call.signal);
      if (call.active()) setQuality(value);
    } catch (error) { if (call.active()) fail(error); } finally { call.finish(); }
  }
  function acceptReceipt(value: ReviewResult) {
    setHead(undefined); clearChoice(); setReceipt(value); retained.current = null; setRecovery(null); setUnresolved(false); setManualKey(""); setManualHash("");
    setMessage("Historical declaration receipt verified. Inspect again for the current head. This is not collective scientific acceptance or permission to train.");
  }
  async function commit() {
    if (working.current || unresolved || !draft || !confirmed || !wording || draft.recovery.actorId !== wording.actor_user_id) return;
    const call = begin(), original = draft; let sent = false;
    try {
      await current(call.signal); if (!call.active()) return;
      retained.current = original.recovery; setRecovery(original.recovery); setUnresolved(true); setDraft(null); clearDocuments(); setConsent(false); setConfirmed(false); sent = true;
      const value = await parseReviewResult(await commitReview(original.action, original.controls, original.documents, original.recovery.intentSha256, call.signal), original.recovery, true,
        { controls: original.controls, action: original.action, basis: original.basis, predecessor: original.predecessor });
      if (call.active()) acceptReceipt(value);
    } catch (error) {
      if (!call.active()) return;
      if (!sent || error instanceof ApiError && [401, 403].includes(error.status)) fail(error);
      else { setHead(undefined); clearChoice(); setMessage("Commit outcome is unknown. Recover the original key and hash; no automatic retry is sent. A missing receipt is not proof of rollback."); }
    } finally { call.finish(); }
  }
  async function recover(manual = false) {
    if (working.current || !wording || manual && unresolved) return;
    const original = manual ? { actorId: wording.actor_user_id, requestKey: manualKey, intentSha256: manualHash } : recovery;
    if (!original || !pilotKey(original.requestKey) || !pilotHash(original.intentSha256)) return;
    const call = begin(); retained.current = original; setRecovery(original); setUnresolved(true); setHead(undefined); clearChoice();
    try { const actor = await current(call.signal); if (!call.active()) return;
      if (actor.actor_user_id !== original.actorId) throw new ApiError(401, null, "Recovery account changed");
      const value = await parseReviewResult(await recoverReview(original, call.signal), original, true);
      if (!call.active()) return; if (!value.replayed) throw new Error("Invalid historical recovery"); acceptReceipt(value);
    } catch (error) { if (!call.active()) return;
      if (error instanceof ApiError && [401, 403].includes(error.status)) fail(error);
      else setMessage(error instanceof ApiError && error.status === 404 ? "No outcome was observed in this snapshot. The original commit may still be in flight; no rollback is inferred."
        : "Outcome remains unknown. Keep the original key and hash; no new write was sent.");
    } finally { call.finish(); }
  }
  return <div className="min-w-0 space-y-5">
    <header className="space-y-3"><h2 className="text-xl font-semibold">ML pilot review declarations</h2>
      <p className="text-sm">Record a declaration about your own complete review contributions and, if you are its recorded author, the exact conclusion.</p>
      <p className="rounded border border-amber-200 bg-amber-50 p-3 text-sm">An account declaration is not proof of independent human review, scientific correctness, source permission, collective pilot acceptance, or authorization to train a model.</p>
      <button className={button} disabled={busy} onClick={() => void refresh()}>Refresh review access</button>
      {wording && <p className="break-all text-xs">Signed-in account: {wording.actor_user_id}. No reviewer role is granted by this check.</p>}
    </header>
    <div aria-live="polite">{busy && <p role="status">Checking the exact private review operation…</p>}{message && <p role="alert" className={panel}>{message}</p>}</div>
    {recovery && <section className={panel} aria-label="Unresolved review operation"><h3 className="font-semibold">Original review operation</h3>
      <p className="text-sm">Keep these references in an approved private record before leaving. No files or recovery references are saved to browser storage. After reloading, use manual recovery under the original account.</p>
      <dl className="break-all text-xs"><dt>Original account</dt><dd>{recovery.actorId}</dd><dt>Original request key</dt><dd>{recovery.requestKey}</dd><dt>Intent SHA-256</dt><dd>{recovery.intentSha256}</dd></dl>
      <button className={button} disabled={busy || !wording} onClick={() => void recover()}>Check original review outcome</button>
    </section>}
    <section className={panel} aria-label="Exact review binding"><h3 className="font-semibold">Your exact participant binding</h3>
      <p className="text-sm">Use your participant binding from the private pilot participation page or an approved handoff. No directory of other reviewers is exposed.</p>
      {([["participant_id", "Participant UUID"], ["participant_sha256", "Participant record SHA-256"], ["registration_sha256", "Registration record SHA-256"]] as const).map(([name, label]) =>
        <label className="block text-sm" key={name}>{label}<input className={field} maxLength={64} autoComplete="off" spellCheck={false} value={query[name]} disabled={locked || !wording}
          onChange={e => { setQuery({ ...query, [name]: e.target.value }); setHead(undefined); clearChoice(); }} /></label>)}
      <button className={button} disabled={locked || !wording || !validReviewRef(query)} onClick={() => void inspect()}>Inspect own declaration history</button>
    </section>
    {head !== undefined && <section className={panel} aria-label="Own declaration history"><h3 ref={heading} tabIndex={-1} className="scroll-mt-24 font-semibold">Your declaration history</h3>
      <p>Latest recorded action: {head?.action ?? "No declaration"}. This is historical inspection, not a current scientific verdict.</p>
      {head && <><Basis value={head.basis} /><details><summary>Exact historical record</summary><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(head, null, 2)}</pre></details></>}
      <label className="block text-sm">Review action<select className={field} value={action} disabled={locked} onChange={e => { const a = e.target.value as typeof action;
        clearChoice(); setAction(a); if (a === "withdraw") setScope(head?.basis ?? null); }}><option value="">Choose an action</option>
        <option value="attest">Declare my complete reviews</option><option value="withdraw" disabled={head?.action !== "attest"}>Withdraw my prior declaration</option></select></label>
      {action && <label className="block text-sm">Reason code<input className={field} value={reason} maxLength={160} autoComplete="off" spellCheck={false} disabled={locked}
        onChange={e => { setReason(e.target.value); invalidate(); }} /><span className="text-xs">Lowercase letters, digits and underscores; start with a letter. No names, source text or sensitive details.</span></label>}
      {action === "attest" && <div key={fileEpoch} className="space-y-3"><p className="text-sm">Read the complete originals through your approved private workflow, then supply all four files below (at most 8 MiB each). Checking uploads their exact bytes; it does not record a declaration. The server checks all candidates and review revisions, including failures.</p>
        {REVIEW_FILES.map(k => <label className="block text-sm" key={k}>{fileLabels[k]}<input className={field} type="file" disabled={locked}
          onChange={e => { setFiles({ ...files, [k]: e.target.files?.[0] }); setDocuments(null); setScope(null); clearEvidenceFiles(); invalidate(); }} /></label>)}
        <button className={button} disabled={locked || !completeFiles} onClick={() => void check()}>Check original review documents</button>
      </div>}
      {action === "withdraw" && <p className="text-sm">Withdrawal uses the exact prior record above and does not erase history. No files or current reviewer grant are needed while your account remains active.</p>}
    </section>}
    {scope && wording && <section className={panel} aria-label="Review declaration consent"><h3 className="font-semibold">Review your exact declaration scope</h3>
      <Basis value={scope} />
      {action === "attest" && documents && <div className="space-y-2"><h4 className="font-semibold">Joint declaration coverage</h4>
        <p className="text-sm">Upload the same four originals again to recheck the latest declarations for every contributing reviewer and the conclusion author. Unused preregistered arbitrators do not need to declare reviews they did not perform. This check does not record a declaration.</p>
        <button className={button} disabled={locked} onClick={() => void checkCoverage()}>Check joint declaration coverage</button>
      </div>}
      {action === "attest" && documents && <div key={`evidence-${fileEpoch}-${evidenceEpoch}`} className="space-y-3" aria-label="Canary and context byte verification">
        <h4 className="font-semibold">Canary and context byte verification</h4>
        <p className="text-sm">Optional, default-off private intake. Supply the exact canary v1.2 bundle declared in your conclusion and every permitted context file referenced anywhere in the complete review log, including superseded reviews. This uploads the four originals again and verifies byte integrity, not scientific support or permission.</p>
        <label className="block text-sm">Exact canary bundle<input className={field} type="file" disabled={locked}
          onChange={e => { setCanaryFile(e.target.files?.[0] ?? null); invalidate(); }} /><span className="text-xs">At most 32 MiB. Its hash must already match the conclusion; this page does not rewrite documents.</span></label>
        <label className="block text-sm">Exact context files<input className={field} type="file" multiple disabled={locked}
          onChange={e => { setContextFiles(Array.from(e.target.files ?? [])); invalidate(); }} /><span className="text-xs">Use lowercase SHA-256 filenames ending in .bin. At most 8 MiB each, 64 MiB total, and 6,000 distinct files. The server rejects missing or unrelated files.</span></label>
        <p className="text-xs">Context bytes are hashed in memory by the application, not stored as database records. Upload only through approved infrastructure and source-access arrangements. Original context bytes are not displayed or saved in browser storage. The optional field report can contain supplied conclusion text.</p>
        <button className={button} disabled={locked || !canaryFile} onClick={() => void checkEvidence()}>Verify canary and context bytes</button>
      </div>}
      {evidence && <div className="space-y-2 rounded border border-sage-border p-3 text-sm" role="status" aria-label="Byte integrity snapshot">
        <h4 className="font-semibold">Exact canary replay verified</h4>
        <p>Context files hashed: {evidence.contextCount.toLocaleString("en-US")}. Context bytes hashed: {evidence.contextBytes.toLocaleString("en-US")}.</p>
        {evidence.contextCount === 0 && <p>No context files were required by this review log. This is not evidence that any source was accessed or any scientific result was verified.</p>}
        <p>This historical integrity check does not verify source permissions, independent human review, scientific correctness, collective scientific signoff or ML authorization. It records no declaration.</p>
        <button className={button} disabled={locked} onClick={() => void showQuality()}>Show verified field report</button>
        <p className="text-xs">Reads the same local canary and conclusion against these exact hashes; no additional source upload or declaration is sent. Includes recorded human proposals and potentially sensitive small-group summaries. It is not a replacement for the complete offline review report.</p>
        <details><summary>Byte integrity references</summary><dl className="break-all text-xs"><dt>Canary SHA-256</dt><dd>{evidence.canarySha256}</dd>
          <dt>Selected checker implementation SHA-256, not runtime attestation</dt><dd>{evidence.implementationSha256}</dd>
          <dt>Server-observed upload SHA-256</dt><dd>{evidence.inputSha256}</dd></dl></details>
      </div>}
      {coverage && <div className="space-y-2" role="status" aria-label="Joint declaration snapshot">
        <p className="font-semibold">{coverage.account_declarations_complete ? "Account declarations complete for this snapshot" : "Account declarations incomplete for this snapshot"}</p>
        <dl className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
          {([["Required declarations", coverage.required_declaration_count], ["Matching declarations", coverage.matching_declaration_count],
            ["Missing declarations", coverage.missing_declaration_count], ["Withdrawn declarations", coverage.withdrawn_declaration_count],
            ["Stale declarations", coverage.stale_declaration_count]] as const).map(([label, count]) => <div key={label}><dt>{label}</dt><dd>{count.toLocaleString("en-US")}</dd></div>)}
          <div><dt>Your declaration status</dt><dd>{coverage.own_declaration_status}</dd></div>
          <div><dt>Conclusion author matches this snapshot</dt><dd>{coverage.conclusion_author_declaration_current ? "Yes" : "No"}</dd></div>
        </dl>
        <p className="break-all text-xs">Snapshot started (UTC): {coverage.snapshot_started_at}</p>
        <p className="text-sm">This historical snapshot can become stale after a withdrawal, participation change or document revision. It is not collective scientific signoff, independent human review verification, source permission or ML authorization. Recheck before relying on these counts.</p>
      </div>}
      <h4 className="font-semibold">Exact declaration wording</h4><p className="whitespace-pre-wrap text-sm">{wording.declaration_text}</p>
      <p className="break-all text-xs">{wording.declaration_version} · SHA-256: {wording.declaration_sha256}</p>
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={consent} disabled={locked || !canPreview} onChange={e => { setConsent(e.target.checked); setDraft(null); setConfirmed(false); }} />
        <span>{action === "withdraw" ? "I have reviewed the exact prior declaration, its scope and the withdrawal wording. I intend to withdraw that declaration without erasing its history."
          : "I have read the complete original documents, my declaration scope and the exact wording. I take responsibility for my recorded assessments and limitations."}</span></label>
      <button className={button} disabled={locked || !canPreview || !consent} onClick={() => void preview()}>Preview review declaration</button>
    </section>}
    {quality && <MlPilotQualityReport key={quality.canarySha256 + quality.conclusionSha256} value={quality} />}
    {draft && <section className={panel} aria-label="Review declaration preview"><h3 ref={previewHeading} tabIndex={-1} className="scroll-mt-24 font-semibold">Exact preview — not yet committed</h3>
      <p className="text-sm">Review the account, action, basis and predecessor. Preserve this original key and hash privately for recovery. Committing repeats server-side checks; the earlier document check is not an approval token.</p>
      <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(draft.result.intent, null, 2)}</pre><p className="break-all text-xs">Intent SHA-256: {draft.recovery.intentSha256}</p>
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={confirmed} disabled={locked} onChange={e => setConfirmed(e.target.checked)} /><span>I confirm this exact preview and want to record this action.</span></label>
      <button className={button} disabled={locked || !confirmed} onClick={() => void commit()}>Commit exact review declaration</button>
    </section>}
    {receipt?.declaration && <section className={panel} aria-label="Historical review receipt"><h3 ref={receiptHeading} tabIndex={-1} className="scroll-mt-24 font-semibold">Historical review declaration receipt</h3>
      <p>Recorded action: {receipt.intent.action}. {receipt.replayed ? "Recovered existing record." : "New record committed."}</p>
      <Basis value={receipt.declaration.basis} /><pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(receipt.declaration, null, 2)}</pre>
      <p className="text-sm">This receipt stays historical after withdrawal or later revisions. It is not current collective signoff, scientific acceptance or ML authorization.</p>
    </section>}
    <section className={panel} aria-label="Manual review recovery"><h3 className="font-semibold">Recover an earlier review operation</h3><p className="text-sm">Use the original declaration key and intent hash under the original account. No invitation, source upload or current reviewer grant is required.</p>
      <label className="block text-sm">Recovery request key<input className={field} maxLength={120} autoComplete="off" spellCheck={false} value={manualKey} disabled={locked || !wording} onChange={e => setManualKey(e.target.value)} /></label>
      <label className="block text-sm">Recovery intent SHA-256<input className={field} maxLength={64} autoComplete="off" spellCheck={false} value={manualHash} disabled={locked || !wording} onChange={e => setManualHash(e.target.value)} /></label>
      <button className={button} disabled={locked || !wording || !pilotKey(manualKey) || !pilotHash(manualHash)} onClick={() => void recover(true)}>Recover historical review declaration</button>
    </section>
  </div>;
}
