import { FormulaDisplay } from "@/components/FormulaDisplay";
import { getDiscovery } from "@/lib/api";

async function safeDiscovery() {
  try {
    return await getDiscovery();
  } catch {
    return null;
  }
}

function badgeClass(confidence: string) {
  if (confidence.toLowerCase().includes("reference")) {
    return "border-stone-200 bg-stone-50 text-stone-800";
  }
  if (confidence.toLowerCase().includes("literature")) {
    return "border-emerald-200 bg-emerald-50 text-emerald-800";
  }
  if (confidence.toLowerCase().includes("high")) {
    return "border-emerald-200 bg-emerald-50 text-emerald-800";
  }
  if (confidence.toLowerCase().includes("mechanism")) {
    return "border-sky-200 bg-sky-50 text-sky-800";
  }
  return "border-amber-200 bg-amber-50 text-amber-800";
}

function formatEvidenceLabel(evidenceLevel: string) {
  const raw = evidenceLevel.trim();
  const level = evidenceLevel.trim().toUpperCase();
  if (level === "E3") {
    return "DFT-screened";
  }
  if (level === "E2") {
    return "Physics-screened";
  }
  if (level === "E1") {
    return "Heuristic-screened";
  }
  if (level === "E0") {
    return "Early hypothesis";
  }
  if (raw.toLowerCase() === "literature-confirmed") {
    return "Literature-confirmed";
  }
  if (raw.toLowerCase() === "reference") {
    return "Reference";
  }
  if (raw.toLowerCase() === "dft-screened") {
    return "DFT-screened";
  }
  return evidenceLevel;
}

function formatCheckerLabel(checkerStatus: string) {
  const status = checkerStatus.trim().toLowerCase();
  if (status === "verified") {
    return "Verified";
  }
  if (status === "pass") {
    return "Review passed";
  }
  if (status === "pending") {
    return "Under review";
  }
  if (status === "revise") {
    return "Needs revision";
  }
  return checkerStatus.replaceAll("_", " ");
}

function formatRoleLabel(role: string | null | undefined) {
  const value = (role ?? "").trim().toLowerCase();
  if (value === "reference_anchor") return "Reference anchor";
  if (value === "mechanism_anchor") return "Mechanism anchor";
  if (value === "benchmark_control") return "Benchmark control";
  if (value === "exploratory_candidate") return "Active candidate";
  if (value === "conditional_candidate") return "Conditional candidate";
  if (value === "negative_control") return "Negative control";
  if (value === "failed_memory") return "Failed memory";
  return role ?? "Unclassified";
}

function formatClaimLabel(value: string | null | undefined) {
  if (!value) return "Unspecified";
  return value.replaceAll("_", " ");
}

function formatNextAction(value: string | null | undefined) {
  if (!value) return "No next action recorded";
  return value.replaceAll("_", " ");
}

function formatDiscoveryScore(value: number | null) {
  return value == null ? "Insufficient data" : value.toFixed(1);
}

function SummaryFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="text-[11px] font-medium uppercase tracking-wide text-sage-muted">
        {label}
      </p>
      <p className="truncate font-semibold text-sage-ink">{value}</p>
    </div>
  );
}

const SECTION_ORDER = [
  "reference_anchor",
  "mechanism_anchor",
  "benchmark_control",
  "exploratory_candidate",
  "conditional_candidate",
  "negative_control",
  "failed_memory",
] as const;

const SECTION_META: Record<string, { title: string; description: string }> = {
  reference_anchor: {
    title: "Reference Anchors",
    description: "Known superconducting references used for family-level learning, not novelty claims.",
  },
  mechanism_anchor: {
    title: "Mechanism Anchors",
    description: "Known materials that anchor branch generation and mechanism constraints.",
  },
  benchmark_control: {
    title: "Benchmark Controls",
    description: "Calibration materials for known superconducting families and baseline checks.",
  },
  exploratory_candidate: {
    title: "Active Exploratory Candidates",
    description: "Positive exploratory records that remain eligible for further promotion.",
  },
  conditional_candidate: {
    title: "Conditional Candidates",
    description: "Scientifically interesting records with unmet gates that block immediate promotion.",
  },
  negative_control: {
    title: "Negative Controls",
    description: "Reviewed records that currently teach the loop what to avoid in the present proxy/phase regime.",
  },
  failed_memory: {
    title: "Failed Memory",
    description: "Failure records retained so the generator learns explicit avoid rules.",
  },
};

