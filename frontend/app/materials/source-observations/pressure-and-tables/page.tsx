import type { Metadata } from "next";
import Link from "next/link";
import { MaterialPressureTableSources } from "@/components/MaterialPressureTableSources";
import { loadPressureTableBatch, pressureTableDownloadPath } from "@/lib/material-pressure-table-sources";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Pressure and table source records",
  description: "Inspect BiTeCl pressure reports and two distinct Mo borophosphide table columns, retaining original uncertainty notation, conditions, source-label conflicts and exact locators.",
  alternates: { canonical: absoluteUrl("/materials/source-observations/pressure-and-tables") },
};
export default function MaterialPressureTableSourcesPage() {
  const batch = loadPressureTableBatch();
  return <main className="min-w-0 space-y-6">
    <header className="space-y-3">
      <nav className="flex flex-wrap gap-x-5 gap-y-2 text-sm" aria-label="Materials source pages">
        <Link className="site-text-link" href="/materials">Materials catalogue</Link>
        <Link className="site-text-link" href="/materials/source-observations">Initial source observations</Link>
        <Link className="site-text-link" href="/materials/source-observations/followup">Additional source records</Link>
      </nav>
      <h1 className="text-3xl font-semibold tracking-tight">Pressure and table records</h1>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">Compare reported values within their original pressure windows and sample columns, with uncertainty notation and source conflicts preserved.</p>
      {batch && <p className="text-sm tabular-nums text-sage-muted">18 field expressions from 2 papers; 3 source subjects</p>}
      <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm">
        <a className="site-text-link" href={pressureTableDownloadPath} download>Download pressure and table metadata (JSON)</a>
        <a className="site-text-link" href={`${pressureTableDownloadPath}.sha256`} download>Download SHA-256</a>
      </div>
    </header>
    <MaterialPressureTableSources batch={batch} />
  </main>;
}
