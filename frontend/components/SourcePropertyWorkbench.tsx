"use client";

import { useEffect, useRef, useState } from "react";
import { useDashboardUser } from "@/components/dashboard/user-context";
import { ApiError, sourcePropertyCapabilities, sourcePropertyDetail, sourcePropertyDownload, sourcePropertyImportCommit,
  sourcePropertyImportOutcome, sourcePropertyImportPreview, sourcePropertyList, sourcePropertyReviewCommit, sourcePropertyReviewOutcome, sourcePropertyReviewPreview } from "@/lib/api";
import { onAuthChange } from "@/lib/auth-session";
import { canWithdrawPropertyNote, downloadPropertyDetail, knownPropertyCapabilities, knownPropertyDetail, knownPropertyImport,
  knownPropertyPage, knownPropertyReview, loadPropertyImportBytes, PROPERTY_CHECKS, PROPERTY_NOTE_ACTIONS, PROPERTY_SNAPSHOTS,
  propertyDigest, propertyFieldLabel, propertyImportRequestSha, propertySourceHref,
  type PropertyCapabilities, type PropertyDetail, type PropertyImportReceipt, type PropertyImportRequest, type PropertyNote, type PropertyNoteAction,
  type PropertyPage, type PropertyRecovery, type PropertyReviewRequest } from "@/lib/source-properties";

const button = "rounded border border-sage-border bg-white px-3 py-2 text-sm text-accent-deep hover:bg-sage-surface disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2";
const input = "min-w-0 w-full rounded border border-sage-border bg-white p-2 text-sm";
const panel = "min-w-0 rounded-lg border border-sage-border bg-white p-4 space-y-3";
const wording = (value: string) => value.replaceAll("_", " ");
const LABELS: Record<string, string> = { raw_value: "Source value", raw_unit: "Printed unit", unit: "Normalized unit", unit_basis: "Unit basis", unit_source_field: "Unit source field",
  uncertainty: "Uncertainty", raw_uncertainty: "Source uncertainty", pressure: "Pressure", pressure_gpa: "Pressure (GPa)", measurement_temperature_k: "Measurement temperature (K)",
  raw_row_label: "Source row", model_label: "Model", slope_temperature_window_raw: "Temperature window", magnetic_field_direction_raw: "Field direction", curve_criterion_raw: "Curve criterion" };
const NOTE_LABELS: Record<PropertyNoteAction, string> = { matches_inspected_source: "Matches inspected source", requires_clarification: "Requires clarification", source_mismatch: "Source mismatch", withdraw_note: "Withdraw my preceding note" };
const CHECK_LABELS: Record<string, string> = { source_expression: "Source value or statement", source_locator: "Source locator", raw_units: "Units and conversion", source_subject: "Source subject", source_window: "Conditions and source window", derivation_role: "Measurement, fit or derivation role" };
const profiles = ["quantity", "quantity_context", "cif_atomic_sites", "cif_declared_operations", "source_statement", "preparation", "unavailable"];
type Draft = { kind: "import"; request: PropertyImportRequest; preview: PropertyImportReceipt; ref: PropertyRecovery }
  | { kind: "review"; request: PropertyReviewRequest; preview: PropertyNote; ref: PropertyRecovery };
type Phase = "idle" | "loading" | "previewing" | "committing" | "unknown" | "checking" | "downloading";

