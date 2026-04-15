import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Header } from "@/components/Header";

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
      <body className="min-h-screen bg-sage-bg font-sans antialiased">
        <Header />
        <div className="mx-auto max-w-6xl px-6 py-8">{children}</div>
      </body>
    </html>
  );
}
