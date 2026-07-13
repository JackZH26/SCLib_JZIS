"use client";

import { useMemo, useRef, useState, type SyntheticEvent } from "react";
import { FormulaDisplay } from "@/components/FormulaDisplay";
import {
  friendlyErrorMessage,
  getDiscoveryCandidate,
  getDiscoveryCandidates,
  type DiscoveryCandidate,
  type DiscoveryCandidatePage,
  type DiscoveryCandidateSummary,
} from "@/lib/api";

const PAGE_SIZE = 24;

const ROLE_ORDER = [
  "exploratory_candidate",
  "conditional_candidate",
  "reference_anchor",
  "mechanism_anchor",
  "benchmark_control",
  "negative_control",
  "failed_memory",
] as const;

const ROLE_META: Record<string, { title: string; description: string }> = {
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
    description: "Reviewed records that teach the loop what to avoid in the present proxy or phase regime.",
  },
  failed_memory: {
    title: "Failed Memory",
    description: "Failure records retained so the generator learns explicit avoid rules.",
  },
  unclassified: {
    title: "Unclassified",
    description: "Reviewed records awaiting a stable role classification.",
  },
};

function badgeClass(confidence: string) {
  const value = confidence.toLowerCase();
  if (value.includes("reference")) return "border-stone-200 bg-stone-50 text-stone-800";
  if (value.includes("literature") || value.includes("high")) {
    return "border-emerald-200 bg-emerald-50 text-emerald-800";
  }
  if (value.includes("mechanism")) return "border-sky-200 bg-sky-50 text-sky-800";
  return "border-amber-200 bg-amber-50 text-amber-800";
}

function formatEvidenceLabel(evidenceLevel: string) {
  const raw = evidenceLevel.trim();
  const labels: Record<string, string> = {
    E3: "DFT-screened",
    E2: "Physics-screened",
    E1: "Heuristic-screened",
    E0: "Early hypothesis",
  };
  if (labels[raw.toUpperCase()]) return labels[raw.toUpperCase()];
  if (raw.toLowerCase() === "literature-confirmed") return "Literature-confirmed";
  if (raw.toLowerCase() === "reference") return "Reference";
  if (raw.toLowerCase() === "dft-screened") return "DFT-screened";
  return evidenceLevel;
}

function formatCheckerLabel(checkerStatus: string) {
  const labels: Record<string, string> = {
    verified: "Verified",
    pass: "Review passed",
    pending: "Under review",
    revise: "Needs revision",
  };
  const status = checkerStatus.trim().toLowerCase();
  return labels[status] ?? checkerStatus.replaceAll("_", " ");
}

function formatRoleLabel(role: string | null | undefined) {
  const value = (role ?? "unclassified").trim().toLowerCase();
  return ROLE_META[value]?.title.replace(/s$/, "") ?? value.replaceAll("_", " ");
}

function formatLabel(value: string | null | undefined, fallback = "Unspecified") {
  return value ? value.replaceAll("_", " ") : fallback;
}

function formatScore(value: number | null | undefined) {
  return value == null ? "Insufficient data" : value.toFixed(1);
}

function SummaryFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="text-[11px] font-medium uppercase tracking-wide text-sage-muted">{label}</p>
      <p className="truncate font-semibold text-sage-ink">{value}</p>
    </div>
  );
}

function TagList({
  title,
  values,
  tone = "default",
}: {
  title: string;
  values: string[];
  tone?: "default" | "warning" | "danger" | "info";
}) {
  if (values.length === 0) return null;
  const toneClass = {
    default: "border-sage-border bg-white text-sage-muted",
    warning: "border-amber-200 bg-amber-50 text-amber-800",
    danger: "border-red-200 bg-red-50 text-red-800",
    info: "border-sky-200 bg-sky-50 text-sky-800",
  }[tone];
  return (
    <div className="mt-4">
      <p className="mb-2 text-sm font-medium text-sage-ink">{title}</p>
      <div className="flex flex-wrap gap-2">
        {values.map((value, index) => (
          <span
            key={`${value}-${index}`}
            className={`rounded-full border px-3 py-1 text-xs ${toneClass}`}
          >
            {formatLabel(value)}
          </span>
        ))}
      </div>
    </div>
  );
}

