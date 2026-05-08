/**
 * Landing page. Server component — fetches /stats at request time
 * so the counter cards stay fresh without client-side JS.
 *
 * Hero treatment mirrors asrp.jzis.org: a pill "eyebrow" badge, a
 * large heading with a gradient-text highlight on the key phrase,
 * a muted subtitle, and a search bar + two outline CTAs.
 */
import Link from "next/link";
import { SearchBar } from "@/components/SearchBar";
import { StatsCards } from "@/components/StatsCards";
import { getStats } from "@/lib/api";

async function safeStats() {
  try {
    return await getStats();
  } catch {
    return null;
  }
}

export default async function Landing() {
  const stats = await safeStats();
  return (
    <main className="space-y-16">
      <section className="mt-10 space-y-6 text-center">
        <span className="inline-flex items-center gap-2 rounded-full border border-sage-border bg-[rgba(58,125,92,0.08)] px-4 py-1.5 text-xs font-semibold uppercase tracking-wider text-accent">
          arXiv cond-mat.supr-con · JZIS
        </span>
        <h1 className="mx-auto max-w-4xl text-4xl font-extrabold leading-tight tracking-tight md:text-6xl">
          The{" "}
          <span className="bg-sage-gradient-text bg-clip-text text-transparent">
            superconductivity
          </span>{" "}
          research library
        </h1>
        <p className="mx-auto max-w-2xl text-lg text-sage-muted">
          Semantic search and grounded Q&amp;A across the arXiv cond-mat.supr-con
          corpus. Data is automatically extracted and validated by LLM; please
          confirm accuracy through the original literature.
        </p>
        <div className="mx-auto max-w-2xl pt-2">
          <SearchBar />
        </div>
        <div className="flex flex-wrap justify-center gap-3 pt-2 text-sm">
          <Link href="/search" className="btn-outline">
            Ask a question →
          </Link>
          <Link href="/timeline" className="btn-outline">
            Explore the Tc timeline →
          </Link>
        </div>
      </section>

      {stats && (
        <section>
          <h2 className="mb-4 text-xs font-bold uppercase tracking-[0.1em] text-accent">
            Library
          </h2>
          <StatsCards stats={stats} />
        </section>
      )}
    </main>
  );
}
