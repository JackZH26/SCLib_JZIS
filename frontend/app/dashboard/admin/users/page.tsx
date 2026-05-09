"use client";

/**
 * /dashboard/admin/users — admin-only user management.
 *
 * Search, ban, unban, delete, set/revoke reviewer role.
 * The shell layout already gates the sidebar entry behind
 * ``user.is_admin``; this page double-checks with a 403
 * if a non-admin somehow lands here directly.
 */
import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  adminBanUser,
  adminDeleteUser,
  adminListUsers,
  adminSetReviewer,
  adminUnbanUser,
  type AdminUserSummary,
} from "@/lib/api";
import { loadToken } from "@/lib/auth-storage";
import { ConfirmModal } from "@/components/dashboard/ConfirmModal";
import { useDashboardUser } from "@/components/dashboard/user-context";

type Action =
  | { kind: "ban"; user: AdminUserSummary }
  | { kind: "unban"; user: AdminUserSummary }
  | { kind: "delete"; user: AdminUserSummary };

const PAGE_SIZE = 50;

export default function AdminUsersPage() {
  const { user } = useDashboardUser();
  const [rows, setRows] = useState<AdminUserSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<"all" | "admin" | "active" | "inactive">("all");
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<Action | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const token = loadToken();
    if (!token) return;
    try {
      const resp = await adminListUsers(token, {
        q: q || undefined,
        role: filter === "all" ? undefined : filter,
        limit: PAGE_SIZE,
        offset,
      });
      setRows(resp.results);
      setTotal(resp.total);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load users");
    }
  }, [q, filter, offset]);

  useEffect(() => { load(); }, [load]);

  if (!user.is_admin) {
    return <p className="text-sm text-red-700">Admin access required.</p>;
  }

  async function performAction(a: Action) {
    const token = loadToken();
    if (!token) return;
    setBusyId(a.user.id);
    setError(null);
    try {
      if (a.kind === "ban") await adminBanUser(token, a.user.id);
      else if (a.kind === "unban") await adminUnbanUser(token, a.user.id);
      else if (a.kind === "delete") await adminDeleteUser(token, a.user.id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed");
    } finally {
      setBusyId(null);
      setConfirming(null);
    }
  }

  async function toggleReviewer(u: AdminUserSummary) {
    const token = loadToken();
    if (!token) return;
    setBusyId(u.id);
    setError(null);
    try {
      await adminSetReviewer(token, u.id, !u.is_reviewer);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-sage-ink">User management</h2>
        <p className="mt-1 text-sm text-sage-muted">
          {total.toLocaleString()} users total. Ban deactivates the account
          (reversible); delete is permanent. Reviewers can act on the audit
          queue but cannot manage members.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3 rounded-lg border border-sage-border bg-white p-4 text-sm shadow-sage">
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium uppercase tracking-wide text-sage-tertiary">
            Search
          </span>
          <input
            value={q}
            onChange={(e) => { setOffset(0); setQ(e.target.value); }}
            className="w-64 rounded border border-sage-border px-2 py-1"
            placeholder="email or name…"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium uppercase tracking-wide text-sage-tertiary">
            Filter
          </span>
          <select
            value={filter}
            onChange={(e) => { setOffset(0); setFilter(e.target.value as typeof filter); }}
            className="rounded border border-sage-border bg-white px-2 py-1"
          >
            <option value="all">All</option>
            <option value="admin">Admins</option>
            <option value="active">Active</option>
            <option value="inactive">Banned / inactive</option>
          </select>
        </label>
      </div>

      {error && (
        <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
      )}

      <div className="overflow-x-auto rounded-lg border border-sage-border bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-sage-tertiary">
            <tr>
              <th className="px-4 py-2 text-left font-medium">Email</th>
              <th className="px-4 py-2 text-left font-medium">Name</th>
              <th className="px-4 py-2 text-left font-medium">Status</th>
              <th className="px-4 py-2 text-left font-medium">Provider</th>
              <th className="px-4 py-2 text-left font-medium">Created</th>
              <th className="px-4 py-2 text-left font-medium">Last login</th>
              <th className="px-4 py-2 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((u) => (
              <tr key={u.id} className={u.is_active ? undefined : "bg-slate-50/60"}>
                <td className="px-4 py-2 font-mono text-xs text-sage-ink">
                  {u.email}
                </td>
                <td className="px-4 py-2 text-sage-muted">{u.name}</td>
                <td className="px-4 py-2">
                  <div className="flex flex-wrap gap-1">
                    {u.is_admin && (
                      <span className="rounded-full bg-[rgba(58,125,92,0.1)] px-2 py-0.5 text-xs font-medium text-accent-deep">
                        admin
                      </span>
                    )}
                    {u.is_reviewer && (
                      <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
                        reviewer
                      </span>
                    )}
                    {!u.is_active && (
                      <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700">
                        banned
                      </span>
                    )}
                    {!u.email_verified && (
                      <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800">
                        unverified
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-4 py-2 text-sage-muted">{u.auth_provider}</td>
                <td className="px-4 py-2 text-sage-muted">
                  {u.created_at ? u.created_at.slice(0, 10) : "—"}
                </td>
                <td className="px-4 py-2 text-sage-muted">
                  {u.last_login ? u.last_login.slice(0, 10) : "—"}
                </td>
                <td className="px-4 py-2 text-right">
                  {u.is_admin ? (
                    <span className="text-xs text-slate-400">protected</span>
                  ) : (
                    <div className="inline-flex gap-1">
                      {/* Reviewer toggle */}
                      <button
                        onClick={() => toggleReviewer(u)}
                        disabled={busyId === u.id}
                        title={u.is_reviewer ? "Revoke reviewer role" : "Grant reviewer role"}
                        className={[
                          "rounded-md border px-2.5 py-1 text-xs disabled:opacity-60",
                          u.is_reviewer
                            ? "border-blue-300 bg-blue-50 text-blue-700 hover:bg-blue-100"
                            : "border-sage-border bg-white text-sage-muted hover:bg-[rgba(58,125,92,0.08)] hover:text-accent-deep",
                        ].join(" ")}
                      >
                        {u.is_reviewer ? "Reviewer ✓" : "Set reviewer"}
                      </button>
                      {/* Ban / Unban */}
                      {u.is_active ? (
                        <button
                          onClick={() => setConfirming({ kind: "ban", user: u })}
                          disabled={busyId === u.id}
                          className="rounded-md border border-sage-border bg-white px-2.5 py-1 text-xs text-amber-800 hover:bg-amber-50 disabled:opacity-60"
                        >Ban</button>
                      ) : (
                        <button
                          onClick={() => setConfirming({ kind: "unban", user: u })}
                          disabled={busyId === u.id}
                          className="rounded-md border border-sage-border bg-white px-2.5 py-1 text-xs text-accent-deep hover:bg-[rgba(58,125,92,0.08)] disabled:opacity-60"
                        >Unban</button>
                      )}
                      <button
                        onClick={() => setConfirming({ kind: "delete", user: u })}
                        disabled={busyId === u.id}
                        className="rounded-md border border-sage-border bg-white px-2.5 py-1 text-xs text-red-700 hover:bg-red-50 disabled:opacity-60"
                      >Delete</button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between text-xs text-sage-muted">
          <span>
            {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              disabled={offset === 0}
              className="rounded-md border border-sage-border bg-white px-3 py-1 hover:bg-slate-50 disabled:opacity-50"
            >‹ Prev</button>
            <button
              onClick={() => setOffset(offset + PAGE_SIZE)}
              disabled={offset + PAGE_SIZE >= total}
              className="rounded-md border border-sage-border bg-white px-3 py-1 hover:bg-slate-50 disabled:opacity-50"
            >Next ›</button>
          </div>
        </div>
      )}

      <ConfirmModal
        open={confirming !== null}
        title={
          confirming?.kind === "ban"   ? "Ban user?" :
          confirming?.kind === "unban" ? "Unban user?" :
          confirming?.kind === "delete"? "Delete user?" : ""
        }
        body={
          <span>
            <code className="font-mono">{confirming?.user.email}</code>
            {" "}—{" "}
            {confirming?.kind === "ban"   && "account will be deactivated. They can be unbanned later."}
            {confirming?.kind === "unban" && "account will be reactivated. They will regain access immediately."}
            {confirming?.kind === "delete"&& "account + ALL associated API keys, bookmarks, and ask history will be permanently removed. This cannot be undone."}
          </span>
        }
        confirmLabel={
          confirming?.kind === "delete" ? "Delete" :
          confirming?.kind === "ban"    ? "Ban"    : "Unban"
        }
        tone={confirming?.kind === "unban" ? "primary" : "destructive"}
        onConfirm={async () => { if (confirming) await performAction(confirming); }}
        onCancel={() => setConfirming(null)}
      />
    </div>
  );
}
