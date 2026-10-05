import type { Metadata } from "next";
import Link from "next/link";
import { MaterialPressureTableSources } from "@/components/MaterialPressureTableSources";
import { loadPressureTableBatch, pressureTableDownloadPath } from "@/lib/material-pressure-table-sources";
import { StudyContextDownloads } from "@/components/MaterialStudyContext";
import { StudyContextHashReveal } from "@/components/StudyContextHashReveal";
import { loadStudyContextBatch } from "@/lib/material-study-context";
import { MaterialThermalTable } from "@/components/MaterialThermalTable";
import { loadThermalTable } from "@/lib/material-thermal-table";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Pressure and table source records",
  description: "Inspect BiTeCl pressure reports and Mo borophosphide transition, lattice and heat-capacity tables with original compositions, units, conditions and source locators.",
  alternates: { canonical: absoluteUrl("/materials/source-observations/pressure-and-tables") },
};
export default function MaterialPressureTableSourcesPage() {
  const batch = loadPressureTableBatch();
  const studyContext = loadStudyContextBatch();
  const thermalTable = loadThermalTable();
  return <main className="min-w-0 space-y-6">
    <header className="space-y-3">
      <nav className="flex flex-wrap gap-x-5 gap-y-2 text-sm" aria-label="Materials source pages">
        <Link className="site-text-link" href="/materials">Materials catalogue</Link>
        <Link className="site-text-link" href="/materials/source-observations">Initial source observations</Link>
        <Link className="site-text-link" href="/materials/source-observations/followup">Additional source records</Link>
      </nav>
      <h1 className="text-3xl font-semibold tracking-tight">Pressure and table records</h1>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">Compare reported values within their original pressure windows and sample columns, with uncertainty notation and source conflicts preserved.</p>
      {batch && <p className="text-sm tabular-nums text-sage-muted">Pressure and Table I: 18 source expressions.{thermalTable && " Table II: 4 thermal readings."}</p>}
      <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm">
        <a className="site-text-link" href={pressureTableDownloadPath} download>Download pressure and table metadata (JSON)</a>
        <a className="site-text-link" href={`${pressureTableDownloadPath}.sha256`} download>Download SHA-256</a>
      </div>
      <nav className="flex flex-wrap gap-x-5 gap-y-2 text-sm" aria-label="Source sections">
        <a className="site-text-link" href="#bitecl-heading">BiTeCl pressure windows</a>
        <a className="site-text-link" href="#mo-table-heading">Mo Table I: transitions and lattice</a>
        <a className="site-text-link" href="#mo-thermal-table">Mo Table II: thermal readings</a>
      </nav>
    </header>
    <MaterialPressureTableSources batch={batch} studyContext={studyContext} />
    <MaterialThermalTable snapshot={thermalTable} />
    <StudyContextDownloads batch={studyContext} />
    <StudyContextHashReveal />
  </main>;
}
