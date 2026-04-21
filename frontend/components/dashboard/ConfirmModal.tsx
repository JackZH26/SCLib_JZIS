"use client";

/**
 * Destructive-action confirmation dialog. Replaces the browser's
 * native ``window.confirm`` so the UX is consistent with the rest
 * of the dashboard (and readable on mobile, where the native dialog
 * is tiny).
 *
 * Usage::
 *
 *   const [confirming, setConfirming] = useState<K | null>(null);
 *   <ConfirmModal
 *     open={confirming !== null}
 *     title="Revoke key?"
 *     body="…"
 *     confirmLabel="Revoke"
 *     tone="destructive"
 *     onConfirm={async () => { await doIt(confirming); setConfirming(null); }}
 *     onCancel={() => setConfirming(null)}
 *   />
 */
import { useState } from "react";

export function ConfirmModal({
  open,
  title,
  body,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  tone = "destructive",
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  body: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "destructive" | "primary";
  onConfirm: () => void | Promise<void>;
  onCancel: () => void;
}) {
  const [busy, setBusy] = useState(false);

  if (!open) return null;

  const confirmClasses =
    tone === "destructive"
      ? "bg-red-600 text-white hover:bg-red-700"
      : "bg-accent-deep text-white hover:bg-accent";

  async function handleConfirm() {
    setBusy(true);
    try {
      await onConfirm();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/30 p-4 pt-20"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-md rounded-lg border border-sage-border bg-white p-6 shadow-sage-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-base font-semibold text-sage-ink">{title}</h2>
        <div className="mt-2 text-sm text-sage-muted">{body}</div>
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="rounded-md border border-sage-border bg-white px-3 py-1.5 text-sm text-sage-muted hover:text-accent-deep disabled:opacity-60"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={busy}
            className={`rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-60 ${confirmClasses}`}
          >
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
