"use client";

/**
 * API keys table — Claude-Console-style list of the user's keys.
 *
 * Active and revoked rows share the table; revoked rows are muted and
 * show the revocation timestamp in place of the Revoke button. Click
 * Revoke twice (confirm prompt) to turn an active row into a revoked
 * one; we optimistically update the row so the UI reflects the state
 * even before the list refetch lands.
 */
import { useState } from "react";

import { ApiError, revokeKey, type ApiKey } from "@/lib/api";
import { loadToken } from "@/lib/auth-storage";
import { ConfirmModal } from "@/components/dashboard/ConfirmModal";

export function KeysTable({
  keys,
  onChanged,
}: {
  keys: ApiKey[];
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<ApiKey | null>(null);

  async function performRevoke(k: ApiKey) {
    const token = loadToken();
    if (!token) return;
    setBusy(k.id);
    setError(null);
    try {
      await revokeKey(token, k.id);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to revoke");
    } finally {
      setBusy(null);
      setConfirming(null);
    }
  }

  if (keys.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-sage-border bg-white p-8 text-center text-sm text-sage-muted">
        No API keys yet. Create one to start calling the API.
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
      <div className="overflow-x-auto rounded-lg border border-sage-border bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-sage-tertiary">
            <tr>
              <th className="px-4 py-2 text-left font-medium">Name</th>
              <th className="px-4 py-2 text-left font-medium">Key</th>
              <th className="px-4 py-2 text-left font-medium">Created</th>
              <th className="px-4 py-2 text-left font-medium">Last used</th>
              <th className="px-4 py-2 text-right font-medium">Requests</th>
              <th className="px-4 py-2 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {keys.map((k) => (
              <tr
                key={k.id}
                className={k.revoked ? "bg-slate-50 text-sage-tertiary" : undefined}
              >
                <td className="px-4 py-2">
                  <span className={k.revoked ? "line-through" : "font-medium text-sage-ink"}>
                    {k.name ?? "—"}
                  </span>
                </td>
                <td className="px-4 py-2 font-mono text-xs text-sage-muted">
                  {k.key_prefix}…
                </td>
                <td className="px-4 py-2 text-sage-muted">
                  {formatAbs(k.created_at)}
                </td>
                <td className="px-4 py-2 text-sage-muted">
                  {k.last_used ? formatRelative(k.last_used) : "Never"}
                </td>
                <td className="px-4 py-2 text-right tabular-nums text-sage-muted">
                  {k.total_requests.toLocaleString()}
                </td>
                <td className="px-4 py-2 text-right">
                  {k.revoked ? (
                    <span className="text-xs text-slate-400">
                      Revoked{" "}
                      {k.revoked_at ? formatRelative(k.revoked_at) : ""}
                    </span>
                  ) : (
                    <button
                      onClick={() => setConfirming(k)}
                      disabled={busy === k.id}
                      className="rounded-md border border-sage-border bg-white px-3 py-1 text-xs text-red-700 hover:bg-red-50 disabled:opacity-60"
                    >
                      {busy === k.id ? "Revoking…" : "Revoke"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ConfirmModal
        open={confirming !== null}
        title="Revoke API key?"
        body={
          <>
            Key <code>{confirming?.name ?? confirming?.key_prefix}…</code>{" "}
            will stop authenticating requests immediately. You can create a
            new one, but this action cannot be undone.
          </>
        }
        confirmLabel="Revoke"
        tone="destructive"
        onConfirm={async () => {
          if (confirming) await performRevoke(confirming);
        }}
        onCancel={() => setConfirming(null)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Date helpers
// ---------------------------------------------------------------------------

function formatAbs(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

function formatRelative(iso: string): string {
  try {
    const then = new Date(iso).getTime();
    const diffSec = Math.round((Date.now() - then) / 1000);
    if (diffSec < 60) return `${diffSec}s ago`;
    const diffMin = Math.round(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.round(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    const diffDay = Math.round(diffHr / 24);
    if (diffDay < 30) return `${diffDay}d ago`;
    return formatAbs(iso);
  } catch {
    return iso;
  }
}
