"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { confirmPasswordReset, friendlyErrorMessage } from "@/lib/api";

function ResetPasswordForm() {
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [complete, setComplete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (password !== confirmation) {
      setError("Passwords do not match.");
      return;
    }
    setSubmitting(true);
    try {
      await confirmPasswordReset(token, password);
      setComplete(true);
    } catch (err) {
      setError(friendlyErrorMessage(err, "This reset link is invalid or expired."));
    } finally {
      setSubmitting(false);
    }
  }

  if (!token) {
    return (
      <p className="mt-5 text-sm text-red-700">
        This reset link is incomplete. Request a new link from the{" "}
        <Link href="/forgot-password" className="underline">reset page</Link>.
      </p>
    );
  }

  if (complete) {
    return (
      <div className="mt-5 space-y-4 text-sm text-slate-600">
        <p>Your password has been updated and all existing sessions were revoked.</p>
        <Link href="/login" className="font-medium text-slate-900 underline">
          Sign in with your new password
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="mt-6 space-y-4">
      <label className="block">
        <span className="text-sm font-medium">New password</span>
        <input
          type="password"
          autoComplete="new-password"
          minLength={8}
          maxLength={128}
          className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
        />
      </label>
      <label className="block">
        <span className="text-sm font-medium">Confirm new password</span>
        <input
          type="password"
          autoComplete="new-password"
          minLength={8}
          maxLength={128}
          className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
          value={confirmation}
          onChange={(event) => setConfirmation(event.target.value)}
          required
        />
      </label>
      {error && (
        <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={submitting}
        className="w-full rounded-md bg-slate-900 px-4 py-2 text-white hover:bg-slate-700 disabled:opacity-50"
      >
        {submitting ? "Updating…" : "Update password"}
      </button>
    </form>
  );
}

export default function ResetPasswordPage() {
  return (
    <main className="mx-auto max-w-md px-6 py-20">
      <h1 className="text-2xl font-semibold">Choose a new password</h1>
      <Suspense fallback={<p className="mt-5 text-sm text-slate-600">Loading…</p>}>
        <ResetPasswordForm />
      </Suspense>
    </main>
  );
}
