import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import snapshot from "@/public/research-pilots/materials-computational-input-context-2026-10-04.json";
import previousNative from "@/public/research-pilots/materials-computational-native-output-2026-10-02.json";
import {
  computationalInputContextHref,
  computationalInputContextMetadataPath,
  computationalInputContextSnapshotSha256,
  computationalInputContextSourceSha256,
  loadComputationalInputContext,
} from "@/lib/material-computational-input-context";

const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));

describe("Finite additional native input context", () => {
  it("pins the separately downloadable source projection without changing the previous native output", () => {
    const filename = "materials-computational-input-context-2026-10-04.json";
    const bytes = readFileSync(resolve(process.cwd(), "public/research-pilots", filename));
    const digest = createHash("sha256").update(bytes).digest("hex");
    expect(digest).toBe(computationalInputContextSnapshotSha256);
    expect(readFileSync(resolve(process.cwd(), "public/research-pilots", `${filename}.sha256`), "utf8")).toBe(`${digest}  ${filename}\n`);
    expect(computationalInputContextMetadataPath).toMatch(/\/research-pilots\/materials-computational-input-context-2026-10-04\.json$/);
    const oldBytes = readFileSync(resolve(process.cwd(), "public/research-pilots/materials-computational-native-output-2026-10-02.json"));
    expect(createHash("sha256").update(oldBytes).digest("hex")).toBe("c75feec9feb891322eb007604f02d121d1d8a2ce72d010cc9d1ae94e37b14906");
    const data = loadComputationalInputContext()!;
    expect(data.reference).toMatchObject({ entry_id: previousNative.reference.entry_id, formula: "B2Cr", knowledge_origin: "Computed" });
    expect(data.native_source).toMatchObject({ source_sha256: computationalInputContextSourceSha256, source_bytes: 3835451, version: "5.3.2" });
    expect(data.counts).toEqual({ additional_tag_count: 8, additional_occurrence_count: 10, combined_tag_count: 25, combined_occurrence_count: 36, independent_computed_entry_count: 1, independent_experiment_count_established: false, formal_material_property_additions: 0 });
    const allInputs = [...previousNative.native_inputs, ...data.native_inputs];
    expect(allInputs).toHaveLength(36);
    expect(new Set(allInputs.map(input => input.native_tag)).size).toBe(25);
    expect(new Set(allInputs.map(input => input.source_xpath)).size).toBe(36);
    expect(data.authority).toEqual({ formal_human_review: false, scientific_acceptance: false, ML_approval: false, material_sample_state_selected_result_association: null, canonical_promotions: 0, production_imports: 0, new_calculations: 0, execution_authorized: false });
    expect(JSON.stringify(data)).not.toMatch(/\/Users\/|\/private\/|\/tmp\/|<modeling|literal_source_html|password|credential|base64/);
  });

  it("retains vector precision, source atom order and unresolved types/units rather than converting inputs to material properties", () => {
    const data = loadComputationalInputContext()!;
    const spin = data.native_inputs.filter(input => input.native_tag === "MAGMOM");
    expect(spin).toHaveLength(2);
    expect(spin.map(input => input.raw_lexeme)).toEqual(["0.00000000      0.00000000      5.00000000", "0.00000000      0.00000000      5.00000000"]);
    expect(spin.map(input => input.source_context)).toEqual(["./incar[1]", "./parameters[1]/separator[2][@name='electronic']/separator[4][@name='electronic spin']"]);
    for (const input of spin) {
      expect(input.declared_xml_type).toBeNull();
      expect(input.actual_native_attributes).toEqual({ name: "MAGMOM" });
      expect(input.role).toContain("Not final or ordered moments");
    }
    expect(data.spin_components.map(input => [input.zero_based_index, input.source_element_label, input.raw_input_lexeme])).toEqual([[0, "B", "0.00000000"], [1, "B", "0.00000000"], [2, "Cr", "5.00000000"]]);
    expect(data.native_inputs.find(input => input.native_tag === "GGA")).toMatchObject({ raw_text: "--", raw_lexeme: "--", declared_xml_type: "string", normalized_value: null });
    expect(data.native_inputs.find(input => input.native_tag === "GGA")!.role).toContain("uninterpreted");
    expect(data.native_inputs.filter(input => input.native_tag === "ICHARG").map(input => input.raw_lexeme)).toEqual(["1", "1"]);
    for (const input of [...data.native_inputs, ...data.spin_components]) {
      expect(input.unit).toBeNull();
      expect(input.normalized_value).toBeNull();
    }
  });

  it("preserves exact text-content hashes, original attribute bags and one locator per source occurrence", () => {
    const data = loadComputationalInputContext()!;
    for (const input of data.native_inputs) {
      expect(createHash("sha256").update(input.raw_text, "utf8").digest("hex")).toBe(input.text_content_sha256);
      expect(input.raw_text.trim()).toBe(input.raw_lexeme);
      expect(input.actual_native_attributes.name).toBe(input.native_tag);
      expect(input.explicit_unit_attributes_in_element_or_ancestors).toEqual([]);
      expect(input.source_xpath).toContain(`[@name='${input.native_tag}']`);
    }
    expect(data.native_inputs.find(input => input.native_tag === "NELECT")!.actual_native_attributes).toEqual({ name: "NELECT" });
    expect(data.native_inputs.find(input => input.native_tag === "NELECT")!.declared_xml_type).toBeNull();
    expect(data.native_inputs.find(input => input.native_tag === "LDAU")).toMatchObject({ raw_text: " F  ", raw_lexeme: "F", declared_xml_type: "logical" });
  });

  it("keeps current manual meanings and grouped rendered captures separate from original runtime or unit proof", () => {
    const data = loadComputationalInputContext()!;
    expect(data.documentation_annotations).toHaveLength(8);
    const hashes = new Set(data.documentation_annotations.map(annotation => annotation.source.tool_result_capture_sha256));
    expect(hashes).toEqual(new Set(["1d1c6b794f7c0bbba53e5f8faebe2e6b1d6bd10e47633290b3d372e881c3d755", "824b0b99253db81fe096bfd8b7733fd517c960535b4bae2795403c5370591884", "c7fdf3814aa358ac941eb707ad8e02dc65bf3f4d91257028393e6bd6fa514072"]));
    for (const annotation of data.documentation_annotations) {
      expect(annotation.documented_unit).toBeNull();
      expect(annotation.interpretation_role).toBe("current_manual_definition_annotation_not_native_runtime_proof");
      expect(annotation.source).toMatchObject({ capture_kind: "web_tool_rendered_page_text", raw_HTML_response_hash_established: false, captured_on: "2026-10-04" });
      expect(annotation.source.capture_scope).toContain("not original HTML bytes or a single-page byte hash");
      expect(annotation.source.revision_url).toContain(`oldid=${annotation.source.observed_revision_id}`);
    }
    expect(data.documentation_scope).toContain("do not establish original VASP 5.3.2 documentation equivalence");
    expect(data.reproduction_limits.find(limit => limit.id === "original_input_and_restart_context")!.boundary).toContain("do not infer a specific missing file or its provider absence");
  });

  it("returns isolated copies so a consumer cannot mutate the validation baseline", () => {
    const first = loadComputationalInputContext()!;
    first.native_inputs[0].raw_lexeme = "changed";
    first.native_inputs[0].actual_native_attributes.name = "changed";
    first.documentation_annotations[0].source.url = "https://untrusted.invalid/";
    const second = loadComputationalInputContext()!;
    expect(second.native_inputs[0].raw_lexeme).toBe("1");
    expect(second.native_inputs[0].actual_native_attributes.name).toBe("ICHARG");
    expect(second.documentation_annotations[0].source.url).toBe("https://vasp.at/wiki/index.php/ICHARG");
    const provided = clone(snapshot);
    const returned = loadComputationalInputContext(provided)!;
    returned.spin_components[0].raw_input_lexeme = "changed";
    expect(provided.spin_components[0].raw_input_lexeme).toBe("0.00000000");
  });

  it("rejects altered precision, locators, units, contexts, authority, counts and documentation scope", () => {
    const mutations: ((value: typeof snapshot) => void)[] = [
      value => { value.native_inputs[4].raw_lexeme = "0 0 5"; },
      value => { value.native_inputs[4].declared_xml_type = "float"; },
      value => { value.native_inputs[4].unit = "muB"; },
      value => { value.native_inputs[2].raw_lexeme = "PE"; },
      value => { value.native_inputs[0].source_xpath = value.native_inputs[1].source_xpath; },
      value => { value.native_inputs[0].text_content_sha256 = "0".repeat(64); },
      value => { value.native_inputs[0].normalized_value = 1; },
      value => { value.spin_components[0].source_element_label = "Cr"; },
      value => { value.counts.independent_computed_entry_count = 10; },
      value => { value.counts.independent_experiment_count_established = true; },
      value => { value.counts.formal_material_property_additions = 8; },
      value => { value.authority.scientific_acceptance = true; },
      value => { value.authority.execution_authorized = true; },
      value => { value.authority.material_sample_state_selected_result_association = "established"; },
      value => { value.documentation_annotations[0].documented_unit = "eV"; },
      value => { value.documentation_annotations[0].source.raw_HTML_response_hash_established = true; },
      value => { value.documentation_annotations[0].source.capture_scope = "original HTML bytes"; },
      value => { (value as unknown as Record<string, unknown>).raw_XML = "unreviewed"; },
    ];
    for (const mutate of mutations) {
      const value = clone(snapshot);
      mutate(value);
      expect(loadComputationalInputContext(value)).toBeNull();
    }
    expect(loadComputationalInputContext(null)).toBeNull();
    expect(loadComputationalInputContext({ ...snapshot, native_inputs: new Array(10) })).toBeNull();
    expect(loadComputationalInputContext({ ...snapshot, documentation_scope: "x".repeat(2049) })).toBeNull();
    expect(loadComputationalInputContext({ ...snapshot, counts: { ...snapshot.counts, additional_occurrence_count: Infinity } })).toBeNull();
    const hidden = clone(snapshot);
    Object.defineProperty(hidden, "unknown", { value: true });
    expect(loadComputationalInputContext(hidden)).toBeNull();
    const accessor = clone(snapshot);
    let accessorCalls = 0;
    Object.defineProperty(accessor, "version", { get() { accessorCalls += 1; return snapshot.version; } });
    expect(loadComputationalInputContext(accessor)).toBeNull();
    expect(accessorCalls).toBe(0);
  });

  it("permits only the inspected native source, entry and eight exact manual pages/revisions", () => {
    expect(computationalInputContextHref(snapshot.native_source.native_XML_url)).toBe(snapshot.native_source.native_XML_url);
    expect(computationalInputContextHref(previousNative.reference.entry_url)).toBe(previousNative.reference.entry_url);
    for (const annotation of snapshot.documentation_annotations) {
      expect(computationalInputContextHref(annotation.source.url)).toBe(annotation.source.url);
      expect(computationalInputContextHref(annotation.source.revision_url)).toBe(annotation.source.revision_url);
    }
    for (const url of ["javascript:alert(1)", `${snapshot.native_source.native_XML_url}?private=1`, "https://nomad-lab.eu/prod/v1/api/v1/entries/other/raw/vasprun.xml", "https://nomad-lab.eu@untrusted.invalid/", "http://vasp.at/wiki/index.php/MAGMOM", "https://vasp.at:444/wiki/index.php/MAGMOM", "https://vasp.at/wiki/index.php/ENCUT", "https://vasp.at/wiki/index.php?title=MAGMOM&oldid=1", "/private/tmp/vasprun.xml", null]) expect(computationalInputContextHref(url)).toBeNull();
  });
});
