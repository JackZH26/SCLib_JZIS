import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "katex/dist/katex.min.css";
import "./globals.css";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";
import { Analytics } from "@/components/Analytics";
import { CookieConsentBanner } from "@/components/CookieConsent";
import { WebVitalsReporter } from "@/components/WebVitalsReporter";
import { SITE_BASE_URL, SITE_ORIGIN, serializeJsonLd } from "@/lib/seo";

// asrp.jzis.org uses Inter as its primary sans stack (falling back to
// the system font). Load it via next/font so Next handles subsetting +
// self-hosting and we don't add an external CSS request on every page.
const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

export const metadata: Metadata = {
  metadataBase: new URL(SITE_ORIGIN),
  title: {
    default: "SCLib — JZIS Superconductivity Library",
    template: "%s | SCLib",
  },
  description:
    "Search superconductivity papers, explore material properties, and ask grounded research questions with the JZIS Superconductivity Library.",
  applicationName: "SCLib",
  keywords: [
    "superconductivity",
    "superconductor materials",
    "scientific literature search",
    "critical temperature",
    "condensed matter physics",
  ],
  creator: "JZ Institute of Science",
  publisher: "JZ Institute of Science",
  openGraph: {
    type: "website",
    siteName: "SCLib",
    locale: "en_US",
    title: "SCLib — JZIS Superconductivity Library",
    description:
      "Search superconductivity papers, explore material properties, and ask grounded research questions.",
  },
  twitter: {
    card: "summary",
    title: "SCLib — JZIS Superconductivity Library",
    description:
      "Search superconductivity papers and explore material properties.",
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-image-preview": "large",
      "max-snippet": -1,
      "max-video-preview": -1,
    },
  },
};

const websiteStructuredData = {
  "@context": "https://schema.org",
  "@type": ["WebSite", "Dataset"],
  name: "SCLib — JZIS Superconductivity Library",
  alternateName: "SCLib",
  url: `${SITE_BASE_URL}/`,
  description:
    "A searchable superconductivity literature and materials knowledge base.",
  creator: {
    "@type": "Organization",
    name: "JZ Institute of Science",
    url: SITE_ORIGIN,
  },
  potentialAction: {
    "@type": "SearchAction",
    target: `${SITE_BASE_URL}/search?q={search_term_string}`,
    "query-input": "required name=search_term_string",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="flex min-h-screen flex-col bg-sage-bg font-sans antialiased">
        <script
          id="sclib-website-structured-data"
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: serializeJsonLd(websiteStructuredData),
          }}
        />
        <Analytics />
        <WebVitalsReporter />
        <Header />
        <div className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6 sm:py-8">
          {children}
        </div>
        <Footer />
        <CookieConsentBanner />
      </body>
    </html>
  );
}
