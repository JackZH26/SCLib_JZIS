"use client";

/**
 * /dashboard/admin/audit — admin-only data audit dashboard.
 *
 * Two stacked panels:
 *   1. Last-night summary + per-rule report timeline
 *   2. Review queue: every flagged material, with Override / Confirm
 *      actions that record an admin_decision so the nightly job
 *      respects the call.
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import {
  ApiError,
  adminAuditQueue,
  adminConfirmFlag,
  adminListAuditReports,
  adminOverview,
  adminOverrideFlag,
  type AdminOverview,
  type AuditQueueItem,
  type AuditReportSummary,
} from "@/lib/api";
import { loadToken } from "@/lib/auth-storage";
import { useDashboardUser } from "@/components/dashboard/user-context";

const PAGE_SIZE = 50;

export default function AdminAuditPage() {
  const { user } = useDashboardUser();
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [reports, setReports] = useState<AuditReportSummary[]>([]);
  const [queue, setQueue] = useState<AuditQueueItem[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [ruleFilter, setRuleFilter] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [acting, setActing] = useState<string | null>(null);

  const load = useCallback(async () => {
    const token = loadToken();
    if (!token) return;
    try {
      const [ov, rep, q] = await Promise.all([
        adminOverview(token),
        adminListAuditReports(token),
        adminAuditQueue(token, {
          rule: ruleFilter || undefined,
          limit: PAGE_SIZE,
          offset,
        }),
      ]);
      setOverview(ov);
      setReports(rep);
      setQueue(q.results);
      setTotal(q.total);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load");
    }
  }, [ruleFilter, offset]);

  useEffect(() => { load(); }, [load]);

  if (!user.is_admin && !user.is_reviewer) {
    return <p className="text-sm text-red-700">Reviewer or admin access required.</p>;
  }

  async function act(
    kind: "override" | "confirm" | "approve",
    item: AuditQueueItem,
  ) {
    const token = loadToken();
    if (!token) return;
    let note: string;
    if (kind === "approve") {
      // Quick path: one-click "this material is fine, restore". The
      // backend stores the auto-note + reviewer + timestamp in
      // materials.admin_decision so we still have provenance.
      note = `approved: ${item.review_reason ?? "n/a"} verified valid by admin`;
    } else {
      const prompted = window.prompt(
        kind === "override"
          ? `Override flag on ${item.formula}? Add a short justification:`
          : `Confirm the flag on ${item.formula} after review. Add notes:`,
      );
      if (!prompted || !prompted.trim()) return;
      note = prompted.trim();
    }
    setActing(item.id);
    setError(null);
    try {
      if (kind === "approve" || kind === "override") {
        await adminOverrideFlag(token, item.id, note);
      } else {
        await adminConfirmFlag(token, item.id, note);
      }
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed");
    } finally {
      setActing(null);
    }
  }

  // Distinct rule names from the latest report run, for filter dropdown.
  const knownRules = Array.from(
    new Set([
      ...reports.map((r) => r.rule_name),
      ...Object.keys(overview?.flagged_by_reason ?? {}),
    ]),
  ).sort();

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-sage-ink">Data audit</h2>
        <p className="mt-1 text-sm text-sage-muted">
          Nightly data audit ran most recently at{" "}
          <strong>{overview?.last_audit_started ?? "—"}</strong> and flagged{" "}
          <strong>{overview?.last_audit_total_flagged ?? 0}</strong> new rows.
          Review queue size: <strong>{overview?.flagged_materials ?? 0}</strong>.
        </p>
      </div>

      {error && (
        <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
      )}

      <section className="rounded-lg border border-sage-border bg-white p-5 shadow-sage">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-sage-tertiary">
          Flagged-by-reason snapshot
        </h3>
        {overview && (
          <div className="mt-3 grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
            {Object.entries(overview.flagged_by_reason)
              .sort((a, b) => b[1] - a[1])
              .map(([reason, n]) => (
                <button
                  key={reason}
                  onClick={() => { setRuleFilter(reason); setOffset(0); }}
                  className={[
                    "flex items-center justify-between rounded-md border px-3 py-1.5 text-left transition-colors",
                    ruleFilter === reason
                      ? "border-accent bg-[rgba(58,125,92,0.08)] text-accent-deep"
                      : "border-sage-border bg-white text-sage-muted hover:border-accent-light",
                  ].join(" ")}
                >
                  <code className="font-mono text-xs">{reason}</code>
                  <span className="font-semibold tabular-nums">{n.toLocaleString()}</span>
                </button>
              ))}
          </div>
        )}
        {ruleFilter && (
          <button
            onClick={() => { setRuleFilter(""); setOffset(0); }}
            className="mt-3 text-xs text-sage-tertiary hover:text-accent-deep"
          >Clear filter</button>
        )}
      </section>

      <section className="rounded-lg border border-sage-border bg-white p-5 shadow-sage">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-sage-tertiary">
          Recent audit runs
        </h3>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-sage-tertiary">
              <tr>
                <th className="px-3 py-1.5 text-left font-medium">When</th>
                <th className="px-3 py-1.5 text-left font-medium">Rule</th>
                <th className="px-3 py-1.5 text-left font-medium">Severity</th>
                <th className="px-3 py-1.5 text-right font-medium">Flagged</th>
                <th className="px-3 py-1.5 text-right font-medium">Δ vs prev</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {reports.slice(0, 30).map((r) => (
                <tr key={r.id}>
                  <td className="px-3 py-1.5 text-sage-muted">{r.started_at.replace("T", " ").slice(0, 16)}</td>
                  <td className="px-3 py-1.5 font-mono text-xs">{r.rule_name}</td>
                  <td className="px-3 py-1.5">
                    <span className={[
                      "rounded-full px-2 py-0.5 text-xs font-medium",
                      r.severity === "critical" ? "bg-red-50 text-red-700"
                      : r.severity === "warn"   ? "bg-amber-50 text-amber-800"
                                                : "bg-slate-100 text-slate-700",
                    ].join(" ")}>{r.severity}</span>
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-sage-ink">{r.rows_flagged}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-sage-muted">
                    {r.delta_vs_previous == null ? "—" : (r.delta_vs_previous > 0 ? `+${r.delta_vs_previous}` : r.delta_vs_previous)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-sage-tertiary">
          Review queue
          {ruleFilter && (
            <span className="ml-2 font-normal text-sage-muted">
              · filtered by <code className="font-mono">{ruleFilter}</code>
            </span>
          )}
        </h3>
        <div className="overflow-x-auto rounded-lg border border-sage-border bg-white shadow-sage">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-sage-tertiary">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Material</th>
                <th className="px-2 py-2 text-left font-medium">Family</th>
                <th className="px-2 py-2 text-right font-medium">Tc</th>
                <th className="px-2 py-2 text-right font-medium">Papers</th>
                <th className="px-2 py-2 text-left font-medium">Reason</th>
                <th className="px-2 py-2 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {queue.map((m) => (
                <tr key={m.id}>
                  <td className="px-3 py-2">
                    <Link
                      href={`/materials/${encodeURIComponent(m.id)}`}
                      target="_blank"
                      className="block max-w-[12rem] truncate font-medium text-sage-ink hover:underline"
                      title={m.formula}
                    >
                      {m.formula}
                    </Link>
                  </td>
                  <td className="px-2 py-2 text-xs text-sage-muted">{m.family ?? "—"}</td>
                  <td className="px-2 py-2 text-right tabular-nums text-sage-ink">
                    {m.tc_max == null ? "—" : m.tc_max.toFixed(1)}
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums text-sage-muted">{m.total_papers}</td>
                  <td className="px-2 py-2">
                    <span
                      title={m.review_reason ?? ""}
                      className="inline-block max-w-[10rem] truncate rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-800 align-middle"
                    >
                      {shortReason(m.review_reason)}
                    </span>
                    {m.has_admin_decision && (
                      <span className="ml-1 rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-700">
                        prior
                      </span>
                    )}
                  </td>
                  <td className="px-2 py-2 text-right">
                    <div className="inline-flex gap-1">
                      <button
                        onClick={() => act("approve", m)}
                        disabled={acting === m.id}
                        title="One-click: clear the flag with an auto-generated note. The material reappears on /materials immediately."
                        className="rounded-md border border-accent bg-[rgba(58,125,92,0.08)] px-2 py-1 text-xs font-medium text-accent-deep hover:bg-[rgba(58,125,92,0.18)] disabled:opacity-60"
                      >✓ Pass</button>
                      <button
                        onClick={() => act("override", m)}
                        disabled={acting === m.id}
                        title="Clear the flag with a custom note (will prompt)."
                        className="rounded-md border border-sage-border bg-white px-2 py-1 text-xs text-accent-deep hover:bg-[rgba(58,125,92,0.08)] disabled:opacity-60"
                      >Edit…</button>
                      <button
                        onClick={() => act("confirm", m)}
                        disabled={acting === m.id}
                        title="Keep the flag (the row stays hidden) but record that an admin has reviewed it."
                        className="rounded-md border border-sage-border bg-white px-2 py-1 text-xs text-sage-muted hover:bg-slate-50 disabled:opacity-60"
                      >Hold…</button>
                    </div>
                  </td>
                </tr>
              ))}
              {queue.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-sage-muted">
                    No flagged materials{ruleFilter ? " for this rule" : ""}.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {total > PAGE_SIZE && (
          <div className="mt-3 flex items-center justify-between text-xs text-sage-muted">
            <span>
              {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
            </span>
            <div className="flex gap-2">
              <button
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                disabled={offset === 0}
                className="rounded-md border border-sage-border bg-white px-3 py-1 hover:bg-slate-50 disabled:opacity-50"
              >‹ Prev</button>
              <button
                onClick={() => setOffset(offset + PAGE_SIZE)}
                disabled={offset + PAGE_SIZE >= total}
                className="rounded-md border border-sage-border bg-white px-3 py-1 hover:bg-slate-50 disabled:opacity-50"
              >Next ›</button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

// Map review_reason snake_case to a short human-readable label for the
// queue's Reason column. Full string stays in the title attribute so a
// hover surfaces the canonical name.
const REASON_LABELS: Record<string, string> = {
  tc_max_exceeds_250K:                "Tc > 250 K",
  tc_exceeds_family_cap:              "Tc > family cap",
  tc_at_ambient_above_record:         "ambient > record",
  ambient_sc_with_high_pressure:      "ambient + P>0",
  implausible_pressure:               "P out of range",
  hydride_low_pressure_high_tc:       "hydride low-P high-Tc",
  citation_conflation_review_paper:   "citation conflation",
  family_unconv_contradiction:        "family vs unconv",
  sole_source_retracted:              "all sources retracted",
  ner_extracted_descriptive_text:     "NER caught text not formula",
  english_element_name:               "English element name",
  system_designator_not_compound:     "system, not compound",
  phase_prefix_in_formula:            "space-group prefix",
  incomplete_or_charged_formula:      "incomplete/charged",
  fulleride_tc_implausible_schon_era: "Schön fraud era",
  cnt_tc_ner_hallucination:           "CNT NER hallucination",
};

function shortReason(reason: string | null): string {
  if (!reason) return "—";
  return REASON_LABELS[reason] ?? reason;
}
