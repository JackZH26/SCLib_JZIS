"use client";

import Link from "@/components/AppLink";
import { usePathname } from "next/navigation";

export const discoveryLinks = [
  { href: "/discovery", label: "Overview" },
  { href: "/timeline", label: "TcTimeline" },
  { href: "/discovery/candidates", label: "Candidates" },
  { href: "/docs/data", label: "Data & methodology" },
  { href: "/docs/api", label: "API reference" },
];

export function DiscoveryNav() {
  const pathname = usePathname();
  return <nav className="discovery-navigation" aria-label="Discovery">
    {discoveryLinks.map(link => <Link key={link.href} href={link.href}
      aria-current={pathname === link.href ? "page" : undefined}>{link.label}</Link>)}
  </nav>;
}
