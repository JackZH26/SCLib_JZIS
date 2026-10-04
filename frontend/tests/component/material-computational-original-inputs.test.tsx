import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import snapshot from "@/public/research-pilots/materials-computational-original-inputs-2026-10-04.json";
import { MaterialComputationalOriginalInputs } from "@/components/MaterialComputationalOriginalInputs";
import { computationalOriginalInputsHref, computationalOriginalInputsSnapshotSha256, loadComputationalOriginalInputs } from "@/lib/material-computational-original-inputs";

const clone = () => JSON.parse(JSON.stringify(snapshot)) as typeof snapshot;
describe("Captured original input files", () => {
  it("pins three separately recovered source files and preserves input versus runtime roles", () => {
    const filename = "materials-computational-original-inputs-2026-10-04.json";
    const bytes = readFileSync(resolve(process.cwd(), "public/research-pilots", filename));
    const digest = createHash("sha256").update(bytes).digest("hex");
    expect(digest).toBe(computationalOriginalInputsSnapshotSha256);
    expect(readFileSync(resolve(process.cwd(), "public/research-pilots", filename + ".sha256"), "utf8")).toBe(`${digest}  ${filename}\n`);
    const data = loadComputationalOriginalInputs()!;
    expect(data.source_files.map(file => [file.name, file.source_bytes, file.source_sha256])).toEqual([
      ["INCAR", 469, "4d8039f059a12f650c757b3a1247918756f27460753b3172449a6779c59188b2"],
      ["POSCAR", 228, "d724f952998cbb6888625378368a0fec7f9ca37a98685ef39a629e68523239f3"],
      ["KPOINTS", 32, "c9f61a045a63101e8a9c154c10218c2c10a8c63e487585ec166d1287935d8c15"],
    ]);
    expect(data.incar_controls).toHaveLength(19);
    expect(data.incar_controls.find(control => control.tag === "MAGMOM")!.raw_value_lexeme).toBe("2*0.0000 1*5.0000");
    expect(data.incar_controls.find(control => control.tag === "LORBIT")!.frozen_xml_occurrences.map(context => [context.raw_text.trim(), context.native_type_attribute])).toEqual([["F", "logical"], ["F", "logical"]]);
    expect(data.incar_controls.some(control => control.tag === "ENCUT")).toBe(false);
    expect(data.kpoints.mesh_lexemes).toEqual(["14", "14", "11"]);
    expect(data.poscar.source_species_labels_in_order).toEqual(["B", "B", "Cr"]);
    expect(data.frozen_XML_comparison.POSCAR_input_basis_differs_from_XML_final_basis).toBe(true);
    expect(data.frozen_XML_comparison.checks).toHaveLength(8);
    expect(data.incar_controls.every(control => control.native_unit === null && control.normalized_value === null)).toBe(true);
    expect(data.authority.effective_runtime_controls_validated).toBe(false);
    expect(data.authority.convergence_validated).toBe(false);
    expect(JSON.stringify(data)).not.toMatch(/\/private\/|\/Users\/|"native_lines":|"raw_body":/);
  });

  it("rejects altered source precision, authority and units without evaluating accessors", () => {
    for (const mutate of [
      (data: typeof snapshot) => { data.incar_controls[4].raw_value_lexeme = "0 0 5"; },
      (data: typeof snapshot) => { data.incar_controls[0].native_unit = "eV"; },
      (data: typeof snapshot) => { data.source_differences[0].original_input = "F"; },
      (data: typeof snapshot) => { data.poscar.source_species_labels_in_order = ["Cr", "B", "B"]; },
      (data: typeof snapshot) => { data.authority.convergence_validated = true; },
      (data: typeof snapshot) => { data.authority.material_sample_state_selected_result_association = "matched"; },
    ]) { const value = clone(); mutate(value); expect(loadComputationalOriginalInputs(value)).toBeNull(); }
    let reads = 0;
    const accessor = clone();
    Object.defineProperty(accessor, "version", { get() { reads += 1; return snapshot.version; } });
    expect(loadComputationalOriginalInputs(accessor)).toBeNull();
    expect(reads).toBe(0);
    expect(loadComputationalOriginalInputs({ ...snapshot, source_files: new Array(3) })).toBeNull();
    const first = loadComputationalOriginalInputs()!;
    first.incar_controls[0].raw_value_lexeme = "mutated";
    expect(loadComputationalOriginalInputs()!.incar_controls[0].raw_value_lexeme).toBe("ACC");
  });

  it("permits only the observed public source and documentation URLs", () => {
    for (const file of snapshot.source_files) expect(computationalOriginalInputsHref(file.source_url)).toBe(file.source_url);
    for (const url of ["javascript:alert(1)", snapshot.source_files[0].source_url + "?token=secret", snapshot.source_files[0].source_url.replace("INCAR", "POTCAR"), "https://nomad-lab.eu@untrusted.invalid/", "http://vasp.at/wiki/index.php/POSCAR", null]) expect(computationalOriginalInputsHref(url)).toBeNull();
  });

  it("keeps detailed controls closed, keyboard scrollable and separate from XML discrepancies", () => {
    render(<MaterialComputationalOriginalInputs data={loadComputationalOriginalInputs()} />);
    expect(screen.getByText("Gamma · 14 × 14 × 11")).toBeInTheDocument();
    for (const title of ["Read original input values", "Original input and XML differences", "Input-file provenance and downloads"]) expect(screen.getByText(title).closest("details")).not.toHaveAttribute("open");
    const controls = screen.getByRole("region", { name: "Original INCAR controls, horizontally scrollable" });
    expect(controls).toHaveAttribute("tabindex", "0");
    expect(within(controls).getAllByRole("row")).toHaveLength(20);
    const lorbit = within(controls).getByRole("rowheader", { name: "LORBIT" }).closest("tr")!;
    expect(within(lorbit).getAllByRole("cell")[0]).toHaveTextContent("11");
    expect(lorbit).toHaveTextContent("XML type: logical");
    expect(screen.getByText(/LORBIT differs/)).toHaveTextContent("effective runtime value remains unresolved");
    expect(screen.getByText(/Written numeric values agree/)).toHaveTextContent("precision differs");
    expect(screen.getByText(/The original INCAR Uncategorized/, { selector: "dd" })).toHaveTextContent("not physical magnetic-order evidence");
    expect(screen.getByRole("region", { name: "Original input-file metadata JSON" })).toHaveAttribute("tabindex", "0");
    expect(JSON.parse(screen.getByRole("region", { name: "Original input-file metadata JSON" }).textContent!)).toEqual(loadComputationalOriginalInputs());
    expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]|\u2014/);
  });

  it("shows an explicit unavailable state without publishing input links", () => {
    render(<MaterialComputationalOriginalInputs data={null} />);
    expect(screen.getByRole("status")).toHaveTextContent("Original input-file metadata is unavailable");
    expect(screen.queryByRole("link")).toBeNull();
  });
});
