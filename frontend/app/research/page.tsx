import type { Metadata } from "next";
import Link from "next/link";
import { InformationPage } from "@/components/InformationPage";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Research", description: "Superconductivity research at JZIS: literature, reported materials properties and evidence-based research priorities.",
  alternates: { canonical: absoluteUrl("/research") }, openGraph: { url: absoluteUrl("/research") },
};

export default function ResearchPage() {
  return <InformationPage title="Superconductivity research" description="SCLib supports the path from a literature question to a closer examination of the underlying evidence.">
    <h2>Literature and reported properties</h2>
    <p>Comparing superconductivity reports requires attention to material identity, composition, pressure, temperature and how a result was obtained. <Link href="/search">Search</Link> helps locate publications; <Link href="/materials">Materials</Link> connects reported properties to sources.</p>
    <h2>Trends over time</h2>
    <p>The <Link href="/timeline">Reported Tc Timeline</Link> supports exploration of the literature by year, material family and reported conditions. A plotted value is a report in the library, not independent confirmation of a record or a reproduced result.</p>
    <h2>Research priorities and candidate leads</h2>
    <p><Link href="/discovery">Discovery</Link> presents published research-priority information and historical candidate leads with their stated limitations. Priority assessments guide further investigation; they are not probabilities of superconductivity or proof of experimental discovery.</p>
    <h2>Contributing evidence</h2>
    <p>Corrections, source review and reproducible scientific inputs improve the usefulness of the library. See <Link href="/about/join">Join &amp; contribute</Link> to discuss a contribution and <Link href="/docs/data">Data &amp; methodology</Link> to understand the current data boundaries.</p>
  </InformationPage>;
}
