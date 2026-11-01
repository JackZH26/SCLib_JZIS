import type { Metadata } from "next";
import { MaterialsTcTimeline } from "@/components/MaterialsTcTimeline";
import { absoluteUrl } from "@/lib/seo";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "TcTimeline",
  description: "Explore source-reported superconducting transition temperatures by paper submission date and material family.",
  alternates: { canonical: absoluteUrl("/timeline") },
  openGraph: { url: absoluteUrl("/timeline") },
};

export default function TimelinePage() {
  return <main className="space-y-6">
    <header className="product-page-intro">
      <h1 className="text-3xl font-bold tracking-tight">TcTimeline</h1>
      <p className="mt-3 max-w-3xl text-sm text-sage-muted">Reported superconducting transitions through time. Colours and point shapes identify material families; dates follow the source papers. Click a point to keep its details open and visit its material data.</p>
    </header>
    <section aria-label="Reported Tc timeline" className="rounded-xl border border-sage-border bg-white p-4 sm:p-6">
      <MaterialsTcTimeline />
    </section>
  </main>;
}
