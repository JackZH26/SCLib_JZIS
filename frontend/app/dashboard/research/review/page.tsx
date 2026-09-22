"use client";

import { useEffect, useRef, useState } from "react";

import { ApiError, scientificReviewCapabilities, scientificReviewDossier, scientificReviewQueue } from "@/lib/api";
import { onAuthChange } from "@/lib/auth-session";
import { ScientificReviewDecisionPanel } from "@/components/ScientificReviewDecisionPanel";
import { ScientificReviewDossier } from "@/components/ScientificReviewDossier";
import { knownReviewCapabilities, knownReviewDossier, knownReviewQueue, reviewNumber,
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
export default function ScientificReviewPage() {
  const [capabilities, setCapabilities] = useState<ReviewCapabilities | null>(null);
  const [queue, setQueue] = useState<ReviewQueue | null>(null);
  const [selected, setSelected] = useState<ReviewQueueItem | null>(null);
  const [dossier, setDossier] = useState<ReviewDossier | null>(null);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reviewTargets, setReviewTargets] = useState<ReviewQueueItem[]>([]);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [reviewOpened, setReviewOpened] = useState(false);
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
    clearEvidence(); setReviewTargets([]); setReviewBusy(false); setReviewOpened(false); setCapabilities(null); setLoading(false); setError(unavailable(error));
  }
  async function load(after: string | null = null) {
    const current = ++generation.current;
    requests.current.main?.abort();
    const controller = new AbortController();
    requests.current.main = controller;
    clearEvidence(); setReviewTargets([]); setReviewBusy(false); setReviewOpened(false); setCapabilities(null); setError(null); setLoading(true);
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
    const unsubscribe = onAuthChange(() => fail(new ApiError(401, null, "Session changed")));
    return () => {
      generation.current += 1; detailGeneration.current += 1;
      requests.current.main?.abort(); requests.current.detail?.abort();
      unsubscribe();
    };
    // Initial mount only; refresh and pagination explicitly recheck access.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  function invalidateReview(recoverable: boolean) {
    generation.current += 1; requests.current.main?.abort();
    clearEvidence(); setCapabilities(null); setLoading(false);
    if (!recoverable) { setReviewTargets([]); setReviewBusy(false); setReviewOpened(false); }
    setError(recoverable
      ? "Commit outcome is unknown. Prior evidence has been cleared. Use Check outcome below without sending another write."
      : "Review context, access or decision head could not be verified. Prior evidence and selections have been cleared. Refresh access and review again.");
  }

  return <div className="min-w-0 space-y-5">
    <header className="space-y-2">
      <h2 className="text-xl font-semibold text-sage-ink">Scientific evidence workbench</h2>
      <p className="text-sm text-sage-muted">Private inspection and explicitly scoped review of exact canonical non-Tc, non-RPS results. No source text or downloads are provided.</p>
      <p className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
        Inspection does not approve science, authorize publication or admit ML training data. Scope-limited review requires a current reviewer grant, explicitly selected results and a successful preview before commit.
      </p>
      <button className={button} disabled={reviewBusy} onClick={() => void load()}>{loading ? "Restart access check" : "Refresh access"}</button>
    </header>
    <div aria-live="polite">
      {loading && <p role="status" className="text-sm text-sage-muted">Checking research access and loading the current page…</p>}
      {error && <p role="alert" className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      {capabilities && !capabilities.can_read && <p role="alert" className="text-sm">An active curator or reviewer research grant is required. Ordinary administrator or legacy reviewer flags do not grant access.</p>}
    </div>
    {queue && <section className={panel} aria-labelledby="queue-heading">
      <h3 id="queue-heading" className="font-semibold">Result inventory</h3>
      <p className="my-2 text-xs text-sage-muted">{queue.count_basis} Showing {reviewNumber(queue.items.length)} entries on this page; no global total is reported.</p>
      <p className="my-2 text-xs text-sage-muted">Select up to 20 results on this page for review. There is no implicit select-all; page changes clear the selection. Selecting a checkbox does not submit a decision.</p>
      {queue.items.length === 0 ? <p className="text-sm">No results were returned in this bounded inventory page.</p>
        : <ul className="divide-y divide-sage-border">{queue.items.map(item => <li key={item.property_id} className="py-2">
          <label className="mb-2 flex items-start gap-2 text-sm">
            <input className="mt-1" type="checkbox" aria-label={"Select for review: " + item.formula + " · " + item.property_id}
              checked={reviewTargets.some(target => target.property_id === item.property_id)}
              disabled={reviewBusy || reviewTargets.length >= 20 && !reviewTargets.some(target => target.property_id === item.property_id)}
              onChange={event => {
                setReviewOpened(false);
                setReviewTargets(current => event.target.checked
                  ? [...current, item].sort((a, b) => a.property_id.localeCompare(b.property_id, "en"))
                  : current.filter(target => target.property_id !== item.property_id));
              }} />
            Select this exact result for review
          </label>
          <button className={`${button} w-full text-left ${selected?.property_id === item.property_id ? "bg-sage-surface ring-1 ring-accent" : ""}`}
            disabled={reviewBusy}
            aria-pressed={selected?.property_id === item.property_id} aria-controls="scientific-evidence-detail" onClick={() => void select(item)}>
            <span className="block break-words font-medium">{item.formula} · {label(item.property_key)}</span>
            <span className="block text-xs text-sage-muted">{item.knowledge_origin} · Event revision {reviewNumber(item.event_revision)} · Parent review: {label(item.review_status)} · Parent validity: {label(item.validity_status)}</span>
            <span className="block break-all font-mono text-xs">{item.property_id}</span>
          </button>
        </li>)}</ul>}
      <div className="mt-3 flex flex-wrap gap-2">
        <button className={button} disabled={reviewTargets.length === 0 || reviewBusy}
          onClick={() => setReviewOpened(true)}>Load review context for {reviewTargets.length} selected results</button>
        <button className={button} disabled={reviewBusy} onClick={() => void load()}>First page</button>
        <button className={button} disabled={reviewBusy || !queue.has_more} onClick={() => void load(queue.next_cursor)}>Next page</button>
      </div>
    </section>}
    <section id="scientific-evidence-detail" aria-live="polite" aria-busy={detailLoading}>
      {detailLoading && <p role="status" className="text-sm text-sage-muted">Loading the selected exact result… Previous detail has been cleared.</p>}
      {queue && !selected && <p className="text-sm text-sage-muted">Select a result to inspect its typed fields and evidence bindings.</p>}
      {dossier && <ScientificReviewDossier value={dossier} />}
    </section>
    {reviewOpened && reviewTargets.length > 0 && <ScientificReviewDecisionPanel key={reviewTargets.map(item => item.property_id).join("|")}
      selected={reviewTargets} onInvalidate={invalidateReview} onBusyChange={setReviewBusy} onRecovered={() => setError(null)} />}
  </div>;
}
