import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { act } from "react";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DiscoveryStructureWorkspace } from "@/components/DiscoveryStructureWorkspace";
import { fractionalToCartesian, latticeBasis, latticeProposal, latticeProposalCif, parseLatticeChange,
  structureAssetPath, structureCoordinatesFilename, structureCoordinatesSha256, structureReference,
  structureReferences, unitCellVolume } from "@/lib/discovery-structures";

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

describe("Source coordinate references and uniform lattice proposals", () => {
  it("hydrates the server-rendered crystal SVG without replacing the scientific workspace", async () => {
    const container = document.createElement("div");
    container.innerHTML = renderToString(<DiscoveryStructureWorkspace />);
    document.body.append(container);
    const recoverable = vi.fn();
    let root: ReturnType<typeof hydrateRoot> | undefined;
    try {
      await act(async () => { root = hydrateRoot(container, <DiscoveryStructureWorkspace />, { onRecoverableError: recoverable }); });
      expect(recoverable).not.toHaveBeenCalled();
      expect(container.querySelector("svg title")).toHaveTextContent("CrB2 coordinate model");
    } finally { await act(async () => root?.unmount()); container.remove(); }
  });

  it("pins all three original CIFs and retains partial occupancy, source tokens and declared operations", () => {
    const bytes = readFileSync(`public/research-pilots/${structureCoordinatesFilename}`);
    expect(createHash("sha256").update(bytes).digest("hex")).toBe(structureCoordinatesSha256);
    expect(readFileSync(`public/research-pilots/${structureCoordinatesFilename}.sha256`, "utf8")).toBe(`${structureCoordinatesSha256}  ${structureCoordinatesFilename}\n`);
    const references = structureReferences();
    expect(references.map(item => item.display_unit_cell_sites.length)).toEqual([3, 3, 4]);
    expect(references.map(item => item.declared_symmetry_operations.length)).toEqual([24, 24, 16]);
    for (const reference of references) {
      const cif = readFileSync(`public/research-pilots/structure-cifs/${reference.original_cif_filename}`);
      expect(createHash("sha256").update(cif).digest("hex")).toBe(reference.source.file_sha256);
      expect(cif.length).toBe(reference.source.bytes);
      for (const site of reference.sites) {
        expect(cif.toString()).toContain(site.fractional.map(coordinate => coordinate.raw).join(" "));
        const expanded = reference.display_unit_cell_sites.filter(point => point.source_site_label === site.label);
        expect(expanded.flatMap(point => point.equivalent_operation_indices).sort((a, b) => a - b)).toEqual(reference.declared_symmetry_operations.map((_, index) => index));
        expect(expanded.every(point => point.occupancy.raw === site.occupancy.raw)).toBe(true);
      }
    }
    const fese = structureReference("cod-4002152");
    expect(fese.sites[0].occupancy).toEqual({ raw: "0.996(3)", value: 0.996 });
    expect(fese.sites[1].fractional[2]).toEqual({ raw: "0.26526(14)", value: 0.26526 });
    expect(fese.source.download_is_mutable_current_file).toBe(true);
    expect(fese.structure_conditions.celltemp.value).toBe(295);
    expect(fese.structure_conditions.cellpressure.value).toBeNull();
    expect(references[0].sites[0].fractional.map(value => value.raw)).toEqual(["0.3333", "0.6667", "0.5"]);
    expect(bytes.toString()).not.toMatch(/\/Users\/|material_id|selected_result_id/);
  });

  it("uses the hexagonal metric and cubic volume scaling, without inferring pressure or changing sites", () => {
    const crb = structureReference("cod-1510641");
    expect(unitCellVolume(crb)).toBeCloseTo(2.97 ** 2 * 3.07 * Math.sqrt(3) / 2, 10);
    const [x, y, z] = fractionalToCartesian([0, 1, 0], latticeBasis(crb));
    expect(x).toBeCloseTo(-2.97 / 2, 10); expect(y).toBeCloseTo(2.97 * Math.sqrt(3) / 2, 10); expect(z).toBe(0);
    for (const percent of [-10, -2, 0, 2, 10]) {
      const proposal = latticeProposal("cod-4002152", percent);
      const factor = 1 + percent / 100;
      expect(proposal.proposed_cell.a_angstrom).toBeCloseTo(3.77354 * factor, 10);
      expect(proposal.proposed_cell.geometric_volume_angstrom_cubed).toBeCloseTo(3.77354 ** 2 * 5.52226 * factor ** 3, 9);
      expect(proposal.sites).toEqual(structureReference("cod-4002152").sites);
      expect(proposal.proposed_conditions).toEqual({ temperature_k: null, pressure_gpa: null });
      expect(proposal.results).toEqual({ tc_k: null, energy_ev: null, phonon_stability: null });
      expect(proposal.scope.calculation_executed).toBe(false);
      expect(proposal.scope.stable_host_validated).toBe(false);
      expect(proposal.scope.automatic_database_write).toBe(false);
      expect(proposal.source_reference.structure_conditions.celltemp.value).toBe(295);
    }
    expect(latticeProposal("cod-1510641", 2).proposed_cell.volume_change_percent).toBeCloseTo(6.1208, 8);
  });

  it("rejects malformed inputs and unknown structures and isolates exported edits from the reference", () => {
    for (const input of ["", " ", "1e2", "NaN", "Infinity", "0x1", "1,2", "10.01", "-10.01", "1 2"]) expect(parseLatticeChange(input)).toBeNull();
    expect(parseLatticeChange(" +2.5 ")).toBe(2.5);
    for (const value of [NaN, Infinity, -Infinity, 10.01, -10.01]) expect(() => latticeProposal("cod-1510641", value)).toThrow();
    expect(() => latticeProposal("catalogue-id", 0)).toThrow();
    const proposal = latticeProposal("cod-4002152", 0); proposal.sites[0].occupancy.value = 1;
    expect(structureReference("cod-4002152").sites[0].occupancy.value).toBe(0.996);
    vi.stubEnv("NEXT_PUBLIC_BASE_PATH", "/sclib");
    expect(structureAssetPath(structureCoordinatesFilename)).toBe(`/sclib/research-pilots/${structureCoordinatesFilename}`);
  });

  it("exports a new source-linked coordinate CIF with exact site tokens and no inherited temperature or measurement results", () => {
    const cif = latticeProposalCif("cod-4002152", 2);
    expect(cif).toContain("_cell_length_a 3.8490108");
    expect(cif).toContain("Fe1 Fe 0 0 0 0.996(3)");
    expect(cif).toContain("Se1 Se 0 0.5 0.26526(14) 1");
    expect(cif).toContain("_symmetry_space_group_name_H-M 'P 4/n m m :1'");
    expect(cif).toContain(structureReference("cod-4002152").source.file_sha256);
    expect(cif).not.toMatch(/_cell_measurement_temperature|_diffrn_ambient_temperature|_cell_measurement_pressure|_refine|_pd_proc/);
    expect(cif).toContain("No relaxation, stability calculation or Tc prediction.");
    expect(latticeProposalCif("cod-1510641", 2)).toContain("B1 B 0.3333 0.6667 0.5 1");
  });

  it("renders usable reference selectors and the full scientific detail, then resets proposals when switching source", () => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    render(<DiscoveryStructureWorkspace />);
    const reference = screen.getByRole("combobox", { name: "Structure reference" });
    expect(within(reference).getAllByRole("option")).toHaveLength(3);
    expect(screen.getByRole("img", { name: /CrB2.*3 symmetry-expanded sites/ })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Linear lattice change (%)" }), { target: { value: "2" } });
    expect(screen.getByText(/Volume change: 6.1208%/)).toBeInTheDocument();
    fireEvent.change(reference, { target: { value: "cod-4002152" } });
    expect(screen.getByRole("textbox", { name: "Linear lattice change (%)" })).toHaveValue("0");
    expect(screen.getByText(/Cell temperature: 295 K/)).toBeInTheDocument();
    expect(screen.getByText(/Fe occupancy is 0.996\(3\)/)).toHaveTextContent("choose a disorder model");
    expect(screen.getByRole("table", { name: "Original asymmetric-unit site tokens" })).toHaveTextContent("0.26526(14)");
    expect(screen.getByRole("link", { name: "Download captured source CIF" })).toHaveAttribute("href", expect.stringContaining("4002152-83a6bd28f07e.cif"));
    expect(screen.getByText(/checked historical catalogue snapshot/)).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
    expect(document.body.textContent).not.toMatch(/[\u3400-\u9fff]/);
  });

  it("disables proposal export for invalid input and reports download failures without source mutation", () => {
    render(<DiscoveryStructureWorkspace />);
    fireEvent.change(screen.getByRole("textbox", { name: "Linear lattice change (%)" }), { target: { value: "" } });
    expect(screen.getByRole("button", { name: "Export unrelaxed CIF" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Export proposal JSON" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "Linear lattice change (%)" })).toHaveAttribute("aria-invalid", "true");
    fireEvent.change(screen.getByRole("textbox", { name: "Linear lattice change (%)" }), { target: { value: "-2" } });
    vi.stubGlobal("URL", { createObjectURL: () => { throw new Error("unavailable"); } });
    fireEvent.click(screen.getByRole("button", { name: "Export unrelaxed CIF" }));
    expect(screen.getByRole("status")).toHaveTextContent("could not start the download");
  });
});
