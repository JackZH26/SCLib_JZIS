import snapshot from "@/public/research-pilots/materials-computational-reference-2026-10-02.json";

export type ComputationalReference = typeof snapshot;
export type ArchiveReferenceField = ComputationalReference["archive_fields"][number];
export type NativeReferenceInput = ComputationalReference["native_inputs"][number];
export type NativeTagDocumentationAnnotation = ComputationalReference["native_tag_documentation_annotations"][number];
export const computationalReferenceSnapshotSha256 = "c42acb658f255e020c65266a3da891a7acd05426ccb71b052f38c0e13406837d";
export const computationalReferenceMetadataPath = `${process.env.NEXT_PUBLIC_BASE_PATH || ""}/research-pilots/materials-computational-reference-2026-10-02.json`;

const archiveIds = ["program_name", "program_version", "electronic_method", "xc_functional_name", "k_mesh_sampling_method", "k_mesh_grid", "k_mesh_n_points", "basis_set_type", "basis_native_tier", "basis_cutoff_valence", "basis_cutoff_augmentation", "scf_energy_change_threshold", "core_electron_treatment", "dos_spin_polarized_flag", "final_system_composition", "final_system_atom_labels", "final_system_periodic", "final_system_lattice_vectors_raw", "final_system_positions_raw", "workflow_type", "workflow_optimization_steps", "workflow_is_converged_geometry_flag"];
const nativeTags = ["EDIFF", "ISPIN", "LSORBIT", "LNONCOLLINEAR", "ISMEAR", "SIGMA", "PSTRESS", "ENAUG"];
const row = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);

/** Accept only this finite, inspected projection. This is a data-shape check, not scientific approval. */
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

export function loadComputationalReference(value: unknown = snapshot): ComputationalReference | null {
  if (!row(value) || value.version !== "materials-computational-reference/1.0.0"
    || value.status !== "independent_source_metadata_pending" || !matchesSnapshot(value, snapshot)) return null;
  const data = value as ComputationalReference;
  if (data.reference.entry_id !== "0dTJ0oCkwgt1xEV8EcXKIV8k9Zjq" || data.reference.formula !== "B2Cr"
    || data.reference.knowledge_origin !== "Computed" || data.reference.match_level !== "fixed_composition_only"
    || data.authority.canonical_promotions !== 0 || data.authority.selected_result_association !== "unestablished"
    || data.authority.material_state_association !== "unestablished"
    || Object.values(data.authority).some(flag => flag !== false && flag !== 0 && flag !== "unestablished")
    || data.native_source.complete_file_established !== false || data.native_source.truncated_at_read_bound !== true
    || data.native_source.validated_final_geometry_established !== false || data.task_boundary.run_gate !== "NOT_OPEN"
    || data.archive_fields.map(field => field.field_id).join("|") !== archiveIds.join("|")
    || data.native_inputs.map(field => field.native_tag).join("|") !== nativeTags.join("|")
    || data.native_potential_labels.length !== 2
    || data.native_tag_documentation_annotations.map(annotation => annotation.native_tag).join("|") !== "SIGMA|ENAUG|PSTRESS|ISMEAR"
    || data.native_tag_documentation_annotations.some(annotation => annotation.source.capture_kind !== "web_tool_rendered_page_text"
      || annotation.source.raw_HTML_response_hash_established !== false)) return null;
  return data;
}

const sourceUrls = new Set([
  snapshot.reference.entry_url, snapshot.native_source.url, snapshot.native_EDIFF_unit_source.url,
  ...snapshot.archive_projection_sources.map(source => source.url),
  ...snapshot.reference.source_origin.source_references.map(source => source.url),
  ...snapshot.native_tag_documentation_annotations.flatMap(annotation => [annotation.source.url, annotation.source.revision_url]),
]);
/** Only exact public locators belonging to the bundled reference can become links. */
export function computationalReferenceHref(value: unknown): string | null {
  if (typeof value !== "string" || !sourceUrls.has(value)) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password && !url.port ? url.href : null;
  } catch { return null; }
}

export function archiveReferenceField(data: ComputationalReference, id: string): ArchiveReferenceField | null {
  return data.archive_fields.find(field => field.field_id === id) ?? null;
}

/** Raw archive JSON numbers remain raw metadata; this function assigns no physical unit or conversion. */
export function archiveReferenceValue(field: ArchiveReferenceField | null): string {
  if (!field || field.raw_value === null) return "Not supplied in this projection";
  return typeof field.raw_value === "string" ? field.raw_value : JSON.stringify(field.raw_value);
}

export const archiveReferenceRole: Record<string, string> = {
  computed_task_metadata: "Reported computation metadata",
  normalized_method_metadata: "Normalized method metadata",
  normalized_electronic_DOS_flag: "Normalized DOS flag",
  computed_system: "Calculation-linked system metadata",
  computed_structure: "Raw calculation-linked structure metadata",
  source_workflow: "Reported source workflow",
  source_workflow_report_flag: "Reported workflow flag",
};
