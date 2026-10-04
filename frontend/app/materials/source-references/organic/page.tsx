import type { Metadata } from "next";
import Link from "next/link";
import { OrganicReferenceBrowser } from "@/components/OrganicReferenceBrowser";
import { type OrganicParams, ORGANIC_ROUTE } from "@/lib/mdr-organic";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = { title: "Organic superconductivity source references", description: "Search 568 versioned NIMS Organic source rows, preserving full material names, transition and pressure roles, raw properties, remarks and bibliography.", alternates: { canonical: absoluteUrl(ORGANIC_ROUTE) } };
export default async function OrganicReferencesPage({ searchParams }: { searchParams: Promise<OrganicParams> }) {
  return <main className="min-w-0 space-y-5"><header className="space-y-3"><nav aria-label="Organic reference navigation" className="flex flex-wrap gap-5 text-sm"><Link href="/materials" className="site-text-link">Materials</Link><Link href="/materials/source-references" className="site-text-link">Source references</Link></nav><h1 className="text-3xl font-semibold tracking-tight">Organic source references</h1><p className="max-w-3xl text-base leading-6">Explore reported properties, pressure context and source remarks from NIMS MDR SuperCon, version 240322.</p></header><OrganicReferenceBrowser params={await searchParams} /></main>;
}
