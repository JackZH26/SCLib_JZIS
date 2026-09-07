"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { useDashboardUser } from "@/components/dashboard/user-context";
import { adminBackgroundJobs, ApiError, type BackgroundCycle, type BackgroundJobStatus, type BackgroundJobsResponse } from "@/lib/api";

const LABELS: Record<BackgroundJobStatus["job_name"], string> = {
  stats_refresh: "Dashboard statistics", timeline_projection: "Timeline projection",
  formula_audit: "Formula audit", nightly_audit: "Nightly data audit", ask_history_prune: "Ask history retention",
};
const COUNTERS: Record<string, string> = {
  total_papers: "papers", total_materials: "materials", total_chunks: "chunks",
  materials_processed: "materials processed", active_materials: "active materials", active_points: "active points",
  flagged: "newly flagged", rule_count: "rules", deleted: "history rows removed",
};

function time(value: string | null | undefined): string {
  if (!value) return "Not recorded";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Unavailable" : new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium", timeStyle: "medium", timeZone: "UTC",
  }).format(date);
}

function duration(value: number | null | undefined): string {
  return value == null ? "Not recorded" : `${(value / 1000).toLocaleString("en-US", { maximumFractionDigits: 2 })} s`;
}

function state(job: BackgroundJobStatus): string {
  if (job.oldest_unfinished?.status === "running") return job.active_owner_id ? "Running" : "Interrupted / no owner observed";
  if (job.oldest_unfinished?.status === "failed") return "Failed · retry pending";
  return job.last_success ? "Succeeded" : "Not run";
}

function counters(job: BackgroundJobStatus, cycle: BackgroundCycle | null): string {
  if (!cycle || cycle.status !== "succeeded") return "No committed result counters";
  if (job.job_name === "nightly_audit") {
    const counts = Object.values(cycle.result).filter((value): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0);
    return `${counts.length.toLocaleString("en-US")} rules · ${counts.reduce((sum, value) => sum + value, 0).toLocaleString("en-US")} summed rule matches (not distinct materials)`;
  }
  return Object.entries(COUNTERS).flatMap(([key, label]) => {
    const value = cycle.result[key];
    return typeof value === "number" && Number.isFinite(value) ? [`${value.toLocaleString("en-US")} ${label}`] : [];
  }).join(" · ") || "No result counters";
}

