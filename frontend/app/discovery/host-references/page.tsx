import type { Metadata } from "next";
import Link from "next/link";
import { DiscoveryHostReference } from "@/components/DiscoveryHostReference";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Host energy and electronic references",
  description: "Compare captured JARVIS formation energies and electronic band gaps for 22 proposed host formulas, with separate provider structures and source downloads.",
  alternates: { canonical: absoluteUrl("/discovery/host-references") },
};

export default function HostReferencesPage() {
  return <main className="min-w-0 space-y-6">
    <header className="space-y-3">
      <nav aria-label="Host reference navigation" className="flex flex-wrap gap-5 text-sm">
        <Link className="site-text-link" href="/discovery">Discovery</Link>
        <Link className="site-text-link" href="/discovery/structures">COD structure workspace</Link>
      </nav>
      <h1 className="text-3xl font-semibold tracking-tight">Host energy and electronic references</h1>
      <p className="max-w-3xl text-base leading-6">Compare formation energy and band gap across 22 proposed host formulas and their calculated structures.</p>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">JARVIS-DFT · OptB88vdW · external computed references. Formation energy alone does not establish host stability.</p>
    </header>
    <DiscoveryHostReference />
  </main>;
}