function CandidateDetail({ candidate }: { candidate: DiscoveryCandidate }) {
  const gateFlags = [
    ...candidate.literature_verifier_flags,
    ...candidate.synthesis_feasibility_flags,
    ...candidate.correlation_gate_flags,
  ];
  return (
    <div className="border-t border-sage-border px-4 pb-4 pt-3">
      <div className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <SummaryFact label="Claim level" value={formatLabel(candidate.claim_level)} />
        <SummaryFact label="Next action" value={formatLabel(candidate.next_action, "No next action recorded")} />
        <SummaryFact label="Condition" value={formatLabel(candidate.condition_class)} />
        <SummaryFact label="Family ruleset" value={formatLabel(candidate.family_ruleset_id)} />
        <SummaryFact label="Literature gate" value={formatLabel(candidate.literature_verifier_status)} />
        <SummaryFact label="Correlation gate" value={formatLabel(candidate.correlation_gate_status)} />
        <SummaryFact label="Synthesis feasibility" value={formatScore(candidate.synthesis_feasibility_score)} />
        <SummaryFact label="Measurement clarity" value={formatScore(candidate.measurement_clarity_score)} />
      </div>

      {candidate.mechanism_hypothesis && (
        <p className="mt-4 text-sm leading-6 text-sage-ink">
          <span className="font-medium">Mechanism hypothesis:</span>{" "}
          {candidate.mechanism_hypothesis}
        </p>
      )}
      {candidate.review_summary && (
        <p className="mt-3 text-sm leading-6 text-sage-muted">{candidate.review_summary}</p>
      )}
      {candidate.provenance_summary && (
        <p className="mt-3 text-sm leading-6 text-sage-muted">
          <span className="font-medium text-sage-ink">Provenance:</span>{" "}
          {candidate.provenance_summary}
        </p>
      )}
      {candidate.recommended_next_step && (
        <p className="mt-3 text-sm leading-6 text-sage-muted">
          <span className="font-medium text-sage-ink">Recommended next step:</span>{" "}
          {candidate.recommended_next_step}
        </p>
      )}

      <TagList title="Risk tags" values={candidate.risk_tags} />
      <TagList title="Failure taxonomy" values={candidate.failure_mode_taxonomy} tone="danger" />
      <TagList title="Gate flags" values={gateFlags} tone="warning" />
      <TagList title="Required condition vector" values={candidate.required_condition_vector} tone="info" />
      <TagList title="Upgrade requirements" values={candidate.upgrade_requirements} />
    </div>
  );
}

