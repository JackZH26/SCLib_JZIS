import frozenSnapshot from "@/public/research-pilots/materials-computational-input-context-2026-10-04.json";

export type ComputationalInputContext = typeof frozenSnapshot;
export const computationalInputContextMetadataPath = `${process.env.NEXT_PUBLIC_BASE_PATH || ""}/research-pilots/materials-computational-input-context-2026-10-04.json`;
export const computationalInputContextSnapshotSha256 = "f041c7dc33bae709a52c88f253e96e420f90e1ff45a26de259df127a1ec075ad";
export const computationalInputContextSourceSha256 = "09b0088b66057f364ae436c6e6d15621572408aede91e19ae0b5ce1594f99d5e";

// Keep the validation baseline private so importing the JSON elsewhere cannot alter it.
const expectedSnapshot: ComputationalInputContext = JSON.parse(JSON.stringify(frozenSnapshot));
const row = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object"
  && !Array.isArray(value) && (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null);

function matchesSnapshot(value: unknown, expected: unknown, depth = 0): boolean {
  if (depth > 20) return false;
  if (expected === null || typeof expected !== "object") return value === expected
    && (typeof value !== "number" || Number.isFinite(value)) && (typeof value !== "string" || value.length <= 2048);
  if (Array.isArray(expected)) return Array.isArray(value) && Object.getPrototypeOf(value) === Array.prototype
    && value.length === expected.length && value.length <= 64 && Reflect.ownKeys(value).length === value.length + 1
    && expected.every((item, index) => {
      const descriptor = Object.getOwnPropertyDescriptor(value, index);
      return descriptor !== undefined && descriptor.enumerable === true && "value" in descriptor
        && matchesSnapshot(descriptor.value, item, depth + 1);
    });
  if (!row(value) || !row(expected)) return false;
  const keys = Object.keys(expected);
  return keys.length <= 40 && Reflect.ownKeys(value).length === keys.length && keys.every(key => {
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    return descriptor !== undefined && descriptor.enumerable === true && "value" in descriptor
      && matchesSnapshot(descriptor.value, expected[key], depth + 1);
  });
}

/** Only the inspected input projection is accepted; source inputs grant no result or execution authority. */
export function loadComputationalInputContext(value: unknown = expectedSnapshot): ComputationalInputContext | null {
  try {
    if (!row(value) || !matchesSnapshot(value, expectedSnapshot)) return null;
    const data = value as ComputationalInputContext;
    if (data.version !== "materials-computational-input-context/1.0.0" || data.status !== "source_qualified_reference"
      || data.reference.entry_id !== "0dTJ0oCkwgt1xEV8EcXKIV8k9Zjq" || data.reference.formula !== "B2Cr"
      || data.reference.knowledge_origin !== "Computed"
      || data.native_source.source_sha256 !== computationalInputContextSourceSha256 || data.native_source.source_bytes !== 3835451
      || data.counts.additional_tag_count !== 8 || data.counts.additional_occurrence_count !== 10
      || data.counts.combined_tag_count !== 25 || data.counts.combined_occurrence_count !== 36
      || data.counts.independent_computed_entry_count !== 1 || data.counts.independent_experiment_count_established !== false
      || data.counts.formal_material_property_additions !== 0
      || Object.values(data.authority).some(flag => flag !== false && flag !== 0 && flag !== null)
      || data.native_inputs.length !== 10 || new Set(data.native_inputs.map(input => input.native_tag)).size !== 8
      || data.native_inputs.some(input => input.unit !== null || input.normalized_value !== null
        || input.explicit_unit_attributes_in_element_or_ancestors.length !== 0)
      || data.native_inputs.filter(input => input.native_tag === "MAGMOM").some(input => input.declared_xml_type !== null)
      || data.native_inputs.find(input => input.native_tag === "GGA")?.raw_lexeme !== "--"
      || data.spin_components.length !== 3 || data.spin_components.some(input => input.unit !== null || input.normalized_value !== null)
      || data.documentation_annotations.some(annotation => annotation.documented_unit !== null
        || annotation.interpretation_role !== "current_manual_definition_annotation_not_native_runtime_proof"
        || annotation.source.raw_HTML_response_hash_established !== false)) return null;
    return JSON.parse(JSON.stringify(data)) as ComputationalInputContext;
  } catch { return null; }
}

const publicSourceUrls = new Set([
  expectedSnapshot.native_source.native_XML_url,
  "https://nomad-lab.eu/prod/v1/gui/search/entries/entry/id/0dTJ0oCkwgt1xEV8EcXKIV8k9Zjq",
  ...expectedSnapshot.documentation_annotations.flatMap(annotation => [annotation.source.url, annotation.source.revision_url]),
]);
export function computationalInputContextHref(value: unknown): string | null {
  if (typeof value !== "string" || !publicSourceUrls.has(value)) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password && !url.port ? url.href : null;
  } catch { return null; }
}
