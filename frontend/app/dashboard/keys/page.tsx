"use client";

/**
 * /dashboard/keys — API keys tab.
 *
 * Claude-Console style: one button to create, one table of existing
 * keys with per-row Revoke. The create modal is the only place the
 * plaintext secret is ever shown.
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { listKeys, type ApiKey } from "@/lib/api";
import { loadToken } from "@/lib/auth-storage";
import { KeysTable } from "@/components/dashboard/KeysTable";
import { NewKeyModal } from "@/components/dashboard/NewKeyModal";

export default function KeysPage() {
  const [keys, setKeys] = useState<ApiKey[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);

  const refetch = useCallback(() => {
    const token = loadToken();
    if (!token) return;
    listKeys(token)
      .then(setKeys)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load keys"),
      );
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  const active = (keys ?? []).filter((k) => !k.revoked).length;

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold text-sage-ink">API keys</h2>
          <p className="mt-1 text-sm text-sage-muted">
            Use <code>X-API-Key: scl_…</code> to authenticate API
            requests. {active} active, {(keys?.length ?? 0) - active} revoked.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/docs/api"
            target="_blank"
            className="rounded-md border border-sage-border bg-white px-3 py-2 text-sm font-medium text-sage-muted hover:text-accent-deep hover:border-accent-light"
          >
            API Docs
          </Link>
          <button
            onClick={() => setShowModal(true)}
            className="rounded-md bg-accent-deep px-3 py-2 text-sm font-medium text-white hover:bg-accent"
          >
            + New key
          </button>
        </div>
      </div>

      {error && (
        <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      {keys === null ? (
        <p className="text-sm text-sage-muted">Loading keys…</p>
      ) : (
        <KeysTable keys={keys} onChanged={refetch} />
      )}

      <NewKeyModal
        open={showModal}
        onClose={() => setShowModal(false)}
        onCreated={refetch}
      />
    </div>
  );
}
