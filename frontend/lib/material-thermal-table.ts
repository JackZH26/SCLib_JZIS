import rawTable from "@/public/research-pilots/materials-thermal-table-2026-10-05.json";

export type ThermalTable = typeof rawTable;
export type ThermalReading = ThermalTable["readings"][number];
export const thermalTableSnapshotSha256 = "461a1212c58e97c46eb734deaa38870753e65c89c9709442b312a091586e6891";
export function thermalTableDownloadPath() {
  return `${process.env.NEXT_PUBLIC_BASE_PATH || ""}/research-pilots/materials-thermal-table-2026-10-05.json`;
}

function matches(value: unknown, expected: unknown, depth = 0): boolean {
  if (depth > 12) return false;
  if (expected === null || typeof expected !== "object") return value === expected;
  if (Array.isArray(expected)) return Array.isArray(value) && value.length === expected.length
    && expected.every((entry, index) => matches(value[index], entry, depth + 1));
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const keys = Object.keys(expected);
  return Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key)
    && matches((value as Record<string, unknown>)[key], (expected as Record<string, unknown>)[key], depth + 1));
}

/** Read-only, finite source snapshot. It cannot establish a catalogue sample association. */
export function loadThermalTable(value: unknown = rawTable): ThermalTable | null {
  return matches(value, rawTable) ? JSON.parse(JSON.stringify(value)) as ThermalTable : null;
}
