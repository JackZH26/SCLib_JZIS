"use client";

import { useEffect, useRef, useState } from "react";
import { useDashboardUser } from "@/components/dashboard/user-context";
import { ApiError, sourceExpressionCapabilities, sourceExpressionCaptureDetail, sourceExpressionCaptures, sourceExpressionCommit,
  sourceExpressionDetail, sourceExpressionList, sourceExpressionOutcome, sourceExpressionPreview } from "@/lib/api";
import { onAuthChange } from "@/lib/auth-session";
import { EXPRESSION_FIELDS, EXPRESSION_PAGE_SIZE, MAX_PACKAGE_BYTES, ExpressionPackageError, expressionCanonical, expressionFieldLabel, expressionRecovery, expressionSourceHref,
  knownCapturePage, knownExpressionCapabilities, knownExpressionPage, knownExpressionReceipt, knownSourceCapture, knownSourceRevision,
  prepareExpressionPackage, sourceValueLabel, type CapturePage, type ExpressionCapabilities, type ExpressionFilters, type ExpressionImportRequest, type ExpressionRequest,
  type ExpressionLocator, type ExpressionPage, type ExpressionReceipt, type ExpressionRecovery, type PreparedExpressionPackage, type SourceCapture, type SourceRevision, type SourceValue } from "@/lib/source-expressions";

const button = "rounded border border-sage-border bg-white px-3 py-2 text-sm text-accent-deep hover:bg-sage-surface disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2";
const input = "min-w-0 w-full rounded border border-sage-border bg-white p-2 text-sm";
const panel = "min-w-0 rounded-lg border border-sage-border bg-white p-4 space-y-3";
const wording = (value: string) => value.replaceAll("_", " ");
const roles: Record<string, string> = { source_reported: "Source reported", source_fitted: "Source fitted", source_model_estimate: "Source model estimate", source_proposed: "Source proposed" };
const conditionRoles: Record<string, string> = { reported_result_condition: "Reported result condition", study_extent: "Study extent", synthesis_condition: "Synthesis condition", fit_window: "Fit window" };
const missing = "Not supplied in this expression";
type Phase = "idle" | "loading" | "reading" | "previewing" | "committing" | "unknown" | "checking";
type Draft = { request: ExpressionImportRequest; preview: ExpressionReceipt; ref: ExpressionRecovery };

