import type { Metadata } from "next";
import "./globals.css";
import { Header } from "@/components/Header";

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
    <html lang="en">
      <body className="min-h-screen bg-slate-50 antialiased">
        <Header />
        <div className="mx-auto max-w-6xl px-6 py-8">{children}</div>
      </body>
    </html>
  );
}
