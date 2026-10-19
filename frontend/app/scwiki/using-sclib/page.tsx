import type { Metadata } from "next";
import Link from "@/components/AppLink";
import { InformationPage } from "@/components/InformationPage";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Using SCLib", description: "Getting started with SCLib search, materials, reported Tc trends, research leads and API access.",
  alternates: { canonical: absoluteUrl("/scwiki/using-sclib") }, openGraph: { url: absoluteUrl("/scwiki/using-sclib") },
};

export default function UsingSCLibPage() {
  return <InformationPage title="Using SCLib" description="Learn how to use SCLib and understand the evidence behind the data.">
    <h2>Search literature and SCWiki</h2>
    <p>Enter a paper topic, material formula or research question on <Link href="/">Home</Link>. Literature excerpts and SCWiki articles appear in separate result sections. Follow literature citations to the original publication; for Wiki articles and research notes, check their sources and stated review scope.</p>
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
