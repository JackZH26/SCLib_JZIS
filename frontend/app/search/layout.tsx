import type { Metadata } from "next";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Search papers and ask SCLib",
  description:
    "Search superconductivity literature and ask grounded questions with citations to source papers.",
  alternates: { canonical: absoluteUrl("/search") },
  openGraph: { url: absoluteUrl("/search") },
};

export default function SearchLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
