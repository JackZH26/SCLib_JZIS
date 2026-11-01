import { DiscoveryNav } from "@/components/DiscoveryNav";
import type { Metadata } from "next";
import { DataMethodologyContent } from "@/components/discovery/DataMethodologyContent";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Data & methodology", description: "Understand SCLib data coverage, source provenance, reported scientific conditions and research-priority limitations.",
  alternates: { canonical: absoluteUrl("/docs/data") }, openGraph: { url: absoluteUrl("/docs/data") },
};

export default function DataPage() {
  return <main className="information-page py-3 sm:py-6"><DiscoveryNav />
    <header className="mb-9 max-w-4xl"><h1 className="page-title">Data &amp; methodology</h1>
      <p className="page-description">Use the library as a route to research evidence, with the original sources and reported conditions in view.</p>
    </header>
    <DataMethodologyContent />
  </main>;
}
