import Link from "@/components/AppLink";

export function DataMethodologyContent({ embedded = false }: { embedded?: boolean }) {
  const Tag = embedded ? "h3" : "h2";
  const Heading = ({ children, id }: { children: string; id?: string }) => <Tag id={id ?? children.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")} className="scroll-mt-28">{children}</Tag>;
  return <article className="prose prose-slate min-w-0 max-w-[78ch] prose-headings:font-semibold prose-headings:tracking-tight prose-h3:mt-7 prose-p:leading-relaxed prose-a:text-accent-deep prose-a:underline-offset-4">
    <Heading>Coverage and updates</Heading>
    <p>SCLib indexes superconductivity literature and links material records to supporting publications. Source coverage, paper counts and data versions are reported in <Link href="/stats">Library statistics</Link>. Coverage is not a claim to include every relevant publication.</p>
    <p>Catalogued material counts describe stored library records. Public browsing applies visibility and source policies, so its total can differ. A statistics refresh is separate from the date of the latest indexed paper or ingestion run.</p>
    <Heading>Read a property in context</Heading>
    <p>Before comparing values, check the material identity, source, units, pressure and other reported conditions. Distinguish measurements from calculations or proposals. A missing condition is unknown, not automatically ambient pressure or experimental evidence.</p>
    <p>Follow field-level provenance and linked publications where available. Multiple reports about the same material can describe different phases, conditions or methods.</p>
    <Heading>AI-assisted retrieval and extraction</Heading>
    <p>AI assists literature retrieval, question answering and extraction of structured data. It may miss context, confuse material identities or extract an incorrect value. Generated answers and extracted fields should be checked against the cited literature.</p>
    <Heading id="timeline-and-discovery">Public Tc display and discovery</Heading>
    <p>Public Materials and timeline views display reported Tc up to and including 300 K. Assertions with a scalar or range endpoint above 300 K, or a strict lower bound of &gt;300 K, receive the <code>tc_above_300k</code> display flag and are hidden from these views. Original assertions, evidence and archived downloads are retained. This display limit is not an independently certified ranking. Discovery separates scientific material information, published research-priority assessments and historical candidate leads. Historical heuristic scores are not new assessments or superconductivity probabilities.</p>
    <Heading>Rights and corrections</Heading>
    <p>Source publications retain their own rights and access conditions. Library visibility does not itself grant rights to redistribute full text or use it for model training. See the <Link href="/terms">Terms</Link> and repository licensing for the applicable scope.</p>
    <p>If you find an error, include the affected URL, field and supporting source in <Link href="/dashboard/feedback">Feedback</Link>. See <Link href="/about/join">Join &amp; contribute</Link> for other contribution options.</p>
  </article>;
}
