import type { Metadata } from "next";
import Link from "next/link";
import { InformationPage } from "@/components/InformationPage";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "About JZIS", description: "JZ Institute of Science develops and maintains SCLib, the superconductivity research library.",
  alternates: { canonical: absoluteUrl("/about") }, openGraph: { url: absoluteUrl("/about") },
};

export default function AboutPage() {
  return <InformationPage title="About JZ Institute of Science" description="We develop and maintain SCLib to make superconductivity literature and source-linked materials data easier to explore.">
    <h2>A library built around research evidence</h2>
    <p>JZ Institute of Science (JZIS), based in Hong Kong, China, brings literature retrieval, reported material properties and research evidence together in SCLib. The library is the central service of this website.</p>
    <p>Researchers can search publications, explore materials, review reported transition temperatures and examine research priorities. Each task starts with evidence and returns to the original literature.</p>
    <h2>Transparent methods and limitations</h2>
    <p>AI assists retrieval and data extraction. Automatically extracted values and generated answers can contain errors. SCLib distinguishes source reports, computational results and research leads so readers can assess what the evidence supports.</p>
    <p>Read <Link href="/docs/data">Data &amp; methodology</Link> for guidance on provenance, coverage and interpretation, or visit <Link href="/research">Research</Link> for our scientific focus.</p>
    <h2>Open development</h2>
    <p>The <a href="https://github.com/JackZH26/SCLib_JZIS" target="_blank" rel="noopener noreferrer">SCLib source repository</a> contains the application code and technical documentation. Code and data licensing are described in the repository; source publications retain their own rights and conditions.</p>
    <p><Link href="/about/join">Join &amp; contribute</Link> explains how to report data issues or discuss research and development contributions.</p>
    <h2 id="contact" className="scroll-mt-24">Contact</h2>
    <p>For questions about JZIS or SCLib, email <a href="mailto:info@jzis.org">info@jzis.org</a>. Account holders can also use <Link href="/dashboard/feedback">Feedback</Link> to report a problem with the library.</p>
  </InformationPage>;
}
