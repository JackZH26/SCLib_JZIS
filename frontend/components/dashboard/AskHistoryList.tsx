"use client";

/**
 * Collapsible list of past /ask questions.
 *
 * Entries are newest first, paginated from the server. Each row is
 * collapsed by default (just the question preview + timestamp + meta)
 * and expands in place to show the full markdown answer + citation
 * list — no separate detail page. Delete is an immediate DB delete
 * (no undo) so we gate it behind ConfirmModal.
 *
 * The answer uses <pre white-space: pre-wrap> to render the markdown
 * source as-is. A later polish commit can swap in react-markdown
 * when we're ready to carry the dependency.
 */
import Link from "next/link";
import { useState } from "react";

import {
  ApiError,
  deleteHistoryEntry,
  type AskHistoryEntry,
} from "@/lib/api";
import { loadToken } from "@/lib/auth-storage";
import { ConfirmModal } from "@/components/dashboard/ConfirmModal";

export function AskHistoryList({
  entries,
  onDeleted,
}: {
  entries: AskHistoryEntry[];
  onDeleted: () => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [confirming, setConfirming] = useState<AskHistoryEntry | null>(null);
  const [error, setError] = useState<string | null>(null);

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function performDelete(entry: AskHistoryEntry) {
    const token = loadToken();
    if (!token) return;
    setError(null);
    try {
      await deleteHistoryEntry(token, entry.id);
      onDeleted();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to delete");
    } finally {
      setConfirming(null);
    }
  }

  if (entries.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-sage-border bg-white p-8 text-center text-sm text-sage-muted">
        No questions in the last 90 days. Ask something on{" "}
        <Link href="/ask" className="text-accent-deep hover:underline">
          /ask
        </Link>{" "}
        and it will show up here.
      </div>
    );
  }

  return (
    <div>
      {error && (
        <p className="mb-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}
      <ul className="space-y-2">
        {entries.map((e) => {
          const open = expanded.has(e.id);
          return (
            <li
              key={e.id}
              className="rounded-lg border border-sage-border bg-white shadow-sage"
            >
              <div className="flex items-start gap-3 p-4">
                <button
                  type="button"
                  onClick={() => toggle(e.id)}
                  className="flex-1 text-left"
                >
                  <p className="text-sm font-medium text-sage-ink">
                    {truncate(e.question, 160)}
                  </p>
                  <p className="mt-1 text-xs text-sage-tertiary">
                    {formatDate(e.created_at)} · {e.latency_ms} ms ·{" "}
                    {e.sources.length} source{e.sources.length === 1 ? "" : "s"}
                    {e.tokens_used != null ? ` · ${e.tokens_used} tokens` : ""}
                  </p>
                </button>
                <div className="flex shrink-0 items-center gap-2">
                  <button
                    type="button"
                    onClick={() => toggle(e.id)}
                    className="rounded-md border border-sage-border bg-white px-2.5 py-1 text-xs text-sage-muted hover:text-accent-deep"
                  >
                    {open ? "Collapse" : "Expand"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirming(e)}
                    className="rounded-md border border-sage-border bg-white px-2.5 py-1 text-xs text-red-700 hover:bg-red-50"
                  >
                    Delete
                  </button>
                </div>
              </div>
              {open && (
                <div className="border-t border-sage-border bg-slate-50/60 px-4 pb-4 pt-3">
                  <h4 className="text-xs font-semibold uppercase tracking-wide text-sage-tertiary">
                    Question
                  </h4>
                  <p className="mt-1 whitespace-pre-wrap text-sm text-sage-ink">
                    {e.question}
                  </p>
                  <h4 className="mt-4 text-xs font-semibold uppercase tracking-wide text-sage-tertiary">
                    Answer
                  </h4>
                  <pre className="mt-1 whitespace-pre-wrap break-words rounded-md bg-white p-3 text-sm leading-relaxed text-sage-ink">
                    {e.answer}
                  </pre>
                  {e.sources.length > 0 && (
                    <>
                      <h4 className="mt-4 text-xs font-semibold uppercase tracking-wide text-sage-tertiary">
                        Sources
                      </h4>
                      <ol className="mt-1 space-y-1 text-xs text-sage-muted">
                        {e.sources.map((s, i) => (
                          <li key={i} className="flex gap-2">
                            <span className="font-semibold text-accent-deep">
                              [{s.index ?? i + 1}]
                            </span>
                            <span>
                              {s.paper_id ? (
                                <Link
                                  href={`/paper/${encodeURIComponent(s.paper_id)}`}
                                  className="text-accent-deep hover:underline"
                                >
                                  {s.title ?? s.paper_id}
                                </Link>
                              ) : (
                                s.title ?? "(untitled)"
                              )}
                              {s.authors_short ? ` — ${s.authors_short}` : ""}
                              {s.year ? ` (${s.year})` : ""}
                            </span>
                          </li>
                        ))}
                      </ol>
                    </>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>

      <ConfirmModal
        open={confirming !== null}
        title="Delete this question?"
        body={
          <>
            <span className="block italic text-sage-ink">
              {confirming ? truncate(confirming.question, 120) : ""}
            </span>
            <span className="mt-2 block">
              The answer and its citations will be permanently removed from
              your history. This cannot be undone.
            </span>
          </>
        }
        confirmLabel="Delete"
        tone="destructive"
        onConfirm={async () => {
          if (confirming) await performDelete(confirming);
        }}
        onCancel={() => setConfirming(null)}
      />
    </div>
  );
}

function truncate(s: string, n: number): string {
  const clean = s.replace(/\s+/g, " ").trim();
  return clean.length > n ? `${clean.slice(0, n - 1)}…` : clean;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}
