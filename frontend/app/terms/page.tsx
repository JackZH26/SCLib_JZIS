import type { Metadata } from "next";
import Link from "next/link";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Terms of Use",
  description: "Terms governing access to the JZIS Superconductivity Library.",
  alternates: { canonical: absoluteUrl("/terms") },
};

export default function TermsPage() {
  return (
    <article className="prose prose-slate mx-auto max-w-3xl prose-headings:text-slate-900 prose-a:text-accent-deep">
      <h1>Terms of Use</h1>
      <p className="lead">Last updated: July 13, 2026</p>

      <p>
        These Terms govern access to the JZIS Superconductivity Library
        (&quot;SCLib&quot;), operated by the JZ Institute of Science
        (&quot;JZIS&quot;) in Hong Kong, China. By creating an account,
        signing in with Google, or using SCLib, you agree to these Terms and
        acknowledge our <Link href="/privacy">Privacy Policy</Link>.
      </p>

      <h2>1. Research service</h2>
      <p>
        SCLib provides literature discovery, extracted scientific data,
        visualizations, and AI-assisted answers for research and educational
        use. It is not medical, legal, financial, engineering-safety, or other
        professional advice. Verify important claims against the cited primary
        literature before relying on them.
      </p>

      <h2>2. Eligibility and accounts</h2>
      <ul>
        <li>You must be at least 13 and able to agree to these Terms.</li>
        <li>Provide accurate required account information and keep it current.</li>
        <li>You are responsible for activity under your account and API keys.</li>
        <li>Do not share credentials or expose API keys in public code or logs.</li>
        <li>Notify <a href="mailto:info@jzis.org">info@jzis.org</a> if you suspect compromise.</li>
      </ul>

      <h2>3. Acceptable use</h2>
      <p>You may not:</p>
      <ul>
        <li>evade quotas, rate limits, access controls, or security measures;</li>
        <li>probe, disrupt, overload, or attempt unauthorized access to SCLib or its providers;</li>
        <li>use the service to distribute malware, infringe rights, or violate applicable law;</li>
        <li>misrepresent generated output as verified primary-source evidence; or</li>
        <li>systematically extract or republish restricted third-party content contrary to its licence.</li>
      </ul>
      <p>
        Automated use must follow the published API, quotas, source licences,
        and reasonable retry behaviour.
      </p>

      <h2>4. Scientific data and AI output</h2>
      <p>
        Literature metadata, extracted material properties, and generated
        answers can be incomplete, stale, disputed, or incorrect. AI output may
        contain hallucinations. Citation links are evidence pointers, not a
        guarantee that every sentence is supported. You remain responsible for
        scientific validation and for conclusions drawn from the service.
      </p>

      <h2>5. Intellectual property and licences</h2>
      <p>
        JZIS&apos;s SCLib code is made available under Apache 2.0 and the SCLib
        dataset under CC BY 4.0 where JZIS has authority to apply that licence.
        Papers, abstracts, publisher content, trademarks, and external datasets
        remain subject to their original owners&apos; terms. Nothing in these Terms
        grants rights in third-party content beyond those terms.
      </p>

      <h2>6. Availability, quotas, and changes</h2>
      <p>
        We may apply quotas, change or discontinue features, correct data, or
        interrupt service for maintenance and security. We aim to communicate
        material changes but do not guarantee uninterrupted or error-free access.
      </p>

      <h2>7. Suspension and termination</h2>
      <p>
        We may suspend or terminate access for security risk, material breach,
        unlawful activity, or repeated quota evasion. You may stop using SCLib
        at any time and can delete your non-administrator account from Dashboard
        → Data &amp; privacy. Deletion is irreversible; export your data first if
        you want a copy.
      </p>

      <h2>8. Disclaimers and limitation</h2>
      <p>
        To the maximum extent permitted by law, SCLib is provided &quot;as is&quot;
        and &quot;as available&quot;, without warranties of accuracy, completeness,
        fitness for a particular purpose, or non-infringement. JZIS is not
        liable for indirect, incidental, special, consequential, or punitive
        loss arising from use of, or inability to use, SCLib. Nothing here
        excludes liability that cannot lawfully be excluded.
      </p>

      <h2>9. Governing law</h2>
      <p>
        These Terms are governed by the laws of Hong Kong. Courts with
        jurisdiction in Hong Kong will have non-exclusive jurisdiction, subject
        to any mandatory consumer protections that apply where you live.
      </p>

      <h2>10. Changes and contact</h2>
      <p>
        We may update these Terms by posting a revised version and date. If you
        do not agree to a material change, stop using the service and delete
        your account. Questions can be sent to{" "}
        <a href="mailto:info@jzis.org">info@jzis.org</a>.
      </p>
    </article>
  );
}
