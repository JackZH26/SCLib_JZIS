import type { Metadata } from "next";
import Link from "next/link";
import { MaterialSourceFollowup } from "@/components/MaterialSourceFollowup";
import { loadSourceFollowupBatch, sourceFollowupDownloadPath } from "@/lib/material-source-followup";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Additional material source records",
  description: "Inspect a bounded batch of preparation, measurement, model and CIF source expressions with conditions, original locators and downloadable metadata. Unavailable numerical settings remain unresolved.",
  alternates: { canonical: absoluteUrl("/materials/source-observations/followup") },
};
export default function MaterialSourceFollowupPage() {
  const batch=loadSourceFollowupBatch();
  return <main className="min-w-0 space-y-6">
    <header className="space-y-3">
      <nav className="flex flex-wrap gap-x-5 gap-y-2 text-sm" aria-label="Materials source pages">
        <Link href="/materials" className="site-text-link">Materials catalogue</Link>
        <Link href="/materials/source-observations" className="site-text-link">Initial source observations</Link>
        <Link href="/materials/source-observations/pressure-and-tables" className="site-text-link">Pressure and table records</Link>
      </nav>
      <h1 className="text-3xl font-semibold tracking-tight">Additional source records</h1>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">Inspect preparation, probe definitions, model estimates and crystal metadata with their conditions and original sources.</p>
      {batch && <p className="text-sm tabular-nums text-sage-muted">31 source expressions · 3 unavailable settings · 8 source groups</p>}
      <p className="max-w-3xl text-xs leading-5 text-sage-muted">These field records remain separate from selected catalogue properties. Sample/state matching and current publication status remain unresolved.</p>
      <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm">
        <a href={sourceFollowupDownloadPath} className="site-text-link" download>Download source-record metadata (JSON)</a>
        <a href={`${sourceFollowupDownloadPath}.sha256`} className="site-text-link" download>Download SHA-256</a>
      </div>
    </header>
    <MaterialSourceFollowup batch={batch}/>
  </main>;
}
