"use client";

/**
 * Four-up card row for the landing / stats pages: papers, materials,
 * chunks, and last-ingest timestamp.
 *
 * The "last ingest" card shows a relative time ("3h ago") which
 * depends on the client's current wall clock. Computing that during
 * SSR would bake the server's clock into the HTML and trigger a
 * hydration mismatch when the client renders a different value a
 * few hundred ms later. We render a stable placeholder on the first
 * pass and swap in the relative string inside useEffect, after
 * hydration has finished.
 */
import { useEffect, useState } from "react";
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
  const [rel, setRel] = useState<string>(stats.last_ingest_at ? "…" : "—");

  useEffect(() => {
    if (!stats.last_ingest_at) return;
    const tick = () => setRel(relativeTime(stats.last_ingest_at!));
    tick();
    const id = setInterval(tick, 60_000);
    return () => clearInterval(id);
  }, [stats.last_ingest_at]);

  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      <Card label="Papers" value={stats.total_papers.toLocaleString()} />
      <Card label="Materials" value={stats.total_materials.toLocaleString()} />
      <Card label="Chunks" value={stats.total_chunks.toLocaleString()} />
      <Card
        label="Last ingest"
        value={rel}
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
