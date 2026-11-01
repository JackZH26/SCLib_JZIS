"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";

export const discoveryLinks = [
  { hash: "#overview", label: "Overview" },
  { hash: "#candidates", label: "Candidates" },
  { hash: "#data-methodology", label: "Data & methodology" },
  { hash: "#api-reference", label: "API reference" },
];

export function DiscoveryNav() {
  const pathname = usePathname(), inline = pathname === "/discovery";
  const nav = useRef<HTMLElement>(null);
  const [active, setActive] = useState("#overview");
  useEffect(() => {
    if (!inline) return;
    const restore = () => {
      const section = discoveryLinks.find(link => link.hash === window.location.hash);
      if (section) setActive(section.hash);
    };
    const measure = () => {
      if (!nav.current) return;
      const top = Math.ceil(document.querySelector(".site-header")?.getBoundingClientRect().height ?? 72);
      nav.current.style.top = `${top}px`;
      nav.current.parentElement?.style.setProperty("--discovery-jump-offset", `${top + nav.current.getBoundingClientRect().height + 20}px`);
    };
    measure(); restore();
    const resize = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    if (nav.current) resize?.observe(nav.current);
    const header = document.querySelector(".site-header"); if (header) resize?.observe(header);
    const observer = typeof IntersectionObserver !== "undefined" ? new IntersectionObserver(entries => {
      const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
      if (visible) setActive("#" + visible.target.id);
    }, { rootMargin: "-145px 0px -65% 0px" }) : null;
    discoveryLinks.forEach(link => { const target = document.getElementById(link.hash.slice(1)); if (target) observer?.observe(target); });
    window.addEventListener("hashchange", restore); window.addEventListener("popstate", restore);
    return () => { resize?.disconnect(); observer?.disconnect(); window.removeEventListener("hashchange", restore); window.removeEventListener("popstate", restore); };
  }, [inline]);
  return <nav ref={nav} className="discovery-navigation" aria-label="Discovery">
    {discoveryLinks.map(link => <a key={link.hash} href={(inline ? "" : "/discovery") + link.hash}
      aria-current={inline && active === link.hash ? "location" : undefined}
      onClick={() => { if (inline) setActive(link.hash); }}>{link.label}</a>)}
  </nav>;
}
