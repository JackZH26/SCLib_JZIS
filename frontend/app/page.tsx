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
  { href: "/materials", title: "Materials", description: "Compare reported properties, pressure conditions and the literature behind each record.", detail: "Properties & source records" },
  { href: "/timeline", title: "Reported Tc Timeline", description: "Explore transition temperatures over time and return to the original reports.", detail: "Reports through time" },
  { href: "/discovery", title: "Discovery", description: "Review research priorities and historical candidate leads with their evidence and limitations.", detail: "Priorities & candidate leads" },
];
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";

function dateLabel(value: string | null | undefined) {
  if (!value || !Number.isFinite(Date.parse(value))) return "Not recorded";
  return new Date(value).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

export default async function Landing() {
  const stats = await getLibrarySnapshot();
  return (
    <main className="library-home">
      <LegacyHomeAnchor />
      <section aria-labelledby="library-heading" className="library-hero grid items-center gap-8 pb-10 pt-3 sm:pb-14 sm:pt-5 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] lg:gap-10">
        <div className="min-w-0">
          <h1 id="library-heading" className="library-headline font-semibold">The superconductivity research library</h1>
          <p className="mt-5 max-w-xl text-base leading-relaxed text-sage-muted sm:text-lg">Search superconductivity literature, explore source-linked materials data, and review reported Tc trends and research leads.</p>
          <div id="search" className="mt-7 scroll-mt-24"><SearchBar placeholder="Paper, material, or research question" /></div>
          <Link href="/materials" className="site-text-link mt-4 inline-flex items-center gap-2 text-sm font-semibold">Browse materials <span aria-hidden="true">→</span></Link>
        </div>
        <figure className="min-w-0">
          <img
            src={`${basePath}/images/layered-material-concept-1120.webp`}
            srcSet={`${basePath}/images/layered-material-concept-640.webp 640w, ${basePath}/images/layered-material-concept-1120.webp 1120w`}
            sizes="(min-width: 1280px) 474px, (min-width: 1024px) 38vw, (min-width: 640px) 600px, calc(100vw - 32px)"
            width={1120} height={747} fetchPriority="high" decoding="async"
            alt="AI-generated conceptual illustration of layered graphite-like and ceramic forms, not an experimental specimen."
            className="hero-material-image w-full rounded-xl object-cover"
          />
          <figcaption className="mt-2 text-xs leading-relaxed text-sage-muted">Conceptual material study. AI-generated illustration.</figcaption>
        </figure>
      </section>

      <section aria-labelledby="coverage-heading" className="coverage-panel rounded-xl border border-sage-border bg-white p-5 sm:p-7">
        <h2 id="coverage-heading" className="text-base font-semibold">Library coverage</h2>
        {stats ? <>
          <dl className="mt-5 grid gap-6 sm:grid-cols-[1fr_1fr_1.2fr] sm:gap-8">
            <div><dt className="text-sm text-sage-muted">Indexed papers</dt><dd className="mt-1 text-4xl font-medium tracking-tight tabular-nums lg:text-5xl">{stats.total_papers.toLocaleString("en-US")}</dd></div>
            <div><dt className="text-sm text-sage-muted">Catalogued materials</dt><dd className="mt-1 text-4xl font-medium tracking-tight tabular-nums lg:text-5xl">{stats.total_materials.toLocaleString("en-US")}</dd></div>
            <div><dt className="text-sm text-sage-muted">Latest indexed paper</dt><dd className="mt-2 text-2xl font-medium tracking-tight sm:text-3xl">{dateLabel(stats.last_ingest_at)}</dd></div>
          </dl>
          <p className="mt-6 max-w-3xl text-xs leading-relaxed text-sage-muted">Catalogued materials include records outside the current public browsing scope. Statistics refreshed {dateLabel(stats.stats_refreshed_at ?? stats.updated_at)} (UTC).</p>
        </> : <p className="mt-4 max-w-2xl text-sm text-sage-muted">The coverage snapshot is temporarily unavailable. You can still search the library and browse materials.</p>}
        <Link href="/stats" className="site-text-link mt-3 inline-block text-sm font-semibold">View coverage and update details</Link>
      </section>

      <section aria-labelledby="explore-heading" className="mt-14 sm:mt-20">
        <h2 id="explore-heading" className="text-3xl font-semibold tracking-tight">Explore the research</h2>
        <div className="mt-6 grid gap-3 lg:grid-cols-[1.15fr_1fr]">
          {researchRoutes.map((item, index) => (
            <Link key={item.href} href={item.href} className={`research-entry group flex flex-col justify-between rounded-xl border border-sage-border p-6 sm:p-7 ${index === 0 ? "bg-sage-surface lg:row-span-2 lg:min-h-[310px]" : "bg-white"}`}>
              <div className="flex items-start justify-between gap-5">
                <h3 className={`${index === 0 ? "text-2xl sm:text-3xl" : "text-xl"} font-semibold group-hover:text-accent-deep`}>{item.title}</h3>
                <span aria-hidden="true" className="entry-arrow shrink-0 text-2xl text-accent">↗</span>
              </div>
              <div className={index === 0 ? "mt-8" : "mt-3"}>
                {index === 0 && <p className="mb-2 text-sm font-semibold text-accent-deep">{item.detail}</p>}
                <p className="max-w-md text-sm leading-relaxed text-sage-muted">{item.description}</p>
              </div>
            </Link>
          ))}
        </div>
      </section>

      <section aria-labelledby="sources-heading" className="mt-14 grid gap-8 border-t border-sage-border pt-10 sm:mt-20 sm:pt-12 lg:grid-cols-[1.15fr_1fr] lg:gap-16">
        <div>
          <h2 id="sources-heading" className="max-w-lg text-3xl font-semibold tracking-tight">Follow the evidence to its source</h2>
          <p className="mt-5 max-w-xl text-sage-muted">Material properties depend on reported conditions. Check pressure, temperature, experimental or computational origin, and the source literature before comparing results.</p>
          <Link href="/docs/data" className="site-text-link mt-5 inline-block text-sm font-semibold">Read about data and methodology</Link>
        </div>
        <div className="self-start rounded-xl bg-sage-surface p-6 sm:p-7">
          <h3 className="text-base font-semibold">Read research leads in context</h3>
          <p className="mt-3 text-sm leading-relaxed text-sage-muted">AI-assisted extraction may contain errors. Research priorities and candidate leads are not superconductivity probabilities or confirmed discoveries.</p>
        </div>
      </section>

      <section aria-labelledby="institution-heading" className="mt-14 border-t border-sage-border pt-10 sm:mt-20 sm:pt-12">
        <h2 id="institution-heading" className="text-2xl font-semibold">Developed by JZIS</h2>
        <p className="mt-4 max-w-2xl text-sage-muted">JZ Institute of Science maintains SCLib to support superconductivity research through accessible literature, source-linked data and transparent methods.</p>
        <Link href="/about" className="site-text-link mt-5 inline-block text-sm font-semibold">About JZ Institute of Science</Link>
      </section>
    </main>
  );
}
