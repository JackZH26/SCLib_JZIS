import { API_BASE, type StatsResponse } from "@/lib/api";

/** Public aggregates only. Never attach a user's cookie to the shared snapshot. */
export async function getLibrarySnapshot(): Promise<StatsResponse | null> {
  try {
    const response = await fetch(`${API_BASE}/stats`, {
      credentials: "omit",
      next: { revalidate: 300 },
      signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) return null;
    const stats = await response.json() as StatsResponse;
    if (![stats.total_papers, stats.total_materials].every(value => Number.isSafeInteger(value) && value >= 0)) return null;
    return stats;
  } catch {
    return null;
  }
}
