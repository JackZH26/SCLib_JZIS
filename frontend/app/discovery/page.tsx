import type { Metadata } from "next";
import { DiscoveryNav } from "@/components/DiscoveryNav";
import { DiscoveryDisclosure } from "@/components/DiscoveryDisclosure";
import { DiscoveryCandidatesContent } from "@/components/discovery/DiscoveryCandidatesContent";
import { DataMethodologyContent } from "@/components/discovery/DataMethodologyContent";
import { ApiReferenceContent } from "@/components/discovery/ApiReferenceContent";
import { absoluteUrl } from "@/lib/seo";
import "./discovery-stream.css";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Discovery",
  description: "Browse candidate hypotheses, data methodology and the SCLib API in one place.",
  alternates: { canonical: absoluteUrl("/discovery") },
};

export default function DiscoveryPage({ searchParams = Promise.resolve({}) }: {
  searchParams?: Promise<{ preview?: string }>;
}) {
  return <main className="discovery-stream">
    <DiscoveryNav />
    <header id="overview" className="discovery-intro"><p className="section-kicker">Superconductivity research</p>
      <h1 className="page-title">Discovery</h1>
      <p className="page-description">Candidate hypotheses, their evidence, and access to research data.</p>
    </header>
    <section id="candidates" className="discovery-segment" aria-labelledby="candidates-heading">
      <header className="discovery-segment-heading"><h2 id="candidates-heading">Candidates</h2>
        <p>Source-computed hypotheses and research assessments. These are not probabilities of superconductivity or confirmed discoveries.</p>
      </header>
      <DiscoveryCandidatesContent searchParams={searchParams} />
    </section>
    <section id="data-methodology" className="discovery-segment" aria-labelledby="data-methodology-heading">
      <header className="discovery-segment-heading"><h2 id="data-methodology-heading">Data &amp; methodology</h2>
        <p>Coverage, source attribution, display policies and scientific limitations.</p>
      </header>
      <DiscoveryDisclosure id="discovery-data-details" summary="Read data and methodology"><DataMethodologyContent embedded /></DiscoveryDisclosure>
    </section>
    <section id="api-reference" className="discovery-segment" aria-labelledby="api-reference-heading">
      <header className="discovery-segment-heading"><h2 id="api-reference-heading">API reference</h2>
        <p>Authentication, endpoints, request formats and response examples.</p>
      </header>
      <DiscoveryDisclosure id="discovery-api-details" summary="Read API reference"><ApiReferenceContent embedded /></DiscoveryDisclosure>
    </section>
  </main>;
}
