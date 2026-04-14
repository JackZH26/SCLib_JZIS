"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  me,
  createKey,
  revokeKey,
  ApiError,
  type User,
  type ApiKeyWithSecret,
} from "@/lib/api";
import { clearToken, loadToken } from "@/lib/auth-storage";

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newKey, setNewKey] = useState<ApiKeyWithSecret | null>(null);
  const [keyName, setKeyName] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const token = loadToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    me(token)
      .then(setUser)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          clearToken();
          router.replace("/login");
        } else {
          setError(err.message);
        }
      });
  }, [router]);

  async function onCreateKey(e: React.FormEvent) {
    e.preventDefault();
    const token = loadToken();
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      const k = await createKey(token, keyName || "default");
      setNewKey(k);
      setKeyName("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  async function onRevoke(id: string) {
    const token = loadToken();
    if (!token) return;
    try {
      await revokeKey(token, id);
      if (newKey?.id === id) setNewKey(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed");
    }
  }

  function onSignOut() {
    clearToken();
    router.push("/login");
  }

  if (!user) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-20">
        {error ? (
          <p className="text-red-700">{error}</p>
        ) : (
          <p className="text-slate-500">Loading…</p>
        )}
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-16">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold">Welcome, {user.name}</h1>
        <button onClick={onSignOut} className="text-sm underline">
          Sign out
        </button>
      </div>
      <p className="mt-1 text-slate-600">{user.email}</p>

      <section className="mt-10">
        <h2 className="text-lg font-semibold">API keys</h2>
        <p className="mt-1 text-sm text-slate-600">
          API keys authenticate requests to the SCLib API. Keep them secret —
          they will only be shown once, right after creation.
        </p>

        <form onSubmit={onCreateKey} className="mt-4 flex gap-2">
          <input
            placeholder="key name (e.g. laptop)"
            className="flex-1 rounded-md border border-slate-300 px-3 py-2"
            value={keyName}
            onChange={(e) => setKeyName(e.target.value)}
          />
          <button
            type="submit"
            disabled={busy}
            className="rounded-md bg-slate-900 px-4 py-2 text-white hover:bg-slate-700 disabled:opacity-50"
          >
            Create key
          </button>
        </form>

        {newKey && (
          <div className="mt-4 rounded-md border border-green-300 bg-green-50 p-4">
            <p className="text-sm font-medium text-green-900">
              New key — copy it now:
            </p>
            <pre className="mt-2 overflow-x-auto rounded bg-slate-900 px-3 py-2 text-xs text-slate-100">
              {newKey.key}
            </pre>
            <button
              onClick={() => onRevoke(newKey.id)}
              className="mt-3 text-xs text-red-700 underline"
            >
              Revoke immediately
            </button>
          </div>
        )}

        {error && (
          <p className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}
      </section>
    </main>
  );
}
