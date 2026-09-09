"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ApiError, historyDetail, type AskResponse } from "@/lib/api";
import { knownHistoryDetail, type HistoryDetail } from "@/lib/answer-history";
import { knownSourceVisibility } from "@/lib/material-visibility";
import { knownScientificMixedResponse } from "@/lib/scientific-mixed";
import { AskSupportNotice } from "@/components/AskSupportNotice";
import { EvidencePackingNotice, PackingSourceNotice } from "@/components/EvidencePackingNotice";
import { EvidenceProvenanceNotice } from "@/components/EvidenceProvenanceNotice";
import { MarkdownAnswer } from "@/components/MarkdownAnswer";
import { ScientificMixedNotice } from "@/components/ScientificMixedNotice";
import { ScientificQueryNotice } from "@/components/ScientificQueryNotice";

export function AskHistoryDetail({ historyId }: { historyId: string }) {
  // A changed URL cannot briefly display the previous private answer.
  return <HistoryDetailLoader key={historyId} historyId={historyId} />;
}

function HistoryDetailLoader({ historyId }: { historyId: string }) {
  const [data, setData] = useState<HistoryDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setData(null); setError(null);
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(historyId)) {
      setError("The history identifier is invalid. No private history was requested.");
      return () => { active = false; controller.abort(); };
    }
    historyDetail(historyId, controller.signal).then(raw => {
      if (!active) return;
      const checked = knownHistoryDetail(raw, historyId);
      if (!checked) { setError("The history detail is incomplete or inconsistent. Saved receipt content is withheld."); return; }
      setData(checked);
    }).catch((failure: unknown) => {
      if (!active) return;
      setError(failure instanceof ApiError && [401, 403].includes(failure.status)
        ? "Please sign in with the account that owns this history entry."
        : failure instanceof ApiError && failure.status === 404
          ? "This history entry is unavailable in the current snapshot. This does not resolve an earlier unknown save outcome."
          : "History detail is temporarily unavailable. No saved outcome has been inferred.");
    });
    return () => { active = false; controller.abort(); };
  }, [historyId, attempt]);
  return <div className="space-y-5">
    <Link href="/dashboard/history" className="text-sm text-accent-deep underline">Back to Ask history</Link>
    <h2 className="text-xl font-semibold text-sage-ink">Saved answer receipt</h2>
    <p className="text-sm text-sage-muted">Private account history, retained for the existing 90-day window. Reading a receipt does not rerun the question or create scientific approval.</p>
    {error ? <div role="alert" aria-label="History detail unavailable" className="space-y-3 rounded border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
      <p>{error}</p><button className="rounded border border-amber-800 px-3 py-1" onClick={() => setAttempt(value => value + 1)}>Retry history read</button>
    </div> : !data ? <p role="status" className="text-sm text-sage-muted">Loading private history detail…</p>
      : <HistoryReceiptContent detail={data} />}
  </div>;
}

