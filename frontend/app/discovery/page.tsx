import { FormulaDisplay } from "@/components/FormulaDisplay";
import { getDiscovery, type DiscoveryCandidate } from "@/lib/api";
import type { ReactNode } from "react";

export default async function DiscoveryPage() {
  const feed = await getDiscovery().catch(() => null);
  if (!feed) {
    return <p className="text-sm text-red-600">Failed to load discovery preview.</p>;
  }
  const standard = feed.standard ?? {
    mode: "preview",
    minimum_evidence_level: "label required",
    accepted_checker_statuses: ["verified / pass"],
    dossier_required: true,
  };
  const updatedAt = feed.updated_at ?? feed.updated_at_utc ?? new Date().toISOString();

  return (
    <main className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Discovery preview</h1>
          <p className="mt-1 text-sm text-slate-600">
            Last updated {new Date(updatedAt).toLocaleString()}
          </p>
        </div>
        <div className="rounded-lg border border-sage-border bg-white px-4 py-3 text-sm">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Mode
          </span>
          <div className="mt-1 font-semibold text-sage-ink">
            {standard.mode} · {feed.status}
          </div>
        </div>
      </div>

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Visible candidates" value={feed.candidates.length.toString()} />
        <Metric label="Minimum evidence" value={standard.minimum_evidence_level} />
        <Metric
          label="Checker status"
          value={standard.accepted_checker_statuses.join(" / ")}
        />
        <Metric label="Dossier" value={standard.dossier_required ? "required" : "optional"} />
      </section>

      {feed.message && (
        <div className="rounded-lg border border-sage-border bg-white px-4 py-3 text-sm text-slate-600">
          {feed.message}
        </div>
      )}

      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Candidates
        </h2>
        {feed.candidates.length === 0 ? (
          <div className="rounded-lg border border-sage-border bg-white px-4 py-8 text-center text-sm text-slate-500">
            No preview candidates are currently visible.
          </div>
        ) : (
          <div className="space-y-3">
            {feed.candidates.map((candidate) => (
              <CandidateCard key={candidateKey(candidate)} candidate={candidate} />
            ))}
          </div>
        )}
      </section>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-sage-border bg-white p-4">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className="mt-2 text-2xl font-semibold text-sage-ink">{value}</div>
    </div>
  );
}

function CandidateCard({ candidate }: { candidate: DiscoveryCandidate }) {
  const primaryLabel = candidate.name || candidate.formula;
  const primaryIsFormula = primaryLabel === candidate.formula;
  const metadata = candidate.metadata ?? {};
  const family =
    candidate.family ||
    candidate.branch ||
    candidate.prototype_family ||
    metadataText(metadata, "family", "branch", "prototype_family");
  const prototype = candidate.prototype_family || metadataText(metadata, "prototype_family");
  const subfamily = sameLabel(prototype, family) ? null : prototype;
  const confidence =
    candidate.public_confidence || metadataText(metadata, "public_confidence");
  const evidence = confidence || candidate.evidence_level;
  const role = candidate.record_role || metadataText(metadata, "role", "candidate_role");
  const claimLevel = candidate.claim_level || metadataText(metadata, "claim_level", "claim");
  const reviewStatus =
    metadataText(metadata, "review_status", "status") || candidate.checker_status;
  const nextAction =
    candidate.next_action ||
    candidate.recommended_next_step ||
    metadataText(metadata, "next_action", "action");
  const discoveryScore =
    candidate.discovery_score ?? metadataText(metadata, "discovery_score", "score");
  const mechanism =
    candidate.mechanism_hypothesis ||
    metadataText(metadata, "mechanism_hypothesis", "mechanism");
  const tags = candidate.risk_tags?.length
    ? candidate.risk_tags
    : metadataList(metadata, "tags", "flags", "labels", "risk_tags");
  const summary = candidate.summary || candidate.review_summary;
  const source = candidate.source || candidate.provenance_summary;
  const updated =
    candidate.updated_at || candidate.last_reviewed_at_utc || candidate.published_at_utc;
  const visibleMetadata = omitMetadata(metadata, [
    "role",
    "candidate_role",
    "claim_level",
    "claim",
    "review_status",
    "status",
    "next_action",
    "action",
    "discovery_score",
    "score",
    "mechanism_hypothesis",
    "mechanism",
    "tags",
    "flags",
    "labels",
  ]);

  return (
    <details className="group rounded-lg border border-sage-border bg-white text-sm shadow-sm transition-colors open:bg-sage-soft">
      <summary className="grid cursor-pointer list-none gap-3 px-4 py-3 [&::-webkit-details-marker]:hidden sm:grid-cols-[minmax(0,1.5fr)_auto] sm:items-center">
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
            <h3 className="truncate text-lg font-semibold text-sage-ink">
              {primaryIsFormula ? (
                <FormulaDisplay formula={candidate.formula} />
              ) : (
                primaryLabel
              )}
            </h3>
            {candidate.name && candidate.name !== candidate.formula && (
              <FormulaDisplay
                formula={candidate.formula}
                className="font-normal text-slate-500"
              />
            )}
            {evidence && (
              <Badge>{formatLabel(evidence)}</Badge>
            )}
          </div>
          <div className="mt-1 flex flex-wrap gap-x-2 gap-y-1 text-xs text-slate-500">
            {uniqueLabels([family, subfamily, role, claimLevel]).map((item) => (
              <span key={item}>{formatLabel(item)}</span>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2 sm:min-w-[28rem] sm:grid-cols-5">
          <MiniStat label="Tc" value={formatNumber(candidate.tc_kelvin, " K")} />
          <MiniStat label="P" value={formatNumber(candidate.pressure_gpa, " GPa")} />
          <MiniStat label="Evidence" value={formatLabel(evidence)} />
          <MiniStat label="Review" value={formatLabel(reviewStatus)} />
          <div className="flex items-center justify-end text-xs font-semibold text-accent-deep">
            <span className="rounded-full border border-sage-border px-3 py-1 group-open:hidden">
              Details
            </span>
            <span className="hidden rounded-full border border-sage-border bg-white px-3 py-1 group-open:inline">
              Close
            </span>
          </div>
        </div>
      </summary>

      <div className="border-t border-sage-border px-4 pb-4 pt-3">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Fact label="Role" value={formatLabel(role)} />
          <Fact label="Claim level" value={formatLabel(claimLevel)} />
          <Fact label="Discovery score" value={formatLabel(discoveryScore)} />
          <Fact label="Next action" value={formatLabel(nextAction)} />
          <Fact label="Review status" value={formatLabel(reviewStatus)} />
          <Fact label="Checker" value={formatLabel(candidate.checker_status)} />
          <Fact label="Updated" value={updated || "-"} />
          <Fact
            label="Dossier"
            value={
              candidate.dossier_url ? (
                <a
                  href={candidate.dossier_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-accent hover:text-accent-deep hover:underline"
                >
                  Open dossier
                </a>
              ) : (
                "-"
              )
            }
          />
        </div>

        {mechanism && (
          <p className="mt-4 leading-relaxed text-slate-700">
            <span className="font-semibold text-sage-ink">Mechanism hypothesis: </span>
            {mechanism}
          </p>
        )}

        {summary && (
          <p className="mt-3 leading-relaxed text-slate-600">
            {summary}
          </p>
        )}

        {source && (
          <p className="mt-3 leading-relaxed text-slate-600">
            <span className="font-semibold text-sage-ink">Source: </span>
            {source}
          </p>
        )}

        {tags.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {tags.map((tag) => (
              <span
                key={tag}
                className="rounded-full border border-sage-border bg-white px-3 py-1 text-xs font-medium text-slate-600"
              >
                {formatLabel(tag)}
              </span>
            ))}
          </div>
        )}

        {Object.keys(visibleMetadata).length > 0 && (
          <dl className="mt-4 grid gap-3 border-t border-sage-border pt-4 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(visibleMetadata).map(([key, value]) => (
              <Fact key={key} label={formatLabel(key)} value={formatMetadataValue(value)} />
            ))}
          </dl>
        )}
      </div>
    </details>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
        {label}
      </div>
      <div className="truncate font-semibold tabular-nums text-sage-ink">{value}</div>
    </div>
  );
}

