"use client";

import { useCallback, useEffect, useRef } from "react";
import { useReportWebVitals } from "next/web-vitals";

import { loadConsent, type ConsentState } from "@/components/CookieConsent";
import { PUBLIC_API_BASE } from "@/lib/api";

type ClientEvent = {
  event_type: "web_vital" | "js_error" | "unhandled_rejection";
  name: "CLS" | "FCP" | "INP" | "LCP" | "TTFB" | "error" | "rejection";
  value?: number;
  rating?: "good" | "needs-improvement" | "poor" | "unknown";
};

const rawSampleRate = Number(process.env.NEXT_PUBLIC_WEB_VITALS_SAMPLE_RATE ?? "0.1");
const sampleRate = Number.isFinite(rawSampleRate)
  ? Math.max(0, Math.min(1, rawSampleRate))
  : 0.1;

export function WebVitalsReporter() {
  const allowed = useRef(false);
  const sampled = useRef(Math.random() < sampleRate);

  const send = useCallback((event: ClientEvent) => {
    if (!allowed.current || !sampled.current) return;
    void fetch(`${PUBLIC_API_BASE}/telemetry/client`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(event),
      credentials: "omit",
      keepalive: true,
    }).catch(() => undefined);
  }, []);

  useReportWebVitals((metric) => {
    if (!["CLS", "FCP", "INP", "LCP", "TTFB"].includes(metric.name)) return;
    send({
      event_type: "web_vital",
      name: metric.name as ClientEvent["name"],
      value: metric.value,
      rating: metric.rating ?? "unknown",
    });
  });

  useEffect(() => {
    const syncConsent = (event?: Event) => {
      const detail = (event as CustomEvent<ConsentState> | undefined)?.detail;
      allowed.current = (detail ?? loadConsent()).analytics;
    };
    const onError = () => send({ event_type: "js_error", name: "error" });
    const onRejection = () =>
      send({ event_type: "unhandled_rejection", name: "rejection" });

    syncConsent();
    window.addEventListener("consent-change", syncConsent);
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("consent-change", syncConsent);
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, [send]);

  return null;
}
