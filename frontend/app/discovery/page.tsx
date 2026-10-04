import type { Metadata } from "next";
import { Suspense } from "react";
import Link from "next/link";
import { DiscoveryFeed } from "@/components/DiscoveryFeed";
import { ResearchPriorityBoard } from "@/components/ResearchPriorityBoard";
import { ScientificDiscoveryMatrix } from "@/components/ScientificDiscoveryMatrix";
import { DiscoveryFieldGuide } from "@/components/DiscoveryFieldGuide";
import { DiscoverySourceComparison } from "@/components/DiscoverySourceComparison";
import { DiscoveryPressureSeries } from "@/components/DiscoveryPressureSeries";
import {
  getDiscoveryCandidates,
  getDiscoveryMetadata,
  verifyDiscoveryPage,
  type DiscoveryCandidatePage,
  type DiscoveryMetadata,
} from "@/lib/api";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Design superconducting conditions",
  description:
    "Explore host stability, electronic activation, pairing and coherence, then outline the next superconductivity calculation or experiment.",
  alternates: { canonical: absoluteUrl("/discovery") },
  openGraph: { url: absoluteUrl("/discovery") },
};

const PAGE_SIZE = 24;

async function safeDiscovery(): Promise<{
  metadata: DiscoveryMetadata;
  page: DiscoveryCandidatePage;
} | null> {
  try {
    const metadata = await getDiscoveryMetadata();
    const page = await getDiscoveryCandidates({ limit: PAGE_SIZE, dataVersion: metadata.data_version });
    verifyDiscoveryPage(page, metadata.data_version, 0, [], null, metadata.total_candidates);
    return { metadata, page };
  } catch {
    // Never combine an unversioned legacy fallback with paginated endpoints.
    return null;
  }
}

export default async function DiscoveryPage({ searchParams }: { searchParams: Promise<{ preview?: string }> }) {
  // Explicit development-only layout preview. Never replace API errors with fake rows.
  if (process.env.NODE_ENV === "development" && (await searchParams).preview === "layout") {
    const { DiscoveryLayoutPreview } = await import("@/components/DiscoveryLayoutPreview");
    return <DiscoveryLayoutPreview />;
  }
  return (
    <main className="space-y-4">
      <header className="space-y-3 pb-2">
        <h1 className="text-3xl font-semibold tracking-tight">Discovery</h1>
        <p className="max-w-3xl text-base leading-6">Design the conditions for superconductivity, then choose the next calculation or experiment.</p>
        <p className="text-sm text-sage-muted">Research target: approximately 300 K at 1 atm.</p>
        <nav aria-label="Discovery research workflow" className="flex flex-wrap gap-x-5 gap-y-3 text-sm">
          <Link href="/discovery/host-references" className="min-h-11 content-center text-accent underline underline-offset-4">Compare host energy and band gaps</Link>
          <Link href="/discovery/structures" className="min-h-11 content-center text-accent underline underline-offset-4">Inspect structure coordinates</Link>
          <Link href="/discovery/calculations" className="min-h-11 content-center text-accent underline underline-offset-4">Read calculation output</Link>
          <a href="#discovery-evidence" className="min-h-11 content-center text-accent underline underline-offset-4">Inspect state evidence</a>
          <a href="#discovery-source-comparisons" className="min-h-11 content-center text-accent underline underline-offset-4">Compare reported modifications</a>
          <a href="#discovery-pressure-response" className="min-h-11 content-center text-accent underline underline-offset-4">Compare pressure reports</a>
          <a href="#discovery-condition-design" className="min-h-11 content-center text-accent underline underline-offset-4">Design a research plan</a>
          <a href="#discovery-methodology" className="min-h-11 content-center text-accent underline underline-offset-4">Methodology and scope</a>
        </nav>
      </header>

      <ScientificDiscoveryMatrix />
      <DiscoveryPressureSeries />
      <DiscoverySourceComparison />
      <p className="max-w-3xl text-sm"><Link className="site-text-link inline-flex min-h-11 items-center" href="/materials/source-observations/nbsctizr-annealing">Compare reported annealing effects in NbScTiZr</Link>: an experimental preparation study with separate transition criteria and source-derived field parameters.</p>
      <details id="discovery-methodology" className="scroll-mt-24 rounded-xl border border-sage-border p-4">
        <summary className="cursor-pointer text-sm font-semibold">Methodology and scope</summary>
        <div className="mt-3 max-w-3xl space-y-3 text-sm leading-6 text-sage-muted">
          <p>Stable host → Electronic activation → Pairing → Coherence → Superconducting state is a conceptual research framework. Each stage requires evidence for its own structure, state, conditions and method.</p>
          <p>Discovery studies how doping, substitution, vacancies, strain, interfaces, layer count, twist or pressure could change those conditions. A proposed modification is a hypothesis; reference results remain attached to their original state.</p>
          <p>High-pressure results can motivate ambient-pressure research, but translation requires matched-state comparisons and independent stability checks. Different pairing channels need their own models and evidence.</p>
          <p>RPS allocates research effort to an action within a fixed campaign and budget. It is not a superconductivity probability or a physical design-space coordinate.</p>
        </div>
      </details>
      <details className="rounded-xl border border-sage-border p-4">
        <summary className="cursor-pointer text-sm font-semibold">Original RPS assessment releases · action-level view</summary>
        <p className="my-3 text-sm text-sage-muted">This separate view retains the original assessment catalog. An assessment release is not a published scientific companion or a one-material matrix.</p>
        <ResearchPriorityBoard />
      </details>
      <DiscoveryFieldGuide />

      <Suspense fallback={<p className="text-sm text-sage-muted">Loading historical candidate leads…</p>}>
        <LegacyDiscovery />
      </Suspense>
    </main>
  );
}

