"use client";

import { useEffect, useRef, useState } from "react";

import { ApiError, scientificReviewCapabilities, scientificReviewDossier, scientificReviewQueue } from "@/lib/api";
import { knownReviewCapabilities, knownReviewDossier, knownReviewQueue, reviewNumber, reviewQuantity,
  type ReviewCapabilities, type ReviewDossier, type ReviewQueue, type ReviewQueueItem } from "@/lib/scientific-review";

const button = "rounded border border-sage-border bg-white px-3 py-2 text-sm text-accent-deep hover:bg-sage-surface focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50";
const panel = "min-w-0 rounded-lg border border-sage-border bg-white p-4";
function unavailable(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) return "Your session is unavailable. Sign in again, then refresh access.";
  if (error instanceof ApiError && error.status === 403) return "An active curator or reviewer research grant is required. Previously displayed evidence has been cleared.";
  if (error instanceof ApiError && error.status === 404) return "This evidence view is unavailable. Refresh access to check the current inventory.";
  return "Evidence could not be checked. Previously displayed data has been cleared. Refresh access to try again.";
}
const label = (value: string) => value.replaceAll("_", " ");
function Field({ name, children }: { name: string; children: React.ReactNode }) {
  return <div className="min-w-0 py-1"><dt className="text-xs font-medium text-sage-muted">{name}</dt><dd className="break-words text-sm text-sage-ink">{children}</dd></div>;
}
function Hash({ value }: { value: string | null }) {
  return value === null ? <>Not available</> : <code className="break-all text-xs">{value}</code>;
}

