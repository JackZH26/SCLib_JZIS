import snapshot from "@/public/research-pilots/materials-yin3-source-context-2026-10-04.json";

export type Yin3SourceContext = typeof snapshot;
export const yin3SourceContextMetadataPath = `${process.env.NEXT_PUBLIC_BASE_PATH || ""}/research-pilots/materials-yin3-source-context-2026-10-04.json`;
export const yin3SourceContextSnapshotSha256 = "9abb585c9e867f7cccec951b1400babec0c5684e4f01fc98bb7122e472550d27";
const expected: Yin3SourceContext = JSON.parse(JSON.stringify(snapshot));
const row = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object"
  && !Array.isArray(value) && (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null);
function matches(value: unknown, baseline: unknown, depth = 0): boolean {
  if (depth > 20) return false;
  if (baseline === null || typeof baseline !== "object") return value === baseline
    && (typeof value !== "number" || Number.isFinite(value)) && (typeof value !== "string" || value.length <= 2048);
  if (Array.isArray(baseline)) return Array.isArray(value) && Object.getPrototypeOf(value) === Array.prototype
    && value.length === baseline.length && value.length <= 64 && Reflect.ownKeys(value).length === value.length + 1
    && baseline.every((item, index) => {
      const descriptor = Object.getOwnPropertyDescriptor(value, index);
      return descriptor?.enumerable === true && "value" in descriptor && matches(descriptor.value, item, depth + 1);
    });
  if (!row(value) || !row(baseline)) return false;
  const keys = Object.keys(baseline);
  return keys.length <= 64 && Reflect.ownKeys(value).length === keys.length && keys.every(key => {
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    return descriptor?.enumerable === true && "value" in descriptor && matches(descriptor.value, baseline[key], depth + 1);
  });
}

/** Source-qualified study context preserves separate samples, roles and retained-result identity. */
export function loadYin3SourceContext(value: unknown = expected): Yin3SourceContext | null {
  try {
    if (!row(value) || !matches(value, expected)) return null;
    const data = value as Yin3SourceContext;
    if (data.version !== "materials-yin3-source-context/1.0.0" || data.status !== "source_qualified_reference"
      || data.source.paper_id !== "arxiv:1112.3083" || data.source.edition !== "v1"
      || data.source.sha256 !== "10b8722eb2a7f8d8a7e41aa6b797ab2ffb8ed749e550522ec0a0de16c2248dc5"
      || data.observation_count !== 9 || data.observations.length !== 9 || data.source_locator_count !== 12
      || Object.keys(data.source_locators).length !== 12 || data.saved_catalogue_context.id !== "mat:yin3"
      || data.saved_catalogue_context.retained_raw_tc_kelvin !== 1.2 || data.saved_catalogue_context.sample_id !== null
      || data.saved_catalogue_context.state_id !== null || data.saved_catalogue_context.legacy_pressure_read_state !== "ambiguous"
      || data.classification.is_unconventional !== null || data.classification.classification_assigned !== null
      || Object.values(data.authority).some(flag => flag !== false && flag !== 0 && flag !== null)) return null;
    return JSON.parse(JSON.stringify(data)) as Yin3SourceContext;
  } catch { return null; }
}

const sourceUrls = new Set([expected.source.final_url, ...Object.values(expected.source_locators).map(locator => locator.source_url)]);
export function yin3SourceContextHref(value: unknown): string | null {
  if (typeof value !== "string" || !sourceUrls.has(value)) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password && !url.port ? url.href : null;
  } catch { return null; }
}