export default async function DiscoveryPage() {
  const data = await safeDiscovery();
  type CandidateList = NonNullable<Awaited<ReturnType<typeof safeDiscovery>>>["candidates"];
  const grouped = new Map<string, CandidateList>();
  for (const role of SECTION_ORDER) grouped.set(role, []);
  for (const candidate of data?.candidates ?? []) {
    const role = candidate.record_role ?? "reference_anchor";
    if (!grouped.has(role)) grouped.set(role, []);
    grouped.get(role)!.push(candidate);
  }

  return (
    <main className="space-y-8">
      <section className="space-y-4">
        <span className="inline-flex items-center gap-2 rounded-full border border-sage-border bg-[rgba(58,125,92,0.08)] px-4 py-1.5 text-xs font-semibold uppercase tracking-wider text-accent">
          Reviewed discovery feed · SCLib × SC SuperLoop
        </span>
        <div className="space-y-2">
          <h1 className="text-3xl font-bold tracking-tight md:text-4xl">
            {data?.page_title ?? "Discovery"}
          </h1>
          {(data?.intro ?? [
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
            {(data?.filter_rules ?? []).map((rule) => (
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
                {data?.status === "active" ? "Active" : "Planned / awaiting reviewed feed"}
              </dd>
            </div>
            <div className="flex items-start justify-between gap-4">
              <dt className="text-sage-muted">Last update</dt>
              <dd className="text-right font-medium text-sage-ink">
                {data?.updated_at_utc ?? "Not published yet"}
              </dd>
            </div>
            <div className="flex items-start justify-between gap-4">
              <dt className="text-sage-muted">Visible candidates</dt>
              <dd className="font-medium text-sage-ink">
                {data?.candidates.length ?? 0}
              </dd>
            </div>
          </dl>
        </div>
      </section>

      <section className="rounded-2xl border border-sage-border bg-white p-5 shadow-soft">
        <div className="mb-4 flex items-end justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-sage-ink">Role-classified records</h2>
            <p className="mt-1 text-sm text-sage-muted">
              The feed separates anchors, controls, active candidates, conditional cases, and negative controls.
            </p>
          </div>
        </div>

        {!data ? (
          <p className="text-sm text-red-600">Failed to load discovery feed.</p>
        ) : data.candidates.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-sage-border bg-sage-surface px-6 py-10 text-center">
            <p className="text-base font-medium text-sage-ink">
              No public discovery candidates yet.
            </p>
            <p className="mt-2 text-sm text-sage-muted">
              The feed is ready, but only corpus records with explicit evidence
              labels, provenance, and preview-eligible review status will
              appear here.
            </p>
          </div>
        ) : (
          <div className="space-y-8">
            {SECTION_ORDER.map((role) => {
              const candidates = grouped.get(role) ?? [];
              if (candidates.length === 0) return null;
              const meta = SECTION_META[role];
              return (
                <section key={role} className="space-y-4">
                  <div>
                    <h3 className="text-base font-semibold text-sage-ink">{meta.title}</h3>
                    <p className="mt-1 text-sm text-sage-muted">{meta.description}</p>
                  </div>
                  <div className="space-y-4">
                    {candidates.map((candidate) => (
                      <details
                        key={candidate.candidate_id}
                        className="group rounded-2xl border border-sage-border bg-sage-surface text-sm shadow-sm transition-colors open:bg-sage-soft"
                      >
                        <summary className="grid cursor-pointer list-none gap-3 px-4 py-3 [&::-webkit-details-marker]:hidden md:grid-cols-[minmax(0,1.3fr)_auto] md:items-center">
                          <div className="min-w-0">
                            <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
                              <h4 className="truncate text-lg font-semibold tracking-tight text-sage-ink">
                                <FormulaDisplay formula={candidate.formula} />
                              </h4>
                              <span
                                className={`rounded-full border px-3 py-1 text-xs font-semibold ${badgeClass(
                                  candidate.public_confidence,
                                )}`}
                              >
                                {candidate.public_confidence}
                              </span>
                            </div>
                            <p className="mt-1 flex flex-wrap gap-x-2 gap-y-1 text-xs text-sage-muted">
                              <span>{candidate.branch}</span>
                              {candidate.prototype_family && (
                                <span>{candidate.prototype_family}</span>
                              )}
                              <span>{formatRoleLabel(candidate.record_role)}</span>
                              <span>{formatClaimLabel(candidate.claim_level)}</span>
                            </p>
                          </div>

                          <div className="grid grid-cols-2 gap-2 md:min-w-[28rem] md:grid-cols-5">
                            <SummaryFact
                              label="Evidence"
                              value={formatEvidenceLabel(candidate.evidence_level)}
                            />
                            <SummaryFact
                              label="Review"
                              value={formatCheckerLabel(candidate.checker_status)}
                            />
                            <SummaryFact
                              label="Score"
                              value={formatDiscoveryScore(candidate.discovery_score)}
                            />
                            <SummaryFact
                              label="Action"
                              value={formatNextAction(candidate.next_action)}
                            />
                            <div className="flex items-center justify-end text-xs font-semibold text-accent-deep">
                              <span className="rounded-full border border-sage-border bg-white/70 px-3 py-1 group-open:hidden">
                                Details
                              </span>
                              <span className="hidden rounded-full border border-sage-border bg-white px-3 py-1 group-open:inline">
                                Close
                              </span>
                            </div>
                          </div>
                        </summary>

                        <div className="border-t border-sage-border px-4 pb-4 pt-3">
                          <div className="grid gap-3 text-sm md:grid-cols-2">
                          <div>
                            <p className="text-sage-muted">Claim level</p>
                            <p className="font-medium text-sage-ink">
                              {formatClaimLabel(candidate.claim_level)}
                            </p>
                          </div>
                          <div>
                            <p className="text-sage-muted">Next action</p>
                            <p className="font-medium text-sage-ink">
                              {formatNextAction(candidate.next_action)}
                            </p>
                          </div>
                          </div>

                          {candidate.mechanism_hypothesis && (
                            <p className="mt-4 text-sm leading-6 text-sage-ink">
                              <span className="font-medium">Mechanism hypothesis:</span>{" "}
                              {candidate.mechanism_hypothesis}
                            </p>
                          )}

                          {candidate.review_summary && (
                            <p className="mt-3 text-sm leading-6 text-sage-muted">
                              {candidate.review_summary}
                            </p>
                          )}

                          {candidate.risk_tags.length > 0 && (
                            <div className="mt-4 flex flex-wrap gap-2">
                              {candidate.risk_tags.map((tag) => (
                                <span
                                  key={tag}
                                  className="rounded-full border border-sage-border bg-white px-3 py-1 text-xs text-sage-muted"
                                >
                                  {tag}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      </details>
                    ))}
                  </div>
                </section>
              );
            })}
          </div>
        )}
      </section>
    </main>
  );
}
