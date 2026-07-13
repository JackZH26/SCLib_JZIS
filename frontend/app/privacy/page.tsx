import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Privacy Policy — SCLib",
  description: "How SCLib collects, uses, retains, and protects personal data.",
};

export default function PrivacyPolicyPage() {
  return (
    <article className="prose prose-slate mx-auto max-w-3xl prose-headings:text-slate-900 prose-a:text-accent-deep">
      <h1>Privacy Policy</h1>
      <p className="lead">Last updated: July 13, 2026</p>

      <p>
        This policy describes how the JZ Institute of Science
        (&quot;JZIS&quot;, &quot;we&quot;, &quot;us&quot;) handles personal data
        for the JZIS Superconductivity Library (&quot;SCLib&quot;) at{" "}
        <a href="https://jzis.org/sclib">jzis.org/sclib</a>. JZIS is the
        data user responsible for the SCLib account service. Our address is
        Hong Kong, China, and our privacy contact is{" "}
        <a href="mailto:info@jzis.org">info@jzis.org</a>.
      </p>

      <h2>1. Data we collect</h2>
      <h3>Required account data</h3>
      <ul>
        <li>Email address and name, used to identify and communicate with your account.</li>
        <li>
          For email sign-in, a one-way password hash. We never store your
          plaintext password.
        </li>
        <li>
          For Google sign-in, the Google account identifier, verified email,
          display name, and avatar returned by Google.
        </li>
      </ul>

      <h3>Optional research profile</h3>
      <p>
        Institution, country, research area, purpose of use, biography, ORCID,
        and any legacy age value are optional. They are not required to search,
        ask questions, or use the API. You can edit or clear them in your
        dashboard. The current registration form no longer asks for age.
      </p>

      <h3>Service activity and security data</h3>
      <ul>
        <li>Ask questions, generated answers, cited sources, bookmarks, and API-key metadata.</li>
        <li>
          Request counts, timestamps, truncated key prefixes, and security
          events. API keys and reset tokens are stored only as non-reversible hashes.
        </li>
        <li>
          IP address and user-agent information used for rate limiting, fraud
          prevention, and feedback delivery. Authentication audit records store
          keyed hashes rather than the raw values.
        </li>
        <li>
          Optional analytics data and sampled browser-health measurements, but
          only after you enable Analytics in the cookie banner. Browser errors
          are counted without sending the error message, stack trace, page URL,
          account identifier, or raw IP address. See our{" "}
          <Link href="/cookies">Cookie Policy</Link>.
        </li>
      </ul>

      <h2>2. Why we use the data</h2>
      <p>We use personal data only to:</p>
      <ul>
        <li>create, verify, secure, and support your account;</li>
        <li>provide search, RAG question answering, saved items, and API access;</li>
        <li>enforce fair-use limits and investigate abuse or security incidents;</li>
        <li>respond to feedback and service requests;</li>
        <li>understand aggregate site usage when analytics consent is enabled; and</li>
        <li>meet legal obligations and establish or defend legal claims.</li>
      </ul>
      <p>
        We do not sell personal data, use it for third-party advertising, or
        use optional research-profile data for direct marketing.
      </p>

      <h2>3. Service providers and international processing</h2>
      <p>
        SCLib uses service providers only where needed to operate the service:
      </p>
      <ul>
        <li>our PostgreSQL, Redis, API, and web infrastructure for account and service data;</li>
        <li>Google OAuth for optional Google sign-in;</li>
        <li>
          Google Cloud Vertex AI Vector Search and Gemini for retrieval and
          answer generation. Questions sent to Ask may be processed outside
          Hong Kong. Google Cloud states that customer data is not used to train
          or fine-tune its managed models without permission, although limited
          abuse-monitoring logging may apply. See Google Cloud&apos;s{" "}
          <a
            href="https://docs.cloud.google.com/vertex-ai/generative-ai/docs/vertex-ai-zero-data-retention"
            target="_blank"
            rel="noopener noreferrer"
          >
            Vertex AI data-governance documentation
          </a>;
        </li>
        <li>Resend for verification, reset, feedback, and account email delivery; and</li>
        <li>Google Analytics, only if you opt in to analytics cookies.</li>
      </ul>
      <p>
        These providers may process data in other jurisdictions. We limit the
        data sent to each provider to what is needed for its function.
      </p>

      <h2>4. Retention</h2>
      <ul>
        <li>
          Account and profile data, bookmarks, and API-key metadata are kept
          while your account exists and are removed when you delete it.
        </li>
        <li>
          Signed-in Ask history is kept in a rolling 90-day window. You can
          also delete individual history entries sooner.
        </li>
        <li>
          Redis quota counters expire automatically after their daily or
          short security windows; the weekly usage view covers seven days.
        </li>
        <li>
          Verification and reset grants stop working at their stated expiry.
          Their security metadata remains attached to the account until account deletion.
        </li>
        <li>
          Authentication audit events are retained as needed for security and
          legal claims. After account deletion, the direct user reference is
          removed and only pseudonymous security evidence remains.
        </li>
        <li>
          Analytics and aggregate browser-health retention are described in the
          Cookie Policy.
        </li>
      </ul>
      <p>
        Deleted data may persist temporarily in protected backups until those
        backups complete their normal rotation. Feedback already delivered by
        email and records we must retain by law are not automatically removed
        by the account-delete button; contact us for a specific request.
      </p>

      <h2>5. Your choices and rights</h2>
      <ul>
        <li>View and correct profile data from the dashboard.</li>
        <li>Download a machine-readable JSON copy from Dashboard → Data &amp; privacy.</li>
        <li>Delete individual Ask-history entries or permanently delete your account.</li>
        <li>Revoke API keys and all browser/bearer sessions.</li>
        <li>Accept or reject optional analytics independently of account authentication.</li>
        <li>
          Request access to or correction of other personal data by emailing{" "}
          <a href="mailto:info@jzis.org">info@jzis.org</a>. We may need to verify
          your identity before acting on a request.
        </li>
      </ul>
      <p>
        These controls support the access and correction principles in Hong
        Kong&apos;s{" "}
        <a
          href="https://www.pcpd.org.hk/english/data_privacy_law/ordinance_at_a_Glance/ordinance.html"
          target="_blank"
          rel="noopener noreferrer"
        >
          Personal Data (Privacy) Ordinance
        </a>. Other rights may apply depending on where you live.
      </p>

      <h2>6. Security</h2>
      <p>
        We use HTTPS, HttpOnly session cookies, hashed credentials, restricted
        service networking, rate limiting, session revocation, and security
        auditing. No internet service is risk-free; please use a unique password
        and keep API keys confidential.
      </p>

      <h2>7. Children</h2>
      <p>
        SCLib is a research service and is not directed to children. Do not
        create an account if you are under 13 or cannot validly agree to the
        <Link href="/terms"> Terms</Link> in your jurisdiction.
      </p>

      <h2>8. Changes and contact</h2>
      <p>
        Material changes will be posted here with a revised date. Questions,
        access/correction requests, or deletion issues can be sent to{" "}
        <a href="mailto:info@jzis.org">info@jzis.org</a>.
      </p>
    </article>
  );
}
