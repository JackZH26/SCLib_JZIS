"use client";

import { useEffect } from "react";

/** Preserve bookmarks into the previous candidate page, including query filters. */
export function LegacyDiscoveryLinks() {
  useEffect(() => {
    const follow = () => {
      if (window.location.hash.startsWith("#discovery-")) {
        const base = process.env.NEXT_PUBLIC_BASE_PATH || "";
        window.location.replace(`${base}/discovery/candidates${window.location.search}${window.location.hash}`);
      }
    };
    follow();
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, []);
  return null;
}
