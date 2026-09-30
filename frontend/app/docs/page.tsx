import type { Metadata } from "next";
import Link from "next/link";
import { InformationPage } from "@/components/InformationPage";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Resources & documentation", description: "Getting started with SCLib search, materials, reported Tc trends, research leads and API access.",
  alternates: { canonical: absoluteUrl("/docs") }, openGraph: { url: absoluteUrl("/docs") },
};

export default function DocsPage() {
  return <InformationPage title="Resources & documentation" description="Learn how to use SCLib and understand the evidence behind the data.">
    <h2>Search the literature</h2>
    <p>Enter a paper topic, material formula or research question in <Link href="/search">Search</Link>. Follow result citations to the original publication and check whether the supporting source addresses your question.</p>
    <h2>Explore materials and reported Tc</h2>
    <p><Link href="/materials">Materials</Link> provides filtering, sorting and paginated browsing. Open a material to examine reported properties and their conditions. Use the <Link href="/timeline">Reported Tc Timeline</Link> to explore how reports are distributed over time.</p>
    <h2>Interpret research leads</h2>
    <p>In <Link href="/discovery">Discovery</Link>, distinguish published priority assessments from historical candidate feeds. An unavailable feed is not evidence that there are no candidates; publication status and available evidence determine what can be shown.</p>
    <h2>Coverage and methodology</h2>
    <ul>
      <li><Link href="/stats">Library statistics</Link>: current coverage, data snapshot and pipeline status.</li>
      <li><Link href="/docs/data">Data &amp; methodology</Link>: provenance, scientific conditions and limits of interpretation.</li>
      <li><Link href="/docs/api">API reference</Link>: authentication, endpoints and examples.</li>
    </ul>
    <h2>Your account</h2>
    <p><Link href="/login">Sign in</Link> with Google or your existing email and password. Use <Link href="/dashboard">Account</Link> to manage your profile, API keys, saved items and question history. New users can <Link href="/register">create an account</Link> with the existing SCLib registration flow.</p>
  </InformationPage>;
}