export default function ScientificReviewPage() {
  const [capabilities, setCapabilities] = useState<ReviewCapabilities | null>(null);
  const [queue, setQueue] = useState<ReviewQueue | null>(null);
  const [selected, setSelected] = useState<ReviewQueueItem | null>(null);
  const [dossier, setDossier] = useState<ReviewDossier | null>(null);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  const detailGeneration = useRef(0);
  const requests = useRef<{ main: AbortController | null; detail: AbortController | null }>({ main: null, detail: null });

  function clearEvidence() {
    setQueue(null); setSelected(null); setDossier(null); setDetailLoading(false);
    detailGeneration.current += 1;
    requests.current.detail?.abort();
  }
  function fail(error: unknown) {
    generation.current += 1;
    requests.current.main?.abort();
    clearEvidence(); setCapabilities(null); setLoading(false); setError(unavailable(error));
  }
  async function load(after: string | null = null) {
    const current = ++generation.current;
    requests.current.main?.abort();
    const controller = new AbortController();
    requests.current.main = controller;
    clearEvidence(); setCapabilities(null); setError(null); setLoading(true);
    const active = () => generation.current === current && !controller.signal.aborted;
    try {
      const access = knownReviewCapabilities(await scientificReviewCapabilities(controller.signal));
      if (!active()) return;
      if (access === null) throw new Error("Invalid capability response");
      setCapabilities(access);
      if (!access.can_read) { setLoading(false); return; }
      const result = knownReviewQueue(await scientificReviewQueue(after, controller.signal));
      if (!active()) return;
      if (result === null || after !== null && result.items.some(item => item.property_id <= after)) throw new Error("Invalid queue response");
      setQueue(result); setLoading(false);
    } catch (caught) { if (active()) fail(caught); }
  }
  async function select(item: ReviewQueueItem) {
    const current = ++detailGeneration.current;
    const parent = generation.current;
    requests.current.detail?.abort();
    const controller = new AbortController();
    requests.current.detail = controller;
    setSelected(item); setDossier(null); setDetailLoading(true); setError(null);
    const active = () => current === detailGeneration.current && parent === generation.current && !controller.signal.aborted;
    try {
      const result = knownReviewDossier(await scientificReviewDossier(item.property_id, controller.signal), item);
      if (!active()) return;
      if (result === null) throw new Error("Invalid or changed detail");
      setDossier(result); setDetailLoading(false);
    } catch (caught) { if (active()) fail(caught); }
  }
  useEffect(() => {
    void load();
    return () => {
      generation.current += 1; detailGeneration.current += 1;
      requests.current.main?.abort(); requests.current.detail?.abort();
    };
    // Initial mount only; refresh and pagination explicitly recheck access.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <div className="min-w-0 space-y-5">
    <header className="space-y-2">
      <h2 className="text-xl font-semibold text-sage-ink">Scientific evidence workbench</h2>
      <p className="text-sm text-sage-muted">Private, read-only inspection of exact canonical non-Tc, non-RPS results. No source text or downloads are provided.</p>
      <p className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
        Scientific adjudication is not available. Accept, reject and request-clarification actions are not implemented here. Inspection does not approve science, authorize publication or admit ML training data.
      </p>
      <button className={button} onClick={() => void load()}>{loading ? "Restart access check" : "Refresh access"}</button>
    </header>
    <div aria-live="polite">
      {loading && <p role="status" className="text-sm text-sage-muted">Checking research access and loading the current page…</p>}
      {error && <p role="alert" className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      {capabilities && !capabilities.can_read && <p role="alert" className="text-sm">An active curator or reviewer research grant is required. Ordinary administrator or legacy reviewer flags do not grant access.</p>}
    </div>
    {queue && <section className={panel} aria-labelledby="queue-heading">
      <h3 id="queue-heading" className="font-semibold">Result inventory</h3>
      <p className="my-2 text-xs text-sage-muted">{queue.count_basis} Showing {reviewNumber(queue.items.length)} entries on this page; no global total is reported.</p>
      {queue.items.length === 0 ? <p className="text-sm">No results were returned in this bounded inventory page.</p>
        : <ul className="divide-y divide-sage-border">{queue.items.map(item => <li key={item.property_id} className="py-2">
          <button className={`${button} w-full text-left ${selected?.property_id === item.property_id ? "bg-sage-surface ring-1 ring-accent" : ""}`}
            aria-pressed={selected?.property_id === item.property_id} aria-controls="scientific-evidence-detail" onClick={() => void select(item)}>
            <span className="block break-words font-medium">{item.formula} · {label(item.property_key)}</span>
            <span className="block text-xs text-sage-muted">{item.knowledge_origin} · Event revision {reviewNumber(item.event_revision)} · Parent review: {label(item.review_status)} · Parent validity: {label(item.validity_status)}</span>
            <span className="block break-all font-mono text-xs">{item.property_id}</span>
          </button>
        </li>)}</ul>}
      <div className="mt-3 flex flex-wrap gap-2">
        <button className={button} onClick={() => void load()}>First page</button>
        <button className={button} disabled={!queue.has_more} onClick={() => void load(queue.next_cursor)}>Next page</button>
      </div>
    </section>}
    <section id="scientific-evidence-detail" aria-live="polite" aria-busy={detailLoading}>
      {detailLoading && <p role="status" className="text-sm text-sage-muted">Loading the selected exact result… Previous detail has been cleared.</p>}
      {queue && !selected && <p className="text-sm text-sage-muted">Select a result to inspect its typed fields and evidence bindings.</p>}
      {dossier && <Dossier value={dossier} />}
    </section>
  </div>;
}

function Dossier({ value }: { value: ReviewDossier }) {
  return <div className="min-w-0 space-y-4">
    <div className={panel}>
      <h3 className="font-semibold">Exact result · {value.material.formula}</h3>
      <dl className="mt-2 grid gap-x-4 sm:grid-cols-2">
        <Field name="Property ID">{value.target.property_id}</Field>
        <Field name="Parent event">{value.target.event_id} · revision {reviewNumber(value.target.event_revision)}</Field>
        <Field name="Captured descriptor SHA-256"><Hash value={value.descriptor_sha256} /></Field>
        <Field name="Dependency inventory SHA-256"><Hash value={value.inventory.sha256} /></Field>
      </dl>
      <p className="mt-2 text-xs text-sage-muted">These hashes identify the server-captured database snapshot. This browser has not independently verified original files. A hash is not scientific validation or persistent currentness.</p>
    </div>
    <div className="grid min-w-0 gap-4 xl:grid-cols-2">
      <section className={panel} aria-labelledby="result-heading">
        <h4 id="result-heading" className="font-semibold">Typed result, state and run</h4>
        <dl className="mt-2">
          <Field name="Quantity">{label(value.result.property_key)}: {reviewQuantity(value.result)}</Field>
          <Field name="Reported relation">{label(value.result.relation)} — a stored quantity relation, not exact underlying physics</Field>
          <Field name="Registry / component">{value.result.registry_version} / {value.result.component_key}</Field>
          <Field name="Origin / event type">{value.event.knowledge_origin} / {label(value.event.event_type)}</Field>
          <Field name="Parent event status">Review: {label(value.event.review_status)}; validity: {label(value.event.validity_status)}. These are stored parent-event states, not a new property-level approval.</Field>
          <Field name="Material / state">{value.material.id} / {value.state.id}</Field>
          <Field name="State resolution">{label(value.state.resolution)}</Field>
          <Field name="Pressure">{value.state.pressure_gpa === null ? "Not reported / unresolved" : `${reviewNumber(value.state.pressure_gpa)} GPa`} · {label(value.state.pressure_status)}</Field>
          <Field name="Temperature">{value.state.temperature_k === null ? "Not reported / unresolved" : `${reviewNumber(value.state.temperature_k)} K`} · role: {label(value.state.temperature_role)}</Field>
          <Field name="Structure">{value.structure ? <>{label(value.structure.structure_kind)} · {value.structure.id}<br />Artifact: {value.structure.artifact_id ?? "Not available"}</> : "Not available"}</Field>
          <Field name="Producer run">{value.run ? <>{label(value.run.run_kind)} · {label(value.run.status)}<br />{value.run.id}</> : "Not available"}</Field>
        </dl>
        <p className="mt-3 text-xs text-sage-muted">Unknown conditions are not zero. An extraction run is not an attested upstream calculation. Formula agreement does not establish phase, sample or state identity.</p>
      </section>
      <section className={panel} aria-labelledby="sources-heading">
        <h4 id="sources-heading" className="font-semibold">Source bindings and locators</h4>
        <p className="my-2 text-xs text-sage-muted">Retained dependency artifacts may include parent, sibling, state and run evidence. Membership does not establish support for this property. Raw source text, metadata payloads and file exports are withheld for every role. Access labels do not grant disclosure rights.</p>
        {value.sources.length === 0 && <p className="text-sm">No source-artifact bindings are included in this dependency inventory.</p>}
        <ul className="space-y-3">{value.sources.map(source => <li className="min-w-0 rounded border border-sage-border p-3" key={source.artifact_id}>
          <dl>
            <Field name="Artifact">{source.artifact_id}</Field>
            <Field name="Kind / access label">{label(source.kind)} / {label(source.access)}</Field>
            <Field name="Stored hash status">{label(source.hash_status)} — not a new browser file verification</Field>
            <Field name="Retained bytes SHA-256"><Hash value={source.bytes_sha256} /></Field>
          </dl>
          <p className="mt-2 text-xs font-medium">Locations only</p>
          <ul className="list-inside list-disc text-xs">{source.locators.map((locator, index) => <li key={index}>{"scope" in locator
            ? "Locator not disclosed" : `Line ${reviewNumber(locator.line)}; byte range ${reviewNumber(locator.start_byte)}–${reviewNumber(locator.end_byte)}`}</li>)}</ul>
          <details className="mt-2 text-xs"><summary className="cursor-pointer">Evidence-link identifiers ({source.evidence_link_ids.length})</summary>
            <ul>{source.evidence_link_ids.map(id => <li key={id} className="break-all font-mono">{id}</li>)}</ul>
          </details>
        </li>)}</ul>
      </section>
    </div>
    <section className={panel} aria-labelledby="warnings-heading">
      <h4 id="warnings-heading" className="font-semibold">Inspection warnings</h4>
      {value.warnings.length ? <ul className="mt-2 list-inside list-disc text-sm">{value.warnings.map(warning => <li key={warning}>{label(warning)}</li>)}</ul>
        : <p className="mt-2 text-sm">No warning codes were returned. This is not a completeness or scientific-acceptance assessment.</p>}
    </section>
    <section className={panel} aria-labelledby="impact-heading">
      <h4 id="impact-heading" className="font-semibold">Bounded dependency relationships</h4>
      <p className="my-2 text-sm">This is a database relationship inventory, not a prediction of scientific effects. This inspection does not approve, refresh, publish or change any records.</p>
      <dl>
        <Field name="Included scope">{value.impact.scope.map(label).join("; ") || "None declared"}</Field>
        <Field name="Unsupported scope">{value.impact.unsupported_scopes.map(label).join("; ") || "None declared; no global completeness is inferred"}</Field>
        <Field name="Captured inventory">{reviewNumber(value.inventory.row_count)} rows; {reviewNumber(value.inventory.artifact_count)} artifacts</Field>
        <Field name="Relationship counts">{Object.entries(value.impact.counts).map(([table, count]) => `${label(table)}: ${reviewNumber(count)}`).join("; ") || "No relationships reported"}</Field>
      </dl>
      <details className="mt-3"><summary className="cursor-pointer text-sm">Inspect {reviewNumber(value.impact.items.length)} declared relationship entries</summary>
        <ul className="mt-2 space-y-2 text-xs">{value.impact.items.map((item, index) => <li key={index} className="break-all rounded bg-sage-surface p-2">
          {item.table}: {item.row_id}<br />{label(item.relation)} via {item.via_table}: {item.via_id}
        </li>)}</ul>
      </details>
    </section>
  </div>;
}
