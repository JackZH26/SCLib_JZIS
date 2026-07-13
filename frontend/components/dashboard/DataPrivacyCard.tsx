"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import {
  deleteAccount,
  exportAccountData,
  friendlyErrorMessage,
  type User,
} from "@/lib/api";
import { notifyAuthChange } from "@/lib/auth-session";

export function DataPrivacyCard({ user }: { user: User }) {
  const router = useRouter();
  const [exporting, setExporting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onExport() {
    setExporting(true);
    setError(null);
    setMessage(null);
    try {
      const data = await exportAccountData();
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `sclib-account-${user.id}.json`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.URL.revokeObjectURL(url);
      setMessage("Your account export is ready.");
    } catch (err) {
      setError(friendlyErrorMessage(err, "Could not export account data."));
    } finally {
      setExporting(false);
    }
  }

  async function onDelete(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    if (email.trim().toLowerCase() !== user.email.toLowerCase()) {
      setError("Enter the account email exactly to confirm deletion.");
      return;
    }
    setDeleting(true);
    try {
      await deleteAccount({
        confirmation: "DELETE",
        email: email.trim(),
        current_password: password || undefined,
      });
      notifyAuthChange();
      router.replace("/login");
    } catch (err) {
      setError(friendlyErrorMessage(err, "Could not delete the account."));
    } finally {
      setDeleting(false);
    }
  }

  const needsPassword = user.auth_provider !== "google";

  return (
    <section className="rounded-lg border border-sage-border bg-white p-5 shadow-sage">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-sage-tertiary">
        Data &amp; privacy
      </h2>
      <p className="mt-2 text-sm text-sage-muted">
        Download a portable JSON copy of your profile, private history,
        bookmarks, key metadata, and security events.
      </p>
      <button
        type="button"
        onClick={onExport}
        disabled={exporting || deleting}
        className="mt-3 rounded-md border border-sage-border bg-white px-3 py-2 text-sm font-medium text-accent-deep hover:bg-[rgba(58,125,92,0.08)] disabled:opacity-60"
      >
        {exporting ? "Preparing export…" : "Download my data"}
      </button>

      <div className="mt-5 border-t border-sage-border pt-5">
        <h3 className="text-sm font-semibold text-red-800">Delete account</h3>
        <p className="mt-1 text-sm text-slate-600">
          This permanently removes your account, API keys, Ask history, and
          bookmarks. Download your data first if you want to keep a copy.
        </p>
        {!confirming ? (
          <button
            type="button"
            onClick={() => {
              setConfirming(true);
              setError(null);
              setMessage(null);
            }}
            className="mt-3 rounded-md border border-red-300 bg-white px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-50"
          >
            Delete my account
          </button>
        ) : (
          <form onSubmit={onDelete} className="mt-4 max-w-lg space-y-3 rounded-md bg-red-50 p-4">
            <label className="block">
              <span className="text-sm font-medium text-red-900">
                Type {user.email} to confirm
              </span>
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
                autoComplete="email"
                className="mt-1 block w-full rounded-md border border-red-200 bg-white px-3 py-2 text-sm"
              />
            </label>
            {needsPassword ? (
              <label className="block">
                <span className="text-sm font-medium text-red-900">Current password</span>
                <input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                  autoComplete="current-password"
                  className="mt-1 block w-full rounded-md border border-red-200 bg-white px-3 py-2 text-sm"
                />
              </label>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <button
                type="submit"
                disabled={deleting}
                className="rounded-md bg-red-700 px-3 py-2 text-sm font-medium text-white hover:bg-red-800 disabled:opacity-60"
              >
                {deleting ? "Deleting…" : "Permanently delete account"}
              </button>
              <button
                type="button"
                disabled={deleting}
                onClick={() => {
                  setConfirming(false);
                  setEmail("");
                  setPassword("");
                  setError(null);
                }}
                className="rounded-md border border-sage-border bg-white px-3 py-2 text-sm text-sage-muted"
              >
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>

      {message ? <p className="mt-3 text-sm text-accent-deep">{message}</p> : null}
      {error ? (
        <p role="alert" className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      ) : null}
    </section>
  );
}