function Fact({
  label,
  value,
}: {
  label: string;
  value: ReactNode;
}) {
  return (
    <div>
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-sm font-medium text-sage-ink">{value || "-"}</div>
    </div>
  );
}

function Badge({ children }: { children: ReactNode }) {
  return (
    <span className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">
      {children}
    </span>
  );
}

function formatNumber(value: number | null, suffix = "") {
  return value == null
    ? "-"
    : `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })}${suffix}`;
}

function formatLabel(value: unknown): string {
  if (value == null || value === "") return "-";
  if (typeof value !== "string") return String(value);
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function metadataText(metadata: Record<string, unknown>, ...keys: string[]) {
  for (const key of keys) {
    const value = metadata[key];
    if (typeof value === "string" && value.trim()) return value;
    if (typeof value === "number" || typeof value === "boolean") return String(value);
  }
  return null;
}

function metadataList(metadata: Record<string, unknown>, ...keys: string[]) {
  for (const key of keys) {
    const value = metadata[key];
    if (Array.isArray(value)) {
      return value
        .filter((item) => typeof item === "string" || typeof item === "number")
        .map(String);
    }
    if (typeof value === "string" && value.trim()) {
      return value.split(",").map((item) => item.trim()).filter(Boolean);
    }
  }
  return [];
}

function omitMetadata(metadata: Record<string, unknown>, keys: string[]) {
  const omitted = new Set(keys);
  return Object.fromEntries(
    Object.entries(metadata).filter((entry) => !omitted.has(entry[0])),
  );
}

function formatMetadataValue(value: unknown): ReactNode {
  if (value == null || value === "") return "-";
  if (Array.isArray(value)) return value.map(formatLabel).join(", ");
  if (typeof value === "object") {
    return (
      <code className="whitespace-pre-wrap break-words rounded bg-white/70 px-1 py-0.5 text-xs text-slate-600">
        {JSON.stringify(value)}
      </code>
    );
  }
  return formatLabel(value);
}

function sameLabel(left: unknown, right: unknown) {
  return formatLabel(left).toLowerCase() === formatLabel(right).toLowerCase();
}

function uniqueLabels(values: unknown[]) {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const value of values) {
    const label = formatLabel(value);
    if (label === "-" || seen.has(label.toLowerCase())) continue;
    seen.add(label.toLowerCase());
    result.push(String(value));
  }
  return result;
}

function candidateKey(candidate: DiscoveryCandidate) {
  return [
    candidate.candidate_id || "",
    candidate.formula,
    candidate.evidence_level || "",
    candidate.checker_status || "",
    candidate.dossier_url || "",
  ].join("|");
}
