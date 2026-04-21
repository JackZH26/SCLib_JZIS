"use client";

/**
 * Today / week / all-time counters for the Overview tab.
 *
 * All three numbers are read from /auth/usage in one call; this
 * component just lays them out. Today also renders a progress bar
 * against the daily_limit cap (currently 999).
 */
import type { UsageStats } from "@/lib/api";

export function UsageStatsCard({ stats }: { stats: UsageStats }) {
  const pct = Math.min(100, (stats.today_used / Math.max(1, stats.daily_limit)) * 100);
  // Red past 90% so the user notices approaching the hard cap.
  const barTone =
    pct >= 90 ? "bg-red-500" : pct >= 60 ? "bg-amber-400" : "bg-accent";

  return (
    <section className="rounded-lg border border-sage-border bg-white p-5 shadow-sage">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-sage-tertiary">
        Query usage
      </h2>
      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat
          label="Today"
          value={stats.today_used.toLocaleString()}
          sub={`of ${stats.daily_limit.toLocaleString()} (${stats.today_remaining.toLocaleString()} left)`}
        />
        <Stat label="Last 7 days" value={stats.week_used.toLocaleString()} />
        <Stat
          label="All time"
          value={stats.all_time_used.toLocaleString()}
          sub="via API keys"
        />
      </div>
      <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
        <div
          className={`h-full ${barTone} transition-all`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="mt-2 text-xs text-sage-tertiary">
        Quota resets at 00:00 UTC. Data queries (search / ask) count toward
        the daily cap; browsing materials and papers is free.
      </p>
    </section>
  );
}

function Stat({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-sage-tertiary">
        {label}
      </p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-sage-ink">
        {value}
      </p>
      {sub ? <p className="text-xs text-sage-muted">{sub}</p> : null}
    </div>
  );
}
