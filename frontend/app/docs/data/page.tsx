import type { Metadata } from "next";
import Link from "next/link";
import { InformationPage } from "@/components/InformationPage";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Data & methodology", description: "Understand SCLib data coverage, source provenance, reported scientific conditions and research-priority limitations.",
  alternates: { canonical: absoluteUrl("/docs/data") }, openGraph: { url: absoluteUrl("/docs/data") },
};

export default function DataPage() {
  return <InformationPage title="Data & methodology" description="Use the library as a route to research evidence, with the original sources and reported conditions in view.">
    <h2>Coverage and updates</h2>
    <p>SCLib indexes superconductivity literature and links material records to supporting publications. Source coverage, paper counts and data versions are reported in <Link href="/stats">Library statistics</Link>. Coverage is not a claim to include every relevant publication.</p>
    <p>Catalogued material counts describe stored library records. Public browsing applies visibility and source policies, so its total can differ. A statistics refresh is separate from the date of the latest indexed paper or ingestion run.</p>
    <h2>Read a property in context</h2>
    <p>Before comparing values, check the material identity, source, units, pressure and other reported conditions. Distinguish measurements from calculations or proposals. A missing condition is unknown, not automatically ambient pressure or experimental evidence.</p>
    <p>Follow field-level provenance and linked publications where available. Multiple reports about the same material can describe different phases, conditions or methods.</p>
    <h2>AI-assisted retrieval and extraction</h2>
    <p>AI assists literature retrieval, question answering and extraction of structured data. It may miss context, confuse material identities or extract an incorrect value. Generated answers and extracted fields should be checked against the cited literature.</p>
    <h2>Timeline and discovery</h2>
    <p>The timeline displays reported transition temperatures, not an independently certified ranking. Discovery separates scientific material information, published research-priority assessments and historical candidate leads. Historical heuristic scores are not new assessments or superconductivity probabilities.</p>
    <h2>Rights and corrections</h2>
    <p>Source publications retain their own rights and access conditions. Library visibility does not itself grant rights to redistribute full text or use it for model training. See the <Link href="/terms">Terms</Link> and repository licensing for the applicable scope.</p>
    <p>If you find an error, include the affected URL, field and supporting source in <Link href="/dashboard/feedback">Feedback</Link>. See <Link href="/about/join">Join &amp; contribute</Link> for other contribution options.</p>
  </InformationPage>;
}
