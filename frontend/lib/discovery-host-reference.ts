import snapshot from "@/public/research-pilots/discovery-host-reference-2026-10-05.json";

export type HostReference = typeof snapshot;
export type HostReferenceRow = HostReference["rows"][number];
export const hostReferenceFilename = "discovery-host-reference-2026-10-05.json";
export const hostReferenceSha256 = "1d3ead91305af81948269ba975a920ce200fc51daf86a3e42c11c0241fd8b257";
export const HOST_REFERENCE_PAGE_SIZE = 12;

function equalFinite(value: unknown, expected: unknown, depth = 0): boolean {
  if (depth > 16) return false;
  if (expected === null || typeof expected !== "object") return value === expected;
  if (Array.isArray(expected)) return Array.isArray(value) && value.length === expected.length && value.length <= 184
    && value.every((item, index) => equalFinite(item, expected[index], depth + 1));
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const keys = Object.keys(expected);
  return Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key)
    && equalFinite((value as Record<string, unknown>)[key], (expected as Record<string, unknown>)[key], depth + 1));
}

/** This public reference is a finite snapshot, never a fallback for native scientific publication. */
export function loadHostReference(value: unknown = snapshot): HostReference | null {
  if (!equalFinite(value, snapshot)) return null;
  return JSON.parse(JSON.stringify(snapshot)) as HostReference;
}

export function hostReferenceAsset(filename: string) {
  const allowed = [hostReferenceFilename, snapshot.source.subset_filename];
  if (!allowed.some(name => filename === name || filename === `${name}.sha256`)) return null;
  return `${process.env.NEXT_PUBLIC_BASE_PATH || ""}/research-pilots/${filename}`;
}

export function filterHostReferences(reference: HostReference, family = "", formula = "") {
  return reference.rows.filter(row => (!family || row.family === family) && (!formula || row.formula === formula));
}

/** Fixed linear axes include every permitted source value; no score, jitter or imputation. */
export function hostReferencePoint(row: HostReferenceRow): { x: number; y: number } | null {
  if (!row.plottable || !Number.isFinite(row.formation_energy.value) || !Number.isFinite(row.band_gap.value)
    || row.formation_energy.value < -4 || row.formation_energy.value > 6 || row.band_gap.value < 0 || row.band_gap.value > 7) return null;
  return { x: 64 + (row.formation_energy.value + 4) / 10 * 492, y: 284 - row.band_gap.value / 7 * 252 };
}
