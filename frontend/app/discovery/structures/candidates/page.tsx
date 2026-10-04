import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { structureReferences } from "@/lib/discovery-structures";
import { DiscoverySiteCandidates } from "@/components/DiscoverySiteCandidates";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Site modification candidates",
  description: "Build a bounded ordered supercell from captured source coordinates and inspect explicit single-site substitution or vacancy proposals.",
  alternates: { canonical: absoluteUrl("/discovery/structures/candidates") },
};

export default async function SiteCandidatesPage({ searchParams }: { searchParams?: Promise<{ reference?: string | string[] }> }) {
  const reference = (await searchParams)?.reference;
  if (reference !== undefined && (typeof reference !== "string" || !structureReferences().some(item => item.id === reference))) notFound();
  return <main className="min-w-0 space-y-7">
    <header className="space-y-3">
      <nav aria-label="Candidate workspace navigation" className="flex flex-wrap gap-5 text-sm"><Link href="/discovery" className="site-text-link">Discovery</Link><Link href="/discovery/structures" className="site-text-link">Inspect source structures</Link></nav>
      <h1 className="text-3xl font-semibold tracking-tight">Site modification candidates</h1>
      <p className="max-w-3xl text-base leading-6">Choose a real source structure, build a supercell, and change one atomic site.</p>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">Coordinate proposals are prepared locally. Energies, stability and superconducting properties require further calculation.</p>
      <p className="text-sm"><Link href="/discovery/structures/combinations" className="site-text-link inline-flex min-h-11 items-center">Combine multiple sites and lattice changes</Link></p>
    </header>
    <DiscoverySiteCandidates initialReferenceId={reference} />
  </main>;
}
