import type { Metadata } from "next";
import { DiscoveryFeed } from "@/components/DiscoveryFeed";
import {
  getDiscovery,
  getDiscoveryCandidates,
  getDiscoveryMetadata,
  type DiscoveryCandidatePage,
  type DiscoveryMetadata,
} from "@/lib/api";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Reviewed superconductivity discovery feed",
  description:
    "Review superconductivity candidates that passed physics-informed screening and evidence checks.",
  alternates: { canonical: absoluteUrl("/discovery") },
  openGraph: { url: absoluteUrl("/discovery") },
};

const PAGE_SIZE = 24;

async function safeDiscovery(): Promise<{
  metadata: DiscoveryMetadata;
  page: DiscoveryCandidatePage;
} | null> {
  try {
    const [metadata, page] = await Promise.all([
      getDiscoveryMetadata(),
      getDiscoveryCandidates({ limit: PAGE_SIZE }),
    ]);
    return { metadata, page };
  } catch {
    // Rolling-deploy fallback: an older API still exposes the full endpoint.
    try {
      const legacy = await getDiscovery();
      const roleCounts = legacy.candidates.reduce<Record<string, number>>(
        (counts, candidate) => {
          const role = candidate.record_role ?? "unclassified";
          counts[role] = (counts[role] ?? 0) + 1;
          return counts;
        },
        {},
      );
      return {
        metadata: {
          schema_version: "1",
          page_title: legacy.page_title,
          intro: legacy.intro,
          status: legacy.status,
          updated_at_utc: legacy.updated_at_utc,
          source: legacy.source,
          filter_rules: legacy.filter_rules,
          total_candidates: legacy.candidates.length,
          role_counts: roleCounts,
        },
        page: {
          schema_version: "1",
          items: legacy.candidates.slice(0, PAGE_SIZE),
          total: legacy.candidates.length,
          offset: 0,
          limit: PAGE_SIZE,
          has_more: legacy.candidates.length > PAGE_SIZE,
          record_role: null,
        },
      };
    } catch {
      return null;
    }
  }
}

export default async function DiscoveryPage() {
  const data = await safeDiscovery();
  const metadata = data?.metadata;

  return (
    <main className="space-y-8">
      <section className="space-y-4">
        <span className="inline-flex items-center gap-2 rounded-full border border-sage-border bg-[rgba(58,125,92,0.08)] px-4 py-1.5 text-xs font-semibold uppercase tracking-wider text-accent">
          Reviewed discovery feed · SCLib × SC SuperLoop
        </span>
        <div className="space-y-2">
          <h1 className="text-3xl font-bold tracking-tight md:text-4xl">
            {metadata?.page_title ?? "Discovery"}
          </h1>
          {(metadata?.intro ?? [
            "This page presents reviewed superconductivity candidates exported from SC SuperLoop into SCLib.",
            "Candidates are generated with physics-informed heuristics, then filtered through prescreening, bounded DFT checks, mechanism audit, and checker review before public display.",
          ]).map((line) => (
            <p key={line} className="max-w-4xl text-sm leading-6 text-sage-muted">
              {line}
            </p>
          ))}
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-[1.3fr_1fr]">
        <div className="rounded-2xl border border-sage-border bg-white p-5 shadow-soft">
          <h2 className="text-sm font-semibold uppercase tracking-[0.08em] text-accent">
            Public Filter
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
            Feed Status
          </h2>
          <dl className="mt-4 space-y-3 text-sm">
            <div className="flex items-start justify-between gap-4">
              <dt className="text-sage-muted">Status</dt>
              <dd className="font-medium text-sage-ink">
                {metadata?.status === "active" ? "Active" : "Planned / awaiting reviewed feed"}
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
          The reviewed discovery feed is temporarily unavailable.
        </section>
      ) : (
        <DiscoveryFeed
          initialPage={data.page}
          roleCounts={data.metadata.role_counts}
          totalCandidates={data.metadata.total_candidates}
        />
      )}
    </main>
  );
}
