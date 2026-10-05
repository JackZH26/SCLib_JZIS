"use client";

import { useEffect, useRef, type ReactNode } from "react";

/** Native disclosure with working links to both the group and its existing inner anchors. */
export function DiscoveryDisclosure({ id, summary, children }: { id: string; summary: string; children: ReactNode }) {
  const element = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    let frame: number | null = null;
    const revealHash = (hash: string) => {
      let anchor: string;
      try { anchor = decodeURIComponent(hash.slice(1)); }
      catch { return; }
      const target = document.getElementById(anchor);
      if (!target || !element.current?.contains(target)) return;
      // Keep nested policy/source disclosures navigable without rewriting their state.
      for (let parent: HTMLElement | null = target; parent && element.current.contains(parent); parent = parent.parentElement) {
        if (parent instanceof HTMLDetailsElement) parent.open = true;
      }
      if (frame !== null) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => target.scrollIntoView?.({ block: "start", behavior: "auto" }));
    };
    const reveal = () => revealHash(window.location.hash);
    const followLink = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
      const link = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>("a[href]") : null;
      if (!link || link.hasAttribute("download") || link.target && link.target !== "_self") return;
      const url = new URL(link.href, window.location.href);
      if (url.origin !== window.location.origin || url.pathname !== window.location.pathname || url.search !== window.location.search || !url.hash) return;
      // A repeated link to the current hash has no hashchange event.
      revealHash(url.hash);
    };
    reveal();
    window.addEventListener("hashchange", reveal); window.addEventListener("popstate", reveal);
    document.addEventListener("click", followLink);
    return () => {
      if (frame !== null) cancelAnimationFrame(frame);
      window.removeEventListener("hashchange", reveal); window.removeEventListener("popstate", reveal);
      document.removeEventListener("click", followLink);
    };
  }, []);
  return <details ref={element} id={id} className="scroll-mt-24 rounded-xl border border-sage-border bg-white p-4">
    <summary className="min-h-6 cursor-pointer text-sm font-semibold">{summary}</summary>
    <div className="mt-4 min-w-0 space-y-4">{children}</div>
  </details>;
}
