"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

/**
 * Cookie-consent categories the user can toggle. "necessary" is always
 * on and cannot be turned off — it covers session handling and the
 * consent preference itself. "analytics" gates Google Analytics (GA4).
 *
 * Consent state is stored in localStorage under `cookie_consent`.
 * The GA script loader in layout.tsx reads this before firing gtag().
 */
export type ConsentState = {
  necessary: true;
  analytics: boolean;
  decided: boolean;           // true once the user clicked any button
  decidedAt?: string;         // ISO-8601
};

const STORAGE_KEY = "cookie_consent";

const DEFAULT_STATE: ConsentState = {
  necessary: true,
  analytics: false,
  decided: false,
};

export function loadConsent(): ConsentState {
  if (typeof window === "undefined") return DEFAULT_STATE;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw) as ConsentState;
  } catch { /* corrupted — treat as undecided */ }
  return DEFAULT_STATE;
}

export function saveConsent(state: ConsentState) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  // Notify GA loader and other listeners
  window.dispatchEvent(new CustomEvent("consent-change", { detail: state }));
}

// ---------- Banner UI ----------

export function CookieConsentBanner() {
  const [consent, setConsent] = useState<ConsentState | null>(null);
  const [showCustomize, setShowCustomize] = useState(false);

  useEffect(() => {
    setConsent(loadConsent());
  }, []);

  // Don't render on the server or if the user already decided
  if (!consent || consent.decided) return null;

  const accept = () => {
    const next: ConsentState = {
      necessary: true,
      analytics: true,
      decided: true,
      decidedAt: new Date().toISOString(),
    };
    saveConsent(next);
    setConsent(next);
  };

  const reject = () => {
    const next: ConsentState = {
      necessary: true,
      analytics: false,
      decided: true,
      decidedAt: new Date().toISOString(),
    };
    saveConsent(next);
    setConsent(next);
  };

  const saveCustom = (analytics: boolean) => {
    const next: ConsentState = {
      necessary: true,
      analytics,
      decided: true,
      decidedAt: new Date().toISOString(),
    };
    saveConsent(next);
    setConsent(next);
  };

  return (
    <div className="fixed bottom-4 right-4 z-[100] w-[340px] max-w-[calc(100vw-2rem)] rounded-xl border border-sage-border bg-white shadow-lg">
      <div className="p-4">
        <h2 className="text-sm font-semibold text-slate-900">
          Cookie preferences
        </h2>

        <p className="mt-1.5 text-xs leading-relaxed text-slate-600">
          We use cookies for site functionality and anonymous analytics.{" "}
          <Link
            href="/cookies"
            className="font-medium text-accent-deep underline underline-offset-2 hover:text-slate-800"
          >
            Cookie Policy
          </Link>
        </p>

        {showCustomize ? (
          /* ---- Customize panel ---- */
          <div className="mt-3 space-y-2">
            {/* Necessary — always on */}
            <label className="flex items-center justify-between rounded-md border border-sage-border bg-slate-50 px-3 py-2">
              <div>
                <span className="text-xs font-medium text-slate-800">
                  Necessary
                </span>
                <p className="text-[11px] leading-tight text-slate-500">
                  Always active
                </p>
              </div>
              <input
                type="checkbox"
                checked
                disabled
                className="h-3.5 w-3.5 accent-accent-deep"
              />
            </label>

            {/* Analytics — toggleable */}
            <label className="flex cursor-pointer items-center justify-between rounded-md border border-sage-border px-3 py-2 transition-colors hover:bg-slate-50">
              <div>
                <span className="text-xs font-medium text-slate-800">
                  Analytics
                </span>
                <p className="text-[11px] leading-tight text-slate-500">
                  Google Analytics (GA4)
                </p>
              </div>
              <input
                type="checkbox"
                defaultChecked
                id="analytics-toggle"
                className="h-3.5 w-3.5 accent-accent-deep"
              />
            </label>

            <div className="flex gap-2 pt-1">
              <button
                onClick={() => {
                  const checked = (
                    document.getElementById("analytics-toggle") as HTMLInputElement
                  )?.checked ?? false;
                  saveCustom(checked);
                }}
                className="btn-primary flex-1 rounded-md px-3 py-1.5 text-xs font-medium"
              >
                Save
              </button>
              <button
                onClick={() => setShowCustomize(false)}
                className="btn-outline flex-1 rounded-md px-3 py-1.5 text-xs font-medium"
              >
                Back
              </button>
            </div>
          </div>
        ) : (
          /* ---- Default buttons ---- */
          <div className="mt-3 flex gap-2">
            <button
              onClick={accept}
              className="btn-primary flex-1 rounded-md px-3 py-1.5 text-xs font-medium"
            >
              Accept all
            </button>
            <button
              onClick={reject}
              className="btn-outline flex-1 rounded-md px-3 py-1.5 text-xs font-medium"
            >
              Reject all
            </button>
            <button
              onClick={() => setShowCustomize(true)}
              className="btn-outline flex-1 rounded-md px-3 py-1.5 text-xs font-medium"
            >
              Customize
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
