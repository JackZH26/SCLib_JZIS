import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "katex/dist/katex.min.css";
import "./globals.css";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";
import { Analytics } from "@/components/Analytics";
import { CookieConsentBanner } from "@/components/CookieConsent";

// asrp.jzis.org uses Inter as its primary sans stack (falling back to
// the system font). Load it via next/font so Next handles subsetting +
// self-hosting and we don't add an external CSS request on every page.
const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: "SCLib — JZIS Superconductivity Library",
  description:
    "Self-hosted search, RAG, and material data platform for superconductivity research.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="flex min-h-screen flex-col bg-sage-bg font-sans antialiased">
        <Analytics />
        <Header />
        <div className="mx-auto w-full max-w-6xl flex-1 px-6 py-8">{children}</div>
        <Footer />
        <CookieConsentBanner />
      </body>
    </html>
  );
}
