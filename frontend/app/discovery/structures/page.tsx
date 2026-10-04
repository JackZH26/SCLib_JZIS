import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { structureReferences } from "@/lib/discovery-structures";
import { DiscoveryStructureWorkspace } from "@/components/DiscoveryStructureWorkspace";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Structure references and lattice proposals",
  description: "Inspect captured COD coordinates and occupancies, then export an unrelaxed uniform-lattice proposal with its original source.",
  alternates: { canonical: absoluteUrl("/discovery/structures") },
};

export default async function DiscoveryStructuresPage({ searchParams }: { searchParams?: Promise<{ reference?: string | string[] }> }) {
  const reference = (await searchParams)?.reference;
  if (reference !== undefined && (typeof reference !== "string" || !structureReferences().some(item => item.id === reference))) notFound();
  return <main className="min-w-0 space-y-7">
    <header className="space-y-3">
      <nav aria-label="Structure workspace navigation" className="flex flex-wrap gap-5 text-sm"><Link className="site-text-link" href="/discovery">Discovery</Link><Link className="site-text-link" href="/materials/source-references">Materials source references</Link></nav>
      <h1 className="text-3xl font-semibold tracking-tight">Structure references</h1>
      <p className="max-w-3xl text-base leading-6">Inspect source coordinates, explore a lattice change, and export a proposal for further calculation.</p>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">{structureReferences().length} captured COD references provide starting geometries. Host stability and association with catalogue measurements remain unestablished.</p>
    </header>
    <DiscoveryStructureWorkspace initialReferenceId={reference} />
  </main>;
}
