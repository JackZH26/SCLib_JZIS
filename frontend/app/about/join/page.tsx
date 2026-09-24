import type { Metadata } from "next";
import Link from "next/link";
import { InformationPage } from "@/components/InformationPage";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Join & contribute", description: "Help improve SCLib through source-backed corrections, software contributions and research collaboration.",
  alternates: { canonical: absoluteUrl("/about/join") }, openGraph: { url: absoluteUrl("/about/join") },
};

export default function JoinPage() {
  return <InformationPage title="Join & contribute" description="Help make superconductivity literature and materials data more useful to researchers.">
    <h2>Report a data issue</h2>
    <p>Send the material or paper URL, the field you believe needs correction, and a source passage or citation supporting it. Include pressure and measurement or calculation conditions when they affect interpretation.</p>
    <p>Use <Link href="/dashboard/feedback">account feedback</Link> or email <a href="mailto:info@jzis.org">info@jzis.org</a>. Avoid including passwords, API keys or private research data in reports.</p>
    <h2>Contribute to the software</h2>
    <p>Visit the <a href="https://github.com/JackZH26/SCLib_JZIS" target="_blank" rel="noopener noreferrer">SCLib repository</a> for the code and development documentation. Reproducible bug reports, accessibility improvements and tests for scientific data handling are useful contributions.</p>
    <h2>Discuss research collaboration</h2>
    <p>Contact JZIS with your research question, relevant experience and the evidence or data you would like to work with. Contributions are reviewed before they become public library content.</p>
    <p>You can use the library with your <Link href="/login">existing SCLib account</Link>. Research workspace access remains subject to the permissions assigned to that account.</p>
  </InformationPage>;
}