export function HistoryReceiptContent({ detail }: { detail: HistoryDetail }) {
  const { entry, evidence } = detail;
  const receipt = evidence.receipt;
  const stored = receipt?.response;
  // Quota fields were deliberately not retained; these nulls are view-only.
  const response: AskResponse | null = stored ? { ...stored, guest_remaining: null, remaining: null } : null;
  const mixed = response ? knownScientificMixedResponse(response, entry.question) : null;
  const originalPapers = entry.sources.map(source => source.paper_id ?? null);
  const resultPapers = stored?.scientific_results?.map(result => result.binding.paper_id) ?? [];
  return <div className="space-y-5">
    <section aria-label="Historical receipt integrity" className="space-y-2 rounded border border-sage-border bg-white p-4 text-sm">
      <h3 className="font-semibold">{evidence.status === "verified" ? "Historical receipt integrity checked" : evidence.status === "legacy_unpinned" ? "Legacy unpinned history" : "Historical receipt unavailable"}</h3>
      <p>{evidence.status === "verified" ? "The server checked the retained receipt and its declared references. This is not scientific acceptance, current source permission, ML-training approval, or a regenerated answer."
        : evidence.status === "legacy_unpinned" ? "No complete answer-time receipt was recorded. Missing generations, extraction rows, associations and checks are not reconstructed from current data."
          : "The saved receipt could not be checked. No structured records or version bindings are displayed."}</p>
      <p className="text-xs text-sage-muted">Saved: {new Date(entry.created_at).toLocaleString("en-US")} · {entry.latency_ms.toLocaleString("en-US")} ms · {entry.tokens_used === null ? "Token usage unknown" : `${entry.tokens_used.toLocaleString("en-US")} recorded tokens`}</p>
      {receipt && <details className="break-all text-xs"><summary className="cursor-pointer font-medium">Recorded identity and generation pins</summary>
        <dl className="mt-2 space-y-2">
          <div><dt>History ID</dt><dd>{receipt.history_id}</dd></div>
          <div><dt>Receipt checksum (server-verified SQL serialization)</dt><dd>{receipt.record_sha256}</dd></div>
          <div><dt>Request / response / bindings checksums</dt><dd>{receipt.request_sha256}<br />{receipt.response_sha256}<br />{receipt.bindings_sha256}</dd></div>
          <div><dt>Binding scope</dt><dd>{evidence.binding_scope === "generation_members" ? "Exact retained generation members"
            : evidence.binding_scope === "legacy_snapshot" ? "Saved legacy snapshot only; no generation identity"
              : "No selected evidence; no missing input is invented"}</dd></div>
          {receipt.bindings.generation_id !== null && <><div><dt>Recorded generation</dt><dd>{receipt.bindings.generation_id}</dd></div>
            <div><dt>Recorded activation event</dt><dd>{receipt.bindings.activation_event_id}</dd></div>
            <div><dt>Recorded manifest</dt><dd>{receipt.bindings.manifest_sha256}</dd></div></>}
        </dl>
        <p className="mt-2">These are historical identifiers, not a claim that this generation is active today. Checksums are not independent evidence authentication.</p>
        {receipt.bindings.items.length > 0 && <ol className="mt-3 list-inside list-decimal space-y-2">{receipt.bindings.items.map(item => <li key={`${item.kind}:${item.position}`}>
          {item.kind === "source" ? "Saved citation" : "Saved extraction"} {item.position.toLocaleString("en-US")} · {item.paper_id}<br />
          Chunk: {item.chunk_id}<br />Content: {item.content_sha256}
        </li>)}</ol>}
      </details>}
    </section>

    <CurrentEvidenceNotice value={entry.current_evidence} paperIds={originalPapers} title="Current metadata for saved citation source papers" />
    <CurrentEvidenceNotice value={detail.result_current_evidence} paperIds={resultPapers} title="Current metadata for saved numerical-result source papers" />

    <section aria-label="Saved question" className="space-y-2"><h3 className="font-semibold">Saved question</h3><p className="whitespace-pre-wrap break-words text-sm">{entry.question}</p></section>
    <section aria-label="Saved answer-time output" className="space-y-4">
      <h3 className="font-semibold">Saved answer-time output</h3>
      {!response ? <>
        <p className="text-sm text-amber-900">Scientific support is unknown for this legacy or unavailable receipt. Only the stored answer text is shown; omitted numerical records are not fabricated.</p>
        <pre className="whitespace-pre-wrap break-words rounded border border-sage-border bg-white p-4 text-sm">{entry.answer}</pre>
      </> : mixed?.status !== "not_requested" ? <>
        <ScientificMixedNotice response={response} rawQuery={entry.question} historical />
        <details className="rounded border border-sage-border p-3 text-sm"><summary className="cursor-pointer">Recorded response text</summary>
          <p className="mt-2 text-xs text-amber-900">Literal saved output, not a new numerical explanation or a scientific finding verified by this history view.</p>
          <pre className="mt-2 whitespace-pre-wrap break-words">{response.answer}</pre>
        </details>
      </> : <>
        <AskSupportNotice response={response} historical />
        <EvidencePackingNotice packing={response.evidence_packing} inputBudget={response.input_budget} sources={response.sources} historical />
        <ScientificQueryNotice context="Ask" query={response.scientific_query} lookup={response.scientific_lookup}
          results={response.scientific_results} generation={response.retrieval_generation} rawQuery={entry.question} historical />
        <MarkdownAnswer markdown={response.answer} sources={response.sources} />
        {response.sources.length > 0 && <section aria-label="Saved citation sources" className="space-y-3"><h4 className="font-semibold">Saved citation sources</h4>
          {response.sources.map(source => <article key={source.index} id={`src-${source.index}`} className="rounded border border-sage-border bg-white p-3 text-sm">
            <Link href={`/paper/${encodeURIComponent(source.paper_id)}`} className="text-accent-deep underline">[{source.index}] {source.title}</Link>
            <p className="text-xs text-sage-muted">The paper link opens its current page, not an immutable document view.</p>
            <EvidenceProvenanceNotice evidence={source.evidence_provenance} historical />
            <blockquote className="mt-2 whitespace-pre-wrap break-words border-l-2 border-sage-border pl-3">{source.snippet}</blockquote>
            <PackingSourceNotice source={source} sources={response.sources} historical />
          </article>)}
        </section>}
      </>}
    </section>
  </div>;
}