async function bounded<T>(call: () => Promise<T>, controller: AbortController): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try { return await Promise.race([call(), new Promise<never>((_, reject) => { timer = setTimeout(() => { controller.abort(); reject(new Error("Private operation timed out")); }, 25000); })]); }
  finally { if (timer) clearTimeout(timer); }
}
function Locator({ value }: { value: ExpressionLocator }) {
  const parts = Object.entries(value).filter(([, item]) => item !== null);
  return <p className="text-xs text-sage-muted [overflow-wrap:anywhere]">{parts.length ? parts.map(([key, item]) => `${wording(key)} ${item}`).join(" · ") : "Source locator not supplied"}</p>;
}
function SpanLocations({ value }: { value: ExpressionRequest }) {
  const groups = [
    { label: "Formula", spans: value.subject.formula_spans }, { label: "Sample label", spans: value.subject.sample_label_spans },
    { label: "Window label", spans: value.window.label_spans }, { label: "Source model", spans: value.model_spans },
    { label: "Source value", spans: value.value_spans }, { label: "Printed unit", spans: value.unit_spans }, { label: "Origin basis", spans: value.origin_basis.spans },
    ...value.conditions.flatMap((condition, index) => [{ label: `${expressionFieldLabel(condition.field_id)} condition ${index + 1}`, spans: condition.value_spans }, { label: `Condition ${index + 1} unit`, spans: condition.unit_spans }]),
  ].filter(group => group.spans.length > 0);
  return <details className="text-xs text-sage-muted"><summary className="cursor-pointer">Exact retained text spans</summary><p className="mt-2">Unicode codepoint offsets in the retained fragment; start is inclusive and end is exclusive.</p><dl className="mt-2 space-y-2 [overflow-wrap:anywhere]">{groups.map(group => <div key={group.label}><dt className="font-medium">{group.label}</dt>{group.spans.map((span, index) => <dd key={index}>{span.start} to {span.end} · SHA256 {span.sha256}</dd>)}</div>)}</dl></details>;
}
function Quantity({ value }: { value: SourceValue }) {
  return <div className="space-y-1 min-w-0 [overflow-wrap:anywhere]"><p className="font-medium text-sage-ink whitespace-pre-wrap">{sourceValueLabel(value)}</p>
    {"raw_unit" in value && <>
      {value.status === "parsed" ? <p className="text-xs text-sage-muted">Normalized: {value.approximate ? "≈ " : ""}{value.value}{value.uncertainty === null ? "" : ` ± ${value.uncertainty}`} {value.unit}{value.uncertainty === null ? "" : " · uncertainty interpretation unspecified"}</p>
        : <p className="text-xs text-amber-900">{value.status === "unit_not_supplied" ? "Unit not supplied; no numerical interpretation assigned" : value.status === "unit_requires_review" ? "Unit requires interpretation" : "Source value requires interpretation"}</p>}
    </>}
  </div>;
}
function CaptureScope({ value }: { value: SourceCapture }) {
  const href = expressionSourceHref(value.source.url);
  return <div className="min-w-0 space-y-2 text-sm [overflow-wrap:anywhere]">
    <p className="font-medium">{value.source.source_id}</p><p>{wording(value.source.kind)} · {wording(value.source.content_kind)} · {value.retained_utf8_bytes.toLocaleString("en-US")} retained UTF-8 bytes</p>
    <p>{value.latest_retained_capture_for_source ? "Latest retained capture in this ledger" : "Earlier retained capture in this ledger"}. Publication currentness remains unverified.</p>
    <dl className="grid gap-x-5 gap-y-2 sm:grid-cols-2"><div><dt className="text-xs text-sage-muted">Declared publication revision</dt><dd>{value.source.revision ?? "Unresolved"}</dd></div>
      <div><dt className="text-xs text-sage-muted">Declared currentness</dt><dd>{wording(value.source.currentness)}</dd></div>
      <div><dt className="text-xs text-sage-muted">Declared rights scope</dt><dd>{wording(value.source.rights_status)}</dd></div>
      <div><dt className="text-xs text-sage-muted">Captured at</dt><dd>{value.source.captured_at}</dd></div></dl>
    <p className="text-xs text-sage-muted">The server verifies the retained fragment bytes. The parent file, publication revision, rights and currentness are caller declarations.</p>
    {href && <a href={href} target="_blank" rel="noopener noreferrer" className="text-accent-deep underline">Open declared source link</a>}
    <details className="text-xs text-sage-muted"><summary className="cursor-pointer">Fragment and parent hashes</summary><dl className="mt-2 space-y-2">
      <div><dt>Verified retained-fragment SHA256</dt><dd>{value.source_content_sha256}</dd></div><div><dt>Declared parent-file SHA256, unverified</dt><dd>{value.source.original_parent_sha256 ?? "Not supplied"}</dd></div>
      <div><dt>Source metadata SHA256</dt><dd>{value.metadata_sha256}</dd></div><div><dt>Capture record SHA256</dt><dd>{value.record_sha256}</dd></div>
    </dl></details>
  </div>;
}
function Revision({ value, inspectPrevious, locked }: { value: SourceRevision; inspectPrevious: (id: string, sha: string) => void; locked: boolean }) {
  const p = value.projection;
  return <section className={panel} aria-label="Exact source expression revision">
    <div className="flex flex-wrap items-start justify-between gap-2"><div><h3 className="font-semibold text-sage-ink">{p.subject.formula} · {expressionFieldLabel(p.field_id)}</h3><p className="text-xs text-sage-muted">Revision {value.revision_number} · {value.is_expression_head ? "Current ledger head" : "Historical ledger revision"}</p></div><span className="rounded bg-sage-surface px-2 py-1 text-xs text-accent-deep">Pending source expression</span></div>
    <Quantity value={p.value} />
    <dl className="grid gap-3 text-sm sm:grid-cols-2"><div><dt className="text-xs text-sage-muted">Source window</dt><dd className="[overflow-wrap:anywhere]">{p.window.raw_label ?? missing}</dd></div><div><dt className="text-xs text-sage-muted">Role and origin</dt><dd>{roles[p.source_role]} · {p.knowledge_origin}</dd></div>
      <div><dt className="text-xs text-sage-muted">Sample label</dt><dd>{p.subject.sample_label ?? missing}</dd></div><div><dt className="text-xs text-sage-muted">Source model</dt><dd>{p.model ?? missing}</dd></div></dl>
    {p.subject.formula_scope === "declared_formula_span_assembly" && <p className="text-xs text-sage-muted">Formula assembled from declared source text spans; physical identity is unestablished.</p>}
    {p.conditions.length > 0 && <div className="border-t border-sage-border pt-3 space-y-3"><h4 className="text-sm font-medium">Conditions in this source window</h4>{p.conditions.map((condition, index) => <div key={index}><p className="text-xs text-sage-muted">{expressionFieldLabel(condition.field_id)} · {conditionRoles[condition.role]}</p><Quantity value={condition.value} /></div>)}</div>}
    <details className="border-t border-sage-border pt-3 text-sm"><summary className="cursor-pointer text-accent-deep">Source locator and provenance</summary><div className="mt-3 space-y-3"><Locator value={p.locator} />
      {(p.origin_basis.statement || p.origin_basis.retained_text) && <div><h4 className="text-xs text-sage-muted">Declared origin basis</h4><p className="whitespace-pre-wrap [overflow-wrap:anywhere]">{p.origin_basis.statement}</p><p className="whitespace-pre-wrap [overflow-wrap:anywhere]">{p.origin_basis.retained_text}</p></div>}
      <CaptureScope value={value.capture} /><SpanLocations value={value.source_entry} /><p className="text-xs text-sage-muted [overflow-wrap:anywhere]">Window identity: {p.window.id}<br />Revision identity: {value.id}<br />Expression record: {value.record_sha256}<br />Original entry: {value.source_entry_sha256}</p>
      {value.predecessor_id && value.predecessor_sha256 && <button type="button" className={button} disabled={locked} onClick={() => inspectPrevious(value.predecessor_id!, value.predecessor_sha256!)}>Inspect preceding revision</button>}
    </div></details>
  </section>;
}

