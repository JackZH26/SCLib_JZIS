import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Cookie Policy — SCLib",
  description:
    "How SCLib uses cookies and similar technologies, and how to manage your preferences.",
};

export default function CookiePolicyPage() {
  return (
    <article className="prose prose-slate mx-auto max-w-3xl prose-headings:text-slate-900 prose-a:text-accent-deep">
      <h1>Cookie Policy</h1>
      <p className="lead">
        Last updated: May 12, 2026
      </p>

      <p>
        This Cookie Policy explains how <strong>JZIS Superconductivity
        Library</strong> (&quot;SCLib&quot;, &quot;we&quot;, &quot;us&quot;)
        uses cookies and similar technologies when you visit{" "}
        <a href="https://jzis.org/sclib">jzis.org/sclib</a>. It covers
        what cookies are, which cookies we set, and how you can manage
        your preferences.
      </p>

      <h2>1. What Are Cookies?</h2>
      <p>
        Cookies are small text files placed on your device by a website.
        They are widely used to make websites work efficiently, to
        provide a better browsing experience, and to give site operators
        reporting information. Similar technologies include{" "}
        <code>localStorage</code>, which stores data locally in your
        browser without transmitting it to a server on every request.
      </p>

      <h2>2. Categories of Cookies We Use</h2>
      <p>
        We organize our cookies into two categories. When you first
        visit SCLib, a consent banner lets you choose which optional
        categories to accept. Your choice is saved in your browser and
        persists across sessions.
      </p>

      <h3>2.1 Necessary (always active)</h3>
      <p>
        These are essential for the site to function and cannot be
        turned off. They do not track you across websites.
      </p>
      <table>
        <thead>
          <tr>
            <th>Name / Key</th>
            <th>Purpose</th>
            <th>Storage</th>
            <th>Expiry</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><code>cookie_consent</code></td>
            <td>
              Stores your cookie preference (accept / reject /
              per-category choices) so the consent banner is not shown
              again.
            </td>
            <td>localStorage</td>
            <td>Persistent until cleared</td>
          </tr>
          <tr>
            <td><code>sclib_token</code></td>
            <td>
              JSON Web Token (JWT) for authenticated sessions after
              login. Contains no personal data beyond your user ID.
            </td>
            <td>localStorage</td>
            <td>7 days (auto-refreshed on activity)</td>
          </tr>
        </tbody>
      </table>

      <h3>2.2 Analytics (optional)</h3>
      <p>
        Analytics cookies help us understand how visitors interact with
        SCLib — which pages are popular, where users arrive from, and
        how long they stay. This data is aggregated and anonymous; we
        do not use it for advertising or sell it to third parties.
      </p>
      <p>
        Analytics cookies are <strong>only loaded after you click
        &quot;Accept all&quot;</strong> or enable the Analytics toggle in
        the consent banner.
      </p>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Provider</th>
            <th>Purpose</th>
            <th>Expiry</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><code>_ga</code></td>
            <td>Google Analytics 4</td>
            <td>
              Distinguishes unique visitors. Generates a random client
              ID; no personally identifiable information is stored.
            </td>
            <td>2 years</td>
          </tr>
          <tr>
            <td><code>_ga_PXQFVFVRST</code></td>
            <td>Google Analytics 4</td>
            <td>
              Maintains session state for the GA4 property.
            </td>
            <td>2 years</td>
          </tr>
        </tbody>
      </table>
      <p>
        Google&apos;s privacy practices for Analytics are described in{" "}
        <a
          href="https://policies.google.com/privacy"
          target="_blank"
          rel="noopener noreferrer"
        >
          Google&apos;s Privacy Policy
        </a>{" "}
        and the{" "}
        <a
          href="https://support.google.com/analytics/answer/6004245"
          target="_blank"
          rel="noopener noreferrer"
        >
          Google Analytics Data Safeguards
        </a>{" "}
        page. You can also install the{" "}
        <a
          href="https://tools.google.com/dlpage/gaoptout"
          target="_blank"
          rel="noopener noreferrer"
        >
          Google Analytics Opt-out Browser Add-on
        </a>{" "}
        for an additional layer of control.
      </p>

      <h2>3. Cookies We Do Not Use</h2>
      <p>
        SCLib does <strong>not</strong> use:
      </p>
      <ul>
        <li>
          <strong>Advertising / targeting cookies</strong> — we do not
          run ads or participate in ad networks.
        </li>
        <li>
          <strong>Social-media tracking pixels</strong> — no Facebook
          Pixel, Twitter tags, or similar.
        </li>
        <li>
          <strong>Third-party personalization</strong> — we do not
          embed any external recommendation or A/B-testing scripts.
        </li>
      </ul>

      <h2>4. Managing Your Preferences</h2>
      <h3>Via the consent banner</h3>
      <p>
        On your first visit, a banner lets you <em>Accept all</em>,{" "}
        <em>Reject all</em>, or <em>Customize</em> cookie categories.
        To change your choice later, clear your browser&apos;s local
        storage for <code>jzis.org</code> — the banner will reappear on
        your next visit.
      </p>

      <h3>Via browser settings</h3>
      <p>
        Most browsers let you block or delete cookies through their
        privacy settings. Note that blocking all cookies may impair
        site functionality (e.g., you will not be able to stay logged
        in).
      </p>
      <ul>
        <li>
          <a
            href="https://support.google.com/chrome/answer/95647"
            target="_blank"
            rel="noopener noreferrer"
          >
            Chrome
          </a>
        </li>
        <li>
          <a
            href="https://support.mozilla.org/en-US/kb/cookies-information-websites-store-on-your-computer"
            target="_blank"
            rel="noopener noreferrer"
          >
            Firefox
          </a>
        </li>
        <li>
          <a
            href="https://support.apple.com/en-us/105082"
            target="_blank"
            rel="noopener noreferrer"
          >
            Safari
          </a>
        </li>
        <li>
          <a
            href="https://support.microsoft.com/en-us/microsoft-edge/manage-cookies-in-microsoft-edge-view-allow-block-delete-and-use-168dab11-0753-043d-7c16-ede5947fc64d"
            target="_blank"
            rel="noopener noreferrer"
          >
            Edge
          </a>
        </li>
      </ul>

      <h2>5. Data Retention</h2>
      <p>
        Necessary data (JWT, consent flag) is stored only on your device
        and is never transmitted to third parties. Google Analytics data
        is retained for 14 months, after which it is automatically
        deleted from Google&apos;s servers.
      </p>

      <h2>6. Changes to This Policy</h2>
      <p>
        We may update this Cookie Policy from time to time. Changes
        will be posted on this page with a revised &quot;Last
        updated&quot; date. If we add new cookie categories, you will
        see the consent banner again.
      </p>

      <h2>7. Contact</h2>
      <p>
        If you have questions about this Cookie Policy, reach us at{" "}
        <a href="mailto:info@jzis.org">info@jzis.org</a>.
      </p>
    </article>
  );
}
