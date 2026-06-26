import { getDiscovery, type DiscoveryCandidate } from "@/lib/api";

export default async function DiscoveryPage() {
  const feed = await getDiscovery().catch(() => null);
  if (!feed) {
    return <p className="text-sm text-red-600">Failed to load discovery preview.</p>;
  }

  return (
    <main className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Discovery preview</h1>
          <p className="mt-1 text-sm text-slate-600">
            Last updated {new Date(feed.updated_at).toLocaleString()}
          </p>
        </div>
        <div className="rounded-lg border border-sage-border bg-white px-4 py-3 text-sm">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Mode
          </span>
          <div className="mt-1 font-semibold text-sage-ink">
            {feed.standard.mode} · {feed.status}
          </div>
        </div>
      </div>

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Visible candidates" value={feed.candidates.length.toString()} />
        <Metric label="Minimum evidence" value={feed.standard.minimum_evidence_level} />
        <Metric
          label="Checker status"
          value={feed.standard.accepted_checker_statuses.join(" / ")}
        />
        <Metric label="Dossier" value={feed.standard.dossier_required ? "required" : "optional"} />
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
          <div className="overflow-x-auto rounded-lg border border-sage-border bg-white">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-3 text-left font-medium">Material</th>
                  <th className="px-4 py-3 text-right font-medium">Tc (K)</th>
                  <th className="px-4 py-3 text-right font-medium">P (GPa)</th>
                  <th className="px-4 py-3 text-left font-medium">Evidence</th>
                  <th className="px-4 py-3 text-left font-medium">Checker</th>
                  <th className="px-4 py-3 text-left font-medium">Dossier</th>
                  <th className="px-4 py-3 text-left font-medium">Summary</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {feed.candidates.map((candidate) => (
                  <CandidateRow key={candidateKey(candidate)} candidate={candidate} />
                ))}
              </tbody>
            </table>
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

function CandidateRow({ candidate }: { candidate: DiscoveryCandidate }) {
  return (
    <tr className="hover:bg-slate-50">
      <td className="px-4 py-3 font-semibold text-sage-ink">
        {candidate.name || candidate.formula}
        {candidate.name && candidate.name !== candidate.formula && (
          <span className="ml-2 font-normal text-slate-500">{candidate.formula}</span>
        )}
        {candidate.family && (
          <span className="ml-2 rounded-full border border-sage-border px-2 py-0.5 text-[11px] font-medium text-slate-500">
            {candidate.family}
          </span>
        )}
      </td>
      <td className="px-4 py-3 text-right tabular-nums text-slate-600">
        {formatNumber(candidate.tc_kelvin)}
      </td>
      <td className="px-4 py-3 text-right tabular-nums text-slate-600">
        {formatNumber(candidate.pressure_gpa)}
      </td>
      <td className="px-4 py-3 text-slate-600">{candidate.evidence_level || "-"}</td>
      <td className="px-4 py-3 text-slate-600">{candidate.checker_status || "-"}</td>
      <td className="px-4 py-3">
        {candidate.dossier_url ? (
          <a
            href={candidate.dossier_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent hover:text-accent-deep hover:underline"
          >
            dossier
          </a>
        ) : (
          <span className="text-slate-500">-</span>
        )}
      </td>
      <td className="max-w-md px-4 py-3 text-slate-600">
        {candidate.summary || candidate.source || "-"}
      </td>
    </tr>
  );
}

function formatNumber(value: number | null) {
  return value == null ? "-" : value.toLocaleString(undefined, { maximumFractionDigits: 1 });
}

function candidateKey(candidate: DiscoveryCandidate) {
  return [
    candidate.formula,
    candidate.evidence_level || "",
    candidate.checker_status || "",
    candidate.dossier_url || "",
  ].join("|");
}
