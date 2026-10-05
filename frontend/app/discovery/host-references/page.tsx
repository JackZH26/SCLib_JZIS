import type { Metadata } from "next";
import Link from "next/link";
import { DiscoveryHostReference } from "@/components/DiscoveryHostReference";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Host physical references",
  description: "Compare captured JARVIS formation energies, electronic band gaps and elastic properties for 22 proposed host formulas, with provider records and source downloads.",
  alternates: { canonical: absoluteUrl("/discovery/host-references") },
};

export default function HostReferencesPage() {
  return <main className="min-w-0 space-y-6">
    <header className="space-y-3">
      <nav aria-label="Host reference navigation" className="flex flex-wrap gap-5 text-sm">
        <Link className="site-text-link" href="/discovery">Discovery</Link>
        <Link className="site-text-link" href="/discovery/structures">COD structure workspace</Link>
      </nav>
      <h1 className="text-3xl font-semibold tracking-tight">Host physical references</h1>
      <p className="max-w-3xl text-base leading-6">Compare energy, band gap and elastic response across 22 proposed host formulas and their calculated structures.</p>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">JARVIS-DFT · OptB88vdW · external computed references. Formation energy alone does not establish host stability.</p>
    </header>
    <DiscoveryHostReference />
  </main>;
}
