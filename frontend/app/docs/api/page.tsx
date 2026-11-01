import type { Metadata } from "next";
import { DiscoveryNav } from "@/components/DiscoveryNav";
import { ApiReferenceContent } from "@/components/discovery/ApiReferenceContent";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "API reference",
  description:
    "Use the SCLib API for superconductivity search, grounded Q&A, materials data, and paper metadata.",
  alternates: { canonical: absoluteUrl("/docs/api") },
  openGraph: { url: absoluteUrl("/docs/api") },
};

/** Retained documentation URL; the same reference is embedded in Discovery. */
export default function ApiDocsPage() {
  return <main className="mx-auto max-w-4xl space-y-8 py-6"><DiscoveryNav />
    <header><h1 className="page-title">SCLib API Reference</h1>
      <p className="page-description">Programmatic access to search, grounded Q&amp;A, material records and paper metadata.</p>
    </header>
    <ApiReferenceContent />
  </main>;
}