/** Closed, validated source values only. Large coordinates/operations stay behind a disclosure. */
function Facts({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (value === null) return <span className="text-sage-muted">Not supplied in this source scope</span>;
  if (typeof value !== "object") return <span className="break-words">{String(value)}</span>;
  if (Array.isArray(value)) return <ol className="space-y-2 list-decimal pl-5">{value.map((item, index) => <li key={index}><Facts value={item} depth={depth + 1} /></li>)}</ol>;
  const fields = Object.entries(value as Record<string, unknown>);
  if (fields.some(([key]) => key === "raw_value")) {
    const q = value as Record<string, unknown>;
    return <div className="space-y-1"><p className="font-medium text-sage-ink">{q.approximate === true ? "≈ " : ""}{String(q.raw_display ?? q.raw_value)}{q.raw_unit ? ` ${q.raw_unit}` : ""}</p>
      {q.unit !== q.raw_unit && <p className="text-xs text-sage-muted">Normalized unit: {q.unit === null ? "unresolved" : String(q.unit)}{q.unit_basis ? ` · ${wording(String(q.unit_basis))}` : ""}</p>}
      {q.uncertainty !== null && q.uncertainty !== undefined && <p className="text-xs text-sage-muted">Uncertainty: {String(q.uncertainty)}{q.unit ? ` ${q.unit}` : ""}</p>}
      {typeof q.unit_review_reason === "string" && <p className="text-xs text-amber-900">{wording(q.unit_review_reason)}</p>}
      <details className="text-xs text-sage-muted"><summary className="cursor-pointer">Quantity and unit provenance</summary><dl className="mt-2 space-y-1">{fields.map(([key, item]) => <div key={key}><dt className="inline font-medium">{LABELS[key] ?? wording(key)}: </dt><dd className="inline"><Facts value={item} depth={depth + 1} /></dd></div>)}</dl></details>
    </div>;
  }
  return <dl className={depth ? "space-y-1" : "space-y-2"}>{fields.map(([key, item]) => <div key={key} className="min-w-0"><dt className="text-xs font-medium text-sage-muted">{LABELS[key] ?? wording(key)}</dt><dd className="text-sm"><Facts value={item} depth={depth + 1} /></dd></div>)}</dl>;
}
function ObservationEvidence({ detail }: { detail: PropertyDetail }) {
  const p = detail.projection, entry = p.source_entry;
  return <div className="space-y-4 [overflow-wrap:anywhere]">
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2"><div className="min-w-0"><p className="text-xs font-medium uppercase tracking-wide text-sage-muted">Source expression</p>
      {p.profile === "unavailable" ? <p className="mt-1">Full text or supplements were unavailable. This does not establish that the field was unreported.</p>
        : p.profile.startsWith("cif_") ? <details><summary className="cursor-pointer">{p.values.sites.length ? `${p.values.sites.length} listed ASU sites` : `${p.values.operations.length} declared operations`}</summary><div className="mt-2"><Facts value={entry.value} /></div></details>
          : <div className="mt-1"><Facts value={entry.value} /></div>}</div>
      <div className="min-w-0"><p className="text-xs font-medium uppercase tracking-wide text-sage-muted">Role</p><p className="text-sm">{wording(p.source_role)}</p><details className="mt-3"><summary className="cursor-pointer text-sm">Source subject and conditions</summary><div className="mt-2 space-y-3"><Facts value={p.subject} /><Facts value={p.window} /></div></details></div></div>
    <details><summary className="cursor-pointer text-sm">Sources and exact locators</summary><div className="mt-3 space-y-3">
      {p.provenance.sources.map((source, index) => <div key={index} className="border-l-2 border-sage-border pl-3">{propertySourceHref(source.source_url) && <a className="text-sm text-accent-deep underline" href={propertySourceHref(source.source_url)!} target="_blank" rel="noopener noreferrer">Open source {index + 1}</a>}<Facts value={source} /></div>)}
      <Facts value={p.provenance.field_locators} /></div></details>
    <details><summary className="cursor-pointer text-sm">Limits and record identity</summary><div className="mt-2 space-y-2 text-xs text-sage-muted">
      <Facts value={entry.limitations} /><p className="break-all">Source entry: {p.source_entry_id}</p><p className="break-all">Source pointer: {p.source_json_pointer}</p>
      <p className="break-all">Pending record: {detail.id} · {detail.record_sha256}</p><p className="break-all">Source JSON SHA-256: {detail.source_json_sha256}</p>
      <p className="break-all">Original batch SHA-256: {detail.original_batch_sha256}</p><p>Source preparation flags remain false. Saving pending history does not establish a material, sample, phase or selected-result association.</p>
    </div></details>
  </div>;
}
function bounded<T>(call: () => Promise<T>, controller: AbortController): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => controller.abort(), 30_000);
    const cleanup = () => { window.clearTimeout(timer); controller.signal.removeEventListener("abort", abort); };
    const abort = () => { cleanup(); reject(new Error("Operation interrupted")); };
    controller.signal.addEventListener("abort", abort, { once: true });
    if (controller.signal.aborted) { abort(); return; }
    try { call().then(value => { cleanup(); resolve(value); }, error => { cleanup(); reject(error); }); }
    catch (error) { cleanup(); reject(error); }
  });
}

