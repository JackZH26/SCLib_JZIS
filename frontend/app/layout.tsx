import type { Metadata } from "next";
import "./globals.css";

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
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
