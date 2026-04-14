/**
 * Landing page. Server component — fetches /stats at request time
 * so the counter cards stay fresh without client-side JS.
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
    <main className="space-y-12">
      <section className="mt-6 space-y-6 text-center">
        <h1 className="text-4xl font-bold tracking-tight md:text-5xl">
          The superconductivity research library
        </h1>
        <p className="mx-auto max-w-2xl text-lg text-slate-600">
          Semantic search and grounded Q&A across the arXiv cond-mat.supr-con
          corpus. Free for everyone; 3 guest queries per day without an
          account.
        </p>
        <div className="mx-auto max-w-2xl">
          <SearchBar />
        </div>
        <div className="flex justify-center gap-3 text-sm">
          <Link
            href="/ask"
            className="rounded-md border border-slate-300 bg-white px-4 py-2 hover:bg-slate-100"
          >
            Ask a question →
          </Link>
          <Link
            href="/timeline"
            className="rounded-md border border-slate-300 bg-white px-4 py-2 hover:bg-slate-100"
          >
            Explore the Tc timeline →
          </Link>
        </div>
      </section>

      {stats && (
        <section>
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Library
          </h2>
          <StatsCards stats={stats} />
        </section>
      )}
    </main>
  );
}
