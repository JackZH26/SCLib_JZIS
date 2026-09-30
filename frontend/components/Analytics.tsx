"use client";

import Script from "next/script";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { isPrivatePage } from "@/lib/site-routes";
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
  const privatePage = isPrivatePage(usePathname());

  useEffect(() => {
    (window as unknown as Record<string, unknown>)[`ga-disable-${GA_ID}`] = privatePage || !allowed;
  }, [privatePage, allowed]);

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

  if (!allowed || privatePage) return null;

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
        gtag('config', '${GA_ID}', {
          page_location: window.location.origin + window.location.pathname,
          page_referrer: window.location.origin,
          allow_google_signals: false,
          allow_ad_personalization_signals: false
        });
      `}</Script>
    </>
  );
}
