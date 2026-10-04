"use client";

import { useEffect } from "react";

const contextAnchors = new Set([
  "study-context-bi-transport",
  "study-context-bi-raman",
  "study-context-pt-calorimetry-attribution",
  "study-context-pt-xrd-correspondence",
]);

/** Reveal the requested source reading context while preserving ordinary closed disclosures. */
export function StudyContextHashReveal() {
  useEffect(() => {
    let revealFrame: number | null = null, scrollFrame: number | null = null, disposed = false;
    const cancelFrames = () => {
      if (revealFrame !== null) cancelAnimationFrame(revealFrame);
      if (scrollFrame !== null) cancelAnimationFrame(scrollFrame);
      revealFrame = null;
      scrollFrame = null;
    };
    const scheduleReveal = () => {
      cancelFrames();
      revealFrame = requestAnimationFrame(() => {
        revealFrame = null;
        if (disposed) return;
        const requestedHash = window.location.hash, id = requestedHash.slice(1);
        if (!contextAnchors.has(id)) return;
        const target = document.getElementById(id);
        if (!target) return;
        for (let element: HTMLElement | null = target; element; element = element.parentElement) {
          if (element instanceof HTMLDetailsElement) element.open = true;
        }
        scrollFrame = requestAnimationFrame(() => {
          scrollFrame = null;
          if (!disposed && target.isConnected && window.location.hash === requestedHash) {
            target.scrollIntoView({ block: "start", behavior: "auto" });
          }
        });
      });
    };
    window.addEventListener("hashchange", scheduleReveal);
    window.addEventListener("popstate", scheduleReveal);
    scheduleReveal();
    return () => {
      disposed = true;
      window.removeEventListener("hashchange", scheduleReveal);
      window.removeEventListener("popstate", scheduleReveal);
      cancelFrames();
    };
  }, []);
  return null;
}
