"use client";

/**
 * /dashboard/history — Ask history tab.
 *
 * Lists the user's past /ask queries within the rolling 90-day window.
 * Pagination is a simple Load-more button against /history?offset=.
 * Delete is per-entry (gated by ConfirmModal inside AskHistoryList).
 */
import { useCallback, useEffect, useState } from "react";

import { listHistory, type AskHistoryEntry } from "@/lib/api";
import { loadToken } from "@/lib/auth-storage";
import { AskHistoryList } from "@/components/dashboard/AskHistoryList";

const PAGE_SIZE = 50;

export default function HistoryPage() {
  const [entries, setEntries] = useState<AskHistoryEntry[] | null>(null);
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    const token = loadToken();
    if (!token) return;
    try {
      const resp = await listHistory(token, PAGE_SIZE, 0);
      setEntries(resp.results);
      setTotal(resp.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load history");
    }
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  async function loadMore() {
    const token = loadToken();
    if (!token || entries === null) return;
    setLoadingMore(true);
    try {
      const resp = await listHistory(token, PAGE_SIZE, entries.length);
      setEntries([...entries, ...resp.results]);
      setTotal(resp.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load more");
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-sage-ink">Ask history</h2>
        <p className="mt-1 text-sm text-sage-muted">
          Your /ask questions from the last 90 days. Older entries are
          pruned automatically. {total > 0 && <>· {total} total</>}
        </p>
      </div>

      {error && (
        <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      {entries === null ? (
        <p className="text-sm text-sage-muted">Loading history…</p>
      ) : (
        <>
          <AskHistoryList entries={entries} onDeleted={refetch} />
          {entries.length < total && (
            <div className="flex justify-center pt-2">
              <button
                onClick={loadMore}
                disabled={loadingMore}
                className="rounded-md border border-sage-border bg-white px-4 py-2 text-sm text-sage-muted hover:text-accent-deep disabled:opacity-60"
              >
                {loadingMore ? "Loading…" : `Load ${Math.min(PAGE_SIZE, total - entries.length)} more`}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