export function SourceExpressionWorkbench() {
  const { user } = useDashboardUser();
  const [access, setAccess] = useState<ExpressionCapabilities | null>(null), [prepared, setPrepared] = useState<PreparedExpressionPackage | null>(null);
  const [page, setPage] = useState<ExpressionPage | null>(null), [captures, setCaptures] = useState<CapturePage | null>(null);
  const [detail, setDetail] = useState<SourceRevision | null>(null), [captureDetail, setCaptureDetail] = useState<SourceCapture | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null), [receipt, setReceipt] = useState<ExpressionReceipt | null>(null), [recovery, setRecovery] = useState<ExpressionRecovery | null>(null);
  const [field, setField] = useState(""), [sourceId, setSourceId] = useState(""), [currentness, setCurrentness] = useState("");
  const [applied, setApplied] = useState<ExpressionFilters>({}), [phase, setPhase] = useState<Phase>("idle"), [message, setMessage] = useState<string | null>(null);
  const mounted = useRef(false), seq = useRef(0), controller = useRef<AbortController | null>(null), retained = useRef<ExpressionRecovery | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const visibleAccess = access?.actor_user_id === user.id ? access : null;
  const busy = !["idle", "unknown"].includes(phase), locked = busy || recovery !== null;
  function clearRecords() { setPage(null); setCaptures(null); setDetail(null); setCaptureDetail(null); }
  function clearDraft() { setDraft(null); setReceipt(null); }
  function clearPrivate() {
    ++seq.current; controller.current?.abort(); setAccess(null); setPrepared(null); clearRecords(); clearDraft(); setRecovery(null); retained.current = null; setPhase("idle");
    if (fileInput.current) fileInput.current.value = "";
  }
  function begin() { const version = ++seq.current; controller.current?.abort(); const next = new AbortController(); controller.current = next;
    return { signal: next.signal, active: () => mounted.current && version === seq.current, run: <T,>(call: () => Promise<T>) => bounded(call, next) }; }
  function failure(error: unknown) {
    clearRecords(); clearDraft(); setPhase("idle");
    if (error instanceof ApiError && [401, 403].includes(error.status)) { clearPrivate(); setMessage("Session or research access changed. Private information has been cleared; refresh access."); }
    else if (error instanceof ApiError && error.status === 404) setMessage("This source-expression interface or record is unavailable. No history was inferred.");
    else if (error instanceof ApiError && error.status === 409) setMessage("The request or current expression head changed. Reload the record and prepare an exact new package preview.");
    else setMessage("The response could not be verified. Refresh access or reload the record before continuing.");
  }
  async function readLists(op: ReturnType<typeof begin>, filters: ExpressionFilters, expressionOffset = 0, captureOffset = 0, expressionLimit = visibleAccess?.max_expression_page_size ?? EXPRESSION_PAGE_SIZE) {
    const [expressionWire, captureWire] = await Promise.all([op.run(() => sourceExpressionList(expressionOffset, expressionLimit, filters, op.signal)), op.run(() => sourceExpressionCaptures(captureOffset, 25, filters.currentness, op.signal))]);
    const [nextPage, nextCaptures] = await Promise.all([knownExpressionPage(expressionWire, expressionOffset, expressionLimit, filters), knownCapturePage(captureWire, captureOffset, 25, filters.currentness)]);
    if (!op.active()) return; if (!nextPage || !nextCaptures) throw new Error("Unsupported source window"); setPage(nextPage); setCaptures(nextCaptures); setPhase("idle");
  }
  async function refreshAccess() {
    const op = begin(); clearRecords(); clearDraft(); setPrepared(null); if (fileInput.current) fileInput.current.value = "";
    setAccess(null); setField(""); setSourceId(""); setCurrentness(""); setApplied({}); setPhase("loading"); setMessage(null);
    try { const current = knownExpressionCapabilities(await op.run(() => sourceExpressionCapabilities(op.signal)), user.id); if (!op.active()) return; if (!current) throw new Error("Unsupported capabilities"); setAccess(current);
      if (retained.current?.actorId === current.actor_user_id) { setRecovery(retained.current); setPhase("unknown"); setMessage("The original submission still needs an outcome check. No write will be retried."); return; }
      retained.current = null; setRecovery(null); await readLists(op, {}, 0, 0, current.max_expression_page_size);
    } catch (error) { if (op.active()) { setAccess(null); failure(error); } }
  }
  useEffect(() => {
    mounted.current = true; clearPrivate(); void refreshAccess(); const unsubscribe = onAuthChange(() => { clearPrivate(); setMessage("Session changed. Private information has been cleared; refresh access to continue."); });
    return () => { unsubscribe(); mounted.current = false; ++seq.current; controller.current?.abort(); };
    // All retained private state belongs to this authenticated dashboard identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user.id]);
  useEffect(() => { const warn = (event: BeforeUnloadEvent) => { if (retained.current) { event.preventDefault(); event.returnValue = ""; } }; window.addEventListener("beforeunload", warn); return () => window.removeEventListener("beforeunload", warn); }, []);
  async function chooseFile(file: File | undefined) {
    if (!visibleAccess?.can_import || locked) return; const op = begin(); setPrepared(null); clearDraft(); setPhase("reading"); setMessage(null);
    try { if (!file || file.size < 1 || file.size > MAX_PACKAGE_BYTES) throw new ExpressionPackageError("Choose a source-package JSON file of at most 1 MiB.");
      const bytes = new Uint8Array(await op.run(() => file.arrayBuffer())); const value = await op.run(() => prepareExpressionPackage(bytes, file.name)); if (!op.active()) return; setPrepared(value); setPhase("idle"); setMessage("Local package checks passed. No source data has been sent. Preview explicitly before saving.");
    } catch (error) { if (op.active()) { setPrepared(null); setPhase("idle"); setMessage(error instanceof ExpressionPackageError ? error.message : "The source package could not be read as bounded UTF-8 JSON."); } }
  }
  async function preview() {
    if (!visibleAccess?.can_import || !prepared || locked) return; const current = visibleAccess, selected = prepared, op = begin(); clearDraft(); setPhase("previewing"); setMessage(null);
    try { const request = { request_key: `source-expression:${crypto.randomUUID()}`, package: selected.package }, ref = expressionRecovery(selected, current, request.request_key);
      const value = await knownExpressionReceipt(await op.run(() => sourceExpressionPreview(request, op.signal)), current, ref, "preview", selected);
      if (!op.active()) return; if (!value) throw new Error("Unverified preview");
      if (value.replayed) { setReceipt(value); setMessage("This original request is already saved. Its historical receipt is shown."); }
      else setDraft({ request, preview: value, ref: { ...ref, previewSha: value.preview_sha256, manifestCanonical: expressionCanonical(value.expression_manifest) } });
      setPhase("idle");
    } catch (error) { if (op.active()) failure(error); }
  }
  async function commit() {
    if (!visibleAccess?.can_import || !draft || locked) return; const current = visibleAccess, selected = draft, op = begin(); retained.current = selected.ref; setPhase("committing"); setMessage(null);
    try { const value = await knownExpressionReceipt(await op.run(() => sourceExpressionCommit(selected.request, selected.ref.previewSha, op.signal)), current, selected.ref, "commit");
      if (!op.active()) return; if (!value) throw new Error("Unverified commit"); retained.current = null; setRecovery(null); setDraft(null); setPrepared(null); if (fileInput.current) fileInput.current.value = ""; clearRecords(); setReceipt(value); setPhase("idle"); setMessage("Saved to private pending history. Refresh records to inspect the retained expressions.");
    } catch (error) { if (!op.active()) return;
      if (error instanceof ApiError && [400, 401, 403, 409, 413, 415, 422].includes(error.status)) { retained.current = null; setRecovery(null); failure(error); }
      else { setPrepared(null); clearDraft(); clearRecords(); setRecovery(selected.ref); setPhase("unknown"); setMessage("Save outcome is unknown. Check the original request; no write will be retried. An unavailable receipt does not prove failure."); }
    }
  }
  async function checkOutcome() {
    if (!visibleAccess?.can_import || !recovery || busy || recovery.actorId !== visibleAccess.actor_user_id) return; const current = visibleAccess, ref = recovery, op = begin(); setPhase("checking"); setMessage(null);
    try { const value = await knownExpressionReceipt(await op.run(() => sourceExpressionOutcome(ref.requestKey, ref.requestSha, op.signal)), current, ref, "outcome");
      if (!op.active()) return; if (!value) throw new Error("Unverified outcome"); retained.current = null; setRecovery(null); setReceipt(value); setPhase("idle"); setMessage("The original submission is saved. No new write was sent; refresh records for the current heads.");
    } catch (error) { if (!op.active()) return; if (error instanceof ApiError && [401, 403].includes(error.status)) { clearPrivate(); setMessage("Session or research access changed. Private information has been cleared."); }
      else { setPhase("unknown"); setMessage("The original outcome remains unverified. No rollback or failed save is inferred; no write was retried."); } }
  }
  async function loadLists(expressionOffset: number, captureOffset: number, filters = applied) {
    if (!visibleAccess || locked) return; const op = begin(); clearRecords(); clearDraft(); setPhase("loading"); setMessage(null); setApplied(filters);
    try { await readLists(op, filters, expressionOffset, captureOffset); } catch (error) { if (op.active()) failure(error); }
  }
  async function inspect(id: string, recordSha?: string) {
    if (!visibleAccess || locked) return; const op = begin(); setDetail(null); setCaptureDetail(null); clearDraft(); setPhase("loading"); setMessage(null);
    try { const value = await knownSourceRevision(await op.run(() => sourceExpressionDetail(id, op.signal)), id, recordSha); if (!op.active()) return; if (!value) throw new Error("Unverified revision"); setDetail(value); setPhase("idle"); }
    catch (error) { if (op.active()) failure(error); }
  }
  async function inspectCapture(item: SourceCapture) {
    if (!visibleAccess || locked) return; const op = begin(); setCaptureDetail(null); setDetail(null); clearDraft(); setPhase("loading"); setMessage(null);
    try { const value = await knownSourceCapture(await op.run(() => sourceExpressionCaptureDetail(item.id, op.signal)), item.id, item); if (!op.active()) return; if (!value) throw new Error("Unverified capture"); setCaptureDetail(value); setPhase("idle"); }
    catch (error) { if (op.active()) failure(error); }
  }
  function editFilters() { clearDraft(); }
  return <div className="space-y-5 min-w-0">
    <header className="space-y-2"><p className="text-xs font-medium uppercase tracking-wide text-accent-deep">Private research workspace</p><h2 className="text-2xl font-semibold text-sage-ink">Source expressions</h2>
      <p className="text-sm text-sage-muted">Retain exact source fragments and inspect typed values in their original subject and condition windows.</p>
      <p className="text-xs text-sage-muted">Pending source expressions do not establish sample, phase or selected-result associations, scientific acceptance or public distribution rights.</p></header>
    <div className="flex flex-wrap gap-3 items-center"><button type="button" className={button} disabled={busy} onClick={() => void refreshAccess()}>Refresh access and records</button>
      <span className="text-xs text-sage-muted">{visibleAccess ? visibleAccess.can_import ? "Curator access: preview and save" : "Read access" : "Research access required"}</span></div>
    {message && <p role="status" aria-live="polite" className="rounded border border-sage-border bg-sage-surface p-3 text-sm">{message}</p>}
    {busy && <p role="status" className="text-sm text-sage-muted">{phase === "reading" ? "Checking package locally…" : phase === "committing" ? "Saving the explicit pending package…" : "Loading private source history…"}</p>}
    {visibleAccess && <>
      {recovery && <section className={panel} aria-label="Unknown save outcome"><h3 className="font-semibold">Check original save outcome</h3><p className="text-sm">Use the original request identity. This action reads the saved receipt and sends no new package.</p><button type="button" className={button} disabled={busy || !visibleAccess.can_import} onClick={() => void checkOutcome()}>Check original request</button></section>}
      {visibleAccess.can_import && !recovery && <section className={panel} aria-label="New source package"><div><h3 className="font-semibold text-sage-ink">Prepare a source package</h3><p className="text-sm text-sage-muted">JSON package, at most 1 MiB; retained fragment at most 128 KiB; up to 20 expressions. File selection stays local.</p></div>
        <label className="block text-sm">Source-package JSON file<input ref={fileInput} type="file" accept=".json,application/json" disabled={locked} onChange={event => void chooseFile(event.target.files?.[0])} className="mt-2 block max-w-full w-full min-w-0 text-sm file:mr-3 file:rounded file:border file:border-sage-border file:bg-sage-surface file:px-3 file:py-2" /></label>
        {prepared && <div className="space-y-3 min-w-0"><p className="text-sm [overflow-wrap:anywhere]">{prepared.fileName} · {prepared.localExpressions.length} source expressions · {prepared.retainedBytes.toLocaleString("en-US")} retained bytes</p>
          <p className="text-xs text-sage-muted">{prepared.package.source.source_id} · {wording(prepared.package.source.kind)} · declared currentness: {wording(prepared.package.source.currentness)}</p>
          <ol className="divide-y divide-sage-border">{prepared.localExpressions.map(entry => <li key={entry.expressionKey} className="py-3 space-y-1 [overflow-wrap:anywhere]"><p className="text-sm font-medium">{entry.formula} · {expressionFieldLabel(entry.field)}</p><p className="whitespace-pre-wrap text-sm">{entry.rawValue}{entry.rawUnit && !entry.rawValue.trim().endsWith(entry.rawUnit) ? ` ${entry.rawUnit}` : ""}</p><p className="text-xs text-sage-muted">{roles[entry.role]} · {entry.origin} · {entry.window ?? "Source window label not supplied"}</p>
            <details className="text-xs text-sage-muted"><summary className="cursor-pointer">Conditions and source scope</summary><div className="mt-2 space-y-2"><p>Sample label: {entry.sampleLabel ?? missing} · Model: {entry.model ?? missing}</p>
              {entry.conditions.map((condition, index) => <p key={index}>{expressionFieldLabel(condition.field)} ({conditionRoles[condition.role]}): {condition.rawValue}{condition.rawUnit && !condition.rawValue.trim().endsWith(condition.rawUnit) ? ` ${condition.rawUnit}` : ""}</p>)}<Locator value={entry.locator} />
              <p>{entry.formulaScope === "declared_formula_span_assembly" ? "Formula assembled from declared spans" : "Formula from one retained span"}. Physical identity remains unestablished.</p>
              {(entry.originStatement || entry.originText) && <p className="whitespace-pre-wrap">Declared origin basis: {entry.originStatement ?? entry.originText}</p>}
            </div></details></li>)}</ol>
          <details className="text-xs text-sage-muted"><summary className="cursor-pointer">Package fingerprints and declared source</summary><dl className="mt-2 space-y-2 [overflow-wrap:anywhere]"><div><dt>Local file SHA256</dt><dd>{prepared.fileSha}</dd></div><div><dt>Retained fragment SHA256</dt><dd>{prepared.package.source_content_sha256}</dd></div><div><dt>Declared parent SHA256, unverified</dt><dd>{prepared.package.source.original_parent_sha256 ?? "Not supplied"}</dd></div><div><dt>Package metadata SHA256</dt><dd>{prepared.packageSha}</dd></div><div><dt>Declared source link</dt><dd>{prepared.package.source.url}</dd></div></dl></details>
          <button type="button" className={button} disabled={locked} onClick={() => void preview()}>Preview pending package</button>
        </div>}
        {draft && <div className="rounded border border-sage-border bg-sage-surface p-3 space-y-3"><p className="text-sm">Preview passed: {draft.preview.expression_count} pending expression revisions. Saving retains the private fragment and appends these records.</p><button type="button" className={`${button} bg-accent-deep text-white hover:bg-accent`} disabled={locked} onClick={() => void commit()}>Save pending source expressions</button></div>}
      </section>}
      {receipt && <section className={panel} aria-label="Saved source package receipt"><h3 className="font-semibold">Saved pending history</h3><p className="text-sm">{receipt.expression_count} expression revisions retained{receipt.replayed ? " · original saved receipt" : ""}. These are source records, not independent experiments.</p><details className="text-xs text-sage-muted"><summary className="cursor-pointer">Operation receipt</summary><dl className="mt-2 space-y-2 [overflow-wrap:anywhere]"><div><dt>Receipt SHA256</dt><dd>{receipt.receipt_sha256}</dd></div><div><dt>Request SHA256</dt><dd>{receipt.request_sha256}</dd></div><div><dt>Package SHA256</dt><dd>{receipt.package_sha256}</dd></div></dl></details></section>}
      <section className={panel} aria-label="Retained expression heads"><h3 className="font-semibold text-sage-ink">Current expression heads</h3><p className="text-xs text-sage-muted">Latest pending revision for each ledger identity. This does not determine current publication status.</p>
        <form onSubmit={event => { event.preventDefault(); void loadLists(0, 0, { field: field || undefined, sourceId: sourceId.trim() || undefined, currentness: currentness || undefined }); }} className="grid gap-3 sm:grid-cols-3">
          <label className="text-xs text-sage-muted">Field<select className={`${input} mt-1`} value={field} disabled={locked} onChange={event => { setField(event.target.value); editFilters(); }}><option value="">All fields</option>{Object.keys(EXPRESSION_FIELDS).map(key => <option value={key} key={key}>{expressionFieldLabel(key)}</option>)}</select></label>
          <label className="text-xs text-sage-muted">Source identity<input className={`${input} mt-1`} value={sourceId} maxLength={160} disabled={locked} onChange={event => { setSourceId(event.target.value); editFilters(); }} placeholder="All sources" /></label>
          <label className="text-xs text-sage-muted">Declared currentness<select className={`${input} mt-1`} value={currentness} disabled={locked} onChange={event => { setCurrentness(event.target.value); editFilters(); }}><option value="">Any declaration</option><option value="unresolved">Unresolved</option><option value="declared_current">Declared current</option><option value="historical">Historical</option></select></label>
          <div className="flex flex-wrap gap-2 sm:col-span-3"><button className={button} disabled={locked} type="submit">Apply filters</button><button className={button} disabled={locked} type="button" onClick={() => { setField(""); setSourceId(""); setCurrentness(""); void loadLists(0, 0, {}); }}>Clear filters</button></div>
        </form>
        {page && <><p className="text-xs text-sage-muted">{page.total} current pending expression heads; showing {page.expressions.length} from offset {page.offset}.</p>
          {page.expressions.length === 0 && <p className="text-sm text-sage-muted">No retained expressions in this bounded view.</p>}
          <ol className="divide-y divide-sage-border">{page.expressions.map(item => <li key={item.id} className="grid gap-3 py-3 sm:grid-cols-[minmax(0,1fr)_auto] min-w-0"><div className="space-y-1 [overflow-wrap:anywhere]"><p className="text-sm font-medium">{item.projection.subject.formula} · {expressionFieldLabel(item.projection.field_id)}</p><Quantity value={item.projection.value} /><p className="text-xs text-sage-muted">{item.capture.source.source_id} · {roles[item.projection.source_role]} · {item.projection.knowledge_origin} · Revision {item.revision_number}</p><p className="text-xs text-sage-muted">{item.projection.window.raw_label ?? "Source window label not supplied"}</p></div><button type="button" className={`${button} self-start`} disabled={locked} onClick={() => void inspect(item.id, item.record_sha256)}>Inspect expression</button></li>)}</ol>
          <div className="flex flex-wrap gap-2"><button type="button" className={button} disabled={locked || page.offset === 0} onClick={() => void loadLists(Math.max(0, page.offset - page.limit), captures?.offset ?? 0)}>Previous expressions</button><button type="button" className={button} disabled={locked || page.offset + page.limit >= page.total || page.offset + page.limit > 10000} onClick={() => void loadLists(page.offset + page.limit, captures?.offset ?? 0)}>Next expressions</button></div>
        </>}
      </section>
      {detail && <Revision value={detail} inspectPrevious={(id, sha) => void inspect(id, sha)} locked={locked} />}
      <details className={panel}><summary className="cursor-pointer font-semibold text-accent-deep">Retained captures{captures ? ` (${captures.total})` : ""}</summary><p className="text-xs text-sage-muted">Bounded retained fragments, not publications or independent experiments. Currentness filters use the caller declaration.</p>
        {captures && <><ol className="divide-y divide-sage-border">{captures.captures.map(item => <li key={item.id} className="grid gap-2 py-3 sm:grid-cols-[minmax(0,1fr)_auto] [overflow-wrap:anywhere]"><div><p className="text-sm font-medium">{item.source.source_id}</p><p className="text-xs text-sage-muted">{item.source.revision ?? "Revision unresolved"} · {item.retained_utf8_bytes.toLocaleString("en-US")} retained bytes · {wording(item.source.currentness)}</p></div><button type="button" className={button} disabled={locked} onClick={() => void inspectCapture(item)}>Inspect capture scope</button></li>)}</ol>
          <div className="flex flex-wrap gap-2"><button type="button" className={button} disabled={locked || captures.offset === 0} onClick={() => void loadLists(page?.offset ?? 0, Math.max(0, captures.offset - 25))}>Previous captures</button><button type="button" className={button} disabled={locked || captures.offset + 25 >= captures.total || captures.offset + 25 > 10000} onClick={() => void loadLists(page?.offset ?? 0, captures.offset + 25)}>Next captures</button></div>
        </>}
      </details>
      {captureDetail && <section className={panel} aria-label="Retained capture scope"><h3 className="font-semibold">Retained capture scope</h3><CaptureScope value={captureDetail} /></section>}
    </>}
  </div>;
}
