import type { Metadata } from "next";
import Link from "next/link";
import { MaterialNbCvsPressure } from "@/components/MaterialNbCvsPressure";
import { loadNbCvsPressure } from "@/lib/material-nb-cvs-pressure";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Nb0.07-CVS pressure-series source readings",
  description: "Compare four pressure columns of measured-data gap fits, penetration depths and fit statistics with exact source locators.",
  alternates: { canonical: absoluteUrl("/materials/source-observations/nb-cvs-pressure") },
};

export default function NbCvsPressurePage() {
  return <main className="min-w-0 space-y-6">
    <header className="space-y-3">
      <nav className="flex flex-wrap gap-x-5 gap-y-2 text-sm" aria-label="Materials source navigation"><Link className="site-text-link" href="/materials">Materials catalogue</Link><Link className="site-text-link" href="/materials/source-observations">Source observations</Link></nav>
      <h1 className="text-3xl font-semibold tracking-tight">Nb0.07-CVS under pressure</h1>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">Compare reported gap fits across four pressure conditions, with original units and source locations.</p>
    </header>
    <MaterialNbCvsPressure snapshot={loadNbCvsPressure()} />
  </main>;
}
