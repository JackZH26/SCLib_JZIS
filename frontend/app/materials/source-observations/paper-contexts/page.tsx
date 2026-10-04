import type { Metadata } from "next";
import Link from "next/link";
import { MaterialNativePaperContexts, NativePaperContextDownloads } from "@/components/MaterialNativePaperContexts";
import { loadNativePaperContexts } from "@/lib/material-native-paper-context";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Material paper contexts and open questions",
  description: "Sample-qualified methods and unresolved scientific claims from captured paper editions, with original page locators and source hashes.",
  alternates: { canonical: absoluteUrl("/materials/source-observations/paper-contexts") },
};

export default function MaterialPaperContextsPage() {
  const batch = loadNativePaperContexts();
  return <main className="min-w-0 space-y-6">
    <header className="space-y-3">
      <nav className="flex flex-wrap gap-x-5 gap-y-2 text-sm" aria-label="Materials source pages">
        <Link className="site-text-link" href="/materials">Materials catalogue</Link>
        <Link className="site-text-link" href="/materials/source-observations">Source observations</Link>
        <Link className="site-text-link" href="/materials/source-observations/followup">Additional source records</Link>
      </nav>
      <h1 className="text-3xl font-semibold tracking-tight">Paper contexts and open questions</h1>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">Read sample-qualified methods and unresolved claims from captured paper editions.</p>
      <p className="max-w-3xl text-xs leading-5 text-sage-muted">Numbers here describe the source's samples and conditions. They remain separate from selected catalogue measurements and classifications.</p>
    </header>
    <MaterialNativePaperContexts batch={batch} />
    <NativePaperContextDownloads batch={batch} />
  </main>;
}
