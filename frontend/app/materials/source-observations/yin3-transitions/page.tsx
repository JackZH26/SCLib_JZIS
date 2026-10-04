import type { Metadata } from "next";
import Link from "next/link";
import { MaterialYin3SourceContext } from "@/components/MaterialYin3SourceContext";
import { loadYin3SourceContext, yin3SourceContextHref } from "@/lib/material-yin3-source-context";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "YIn3 source transitions by sample and method",
  description: "Compare YIn3 sample A and B transition descriptions, original measurement conditions and qualified author interpretation in a captured primary paper edition.",
  alternates: { canonical: absoluteUrl("/materials/source-observations/yin3-transitions") },
};
export default function Yin3SourceTransitionsPage() {
  const data = loadYin3SourceContext();
  return <main className="min-w-0 space-y-7">
    <header className="space-y-3">
      <nav className="flex flex-wrap gap-x-5 gap-y-2 text-sm" aria-label="Materials source pages"><Link className="site-text-link" href="/materials">Materials catalogue</Link><Link className="site-text-link" href="/materials/source-observations">Source observations</Link></nav>
      <h1 className="text-3xl font-semibold tracking-tight">YIn₃: transitions by sample and method</h1>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">Read the original temperature descriptions, with sample labels and measurement roles preserved.</p>
      {data && <a className="site-text-link inline-block text-sm" href={yin3SourceContextHref(data.source.final_url)!} target="_blank" rel="noopener noreferrer">Read arXiv:1112.3083v1</a>}
    </header>
    <MaterialYin3SourceContext data={data} />
  </main>;
}
