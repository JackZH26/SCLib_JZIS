"use client";

/**
 * Modal prompting for a key name, then showing the plaintext secret
 * exactly once. The full key is only returned by POST /auth/keys on
 * the success path; the backend never exposes it again. We render it
 * inside a code block with a Copy button and an explicit warning, so
 * a user closing the modal without copying knows what they lost.
 */
import { useState } from "react";

import { ApiError, createKey, type ApiKeyWithSecret } from "@/lib/api";
import { loadToken } from "@/lib/auth-storage";

export function NewKeyModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fresh, setFresh] = useState<ApiKeyWithSecret | null>(null);
  const [copied, setCopied] = useState(false);

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    const token = loadToken();
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      const k = await createKey(token, name.trim() || "default");
      setFresh(k);
      onCreated(); // triggers list refetch in parent
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create key");
    } finally {
      setBusy(false);
    }
  }

  async function onCopy() {
    if (!fresh) return;
    try {
      await navigator.clipboard.writeText(fresh.key);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Non-fatal; the secret is visible on screen, user can select-copy.
    }
  }

  function onDismiss() {
    setName("");
    setFresh(null);
    setError(null);
    setCopied(false);
    onClose();
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/30 p-4 pt-20">
      <div className="w-full max-w-md rounded-lg border border-sage-border bg-white p-6 shadow-sage-lg">
        {fresh ? (
          <div>
            <h2 className="text-base font-semibold text-sage-ink">
              Copy your new API key
            </h2>
            <p className="mt-1 text-xs text-sage-muted">
              This is the only time the full key will be shown. If you lose
              it, revoke this row and create a new key.
            </p>
            <div className="mt-4">
              <div className="rounded-md bg-slate-900 p-3 font-mono text-xs text-slate-100 break-all">
                {fresh.key}
              </div>
              <div className="mt-3 flex items-center gap-2">
                <button
                  onClick={onCopy}
                  className="rounded-md bg-accent-deep px-3 py-1.5 text-sm font-medium text-white hover:bg-accent"
                >
                  {copied ? "Copied ✓" : "Copy"}
                </button>
                <button
                  onClick={onDismiss}
                  className="rounded-md border border-sage-border bg-white px-3 py-1.5 text-sm text-sage-muted hover:text-accent-deep"
                >
                  Done
                </button>
              </div>
            </div>
          </div>
        ) : (
          <form onSubmit={onCreate}>
            <h2 className="text-base font-semibold text-sage-ink">
              New API key
            </h2>
            <p className="mt-1 text-xs text-sage-muted">
              Give it a short name so you can recognize it later
              (e.g. <code>laptop</code>, <code>ci-runner</code>).
            </p>
            <label className="mt-4 block">
              <span className="text-xs font-medium uppercase tracking-wide text-sage-tertiary">
                Name
              </span>
              <input
                className="mt-1 block w-full rounded-md border border-sage-border px-3 py-2 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="default"
                maxLength={100}
                autoFocus
              />
            </label>
            {error && (
              <p className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </p>
            )}
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={onDismiss}
                disabled={busy}
                className="rounded-md border border-sage-border bg-white px-3 py-1.5 text-sm text-sage-muted hover:text-accent-deep"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={busy}
                className="rounded-md bg-accent-deep px-3 py-1.5 text-sm font-medium text-white hover:bg-accent disabled:opacity-60"
              >
                {busy ? "Creating…" : "Create"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
