import type { Metadata } from "next";
import Link from "next/link";
import { DiscoveryQeResult } from "@/components/DiscoveryQeResult";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Read Quantum ESPRESSO output",
  description: "Inspect source-linked QE output and compare numerical refinement using the original local files.",
  alternates: { canonical: absoluteUrl("/discovery/calculations") },
};
export default function CalculationReadingPage() {
  return <main className="min-w-0 space-y-6">
    <header className="space-y-3"><nav aria-label="Calculation reading navigation" className="flex flex-wrap gap-5 text-sm"><Link className="site-text-link" href="/discovery">Discovery</Link><Link className="site-text-link" href="/discovery/structures/combinations">Candidate inputs</Link></nav><h1 className="text-3xl font-semibold tracking-tight">Read Quantum ESPRESSO output</h1><p className="max-w-3xl text-base leading-6">Inspect source-linked output, then compare numerical refinement across runs of the same candidate.</p></header>
    <DiscoveryQeResult />
  </main>;
}
