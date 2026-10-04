import type { Metadata } from "next";
import Link from "next/link";
import { MaterialSourceSampleTables } from "@/components/MaterialSourceSampleTables";
import { loadSourceSampleTables, sourceSampleTableHref } from "@/lib/material-source-sample-tables";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Fe–Te–Se source sample tables",
  description: "Nominal and EDX compositions with Curie–Weiss fit parameters from a captured Fe–Te–Se paper edition, preserving original units, blanks and source locators.",
  alternates: { canonical: absoluteUrl("/materials/source-observations/fe-te-se-samples") },
};

export default function FeTeSeSampleTablesPage() {
  return <main className="min-w-0 space-y-8">
    <header className="space-y-3">
      <nav className="flex flex-wrap gap-x-5 gap-y-2 text-sm" aria-label="Materials source pages">
        <Link className="site-text-link" href="/materials">Materials catalogue</Link>
        <Link className="site-text-link" href="/materials/source-observations">Source observations</Link>
        <Link className="site-text-link" href="/materials/source-observations/paper-contexts#paper-context-fete">Paper context</Link>
      </nav>
      <h1 className="text-3xl font-semibold tracking-tight">Fe–Te–Se sample tables</h1>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">Nominal and EDX compositions, with susceptibility-fit parameters from Table I.</p>
      <a className="site-text-link inline-block text-sm" href={sourceSampleTableHref()!} target="_blank" rel="noopener noreferrer">Read Table I in arXiv:0911.4758v1 ↗</a>
      <p className="max-w-3xl text-xs leading-5 text-sage-muted">A source-wide reference. Its sample rows remain separate from selected catalogue Tc records.</p>
    </header>
    <MaterialSourceSampleTables data={loadSourceSampleTables()} />
  </main>;
}
