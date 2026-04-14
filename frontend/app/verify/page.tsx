"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { verifyEmail, ApiError } from "@/lib/api";

type State =
  | { kind: "loading" }
  | { kind: "ok"; apiKey: string; email: string }
  | { kind: "error"; message: string };

// useSearchParams() forces client-side bail-out; wrap in Suspense so the
// Next.js static builder can emit a shell for /verify at build time.
export default function VerifyPage() {
  return (
    <Suspense fallback={<main className="mx-auto max-w-md px-6 py-20"><p className="text-slate-500">Loading…</p></main>}>
      <VerifyInner />
    </Suspense>
  );
}

function VerifyInner() {
  const params = useSearchParams();
  const token = params.get("token");
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    if (!token) {
      setState({ kind: "error", message: "Missing verification token." });
      return;
    }
    verifyEmail(token)
      .then((r) =>
        setState({ kind: "ok", apiKey: r.api_key, email: r.user.email }),
      )
      .catch((err) =>
        setState({
          kind: "error",
          message:
            err instanceof ApiError ? err.message : "Verification failed",
        }),
      );
  }, [token]);

  return (
    <main className="mx-auto max-w-md px-6 py-20">
      {state.kind === "loading" && (
        <p className="text-slate-600">Verifying your email…</p>
      )}
      {state.kind === "error" && (
        <>
          <h1 className="text-2xl font-semibold text-red-700">
            Verification failed
          </h1>
          <p className="mt-3 text-slate-600">{state.message}</p>
          <Link href="/register" className="mt-6 inline-block underline">
            Start over
          </Link>
        </>
      )}
      {state.kind === "ok" && (
        <>
          <h1 className="text-2xl font-semibold">Email verified ✓</h1>
          <p className="mt-3 text-slate-600">
            Welcome, <strong>{state.email}</strong>. Here is your first API
            key — copy it now, it will not be shown again:
          </p>
          <pre className="mt-4 overflow-x-auto rounded-md bg-slate-900 px-4 py-3 text-sm text-slate-100">
            {state.apiKey}
          </pre>
          <Link
            href="/login"
            className="mt-6 inline-block rounded-md bg-slate-900 px-4 py-2 text-white"
          >
            Continue to sign in
          </Link>
        </>
      )}
    </main>
  );
}
