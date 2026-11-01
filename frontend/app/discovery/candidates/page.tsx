import type { Metadata } from "next";
import { DiscoveryNav } from "@/components/DiscoveryNav";
import { DiscoveryCandidatesContent } from "@/components/discovery/DiscoveryCandidatesContent";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Discovery candidate materials",
  description:
    "Browse unscored source-computed superconductivity research hypotheses, source comparisons, limitations and next research actions.",
  alternates: { canonical: absoluteUrl("/discovery/candidates") },
  openGraph: { url: absoluteUrl("/discovery/candidates") },
};

/** Retained URL for existing candidate bookmarks; Discovery now embeds this content. */
export default function CandidatesPage({ searchParams }: { searchParams: Promise<{ preview?: string }> }) {
  return <main className="space-y-6 discovery-candidates-page">
    <DiscoveryNav />
    <header className="space-y-2 pb-2"><h1 className="page-title">Candidates</h1>
      <p className="page-description">Source-computed hypotheses, research assessments, and their reported conditions.</p>
    </header>
    <DiscoveryCandidatesContent searchParams={searchParams} />
  </main>;
}
