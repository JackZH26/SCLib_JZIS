import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import snapshot from "@/public/research-pilots/materials-computational-reference-2026-10-02.json";
import { archiveReferenceField, archiveReferenceValue, computationalReferenceHref, computationalReferenceMetadataPath, computationalReferenceSnapshotSha256, loadComputationalReference } from "@/lib/material-computational-reference";

const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
describe("Finite independent NOMAD computation metadata", () => {
  it("pins the public snapshot bytes and the overlapping evidence groups for exactly one composition reference", () => {
    const data = loadComputationalReference()!;
    const filename = "materials-computational-reference-2026-10-02.json";
    const bytes = readFileSync(resolve(process.cwd(), "public/research-pilots", filename));
    const digest = createHash("sha256").update(bytes).digest("hex");
    expect(digest).toBe(computationalReferenceSnapshotSha256);
    expect(readFileSync(resolve(process.cwd(), "public/research-pilots", `${filename}.sha256`), "utf8")).toBe(`${digest}  ${filename}\n`);
    expect(data.version).toBe("materials-computational-reference/1.0.0");
    expect(data.reference).toMatchObject({ entry_id: "0dTJ0oCkwgt1xEV8EcXKIV8k9Zjq", upload_id: "5IvJz3uWTeu7Sgf197BSnw", formula: "B2Cr", knowledge_origin: "Computed", match_level: "fixed_composition_only" });
    expect(data.archive_fields).toHaveLength(22);
    expect(data.native_inputs).toHaveLength(8);
    expect(data.native_potential_labels).toHaveLength(2);
    expect(data.evidence_overlap).toContain("not counts of distinct material properties or independent experiments");
    expect(data.authority).toMatchObject({ scientific_acceptance: false, human_review: false, sample_identity_established: false, phase_identity_established: false, canonical_promotions: 0, ml_training_approved: false, material_state_association: "unestablished", selected_result_association: "unestablished", calculation_executed: false });
  });

  it("preserves the original system2/output binding and the compacted projection index without assigning coordinate units", () => {
    const data = loadComputationalReference()!;
    expect(data.reference.calculation_bindings).toMatchObject({ system_ref: "#/run/0/system/2", method_ref: "#/run/0/method/0", workflow_input_structure_ref: "#/run/0/system/0", workflow_result_ref: "#/run/0/calculation/2", initial_and_final_structure_differ: true });
    const coords = archiveReferenceField(data, "final_system_lattice_vectors_raw")!;
    expect(coords).toMatchObject({ original_archive_pointer: "/run/0/system/2/atoms/lattice_vectors", response_pointer: "/data/archive/run/0/system/0/atoms/lattice_vectors", response_number: 2, unit: null, normalized_value: null });
    expect(data.reference.currentness).toEqual({ cross_projection_atomic_snapshot_established: false, entry_hash_and_selected_metadata_equal_before_after: true, historical_summary_archive_byte_equivalence_established: false });
    for (const id of ["basis_cutoff_valence", "basis_cutoff_augmentation", "scf_energy_change_threshold", "final_system_lattice_vectors_raw", "final_system_positions_raw"]) expect(archiveReferenceField(data, id)).toMatchObject({ unit: null, normalized_value: null, status: "unit_definition_unavailable_in_checked_scope" });
  });

  it("retains source input precision and XML types, gives only native EDIFF an explicit physical unit, and bounds ENCUT absence", () => {
    const data = loadComputationalReference()!;
    expect(data.native_inputs.map(input => [input.native_tag, input.raw_scalar_lexeme, input.unit])).toEqual([
      ["EDIFF", "0.00010000", "eV"], ["ISPIN", "2", null], ["LSORBIT", "F", null], ["LNONCOLLINEAR", "F", null],
      ["ISMEAR", "1", null], ["SIGMA", "0.20000000", null], ["PSTRESS", "0.00000000", null], ["ENAUG", "535.51400000", null],
    ]);
    const inputs = Object.fromEntries(data.native_inputs.map(input => [input.native_tag, input]));
    expect(inputs.EDIFF.occurrences[0]).toMatchObject({ interpreted_value: "0.00010000", declared_xml_type: null, scalar_byte_span_zero_based_half_open: [33568, 33584] });
    expect(inputs.ISPIN.occurrences[0]).toMatchObject({ interpreted_value: 2, declared_xml_type: "int" });
    expect(inputs.LSORBIT.occurrences[0]).toMatchObject({ interpreted_value: false, declared_xml_type: "logical", raw_scalar_text: " F  " });
    expect(inputs.SIGMA.occurrences[0].interpreted_value).toBe("0.20000000");
    expect(data.native_EDIFF_unit_source).toMatchObject({ url: "https://vasp.at/wiki/index.php/EDIFF", plain_text_quote: "EDIFF is specified in units of eV.", response_sha256: "deac44c5c7349fea45ed83d7bbcf0ac6ad0be7f77de13555539fab293ae80662" });
    expect(data.native_EDIFF_unit_source.definition_scope).toContain("not legacy NOMAD schema");
    expect(data.native_unavailable_inputs).toEqual([{ native_tag: "ENCUT", raw_scalar_lexeme: null, role: "independent computed entry native input; no experimental association", source_blocks_absent: ["incar", "parameters"], source_blocks_reported: [], status: "not_found_in_two_checked_complete_blocks", unit: null }]);
    expect(data.native_source).toMatchObject({ captured_bytes: 2097152, source_prefix_sha256: "793f7aedb4bf93e31e6b4342cf30747c7d4bbf59cf60f6b1532799c884adc111", truncated_at_read_bound: true, complete_file_established: false, whole_XML_well_formed: false, last_calculation_checked: false, validated_final_geometry_established: false });
  });

  it("keeps potential label strings and native generator metadata separate from exact dataset identity or reproduction", () => {
    const data = loadComputationalReference()!;
    expect(data.native_potential_labels.map(row => row.dataset_label_literal)).toEqual(["PAW_PBE B 06Sep2000", "PAW_PBE Cr 06Sep2000"]);
    expect(data.native_potential_labels.every(row => row.potential_content_hash === null && row.potential_file_retrieved === false && row.exact_bitwise_dataset_identity_established === false)).toBe(true);
    expect(data.native_potential_labels.map(row => row.selected_native_fields.find(field => field.native_field === "atomspertype")!.raw_scalar_text)).toEqual(["   2", "   1"]);
    expect(data.software_consistency.exact_string_equal_after_declared_whitespace_join).toBe(true);
    expect(data.native_generator_fields.find(field => field.native_field === "version")!.raw_scalar_text).toBe("5.3.2  ");
    expect(data.task_boundary).toMatchObject({ run_gate: "NOT_OPEN", calculation_executed: false, task_proposals_are_source_facts: false, native_PSTRESS_is_Tc_pressure: false, source_spin_input_is_magnetic_order: false, new_native_unit_assigns_legacy_archive_units: false });
    expect(archiveReferenceField(data, "dos_spin_polarized_flag")!.raw_value).toBe(true);
    expect(archiveReferenceValue(archiveReferenceField(data, "dos_spin_polarized_flag"))).toBe("true");
  });

  it("pins documented native-tag annotations separately from raw inputs and labels rendered page text provenance accurately", () => {
    const data = loadComputationalReference()!;
    expect(data.native_tag_documentation_annotations.map(annotation => [annotation.native_tag, annotation.documented_unit, annotation.documented_meaning, annotation.source.observed_revision_id])).toEqual([
      ["SIGMA", "eV", "Smearing width", "29259"], ["ENAUG", "eV", "Augmentation-charge plane-wave cutoff tag", "26953"],
      ["PSTRESS", "kB", "Pressure/stress-tensor model input", "25988"], ["ISMEAR", null, "Methfessel-Paxton order 1", "37501"],
    ]);
    for (const annotation of data.native_tag_documentation_annotations) {
      expect(annotation.source).toMatchObject({ capture_kind: "web_tool_rendered_page_text", page_text_capture_sha256: "17bab1864685b0797c08d1830a9004a40267321ac5fb3213bd1651e401160a55", raw_HTML_response_hash_established: false });
      expect(annotation.interpretation_role).toBe("official_native_tag_definition_annotation");
      expect(computationalReferenceHref(annotation.source.url)).toBe(annotation.source.url);
      expect(computationalReferenceHref(annotation.source.revision_url)).toBe(annotation.source.revision_url);
      expect(data.native_inputs.find(input => input.native_tag === annotation.native_tag)!.unit).toBeNull();
    }
    expect(data.native_tag_documentation_annotations.find(annotation => annotation.native_tag === "ENAUG")!.limitation).toContain("does not establish that this run used the value as an effective cutoff");
    expect(data.native_tag_documentation_annotations.find(annotation => annotation.native_tag === "PSTRESS")!.limitation).toContain("not a Tc measurement pressure");
  });

  it("rejects altered scalars, types, units, completeness, conditions, authority and unknown keys", () => {
    const mutations: ((value: typeof snapshot) => void)[] = [
      value => { value.native_inputs[0].raw_scalar_lexeme = "0.0001"; },
      value => { value.native_inputs[1].occurrences[0].interpreted_value = "2"; },
      value => { value.native_inputs[6].unit = "GPa"; },
      value => { value.archive_fields[9].unit = "J"; },
      value => { value.native_source.complete_file_established = true; },
      value => { value.reference.calculation_bindings.system_ref = "#/run/0/system/0"; },
      value => { value.reference.currentness.cross_projection_atomic_snapshot_established = true; },
      value => { value.authority.scientific_acceptance = true; },
      value => { value.authority.ml_training_approved = true; },
      value => { value.authority.selected_result_association = "established"; },
      value => { value.native_tag_documentation_annotations[2].documented_unit = "GPa"; },
      value => { value.native_tag_documentation_annotations[0].source.capture_kind = "original_HTML_bytes"; },
      value => { value.native_tag_documentation_annotations[0].source.raw_HTML_response_hash_established = true; },
      value => { (value as unknown as Record<string, unknown>).private_notes = "unapproved context"; },
      value => { (value.native_inputs[0] as unknown as Record<string, unknown>).raw_xml = "<i/>"; },
    ];
    for (const mutate of mutations) { const value = clone(snapshot); mutate(value); expect(loadComputationalReference(value)).toBeNull(); }
    expect(loadComputationalReference(null)).toBeNull();
    expect(loadComputationalReference({ ...snapshot, version: null })).toBeNull();
  });

  it("exports only whitelisted selected metadata and accepts only exact public source locators", () => {
    const body = JSON.stringify(snapshot);
    expect(body).not.toMatch(/\/Users\/|\/private\/|\/tmp\/|literal_element_xml|literal_source_html|<modeling|<incar|<parameters|<atominfo|<generator|base64|password|credential|coauthors/);
    expect(computationalReferenceMetadataPath).toMatch(/\/research-pilots\/materials-computational-reference-2026-10-02\.json$/);
    expect(computationalReferenceHref(snapshot.reference.entry_url)).toBe(snapshot.reference.entry_url);
    expect(computationalReferenceHref(snapshot.native_EDIFF_unit_source.url)).toBe(snapshot.native_EDIFF_unit_source.url);
    for (const url of ["javascript:alert(1)", "https://nomad-lab.eu@untrusted.invalid/entry", `${snapshot.reference.entry_url}?private=1`, "https://nomad-lab.eu/prod/v1/api/v1/entries/other/archive", "http://nomad-lab.eu/", "https://vasp.at:444/wiki/index.php/EDIFF", "/private/tmp/source.xml"]) expect(computationalReferenceHref(url)).toBeNull();
  });
});
