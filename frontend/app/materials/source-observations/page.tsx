import type { Metadata } from "next";
import Link from "next/link";
import { MaterialSourceObservations } from "@/components/MaterialSourceObservations";
import { loadSourceObservationBatch, sourceObservationDownloadPath, sourceObservationWindow } from "@/lib/material-source-observations";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Materials source observations",
  description: "Inspect source-specific Hc2 slopes and model estimates, two separate fit windows, and listed crystallographic sites with original locators and downloadable metadata. Sample and state associations remain pending.",
  alternates: { canonical: absoluteUrl("/materials/source-observations") },
};

export default function MaterialsSourceObservationsPage() {
  const batch = loadSourceObservationBatch();
  const window = batch ? sourceObservationWindow(batch.entries, null, "independent_captured_sources") : null;
  return <main className="min-w-0 space-y-6">
    <header className="space-y-3">
      <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm"><Link className="site-text-link" href="/materials">Materials catalogue</Link><Link className="site-text-link" href="/materials/source-references">Paper and CIF reference pilot</Link><Link className="site-text-link" href="/materials/source-observations/followup">Preparation, probes and additional sources</Link><Link className="site-text-link" href="/materials/source-observations/pressure-and-tables">Pressure and table records</Link><Link className="site-text-link" href="/materials/source-observations/computational-references">Computational references</Link></div>
      <h1 className="text-3xl font-semibold tracking-tight">Source observations</h1>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">Inspect source curve parameters, separate fit windows and listed crystallographic sites, with conditions and exact locators.</p>
      <p className="max-w-3xl text-xs leading-5 text-sage-muted">These captured source observations are independent of selected catalogue properties. No physical sample/state association or scientific approval is established. Original files may differ from their current download versions.</p>
      {batch && <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm"><span className="text-sage-muted">Prepared {batch.prepared_on}</span><a className="site-text-link" href={sourceObservationDownloadPath} download>Download captured observation metadata (JSON)</a><a className="site-text-link" href={`${sourceObservationDownloadPath}.sha256`} download>Download SHA-256</a></div>}
    </header>
    {window ? <MaterialSourceObservations window={window} defaultExpanded /> : <p className="text-sm text-sage-muted" role="status">Captured source observations are unavailable. The catalogue remains available.</p>}
  </main>;
}