/** Current metadata never replaces source fields in the retained response. */
function CurrentEvidenceNotice({ value, paperIds, title }: { value: unknown; paperIds: (string | null)[]; title: string }) {
  const data = value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
  const available = data?.version === "ask-history-current-evidence/1.0.0"
    && data.scope === "current_paper_metadata_not_saved_excerpt" && data.saved_answer_revalidated === false
    && data.scientific_acceptance === false && data.ml_training_eligibility_established === false && Array.isArray(data.sources);
  const sources = available ? data.sources as Record<string, unknown>[] : [];
  const matching = sources.filter(item => item && typeof item === "object" && Number.isSafeInteger(item.saved_source_position)
    && Number(item.saved_source_position) >= 0 && Number(item.saved_source_position) < paperIds.length
    && typeof item.paper_id === "string" && item.paper_id === paperIds[Number(item.saved_source_position)]);
  const checked = matching.length === sources.length && new Set(matching.map(item => item.saved_source_position)).size === matching.length;
  return <section aria-label={title} className="space-y-2 rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
    <h3 className="font-semibold">{title}</h3>
    <p className="text-xs">Separate request-time paper metadata only. It does not revalidate saved excerpts, numerical results, associations or the answer.</p>
    {available && typeof data.metadata_snapshot_at === "string" && Number.isFinite(Date.parse(data.metadata_snapshot_at))
      && <p className="text-xs">Metadata snapshot: {new Date(data.metadata_snapshot_at).toLocaleString("en-US")}. Later changes require another read.</p>}
    {!available || !checked ? <p>Current metadata is unavailable or inconsistent; no present-day source status is inferred.</p>
      : paperIds.length === 0 ? <p>No saved source papers are present in this category.</p> : <>
        {matching.map(item => {
          const raw = item.source_visibility && typeof item.source_visibility === "object" ? item.source_visibility as Record<string, unknown> : null;
          const visibility = typeof raw?.source_status === "string" && ["checked", "incomplete", "unavailable"].includes(String(item.metadata_status))
            && typeof item.metadata_status === "string" ? knownSourceVisibility(item.source_visibility) : null;
          return <div key={String(item.saved_source_position)} className="space-y-1 break-words"><p>
            Source {Number(item.saved_source_position) + 1}: {item.paper_id as string} — {item.metadata_status === "unavailable" || !visibility ? "current status unavailable"
              : `current source status ${visibility.source_status}${visibility.reported_claim_filter_eligible ? "; not scientific approval" : "; current claim-support eligibility withheld"}${item.metadata_status === "incomplete" ? "; occurrence checks incomplete" : ""}`}.
            </p><OccurrenceSummary value={item.occurrence_visibility_summary} />
            <MetadataWarnings value={item.warning_codes} />
          </div>;
        })}
        {matching.length !== paperIds.length && <p>Some current metadata is missing; those sources remain unresolved.</p>}
        <MetadataWarnings value={data?.warning_codes} />
      </>}
  </section>;
}

function MetadataWarnings({ value }: { value: unknown }) {
  if (!Array.isArray(value) || value.length > 100 || value.some(code => typeof code !== "string" || !/^[a-z][a-z0-9_]{0,119}$/.test(code))) return null;
  return <>
    {value.some(code => ["saved_source_inventory_truncated", "current_evidence_output_budget_exhausted"].includes(code))
      && <p>Current metadata coverage is incomplete because an inventory or output bound was reached.</p>}
    {value.length > 0 && <details className="text-xs"><summary className="cursor-pointer">Current metadata warning codes</summary>
      <ul className="mt-1 list-inside list-disc">{[...new Set(value)].map(code => <li key={code}>{code.replaceAll("_", " ")}</li>)}</ul>
    </details>}
  </>;
}

function OccurrenceSummary({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <p className="text-xs">Current occurrence-level metadata is unavailable.</p>;
  const data = typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
  const counts = data?.state_counts && typeof data.state_counts === "object" && !Array.isArray(data.state_counts)
    ? data.state_counts as Record<string, unknown> : null;
  const count = (item: unknown): item is number => typeof item === "number" && Number.isSafeInteger(item) && item >= 0 && item <= 5000;
  if (!data || data.version !== "material-visibility/1.0.0" || data.scientific_acceptance !== false || !counts
    || ![data.total_occurrences, data.returned_occurrences, data.omitted_occurrences].every(count)
    || Object.entries(counts).some(([state, amount]) => !["catalogue", "pending", "disputed", "corrected", "retracted", "quarantined", "unknown", "malformed"].includes(state) || !count(amount))
    || Object.values(counts).reduce<number>((sum, amount) => sum + Number(amount), 0) !== data.total_occurrences
    || Number(data.returned_occurrences) + Number(data.omitted_occurrences) !== data.total_occurrences) return <p className="text-xs">Current occurrence metadata is inconsistent; no counts are inferred.</p>;
  return <p className="text-xs">Current paper occurrences: {Object.entries(counts).map(([state, amount]) => `${state}: ${Number(amount).toLocaleString("en-US")}`).join("; ") || "none"}.
    {Number(data.omitted_occurrences) > 0 && ` ${Number(data.omitted_occurrences).toLocaleString("en-US")} restricted or malformed occurrences omitted.`} These are current metadata counts, not independent scientific evidence.</p>;
}
