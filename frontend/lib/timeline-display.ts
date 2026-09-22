import type { TimelinePoint } from "@/lib/api";
import { recordClassification } from "@/lib/result-semantics";

/** Escape all source-owned strings before handing them to Plotly's HTML parser. */
export function escapePlotlyHtml(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]!);
}

/** Display-only formatting: preserve a nonzero sub-kelvin result as nonzero. */
export function formatTimelineTc(kelvin: number): string {
  if (!Number.isFinite(kelvin)) return "Unknown Tc";
  const number = new Intl.NumberFormat("en-US", { maximumSignificantDigits: 6 });
  return kelvin > 0 && kelvin < 1
    ? `${number.format(kelvin)} K (${number.format(kelvin * 1000)} mK)`
    : `${number.format(kelvin)} K`;
}

function canonical(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "null";
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  const source = value as Record<string, unknown>;
  return `{${Object.keys(source).sort().map(key => `${JSON.stringify(key)}:${canonical(source[key])}`).join(",")}}`;
}

export function timelinePointKey(point: TimelinePoint): string {
  // A source-provided identity is preferred; legacy fallback is a display key only.
  return `${point.point_id ?? point.result_metadata?.result_id ?? "legacy-display"}:${canonical(point)}`;
}

export function sortedTimelinePoints(points: TimelinePoint[]): TimelinePoint[] {
  return points.map(point => ({ point, key: timelinePointKey(point) }))
    .sort((left, right) => left.point.year - right.point.year || left.point.tc_kelvin - right.point.tc_kelvin || left.key.localeCompare(right.key, "en"))
    .map(({ point }) => point);
}

export function timelineOrigin(point: TimelinePoint): string {
  const classification = recordClassification({ result_classification: point });
  return classification.origin === "Unknown" || classification.status !== "resolved" || classification.role === "conflicted"
    ? "Unknown / conflict" : classification.origin;
}

export function timelineYearBasis(point: TimelinePoint): string {
  return (point.result_metadata?.year_basis ?? "year basis unavailable").replaceAll("_", " ");
}

export interface TimelineDisplayCluster {
  id: string;
  year: number;
  tc_kelvin: number;
  members: TimelinePoint[];
  sourceCount: number;
  family: string;
  origin: string;
}

/** Exact chart-coordinate overlap only: never a scientific identity or deduplication. */
export function clusterTimelinePoints(points: TimelinePoint[]): TimelineDisplayCluster[] {
  const grouped = new Map<string, TimelinePoint[]>();
  for (const point of sortedTimelinePoints(points)) {
    const key = JSON.stringify([point.year, point.tc_kelvin]);
    const members = grouped.get(key);
    if (members) members.push(point);
    else grouped.set(key, [point]);
  }
  return Array.from(grouped, ([id, members]) => {
    const families = new Set(members.map(point => point.family ?? "unknown"));
    const origins = new Set(members.map(timelineOrigin));
    return { id, year: members[0].year, tc_kelvin: members[0].tc_kelvin, members,
      sourceCount: new Set(members.map(point => point.paper_id).filter(Boolean)).size,
      family: families.size === 1 ? [...families][0] : "mixed",
      origin: origins.size === 1 ? [...origins][0] : "Mixed origins",
    };
  });
}

/** Explicit renderer budget, not a representative or statistical sample. */
export function timelineRenderBudget(clusters: TimelineDisplayCluster[], renderer: string, limit: number): TimelineDisplayCluster[] {
  return renderer === "svg" ? clusters.slice(0, limit) : clusters;
}
