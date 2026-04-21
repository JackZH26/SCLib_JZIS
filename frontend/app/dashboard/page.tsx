"use client";

/**
 * /dashboard — Overview tab.
 *
 * Reads the user from the DashboardUserProvider in layout.tsx
 * instead of calling /auth/me again, so switching between tabs
 * doesn't fire a redundant network round-trip. Only /auth/usage is
 * fetched here (it's tab-specific). The profile edit flow pushes
 * updates back via setUser so the shell header also refreshes.
 */
import { useEffect, useState } from "react";

import { getUsage, type UsageStats } from "@/lib/api";
import { loadToken } from "@/lib/auth-storage";
import { ProfileCard } from "@/components/dashboard/ProfileCard";
import { UsageStatsCard } from "@/components/dashboard/UsageStats";
import { useDashboardUser } from "@/components/dashboard/user-context";

export default function OverviewPage() {
  const { user, setUser } = useDashboardUser();
  const [usage, setUsage] = useState<UsageStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = loadToken();
    if (!token) return;
    getUsage(token)
      .then(setUsage)
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Failed to load usage");
      });
  }, []);

  if (error) {
    return <p className="text-sm text-red-700">{error}</p>;
  }
  if (!usage) {
    return <p className="text-sm text-sage-muted">Loading usage…</p>;
  }

  return (
    <div className="space-y-6">
      <ProfileCard user={user} onUpdated={setUser} />
      <UsageStatsCard stats={usage} />
    </div>
  );
}
