import type { Metadata } from "next";
import Link from "next/link";
import { MaterialAnnealingEvidence } from "@/components/MaterialAnnealingEvidence";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "NbScTiZr annealing and superconducting source reports",
  description: "Compare source-specific annealing groups, transition criteria, phase compositions and fitted superconducting parameters from two versioned NbScTiZr studies.",
  alternates: { canonical: absoluteUrl("/materials/source-observations/nbsctizr-annealing") },
};

export default function NbsctizrAnnealingPage() {
  return <main className="min-w-0 space-y-8">
    <header className="space-y-3">
      <nav className="flex flex-wrap gap-x-5 gap-y-2 text-sm" aria-label="Materials source pages">
        <Link className="site-text-link inline-flex min-h-11 items-center" href="/materials">Materials catalogue</Link>
        <Link className="site-text-link inline-flex min-h-11 items-center" href="/materials/source-observations">Source observations</Link>
        <Link className="site-text-link inline-flex min-h-11 items-center" href="/discovery#discovery-source-comparisons">Discovery source comparisons</Link>
      </nav>
      <h1 className="text-3xl font-semibold tracking-tight">NbScTiZr annealing comparison</h1>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">Compare preparation groups and their superconducting reports, with each paper's criteria and fitted quantities retained.</p>
    </header>
    <MaterialAnnealingEvidence />
  </main>;
}