function CandidateCard({ candidate }: { candidate: DiscoveryCandidateSummary }) {
  const [detail, setDetail] = useState<DiscoveryCandidate | null>(null);
  const [detailState, setDetailState] = useState<"idle" | "loading" | "error">("idle");

  async function loadDetail() {
    if (detail || detailState === "loading") return;
    setDetailState("loading");
    try {
      setDetail(await getDiscoveryCandidate(candidate.candidate_id));
      setDetailState("idle");
    } catch {
      setDetailState("error");
    }
  }

  function handleToggle(event: SyntheticEvent<HTMLDetailsElement>) {
    if (event.currentTarget.open) void loadDetail();
  }

  return (
    <details
      onToggle={handleToggle}
      data-virtualized="true"
      className="group rounded-2xl border border-sage-border bg-sage-surface text-sm shadow-sm transition-colors open:bg-sage-soft [contain-intrinsic-size:180px] [content-visibility:auto]"
    >
      <summary className="grid cursor-pointer list-none gap-3 px-4 py-3 [&::-webkit-details-marker]:hidden lg:grid-cols-[minmax(20rem,1fr)_minmax(0,38rem)] lg:items-center">
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
            <h4 className="truncate text-lg font-semibold tracking-tight text-sage-ink">
              <FormulaDisplay formula={candidate.formula} />
            </h4>
            <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${badgeClass(candidate.public_confidence)}`}>
              {candidate.public_confidence}
            </span>
            {candidate.lane_id && (
              <span className="rounded-full border border-sky-200 bg-sky-50 px-3 py-1 text-xs font-semibold text-sky-800">
                {candidate.lane_id}
              </span>
            )}
          </div>
          <p className="mt-1 flex flex-wrap gap-x-2 gap-y-1 text-xs text-sage-muted">
            <span>{candidate.branch}</span>
            {candidate.prototype_family && <span>{candidate.prototype_family}</span>}
            {candidate.condition_class && <span>{formatLabel(candidate.condition_class)}</span>}
            <span>{formatRoleLabel(candidate.record_role)}</span>
            <span>{formatLabel(candidate.claim_level)}</span>
          </p>
        </div>

        <div className="grid min-w-0 grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-[repeat(4,minmax(0,1fr))_auto]">
          <SummaryFact label="Evidence" value={formatEvidenceLabel(candidate.evidence_level)} />
          <SummaryFact label="Review" value={formatCheckerLabel(candidate.checker_status)} />
          <SummaryFact label="Score" value={formatScore(candidate.discovery_score)} />
          <SummaryFact label="Readiness" value={formatLabel(candidate.experiment_readiness)} />
          <SummaryFact label="Evidence Q" value={formatScore(candidate.evidence_quality_score)} />
          <SummaryFact label="Action" value={formatLabel(candidate.next_action, "No next action recorded")} />
          <SummaryFact label="Lane layer" value={formatLabel(candidate.candidate_layer)} />
          <div className="flex items-center justify-end text-xs font-semibold text-accent-deep">
            <span className="rounded-full border border-sage-border bg-white/70 px-3 py-1 group-open:hidden">Details</span>
            <span className="hidden rounded-full border border-sage-border bg-white px-3 py-1 group-open:inline">Close</span>
          </div>
        </div>
      </summary>

      {detailState === "loading" && (
        <p className="border-t border-sage-border px-4 py-5 text-sm text-sage-muted" role="status">
          Loading reviewed dossier…
        </p>
      )}
      {detailState === "error" && (
        <div className="border-t border-sage-border px-4 py-5 text-sm text-red-700">
          <p>Could not load this dossier.</p>
          <button type="button" onClick={() => void loadDetail()} className="mt-2 font-semibold text-accent-deep underline">
            Try again
          </button>
        </div>
      )}
      {detail && <CandidateDetail candidate={detail} />}
    </details>
  );
}

export function DiscoveryFeed({
  initialPage,
  roleCounts,
  totalCandidates,
}: {
  initialPage: DiscoveryCandidatePage;
  roleCounts: Record<string, number>;
  totalCandidates: number;
}) {
  const [selectedRole, setSelectedRole] = useState<string | null>(initialPage.record_role);
  const [items, setItems] = useState(initialPage.items);
  const [total, setTotal] = useState(initialPage.total);
  const [hasMore, setHasMore] = useState(initialPage.has_more);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestSequence = useRef(0);

  const roles = useMemo(() => {
    const known = ROLE_ORDER.filter((role) => (roleCounts[role] ?? 0) > 0);
    const extras = Object.keys(roleCounts)
      .filter((role) => !ROLE_ORDER.includes(role as (typeof ROLE_ORDER)[number]))
      .sort();
    return [...known, ...extras];
  }, [roleCounts]);

  async function selectRole(role: string | null) {
    if (role === selectedRole && error === null) return;
    const sequence = ++requestSequence.current;
    setSelectedRole(role);
    setItems([]);
    setTotal(role ? (roleCounts[role] ?? 0) : totalCandidates);
    setHasMore(false);
    setError(null);
    setLoading(true);
    try {
      const page = await getDiscoveryCandidates({ limit: PAGE_SIZE, recordRole: role });
      if (sequence !== requestSequence.current) return;
      setItems(page.items);
      setTotal(page.total);
      setHasMore(page.has_more);
    } catch (caught) {
      if (sequence !== requestSequence.current) return;
      setError(friendlyErrorMessage(caught, "Could not load discovery records."));
    } finally {
      if (sequence === requestSequence.current) setLoading(false);
    }
  }

  async function loadMore() {
    if (loading || !hasMore) return;
    const sequence = ++requestSequence.current;
    setError(null);
    setLoading(true);
    try {
      const page = await getDiscoveryCandidates({
        offset: items.length,
        limit: PAGE_SIZE,
        recordRole: selectedRole,
      });
      if (sequence !== requestSequence.current) return;
      setItems((current) => [...current, ...page.items]);
      setTotal(page.total);
      setHasMore(page.has_more);
    } catch (caught) {
      if (sequence !== requestSequence.current) return;
      setError(friendlyErrorMessage(caught, "Could not load more discovery records."));
    } finally {
      if (sequence === requestSequence.current) setLoading(false);
    }
  }

  const selectedMeta = selectedRole ? ROLE_META[selectedRole] : null;

  return (
    <section className="rounded-2xl border border-sage-border bg-white p-4 shadow-soft sm:p-5">
      <div className="flex flex-col gap-4">
        <div>
          <h2 className="text-lg font-semibold text-sage-ink">Role-classified records</h2>
          <p className="mt-1 text-sm text-sage-muted">
            Browse a bounded page at a time; full reviewed dossiers load only when expanded.
          </p>
        </div>
        <div className="flex flex-wrap gap-2" aria-label="Filter discovery records by role">
          <button
            type="button"
            aria-pressed={selectedRole === null}
            onClick={() => void selectRole(null)}
            className={`rounded-full border px-3 py-1.5 text-xs font-semibold ${
              selectedRole === null
                ? "border-accent bg-accent text-white"
                : "border-sage-border bg-sage-surface text-sage-muted hover:bg-sage-soft"
            }`}
          >
            All · {totalCandidates}
          </button>
          {roles.map((role) => (
            <button
              key={role}
              type="button"
              aria-pressed={selectedRole === role}
              onClick={() => void selectRole(role)}
              className={`rounded-full border px-3 py-1.5 text-xs font-semibold ${
                selectedRole === role
                  ? "border-accent bg-accent text-white"
                  : "border-sage-border bg-sage-surface text-sage-muted hover:bg-sage-soft"
              }`}
            >
              {ROLE_META[role]?.title ?? formatLabel(role)} · {roleCounts[role]}
            </button>
          ))}
        </div>
      </div>

      {selectedMeta && (
        <div className="mt-5 rounded-xl border border-sage-border bg-sage-surface px-4 py-3">
          <h3 className="font-semibold text-sage-ink">{selectedMeta.title}</h3>
          <p className="mt-1 text-sm text-sage-muted">{selectedMeta.description}</p>
        </div>
      )}

      <p className="mt-5 text-xs font-medium uppercase tracking-wide text-sage-muted" aria-live="polite">
        Showing {items.length} of {total} records
      </p>

      {error && <p className="mt-4 text-sm text-red-700">{error}</p>}
      {items.length === 0 && !loading && !error ? (
        <div className="mt-4 rounded-2xl border border-dashed border-sage-border bg-sage-surface px-6 py-10 text-center">
          <p className="font-medium text-sage-ink">No public discovery candidates in this role.</p>
        </div>
      ) : (
        <div className="mt-4 space-y-4">
          {items.map((candidate) => (
            <CandidateCard key={candidate.candidate_id} candidate={candidate} />
          ))}
        </div>
      )}

      <div className="mt-6 flex justify-center">
        {hasMore && (
          <button
            type="button"
            disabled={loading}
            onClick={() => void loadMore()}
            className="rounded-lg bg-sage-gradient px-5 py-2.5 text-sm font-semibold text-white shadow-sm disabled:cursor-wait disabled:opacity-60"
          >
            {loading ? "Loading…" : `Load ${Math.min(PAGE_SIZE, total - items.length)} more`}
          </button>
        )}
        {!hasMore && loading && <p className="text-sm text-sage-muted">Loading…</p>}
      </div>
    </section>
  );
}