export function SourcePropertyWorkbench() {
  const { user } = useDashboardUser();
  const [access, setAccess] = useState<PropertyCapabilities | null>(null), [page, setPage] = useState<PropertyPage | null>(null);
  const [detail, setDetail] = useState<PropertyDetail | null>(null), [draft, setDraft] = useState<Draft | null>(null);
  const [receipt, setReceipt] = useState<PropertyImportReceipt | PropertyNote | null>(null), [recovery, setRecovery] = useState<PropertyRecovery | null>(null);
  const [phase, setPhase] = useState<Phase>("idle"), [message, setMessage] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<string>(PROPERTY_SNAPSHOTS[0].sha256), [profile, setProfile] = useState("");
  const [action, setAction] = useState<PropertyNoteAction>("requires_clarification"), [checks, setChecks] = useState<string[]>([]);
  const [note, setNote] = useState(""), [attested, setAttested] = useState(false);
  const seq = useRef(0), mounted = useRef(true), controller = useRef<AbortController | null>(null), identity = useRef<string | null>(null);
  const retained = useRef<PropertyRecovery | null>(null), pending = useRef<Draft | null>(null);
  const busy = !["idle", "unknown"].includes(phase), locked = busy || recovery !== null;
  const visibleAccess = access?.actor_user_id === user.id ? access : null;
  function clearNotes() { setNote(""); setChecks([]); setAttested(false); setAction("requires_clarification"); }
  function clearEvidence() { setPage(null); setDetail(null); setDraft(null); setReceipt(null); pending.current = null; clearNotes(); }
  function clearPrivate() { ++seq.current; controller.current?.abort(); identity.current = null; setAccess(null); clearEvidence(); setRecovery(null); setPhase("idle"); }
  function begin() {
    const version = ++seq.current; controller.current?.abort(); const next = new AbortController(); controller.current = next;
    return { signal: next.signal, active: () => mounted.current && version === seq.current,
      run: <T,>(call: () => Promise<T>) => bounded(call, next) };
  }
  function failure(error: unknown) {
    clearEvidence(); setPhase("idle");
    if (error instanceof ApiError && [401, 403].includes(error.status)) { clearPrivate(); setMessage("Session or research access changed. Private information has been cleared; refresh access."); }
    else if (error instanceof ApiError && error.status === 404) setMessage("This pending source interface or record is unavailable. No new history was inferred.");
    else if (error instanceof ApiError && error.status === 409) setMessage("The source, authority or note head changed. Refresh the record and prepare a new preview.");
    else setMessage("The response could not be verified. Refresh access or reload the record before continuing.");
  }
  async function refreshAccess() {
    const op = begin(); clearEvidence(); setAccess(null); setProfile(""); setPhase("loading"); setMessage(null);
    try {
      const current = knownPropertyCapabilities(await op.run(() => sourcePropertyCapabilities(op.signal)), user.id);
      if (!op.active()) return; if (!current) throw new Error("Unsupported capabilities");
      identity.current = current.actor_user_id; setAccess(current);
      if (retained.current?.actorId === current.actor_user_id) { setRecovery(retained.current); setPhase("unknown"); setMessage("A preceding submission still needs an outcome check. No write will be retried."); return; }
      retained.current = null; setRecovery(null);
      const data = knownPropertyPage(await op.run(() => sourcePropertyList(0, 25, undefined, op.signal)), 0, 25);
      if (!op.active()) return; if (!data) throw new Error("Unsupported page"); setPage(data); setPhase("idle");
    } catch (error) { if (op.active()) { setAccess(null); failure(error); } }
  }
  useEffect(() => {
    mounted.current = true; clearPrivate(); void refreshAccess();
    const unsubscribe = onAuthChange(() => { clearPrivate(); setMessage("Session changed. Private information has been cleared; refresh access to continue."); });
    return () => { unsubscribe(); mounted.current = false; ++seq.current; controller.current?.abort(); };
    // The authenticated dashboard identity owns all private response state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user.id]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (retained.current) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", warn); return () => window.removeEventListener("beforeunload", warn);
  }, []);
  async function loadPage(offset: number, nextProfile = profile) {
    if (!visibleAccess || locked) return; const op = begin(); setPhase("loading"); setMessage(null); clearEvidence();
    try { const value = knownPropertyPage(await op.run(() => sourcePropertyList(offset, 25, nextProfile || undefined, op.signal)), offset, 25);
      if (!op.active()) return; if (!value) throw new Error("Unsupported page"); setPage(value); setPhase("idle");
    } catch (error) { if (op.active()) failure(error); }
  }
  async function inspect(id: string) {
    if (!visibleAccess || locked) return; const op = begin(); setPhase("loading"); setDetail(null); setDraft(null); setReceipt(null); clearNotes(); setMessage(null);
    try { const value = knownPropertyDetail(await op.run(() => sourcePropertyDetail(id, op.signal)), id);
      if (!op.active()) return; if (!value) throw new Error("Unsupported observation"); setDetail(value); setPhase("idle");
    } catch (error) { if (op.active()) failure(error); }
  }
  async function previewImport() {
    if (!visibleAccess?.can_import || locked) return; const current = visibleAccess, selected = snapshot, op = begin();
    setDraft(null); setReceipt(null); setPhase("previewing"); setMessage(null);
    try {
      const body = { request_key: `source-import:${crypto.randomUUID()}`, source_bytes_base64: await op.run(() => loadPropertyImportBytes(selected, op.signal)) };
      if (!op.active()) return;
      const ref: PropertyRecovery = { kind: "import", actorId: current.actor_user_id, requestKey: body.request_key, requestSha256: await propertyImportRequestSha(selected), previewSha256: "", sourceSha256: selected };
      if (!op.active()) return;
      const value = await knownPropertyImport(await op.run(() => sourcePropertyImportPreview(body, op.signal)), current, ref, "preview");
      if (!op.active()) return; if (!value) throw new Error("Unsupported preview");
      if (value.replayed) { setReceipt(value); setMessage("This original request is already saved. Its historical receipt is shown."); }
      else setDraft({ kind: "import", request: body, preview: value, ref: { ...ref, previewSha256: value.preview_sha256 } });
      setPhase("idle");
    } catch (error) { if (op.active()) failure(error); }
  }
  async function previewNote() {
    if (!visibleAccess?.can_append_source_note || locked || !detail || !attested || !checks.length || !note.trim()) return;
    if (action === "withdraw_note" && !canWithdrawPropertyNote(detail, visibleAccess)) return;
    const current = visibleAccess, op = begin(), head = detail.source_notes[0]; setPhase("previewing"); setDraft(null); setReceipt(null); setMessage(null);
    try {
      const request: PropertyReviewRequest = { request_key: `source-note:${crypto.randomUUID()}`, observation_id: detail.id, observation_sha256: detail.record_sha256,
        expected_previous_review_id: head?.review_id ?? null, expected_previous_review_sha256: head?.review_sha256 ?? null,
        scope: "source_expression_fidelity_note", action, checks: [...checks], note: note.trim(), source_inspection_attested: true };
      const ref: PropertyRecovery = { kind: "review", actorId: current.actor_user_id, requestKey: request.request_key, requestSha256: await propertyDigest(request), previewSha256: "", observationId: detail.id, observationSha256: detail.record_sha256 };
      if (!op.active()) return;
      const value = await knownPropertyReview(await op.run(() => sourcePropertyReviewPreview(request, op.signal)), current, ref, request, "preview");
      if (!op.active()) return; if (!value) throw new Error("Unsupported note preview");
      if (value.replayed) setReceipt(value); else setDraft({ kind: "review", request, preview: value, ref: { ...ref, previewSha256: value.preview_sha256, sourceNoteSha256: value.source_note_sha256 } });
      setPhase("idle");
    } catch (error) { if (op.active()) failure(error); }
  }
  async function commit() {
    if (!visibleAccess || !draft || locked) return; const current = visibleAccess, selected = draft, op = begin();
    pending.current = selected; retained.current = selected.ref; setPhase("committing"); setMessage(null);
    try {
      const raw = selected.kind === "import" ? await op.run(() => sourcePropertyImportCommit(selected.request, selected.ref.previewSha256, op.signal))
        : await op.run(() => sourcePropertyReviewCommit(selected.request, selected.ref.previewSha256, op.signal));
      const value = selected.kind === "import" ? await knownPropertyImport(raw, current, selected.ref, "commit") : await knownPropertyReview(raw, current, selected.ref, selected.request, "commit");
      if (!op.active()) return; if (!value) throw new Error("Unverified commit response");
      retained.current = null; pending.current = null; setDraft(null); setRecovery(null); setReceipt(value); setDetail(null); clearNotes(); setPhase("idle");
      setMessage("Saved to private pending history. Scientific status and material associations remain unchanged. Refresh records to see the current note head.");
    } catch (error) {
      if (!op.active()) return;
      if (error instanceof ApiError && [400, 401, 403, 409, 413, 415, 422].includes(error.status)) { retained.current = null; setRecovery(null); failure(error); }
      else { setDraft(null); pending.current = null; setRecovery(selected.ref); setPhase("unknown"); setMessage("Submission outcome is unknown. Check the original request; do not submit another write. An unavailable receipt is not proof of failure."); }
    }
  }
  async function checkOutcome() {
    if (!visibleAccess || !recovery || recovery.actorId !== visibleAccess.actor_user_id || busy) return;
    const current = visibleAccess, ref = recovery, op = begin(); setPhase("checking"); setMessage(null);
    try {
      const raw = ref.kind === "import" ? await op.run(() => sourcePropertyImportOutcome(ref.requestKey, ref.requestSha256, op.signal)) : await op.run(() => sourcePropertyReviewOutcome(ref.requestKey, ref.requestSha256, op.signal));
      const value = ref.kind === "import" ? await knownPropertyImport(raw, current, ref, "outcome") : await knownPropertyReview(raw, current, ref, null, "outcome");
      if (!op.active()) return; if (!value) throw new Error("Unverified outcome");
      retained.current = null; setRecovery(null); setReceipt(value); setPhase("idle"); setMessage("The original submission is saved. No new write was sent; refresh records for the latest history.");
    } catch (error) {
      if (!op.active()) return;
      if (error instanceof ApiError && [401, 403].includes(error.status)) { clearPrivate(); setMessage("Session or access changed. Refresh access before checking the original request."); }
      else { setPhase("unknown"); setMessage("The original outcome remains unverified. No rollback or failure is inferred; no write was retried."); }
    }
  }
  async function download() {
    if (!visibleAccess || !detail || locked) return; const selected = detail, actor = visibleAccess.actor_user_id, op = begin(); setPhase("downloading"); setMessage(null);
    try {
      const value = knownPropertyDetail(await op.run(() => sourcePropertyDownload(selected.id, op.signal)), selected.id);
      if (!op.active() || identity.current !== actor) return;
      if (!value || value.record_sha256 !== selected.record_sha256 || !downloadPropertyDetail(value)) throw new Error("Unverified download");
      setPhase("idle");
    } catch (error) { if (op.active()) failure(error); }
  }
  function editNote() { setDraft(null); setReceipt(null); }
  return <div className="space-y-5">
    <header className="space-y-2"><p className="text-xs font-medium uppercase tracking-wide text-accent-deep">Private research workspace</p><h2 className="text-2xl font-semibold text-sage-ink">Source properties</h2>
      <p className="max-w-3xl text-sm text-sage-muted">Inspect source expressions, save pending records and append source fidelity notes. Values retain their original subjects, conditions and derivation roles.</p>
      <p className="text-xs text-sage-muted">This history does not approve science, modify catalogue values or establish sample, phase or selected-result associations.</p></header>
    <div className="flex flex-wrap items-center gap-3"><button className={button} disabled={busy} onClick={() => void refreshAccess()}>Refresh access</button>
      {visibleAccess && <p className="text-sm text-sage-muted">Current access verified · {visibleAccess.can_import ? "curator" : "reader"}{visibleAccess.can_append_source_note ? " · source note reviewer" : ""}</p>}</div>
    {message && <p role="status" className="rounded border border-sage-border bg-sage-surface p-3 text-sm">{message}</p>}
    {busy && <p role="status" className="text-sm text-sage-muted">{phase === "committing" ? "Saving the exact preview…" : "Loading verified source history…"}</p>}
    {visibleAccess && recovery && <section className={panel}><h3 className="font-semibold">Check preceding submission</h3><p className="text-sm">Use this original request to resolve the pending outcome. New writes remain disabled.</p>
      <details className="text-xs"><summary className="cursor-pointer">Original request identity</summary><p className="mt-2 break-all">{recovery.requestKey}</p><p className="break-all">{recovery.requestSha256}</p></details>
      <button className={button} disabled={busy} onClick={() => void checkOutcome()}>Check original outcome</button></section>}
    {visibleAccess && !recovery && <>
      {visibleAccess.can_import && <section className={panel}><h3 className="font-semibold">Save an inspected source snapshot</h3><p className="text-sm text-sage-muted">Only these two fixed public snapshots are supported. Preview rehearses the pending import without saving history.</p>
        <div className="grid items-end gap-3 sm:grid-cols-[1fr_auto]"><label className="text-sm">Source snapshot<select className={`${input} mt-1`} value={snapshot} disabled={locked} onChange={event => { setSnapshot(event.target.value); setDraft(null); setReceipt(null); }}>
          <option value={PROPERTY_SNAPSHOTS[0].sha256}>First source batch · 15 expressions</option><option value={PROPERTY_SNAPSHOTS[1].sha256}>Follow-up batch · 31 expressions, 3 unavailable records</option></select></label>
          <button className={button} disabled={locked} onClick={() => void previewImport()}>Preview pending import</button></div></section>}
      <section className={panel}><div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold">Pending source records</h3><button className={button} disabled={locked} onClick={() => void loadPage(0)}>Refresh records</button></div>
        <label className="block max-w-xs text-sm">Record type<select className={`${input} mt-1`} value={profile} disabled={locked} onChange={event => { setProfile(event.target.value); void loadPage(0, event.target.value); }}><option value="">All types</option>{profiles.map(item => <option key={item} value={item}>{wording(item)}</option>)}</select></label>
        {page && <><p className="text-xs text-sage-muted">{page.total} pending records · counts describe source tasks, not independent experiments.</p>
          {page.observations.length ? <ul className="divide-y divide-sage-border">{page.observations.map(item => <li key={item.id} className="flex min-w-0 flex-wrap items-center justify-between gap-2 py-3"><div className="min-w-0"><p className="text-sm font-medium">{propertyFieldLabel(item.projection.field_id)}</p><p className="text-xs text-sage-muted">{wording(String(item.projection.source_entry.source_group))} · {wording(item.projection.source_role)}</p></div><button className={button} disabled={locked} onClick={() => void inspect(item.id)}>Inspect {propertyFieldLabel(item.projection.field_id)}</button></li>)}</ul> : <p className="text-sm text-sage-muted">No pending records in this view.</p>}
          <div className="flex flex-wrap items-center gap-3"><button className={button} disabled={locked || page.offset === 0} onClick={() => void loadPage(Math.max(0, page.offset - 25))}>Previous</button><span className="text-xs text-sage-muted">{page.total ? `${page.offset + 1}–${page.offset + page.observations.length} of ${page.total}` : "0 records"}</span><button className={button} disabled={locked || page.offset + 25 >= page.total} onClick={() => void loadPage(page.offset + 25)}>Next</button></div></>}
      </section>
      {detail && <section className={panel}><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs text-sage-muted">Pending · source association unestablished</p><h3 className="font-semibold">{propertyFieldLabel(detail.projection.field_id)}</h3></div><button className={button} disabled={locked} onClick={() => void download()}>Download private record</button></div>
        <ObservationEvidence detail={detail} />
        <details><summary className="cursor-pointer text-sm">Source note history ({detail.source_notes_total})</summary><div className="mt-3 space-y-3">{!detail.source_notes.length && <p className="text-sm text-sage-muted">No source fidelity notes have been saved.</p>}{detail.source_notes.map(item => <article key={item.review_id} className="border-l-2 border-sage-border pl-3"><p className="text-sm font-medium">Note {item.review_number} · {NOTE_LABELS[item.source_note.action]}</p><p className="mt-1 break-words text-sm">{item.source_note.note}</p><p className="mt-1 text-xs text-sage-muted">{item.source_note.checks.map(check => CHECK_LABELS[check]).join(" · ")}{item.actor_user_id === visibleAccess.actor_user_id ? " · your note" : ""}</p></article>)}{detail.source_notes_truncated && <p className="text-xs text-sage-muted">Only the latest 20 notes are returned. Earlier history remains retained.</p>}</div></details>
        {visibleAccess.can_append_source_note && <fieldset disabled={locked} className="space-y-3 border-t border-sage-border pt-4"><legend className="pt-3 font-semibold">Append a source fidelity note</legend>
          <p className="text-xs text-sage-muted">Record your own inspection of the cited source. This note leaves the source value and its scientific status pending.</p>
          <label className="block text-sm">Finding<select className={`${input} mt-1`} value={action} onChange={event => { setAction(event.target.value as PropertyNoteAction); editNote(); }}>{PROPERTY_NOTE_ACTIONS.filter(item => item !== "withdraw_note" || canWithdrawPropertyNote(detail, visibleAccess)).map(item => <option key={item} value={item}>{NOTE_LABELS[item]}</option>)}</select></label>
          {action === "withdraw_note" && <p className="text-xs text-sage-muted">This appends a withdrawal of your preceding note. It does not remove a source record or erase history.</p>}
          <fieldset className="grid gap-2 sm:grid-cols-2"><legend className="mb-2 text-sm">What did you inspect?</legend>{PROPERTY_CHECKS.map(check => <label key={check} className="flex items-start gap-2 text-sm"><input type="checkbox" checked={checks.includes(check)} onChange={event => { setChecks(event.target.checked ? [...checks, check] : checks.filter(item => item !== check)); editNote(); }} /><span>{CHECK_LABELS[check]}</span></label>)}</fieldset>
          <label className="block text-sm">Inspection note<textarea className={`${input} mt-1`} rows={3} maxLength={2000} value={note} onChange={event => { setNote(event.target.value); editNote(); }} /></label>
          <p className="text-xs text-sage-muted">Use a single paragraph, up to 2,000 characters. Line breaks are not accepted.</p>
          <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={attested} onChange={event => { setAttested(event.target.checked); editNote(); }} /><span>I inspected the cited source expressions and locators for the checks selected above.</span></label>
          <button className={button} disabled={locked || !attested || !checks.length || !note.trim() || /[\u0000-\u001f]/.test(note.trim())} onClick={() => void previewNote()}>Preview source note</button>
        </fieldset>}
      </section>}
      {draft && <section className={panel}><h3 className="font-semibold">Confirm exact {draft.kind === "import" ? "pending import" : "source note"} preview</h3>
        {draft.kind === "import" ? <p className="text-sm">{draft.preview.summary.source_task_count} source records · {draft.preview.summary.source_expression_count} source expressions · {draft.preview.summary.source_unavailable_count} unavailable records. Saving writes private pending history.</p>
          : <div className="space-y-2 text-sm"><p>{NOTE_LABELS[draft.request.action]} · {draft.request.checks.map(check => CHECK_LABELS[check]).join(" · ")}</p><p className="break-words">{draft.request.note}</p></div>}
        <details className="text-xs"><summary className="cursor-pointer">Exact request and preview fingerprints</summary><p className="mt-2 break-all">{draft.ref.requestKey}</p><p className="break-all">Request: {draft.ref.requestSha256}</p><p className="break-all">Preview: {draft.ref.previewSha256}</p></details>
        <div className="flex flex-wrap gap-2"><button className={`${button} font-semibold`} disabled={locked} onClick={() => void commit()}>Save {draft.kind === "import" ? "pending import" : "source note"}</button><button className={button} disabled={locked} onClick={() => setDraft(null)}>Discard preview</button></div></section>}
    </>}
    {visibleAccess && receipt && <section className={panel}><h3 className="font-semibold">Saved pending receipt</h3><p className="text-sm">{receipt.replayed ? "Previously saved operation; no new write was sent." : "The private pending operation was saved."} Catalogue values and scientific acceptance remain unchanged.</p><details className="text-xs"><summary className="cursor-pointer">Receipt fingerprints</summary><p className="mt-2 break-all">{"receipt_id" in receipt ? receipt.receipt_id : receipt.review_id}</p><p className="break-all">{receipt.request_sha256}</p><p className="break-all">{receipt.preview_sha256}</p></details></section>}
  </div>;
}
