import snapshot from "@/public/research-pilots/materials-nb-cvs-pressure-2026-10-05.json";

export type NbCvsPressure = typeof snapshot;
export const nbCvsPressureSnapshotSha256 = "10386672eb701add2a070dcf2ff9d564ad6bd9b9e9aceb6ddee126d219e21a2e";
export function nbCvsPressureDownloadPath() {
  return `${process.env.NEXT_PUBLIC_BASE_PATH || ""}/research-pilots/materials-nb-cvs-pressure-2026-10-05.json`;
}

function matches(value: unknown, expected: unknown, depth = 0): boolean {
  if (depth > 16) return false;
  if (expected === null || typeof expected !== "object") return value === expected
    && (typeof value !== "number" || Number.isFinite(value));
  if (!value || typeof value !== "object") return false;
  if (Array.isArray(expected)) return Array.isArray(value)
    && Object.getPrototypeOf(value) === Array.prototype && value.length === expected.length
    && Reflect.ownKeys(value).length === value.length + 1
    && expected.every((entry, index) => {
      const descriptor = Object.getOwnPropertyDescriptor(value, index);
      return descriptor?.enumerable === true && "value" in descriptor && matches(descriptor.value, entry, depth + 1);
    });
  if (Array.isArray(value) || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) return false;
  const keys = Object.keys(expected);
  return Reflect.ownKeys(value).length === keys.length && keys.every(key => {
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    return descriptor?.enumerable === true && "value" in descriptor
      && matches(descriptor.value, (expected as Record<string, unknown>)[key], depth + 1);
  });
}

/** Finite source reference. Scientific review and result association are separate. */
export function loadNbCvsPressure(value: unknown = snapshot): NbCvsPressure | null {
  try { return matches(value, snapshot) ? JSON.parse(JSON.stringify(value)) as NbCvsPressure : null; }
  catch { return null; }
}
