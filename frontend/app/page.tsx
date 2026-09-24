import type { Metadata } from "next";
import Link from "next/link";
import { SearchBar } from "@/components/SearchBar";
import { LegacyHomeAnchor } from "@/components/LegacyHomeAnchor";
import { getLibrarySnapshot } from "@/lib/library-snapshot";
import { absoluteUrl } from "@/lib/seo";

export const revalidate = 300;
export const metadata: Metadata = {
  title: { absolute: "SCLib by JZIS | Superconductivity Research Library" },
  description: "Search superconductivity literature, explore source-linked materials data, and review reported Tc trends and research leads.",
  alternates: { canonical: absoluteUrl("/") },
  openGraph: { url: absoluteUrl("/") },
};

const researchRoutes = [
  { href: "/materials", title: "Materials", description: "Compare reported properties, pressure conditions and the literature behind each record." },
  { href: "/timeline", title: "Reported Tc Timeline", description: "Explore transition temperatures over time and return to the original reports." },
  { href: "/discovery", title: "Discovery", description: "Review research priorities and historical candidate leads with their evidence and limitations." },
];

function dateLabel(value: string | null | undefined) {
  if (!value || !Number.isFinite(Date.parse(value))) return "Not recorded";
  return new Date(value).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

export default async function Landing() {
  const stats = await getLibrarySnapshot();
  return (
    <main className="space-y-14 sm:space-y-20">
      <LegacyHomeAnchor />
      <section aria-labelledby="library-heading" className="pt-4 sm:pt-8">
        <h1 id="library-heading" className="max-w-4xl text-4xl font-bold leading-[1.12] tracking-tight sm:text-5xl lg:text-6xl">The superconductivity research library</h1>
        <p className="mt-5 max-w-2xl text-lg text-sage-muted">Search superconductivity literature, explore source-linked materials data, and review reported Tc trends and research leads.</p>
        <div id="search" className="mt-7 max-w-3xl scroll-mt-24"><SearchBar placeholder="Search papers, materials, or ask a research question" /></div>
        <Link href="/materials" className="mt-4 inline-block text-sm font-semibold underline underline-offset-4">Browse materials</Link>
      </section>
      <section aria-labelledby="explore-heading">
        <h2 id="explore-heading" className="text-2xl font-semibold">Explore the research</h2>
        <div className="mt-5 divide-y divide-sage-border border-y border-sage-border">
          {researchRoutes.map((item) => (
            <Link key={item.href} href={item.href} className="group grid gap-2 py-5 text-sage-ink transition-colors hover:bg-sage-surface/60 sm:grid-cols-[15rem_1fr_auto] sm:items-center sm:gap-6 sm:px-3">
              <h3 className="text-lg font-semibold group-hover:text-accent-deep">{item.title}</h3>
              <p className="max-w-xl text-sm text-sage-muted">{item.description}</p>
              <span aria-hidden="true" className="hidden text-xl sm:block">→</span>
            </Link>
          ))}
        </div>
      </section>
      <section aria-labelledby="coverage-heading" className="rounded-xl bg-sage-surface p-6 sm:p-8">
        <h2 id="coverage-heading" className="text-2xl font-semibold">Library coverage</h2>
        {stats ? <>
          <dl className="mt-6 grid gap-6 sm:grid-cols-3">
            <div><dt className="text-sm text-sage-muted">Indexed papers</dt><dd className="mt-1 text-3xl font-semibold tabular-nums">{stats.total_papers.toLocaleString("en-US")}</dd></div>
            <div><dt className="text-sm text-sage-muted">Catalogued materials</dt><dd className="mt-1 text-3xl font-semibold tabular-nums">{stats.total_materials.toLocaleString("en-US")}</dd></div>
            <div><dt className="text-sm text-sage-muted">Latest indexed paper</dt><dd className="mt-1 text-2xl font-semibold">{dateLabel(stats.last_ingest_at)}</dd></div>
          </dl>
          <p className="mt-5 max-w-3xl text-sm text-sage-muted">Catalogued materials include records outside the current public browsing scope. Statistics refreshed {dateLabel(stats.stats_refreshed_at ?? stats.updated_at)} (UTC).</p>
        </> : <p className="mt-4 text-sm text-sage-muted">The coverage snapshot is temporarily unavailable. You can still search the library and browse materials.</p>}
        <Link href="/stats" className="mt-4 inline-block text-sm font-semibold underline underline-offset-4">View coverage and update details</Link>
      </section>
      <section aria-labelledby="sources-heading" className="grid gap-8 md:grid-cols-[1.4fr_1fr] md:gap-16">
        <div>
          <h2 id="sources-heading" className="text-2xl font-semibold">Follow the evidence to its source</h2>
          <p className="mt-4 max-w-2xl text-sage-muted">Material properties depend on reported conditions. Check pressure, temperature, experimental or computational origin, and the source literature before comparing results.</p>
          <p className="mt-3 max-w-2xl text-sm text-sage-muted">AI-assisted extraction may contain errors. Research priorities and candidate leads are not superconductivity probabilities or confirmed discoveries.</p>
          <Link href="/docs/data" className="mt-5 inline-block text-sm font-semibold underline underline-offset-4">Read about data and methodology</Link>
        </div>
        <div className="border-t border-sage-border pt-6 md:border-l md:border-t-0 md:pl-8 md:pt-0">
          <h2 className="text-2xl font-semibold">Developed by JZIS</h2>
          <p className="mt-4 text-sage-muted">JZ Institute of Science maintains SCLib to support superconductivity research through accessible literature, source-linked data and transparent methods.</p>
          <Link href="/about" className="mt-5 inline-block text-sm font-semibold underline underline-offset-4">About JZ Institute of Science</Link>
        </div>
      </section>
    </main>
  );
}
