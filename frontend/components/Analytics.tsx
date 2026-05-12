"use client";

import Script from "next/script";
import { useEffect, useState } from "react";
import { loadConsent, type ConsentState } from "./CookieConsent";

const GA_ID = "G-PXQFVFVRST";

/**
 * Conditionally loads Google Analytics based on cookie consent.
 *
 * - On first render, reads consent from localStorage.
 * - Listens for `consent-change` events (fired when the user clicks
 *   Accept/Reject in the banner) and reacts immediately.
 * - When analytics=true, injects the gtag scripts.
 * - When analytics=false (or undecided), does not load anything.
 */
export function Analytics() {
  const [allowed, setAllowed] = useState(false);

  useEffect(() => {
    const consent = loadConsent();
    setAllowed(consent.decided && consent.analytics);

    const handler = (e: Event) => {
      const detail = (e as CustomEvent<ConsentState>).detail;
      setAllowed(detail.decided && detail.analytics);
    };
    window.addEventListener("consent-change", handler);
    return () => window.removeEventListener("consent-change", handler);
  }, []);

  if (!allowed) return null;

  return (
    <>
      <Script
        src={`https://www.googletagmanager.com/gtag/js?id=${GA_ID}`}
        strategy="afterInteractive"
      />
      <Script id="gtag-init" strategy="afterInteractive">{`
        window.dataLayer = window.dataLayer || [];
        function gtag(){dataLayer.push(arguments);}
        gtag('js', new Date());
        gtag('config', '${GA_ID}');
      `}</Script>
    </>
  );
}
