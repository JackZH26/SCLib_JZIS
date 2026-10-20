import type { Metadata } from "next";
import Link from "@/components/AppLink";
import { DiscoveryNav } from "@/components/DiscoveryNav";
import { LegacyDiscoveryLinks } from "@/components/LegacyDiscoveryLinks";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Discovery",
  description: "Explore reported transition temperatures, candidate materials, data methodology and the SCLib API.",
  alternates: { canonical: absoluteUrl("/discovery") },
};
const modules = [
  { number: "01", title: "TcTimeline", href: "/timeline", tag: "Reported transition temperatures",
    description: "Explore reported Tc across time, material families and pressure conditions. Inspect individual results and their original sources." },
  { number: "02", title: "Candidates", href: "/discovery/candidates", tag: "Hypotheses and research assessments",
    description: "Review source-computed candidates, proposed modifications and research priorities. Keep predictions separate from experimental observations." },
  { number: "03", title: "Data & methodology", href: "/docs/data", tag: "Scope, provenance and limitations",
    description: "Understand data coverage, source attribution, measurement conditions and the boundaries of automated extraction." },
  { number: "04", title: "API reference", href: "/docs/api", tag: "Programmatic access",
    description: "Query literature and material records. Read request parameters, response formats, versioning and access conditions." },
];
export default function DiscoveryPage() {
  return <main className="discovery-overview">
    <LegacyDiscoveryLinks /><DiscoveryNav />
    <header className="discovery-intro"><p className="section-kicker">Superconductivity research</p>
      <h1 className="page-title">Discovery</h1>
      <p className="page-description">Tools for exploring reported properties,<br className="hidden sm:block" /> evaluating hypotheses, and accessing research data.</p>
    </header>
    <div className="discovery-module-grid">{modules.map(module => <Link href={module.href} key={module.href} className="discovery-module">
      <div className="module-index"><span>{module.number}</span><span aria-hidden>↗</span></div>
      <div><p className="section-kicker">{module.tag}</p><h2>{module.title}</h2><p>{module.description}</p></div>
    </Link>)}</div>
    <section className="discovery-method-note"><h2>Interpret results in context.</h2>
      <p>Reported values depend on the sample, measurement criterion and conditions. Candidate assessments guide research; they are not probabilities of superconductivity or confirmed discoveries.</p>
      <Link href="/scwiki" className="site-text-link">Read the superconductivity reference →</Link>
    </section>
  </main>;
}
