"use client";

/**
 * /dashboard — Overview tab.
 *
 * Default landing page after login. Two cards: editable Profile
 * (view/edit toggle → PATCH /auth/me) and Usage Stats (today / week /
 * all-time with a progress bar toward the 999/day cap). The dashboard
 * shell's auth guard has already resolved the token by the time this
 * page mounts, so we can assume a valid JWT is in localStorage.
 */
import { useEffect, useState } from "react";

import { getUsage, me, type UsageStats, type User } from "@/lib/api";
import { loadToken } from "@/lib/auth-storage";
import { ProfileCard } from "@/components/dashboard/ProfileCard";
import { UsageStatsCard } from "@/components/dashboard/UsageStats";

export default function OverviewPage() {
  const [user, setUser] = useState<User | null>(null);
  const [usage, setUsage] = useState<UsageStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = loadToken();
    if (!token) return;
    // Fetch both in parallel — they hit different endpoints and don't
    // depend on each other.
    Promise.all([me(token), getUsage(token)])
      .then(([u, us]) => {
        setUser(u);
        setUsage(us);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Failed to load overview");
      });
  }, []);

  if (error) {
    return <p className="text-sm text-red-700">{error}</p>;
  }
  if (!user || !usage) {
    return <p className="text-sm text-sage-muted">Loading overview…</p>;
  }

  return (
    <div className="space-y-6">
      <ProfileCard user={user} onUpdated={setUser} />
      <UsageStatsCard stats={usage} />
    </div>
  );
}
