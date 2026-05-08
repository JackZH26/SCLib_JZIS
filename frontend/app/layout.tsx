import type { Metadata } from "next";
import { Inter } from "next/font/google";
import Script from "next/script";
import "katex/dist/katex.min.css";
import "./globals.css";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";

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
        <Script
          src="https://www.googletagmanager.com/gtag/js?id=G-PXQFVFVRST"
          strategy="afterInteractive"
        />
        <Script id="gtag-init" strategy="afterInteractive">{`
          window.dataLayer = window.dataLayer || [];
          function gtag(){dataLayer.push(arguments);}
          gtag('js', new Date());
          gtag('config', 'G-PXQFVFVRST');
        `}</Script>
        <Header />
        <div className="mx-auto w-full max-w-6xl flex-1 px-6 py-8">{children}</div>
        <Footer />
      </body>
    </html>
  );
}
