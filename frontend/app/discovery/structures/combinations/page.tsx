import type { Metadata } from "next";
import Link from "next/link";
import { DiscoveryCombinedCandidates } from "@/components/DiscoveryCombinedCandidates";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Combined site and lattice candidates",
  description: "Enumerate explicit co-substitution, vacancy and uniform lattice-change combinations from source-linked ordered supercells.",
  alternates: { canonical: absoluteUrl("/discovery/structures/combinations") },
};
export default function CombinedCandidatesPage() {
  return <main className="min-w-0 space-y-6">
    <header className="space-y-3"><nav aria-label="Combined candidate navigation" className="flex flex-wrap gap-5 text-sm"><Link className="site-text-link" href="/discovery">Discovery</Link><Link className="site-text-link" href="/discovery/structures">Source coordinates</Link><Link className="site-text-link" href="/discovery/structures/candidates">Single-site candidates</Link></nav><h1 className="text-3xl font-semibold tracking-tight">Combine site and lattice changes</h1><p className="max-w-3xl text-base leading-6">Compare explicit substitutions, vacancies and uniform lattice changes in the same source supercell.</p></header>
    <DiscoveryCombinedCandidates />
  </main>;
}