async function LegacyDiscovery() {
  const data = await safeDiscovery();
  const metadata = data?.metadata;
  return (

      <details className="space-y-5 rounded-xl border border-sage-border p-5">
        <summary className="cursor-pointer text-lg font-semibold">Historical candidate leads · pending RPS assessment ({metadata?.total_candidates ?? 0})</summary>
        <p className="mt-4 text-sm leading-6 text-sage-muted">These records retain the original SC SuperLoop feed and heuristic scores for provenance. They are not new RPS assessments, superconductivity probabilities, or proof of experimental discovery. Original checker status may be pending.</p>
      <section className="mt-5 grid gap-4 md:grid-cols-[1.3fr_1fr]">
        <div className="rounded-2xl border border-sage-border bg-white p-5 shadow-soft">
          <h2 className="text-sm font-semibold uppercase tracking-[0.08em] text-accent">
            Legacy feed filters
          </h2>
          <div className="mt-4 flex flex-wrap gap-2">
            {(metadata?.filter_rules ?? []).map((rule) => (
              <span
                key={rule.key}
                className="rounded-full border border-sage-border bg-sage-surface px-3 py-1 text-xs text-sage-muted"
              >
                {rule.label}: {rule.value}
              </span>
            ))}
          </div>
        </div>

        <div className="rounded-2xl border border-sage-border bg-white p-5 shadow-soft">
          <h2 className="text-sm font-semibold uppercase tracking-[0.08em] text-accent">
            Legacy feed status
          </h2>
          <dl className="mt-4 space-y-3 text-sm">
            <div className="flex items-start justify-between gap-4">
              <dt className="text-sage-muted">Status</dt>
              <dd className="font-medium text-sage-ink">
                {!metadata ? "Unavailable" : metadata.source_status === "stale" ? "Stale · last validated version" : metadata.status === "active" ? "Active legacy feed" : "Planned / awaiting feed"}
              </dd>
            </div>
            <div className="flex items-start justify-between gap-4">
              <dt className="text-sage-muted">Last update</dt>
              <dd className="break-all text-right font-medium text-sage-ink">
                {metadata?.updated_at_utc ?? "Not published yet"}
              </dd>
            </div>
            <div className="flex items-start justify-between gap-4">
              <dt className="text-sage-muted">Visible candidates</dt>
              <dd className="font-medium text-sage-ink">{metadata?.total_candidates ?? 0}</dd>
            </div>
          </dl>
        </div>
      </section>

      {!data ? (
        <section className="rounded-2xl border border-red-200 bg-red-50 px-6 py-8 text-sm text-red-700">
          The historical candidate feed is temporarily unavailable.
        </section>
      ) : (
        <DiscoveryFeed
          initialPage={data.page}
          roleCounts={data.metadata.role_counts}
          totalCandidates={data.metadata.total_candidates}
        />
      )}
      </details>
  );
}
