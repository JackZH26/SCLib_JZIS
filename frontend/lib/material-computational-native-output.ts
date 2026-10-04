import snapshot from "@/public/research-pilots/materials-computational-native-output-2026-10-02.json";

export type ComputationalNativeOutput = typeof snapshot;
export const computationalNativeOutputMetadataPath = `${process.env.NEXT_PUBLIC_BASE_PATH || ""}/research-pilots/materials-computational-native-output-2026-10-02.json`;
export const computationalNativeOutputSnapshotSha256 = "c75feec9feb891322eb007604f02d121d1d8a2ce72d010cc9d1ae94e37b14906";
export const computationalNativeOutputSourceSha256 = "09b0088b66057f364ae436c6e6d15621572408aede91e19ae0b5ce1594f99d5e";

const row = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
function matchesSnapshot(value: unknown, expected: unknown, depth = 0): boolean {
  if (depth > 20) return false;
  if (expected === null || typeof expected !== "object") return value === expected
    && (typeof value !== "number" || Number.isFinite(value)) && (typeof value !== "string" || value.length <= 2048);
  if (Array.isArray(expected)) return Array.isArray(value) && value.length === expected.length && value.length <= 64
    && value.every((item, index) => matchesSnapshot(item, expected[index], depth + 1));
  if (!row(value) || !row(expected)) return false;
  const keys = Object.keys(expected);
  return keys.length <= 40 && Object.keys(value).length === keys.length
    && keys.every(key => Object.hasOwn(value, key) && matchesSnapshot(value[key], expected[key], depth + 1));
}

/** Accept only the inspected source projection. File completeness grants no scientific authority. */
export function loadComputationalNativeOutput(value: unknown = snapshot): ComputationalNativeOutput | null {
  if (!row(value) || value.version !== "materials-computational-native-output/1.0.0" || !matchesSnapshot(value, snapshot)) return null;
  const data = value as ComputationalNativeOutput;
  if (data.reference.entry_id !== "0dTJ0oCkwgt1xEV8EcXKIV8k9Zjq"
    || data.reference.upload_id !== "5IvJz3uWTeu7Sgf197BSnw" || data.reference.formula !== "B2Cr"
    || data.reference.knowledge_origin !== "Computed"
    || Object.values(data.authority).some(flag => flag !== false && flag !== 0 && flag !== null)
    || data.native_source.source_sha256 !== computationalNativeOutputSourceSha256 || data.native_source.captured_bytes !== 3835451
    || data.native_source.complete_file_established !== true || data.native_source.HTTP_EOF_observed !== true
    || data.native_source.whole_XML_well_formed !== true || data.native_source.native_calculation_count !== 3
    || data.reported_final_geometry.atom_count !== 3 || data.reported_final_geometry.convergence_assessment !== null
    || data.native_energy_channels.corrected_energy !== null || data.native_energy_channels.mapping_status !== "deferred") return null;
  return data;
}

const publicSourceUrls = new Set([
  snapshot.reference.entry_url,
  "https://nomad-lab.eu/prod/v1/api/v1/entries/0dTJ0oCkwgt1xEV8EcXKIV8k9Zjq/raw/vasprun.xml",
  "https://vasp.at/wiki/Vasprun.xml",
]);
export function computationalNativeOutputHref(value: unknown): string | null {
  if (typeof value !== "string" || !publicSourceUrls.has(value)) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password && !url.port ? url.href : null;
  } catch { return null; }
}
