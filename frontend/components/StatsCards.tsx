/**
 * Four-up card row for the landing / stats pages: papers, materials,
 * chunks, and last-ingest timestamp. Pure presentational.
 */
import type { StatsResponse } from "@/lib/api";

function Card({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className="mt-2 text-3xl font-semibold text-slate-900">{value}</div>
      {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

export function StatsCards({ stats }: { stats: StatsResponse }) {
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      <Card label="Papers" value={stats.total_papers.toLocaleString()} />
      <Card label="Materials" value={stats.total_materials.toLocaleString()} />
      <Card label="Chunks" value={stats.total_chunks.toLocaleString()} />
      <Card
        label="Last ingest"
        value={stats.last_ingest_at ? relativeTime(stats.last_ingest_at) : "—"}
        sub={stats.last_ingest_at ?? "never"}
      />
    </div>
  );
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const now = Date.now();
  const s = Math.max(0, Math.round((now - then) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}
