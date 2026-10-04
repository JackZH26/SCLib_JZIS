import type { Metadata } from "next";
import Link from "next/link";
import { MaterialComputationalReference } from "@/components/MaterialComputationalReference";
import { loadComputationalReference } from "@/lib/material-computational-reference";
import { loadComputationalNativeOutput } from "@/lib/material-computational-native-output";
import { loadComputationalInputContext } from "@/lib/material-computational-input-context";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Materials computational references",
  description: "Inspect one independent CrB2 NOMAD computation: reported final structure from complete native XML, literal input contexts, archive metadata and source provenance. Convergence and experimental associations retain their checked scope.",
  alternates: { canonical: absoluteUrl("/materials/source-observations/computational-references") },
};

export default function MaterialsComputationalReferencesPage() {
  return <main className="min-w-0 space-y-6">
    <header className="space-y-3">
      <nav className="flex flex-wrap gap-x-5 gap-y-2 text-sm" aria-label="Materials source pages">
        <Link href="/materials" className="site-text-link">Materials catalogue</Link>
        <Link href="/materials/source-observations" className="site-text-link">Source observations</Link>
      </nav>
      <h1 className="text-3xl font-semibold tracking-tight">Computational references</h1>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">Read the reported final structure, computation settings and exact source values, with provenance available for each reference.</p>
    </header>
    <MaterialComputationalReference data={loadComputationalReference()} nativeOutput={loadComputationalNativeOutput()} additionalInputContext={loadComputationalInputContext()} />
  </main>;
}
