"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { notifyAuthChange } from "@/lib/auth-session";
import { friendlyErrorMessage, revokeAllSessions } from "@/lib/api";

export function SessionSecurityCard() {
  const router = useRouter();
  const [revoking, setRevoking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function revoke() {
    if (!window.confirm("Sign out every browser and invalidate every bearer token?")) {
      return;
    }
    setRevoking(true);
    setError(null);
    try {
      await revokeAllSessions();
      notifyAuthChange();
      router.replace("/login");
    } catch (err) {
      setError(friendlyErrorMessage(err, "Unable to revoke sessions."));
      setRevoking(false);
    }
  }

  return (
    <section className="rounded-lg border border-sage-border bg-white p-5 shadow-sage">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-sage-tertiary">
        Session security
      </h2>
      <p className="mt-2 text-sm text-sage-muted">
        If a device or bearer token may be compromised, invalidate every active
        browser and API bearer session. API keys are managed separately in the Keys tab.
      </p>
      {error && <p className="mt-3 text-sm text-red-700">{error}</p>}
      <button
        type="button"
        onClick={revoke}
        disabled={revoking}
        className="mt-4 rounded-md border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
      >
        {revoking ? "Revoking…" : "Revoke all sessions"}
      </button>
    </section>
  );
}
