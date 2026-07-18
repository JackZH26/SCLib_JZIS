"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError, me } from "@/lib/api";
import { notifyAuthChange } from "@/lib/auth-session";

function CallbackInner() {
  const router = useRouter();
  const params = useSearchParams();
  const [status, setStatus] = useState<"loading" | "error">("loading");
  const [errorMsg, setErrorMsg] = useState("");

  useEffect(() => {
    const error = params.get("error");

    if (error) {
      setStatus("error");
      setErrorMsg(
        error === "oauth_failed"
          ? "Google sign-in failed. Please try again."
          : error === "missing_userinfo"
            ? "Could not retrieve account info from Google."
            : error === "account_inactive"
              ? "This account is inactive. Contact an administrator if you believe this is a mistake."
            : "An error occurred during sign-in.",
      );
      return;
    }

    me()
      .then(() => {
        notifyAuthChange();
        router.replace("/dashboard");
      })
      .catch((err: unknown) => {
        setStatus("error");
        setErrorMsg(
          err instanceof ApiError && err.status === 401
            ? "Your sign-in session could not be established. Please try again."
            : "Could not verify your sign-in. Please try again.",
        );
      });
  }, [params, router]);

  if (status === "error") {
    return (
      <main className="mx-auto max-w-md px-6 py-20 text-center">
        <h1 className="text-2xl font-semibold text-red-700">Sign-in failed</h1>
        <p className="mt-3 text-slate-600">{errorMsg}</p>
        <a
          href="/login"
          className="mt-6 inline-block rounded-md bg-slate-900 px-4 py-2 text-white hover:bg-slate-700"
        >
          Back to login
        </a>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-md px-6 py-20 text-center">
      <div className="mx-auto mb-4 h-8 w-8 animate-spin rounded-full border-2 border-slate-300 border-t-slate-900" />
      <p className="text-slate-600">Signing you in...</p>
    </main>
  );
}

export default function AuthCallbackPage() {
  return (
    <Suspense
      fallback={
        <main className="mx-auto max-w-md px-6 py-20 text-center">
          <p className="text-slate-500">Loading...</p>
        </main>
      }
    >
      <CallbackInner />
    </Suspense>
  );
}
