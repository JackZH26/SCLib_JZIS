"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

/** Fragments never reach the server. Preserve links from the former institution page. */
export function LegacyHomeAnchor() {
  const router = useRouter();
  useEffect(() => {
    const destinations: Record<string, string> = {
      "#about": "/about", "#research": "/research", "#join": "/about/join", "#sclib": "/#search",
    };
    const visit = () => {
      const destination = destinations[window.location.hash];
      if (destination) router.replace(destination);
      else if (window.location.hash && window.location.hash !== "#search") {
        window.history.replaceState(null, "", window.location.pathname + window.location.search);
      }
    };
    visit();
    window.addEventListener("hashchange", visit);
    return () => window.removeEventListener("hashchange", visit);
  }, [router]);
  return null;
}