export default function BackgroundJobsPage() {
  const { user } = useDashboardUser();
  const [data, setData] = useState<BackgroundJobsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const requestVersion = useRef(0);

  const load = useCallback(async () => {
    if (!user.is_admin) return;
    const current = ++requestVersion.current;
    setLoading(true); setError(null); setData(null);
    try {
      const result = await adminBackgroundJobs();
      if (current === requestVersion.current) setData(result);
    } catch (err) {
      if (current === requestVersion.current) setError(err instanceof ApiError && err.status === 403
        ? "Administrator access required." : "Background job status is unavailable. Try again later.");
    } finally {
      if (current === requestVersion.current) setLoading(false);
    }
  }, [user.is_admin]);

  useEffect(() => { void load(); return () => { requestVersion.current += 1; }; }, [load]);

  if (!user.is_admin) return <p role="alert" className="text-sm text-red-700">Administrator access required.</p>;

  return <div className="space-y-5">
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 className="text-lg font-semibold text-sage-ink">Background jobs</h2>
        <p className="mt-1 text-sm text-sage-muted">Shared PostgreSQL cycles across API replicas. All times are UTC.</p>
        <Link href="/dashboard/admin/audit" className="text-sm text-accent-deep underline">Back to data audit</Link>
      </div>
      <button type="button" onClick={() => void load()} disabled={loading}
        className="rounded border border-sage-border px-3 py-2 text-sm disabled:opacity-50">
        {loading ? "Refreshing…" : "Refresh status"}
      </button>
    </header>
    <p className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
      Success confirms committed database effects only, not external cache delivery or scientific acceptance.
      Owner visibility is a point-in-time PostgreSQL lock observation, not a heartbeat or a guarantee that a process remains alive.
      Interrupted cycles can be recovered by a later owner; failed cycles retain their retry state.
    </p>
    {loading && <p role="status" className="text-sm text-sage-muted">Loading current job status…</p>}
    {error && <p role="alert" className="rounded bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    {data && <>
      <div className="overflow-x-auto rounded border border-sage-border bg-white">
        <table className="min-w-full text-left text-sm">
          <caption className="sr-only">Background job coordination and committed database results</caption>
          <thead className="bg-slate-50 text-xs text-sage-muted"><tr>
            {["Job", "Current state", "Last successful cycle (UTC)", "Oldest unfinished cycle (UTC)", "Attempts / duration"].map(label => <th key={label} scope="col" className="px-3 py-3">{label}</th>)}
          </tr></thead>
          <tbody className="divide-y divide-sage-border">{data.jobs.map(job => {
            const current = job.oldest_unfinished ?? job.recent_cycles[0];
            return <tr key={job.job_name}>
              <th scope="row" className="px-3 py-3 font-medium">{LABELS[job.job_name]}</th>
              <td className="px-3 py-3">{state(job)}</td>
              <td className="px-3 py-3">{time(job.last_success?.scheduled_for)}</td>
              <td className="px-3 py-3">{time(job.oldest_unfinished?.scheduled_for)}</td>
              <td className="px-3 py-3 tabular-nums">{current ? `${current.attempts.toLocaleString("en-US")} / ${duration(current.duration_ms)}` : "Not recorded"}</td>
            </tr>;
          })}</tbody>
        </table>
      </div>
      <section aria-label="Job cycle details" className="space-y-3">{data.jobs.map(job => <details key={job.job_name} className="rounded border border-sage-border bg-white p-3">
        <summary className="cursor-pointer text-sm font-medium">{LABELS[job.job_name]} · cycle details</summary>
        <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
          <div><dt className="text-sage-muted">Owner lock observed</dt><dd className="break-all font-mono text-xs">{job.active_owner_id ?? "No active owner observed"}</dd></div>
          <div><dt className="text-sage-muted">Last successful completion (UTC)</dt><dd>{time(job.last_success?.completed_at)}</dd></div>
          <div><dt className="text-sage-muted">Last failure code</dt><dd>{job.oldest_unfinished?.error_code ?? "None recorded for unfinished work"}</dd></div>
          <div><dt className="text-sage-muted">Next retry eligible (UTC)</dt><dd>{time(job.oldest_unfinished?.next_retry_at)}</dd></div>
        </dl>
        <p className="mt-3 text-xs text-sage-muted">Last committed counters: {counters(job, job.last_success)}</p>
        {job.recent_cycles.length === 0 ? <p className="mt-3 text-sm">No cycles recorded yet. A disabled job does not create a cycle.</p> :
          <div className="mt-3 overflow-x-auto"><table className="min-w-full text-left text-xs">
            <caption className="sr-only">Recent {LABELS[job.job_name]} cycles</caption>
            <thead><tr>{["Scheduled (UTC)", "Stored status", "Attempts", "Duration", "Failure / retry (UTC)", "Cycle ID"].map(label => <th key={label} scope="col" className="px-2 py-2">{label}</th>)}</tr></thead>
            <tbody>{job.recent_cycles.map(cycle => <tr key={cycle.cycle_id} className="border-t border-sage-border">
              <td className="px-2 py-2">{time(cycle.scheduled_for)}</td><td className="px-2 py-2">{cycle.status}</td>
              <td className="px-2 py-2">{cycle.attempts.toLocaleString("en-US")}</td><td className="px-2 py-2">{duration(cycle.duration_ms)}</td>
              <td className="px-2 py-2">{cycle.error_code ?? "None"}{cycle.next_retry_at ? ` / ${time(cycle.next_retry_at)}` : ""}</td>
              <td className="break-all px-2 py-2 font-mono">{cycle.cycle_id}</td>
            </tr>)}</tbody>
          </table></div>}
      </details>)}</section>
    </>}
  </div>;
}
