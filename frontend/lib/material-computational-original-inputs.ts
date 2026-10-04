import frozenSnapshot from "@/public/research-pilots/materials-computational-original-inputs-2026-10-04.json";

export type ComputationalOriginalInputs = typeof frozenSnapshot;
export type OriginalInputLine = ComputationalOriginalInputs["incar_controls"][number]["source_line"];
export const computationalOriginalInputsMetadataPath = `${process.env.NEXT_PUBLIC_BASE_PATH || ""}/research-pilots/materials-computational-original-inputs-2026-10-04.json`;
export const computationalOriginalInputsSnapshotSha256 = "f9fda0493391c90fef13c5d6d4b73bfc66cfc3452757cc4f9224726b7662cb8f";

const expected: ComputationalOriginalInputs = JSON.parse(JSON.stringify(frozenSnapshot));
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

/** The inspected directory-file projection grants no effective-control, experiment or execution authority. */
export function loadComputationalOriginalInputs(value: unknown = expected): ComputationalOriginalInputs | null {
  try {
    if (!row(value) || !matches(value, expected)) return null;
    const data = value as ComputationalOriginalInputs;
    if (data.version !== "materials-computational-original-inputs/1.0.0" || data.status !== "source_qualified_reference"
      || data.reference.entry_id !== "0dTJ0oCkwgt1xEV8EcXKIV8k9Zjq" || data.reference.formula !== "B2Cr"
      || data.reference.knowledge_origin !== "Computed" || data.source_files.length !== 3
      || data.counts.recovered_original_input_file_count !== 3 || data.counts.original_INCAR_control_count !== 19
      || data.counts.independent_computed_entry_count !== 1 || data.counts.independent_experiment_count_established !== false
      || data.counts.formal_material_property_additions !== 0 || data.incar_controls.length !== 19
      || new Set(data.incar_controls.map(control => control.tag)).size !== 19
      || data.incar_controls.some(control => control.native_unit !== null || control.normalized_value !== null)
      || data.source_files.some(file => file.HTTP_status !== 200 || file.complete_body !== true
        || file.raw_body_redistributed !== false || file.directory_size_matches_capture !== true)
      || data.provider_inventory.provider_absence_claim !== false || data.poscar.native_explicit_physical_unit !== null
      || data.frozen_XML_comparison.source_sha256 !== "09b0088b66057f364ae436c6e6d15621572408aede91e19ae0b5ce1594f99d5e"
      || Object.values(data.authority).some(flag => flag !== false && flag !== 0 && flag !== null)) return null;
    return JSON.parse(JSON.stringify(data)) as ComputationalOriginalInputs;
  } catch { return null; }
}

const sourceUrls = new Set([
  ...expected.source_files.map(file => file.source_url), expected.provider_inventory.source_url,
  expected.file_relationship_scope.documentation_url, ...expected.format_annotations.map(annotation => annotation.url),
]);
export function computationalOriginalInputsHref(value: unknown): string | null {
  if (typeof value !== "string" || !sourceUrls.has(value)) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password && !url.port ? url.href : null;
  } catch { return null; }
}
