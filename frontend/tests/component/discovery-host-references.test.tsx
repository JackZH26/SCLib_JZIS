import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { DiscoveryStructureWorkspace } from "@/components/DiscoveryStructureWorkspace";
import { DiscoveryCombinedCandidates } from "@/components/DiscoveryCombinedCandidates";
import { initialSupercellRepeats, latticeBasis, latticeProposalCif, projectAlongAxis, structureReference, structureReferences } from "@/lib/discovery-structures";
import { generateSiteCandidates, supercellModel } from "@/lib/discovery-site-candidates";
import { generateCombinedCandidates } from "@/lib/discovery-combined-candidates";

afterEach(cleanup);

describe("source-linked host library", () => {
  it("preserves the three historical source objects and covers every formula named in the methodology", () => {
    const old = JSON.parse(readFileSync("public/research-pilots/discovery-structure-coordinates-2026-10-04.json", "utf8"));
    const refs = structureReferences();
    expect(refs.slice(0, 3)).toEqual(old.references);
    expect(refs).toHaveLength(24);
    const named = ["Al2O3", "MgO", "ZrO2", "HfO2", "Ga2O3", "AlN", "BN", "GaN", "TiN", "NbN", "SiC", "TiC", "ZrC", "HfC", "NbC", "TiB2", "ZrB2", "MgB2", "MgAl2O4", "LaAlO3", "SrTiO3", "BaZrO3"];
    for (const formula of named) expect(refs.some(ref => ref.formula === formula)).toBe(true);
    const captures = JSON.parse(readFileSync("../docs/data/discovery-host-source-captures-2026-10-05.json", "utf8"));
    for (const capture of captures) {
      const ref = structureReference(`cod-${capture.cod_id}`);
      const bytes = readFileSync(`public/research-pilots/structure-cifs/${capture.filename}`);
      expect(createHash("sha256").update(bytes).digest("hex")).toBe(capture.capture.sha256);
      expect(ref.source.file_sha256).toBe(capture.capture.sha256);
      expect(ref.source.download_is_mutable_current_file).toBe(!capture.capture.url.includes("@"));
      for (const [key, condition] of Object.entries(ref.structure_conditions)) {
        if (condition.value !== null) expect(bytes.toString().split("\n")[condition.source_line! - 1]).toContain(condition.raw!);
        else expect(condition.status).toBe("not_supplied");
        expect(key.endsWith("pressure") ? condition.unit : "K").toBe(key.endsWith("pressure") ? "kPa" : "K");
      }
    }
  });

  it("keeps diffraction conditions separate, and distinguishes omitted occupancy from explicit decimal tokens", () => {
    const alumina = structureReference("cod-9007634");
    expect(alumina.structure_conditions.celltemp.value).toBeNull();
    expect(alumina.structure_conditions.diffrtemp.value).toBe(300);
    expect(alumina.structure_conditions.diffrpressure.value).toBeNull();
    expect(alumina.sites[0].occupancy).toEqual({ raw: null, value: 1, basis: "cif_dictionary_default" });
    const gallia = structureReference("cod-2004987");
    expect(gallia.structure_conditions.celltemp.value).toBe(273.2);
    expect(gallia.structure_conditions.diffrtemp.value).toBe(273);
    const aln = structureReference("cod-1010514");
    expect(aln.sites[0]).toMatchObject({ element: "Al", type_symbol_raw: "Al3+", occupancy: { raw: "1.", value: 1, basis: "source_token" } });
    expect(supercellModel(aln.id, [1, 1, 1]).atoms.map(atom => atom.element)).not.toContain("Al3+");
    expect(() => supercellModel("cod-4002152", [1, 1, 1])).toThrow(/disorder model/);
    expect(latticeProposalCif(alumina.id, 2)).toContain("CIF dictionary default 1; not measured occupancies");
  });

  it("projects along the actual nonorthogonal c axis and keeps new source cells within the initial preview size", () => {
    const ref = structureReference("cod-2004987");
    expect(ref.lattice.beta.value).toBe(103.83);
    const basis = latticeBasis(ref);
    for (const axis of [0, 1, 2] as const) {
      const projection = projectAlongAxis(ref, basis[axis], axis);
      expect(projection[0]).toBeCloseTo(0, 10); expect(projection[1]).toBeCloseTo(0, 10);
    }
    for (const ref of structureReferences().filter(ref => ref.id !== "cod-4002152")) {
      const model = supercellModel(ref.id, initialSupercellRepeats(ref).map(Number));
      expect(model.atoms.length).toBeLessThanOrEqual(96);
      expect(model.atoms.length).toBeGreaterThan(0);
    }
    expect(initialSupercellRepeats(structureReference("cod-1540775"))).toEqual(["1", "1", "1"]);
    expect(initialSupercellRepeats(structureReference("cod-1526507"))).toEqual(["2", "2", "2"]);
  });

  it("generates alumina oxygen-vacancy and substitution states from actual source sites", async () => {
    const model = supercellModel("cod-9007634", [1, 1, 1]);
    expect(model.atoms).toHaveLength(30);
    const oxygen = model.atoms.find(atom => atom.element === "O")!;
    const one = await generateSiteCandidates(model.reference.id, [1, 1, 1], oxygen.id, "N", true);
    expect(one.candidates[0].composition).toEqual({ Al: 12, N: 1, O: 17 });
    expect(one.candidates[1].composition).toEqual({ Al: 12, O: 17 });
    expect(one.candidates[1].nominal_change.species_site_fraction).toBe(1 / 18);
    const combined = await generateCombinedCandidates({ referenceId: model.reference.id, repeats: [1, 1, 1], sites: [{ targetId: oxygen.id, replacements: "N", vacancy: true, unchanged: false }], strain: "0,2" });
    expect(combined.candidates).toHaveLength(4);
    expect(JSON.stringify(combined)).toContain('"cif_dictionary_default"');
    expect(combined.source_reference).toEqual(model.reference);
    expect(one.boundary.temperature_k).toBeNull(); expect(one.boundary.pressure_gpa).toBeNull();
    expect(one.boundary.stability_validated).toBe(false);
  });

  it("filters by family and phase without silently changing the selected source or proposal", () => {
    render(<DiscoveryStructureWorkspace initialReferenceId="cod-9007634" />);
    const source = screen.getByRole("combobox", { name: "Structure reference" });
    expect(source).toHaveValue("cod-9007634");
    expect(screen.getByText("Diffraction temperature:").parentElement).toHaveTextContent("300 K");
    expect(screen.getByText("Cell temperature:").parentElement).toHaveTextContent("not supplied");
    expect(screen.getByRole("link", { name: "Modify one site" })).toHaveAttribute("href", "/discovery/structures/candidates?reference=cod-9007634");
    expect(screen.queryByRole("link", { name: "Reference context" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Host family" }), { target: { value: "Oxides" } });
    expect(within(source).getAllByRole("option")).toHaveLength(5);
    fireEvent.change(screen.getByRole("textbox", { name: "Find formula, phase or COD ID" }), { target: { value: "monoclinic" } });
    expect(within(source).getAllByRole("option")).toHaveLength(4); // three matches plus retained current source
    fireEvent.change(screen.getByRole("textbox", { name: "Find formula, phase or COD ID" }), { target: { value: "no-matching-source" } });
    expect(screen.getByText(/0 matching references/)).toBeInTheDocument();
    expect(source).toHaveValue("cod-9007634");
    expect(document.body.textContent).not.toMatch(/[\u3400-\u9fff]/);
  });

  it("starts large selected hosts at one cell, identifies all three species, and can generate from that selection", async () => {
    const { unmount } = render(<DiscoveryStructureWorkspace initialReferenceId="cod-1540775" />);
    expect(within(screen.getByRole("list", { name: "Element legend" })).getAllByRole("listitem").map(item => item.textContent)).toEqual(["Al", "O", "Mg"]);
    unmount();
    render(<DiscoveryCombinedCandidates initialReferenceId="cod-9007634" />);
    expect(screen.getByRole("combobox", { name: "Source structure" })).toHaveValue("cod-9007634");
    expect(screen.getByRole("spinbutton", { name: "Along a" })).toHaveValue(1);
    fireEvent.change(screen.getByRole("textbox", { name: "Modification 1 replacement elements" }), { target: { value: "Ti" } });
    fireEvent.click(screen.getByRole("button", { name: "Generate combined candidates" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "1 combined coordinate candidates" })).toBeInTheDocument());
    fireEvent.change(screen.getByRole("combobox", { name: "Source structure" }), { target: { value: "cod-1540775" } });
    expect(screen.queryByRole("heading", { name: "1 combined coordinate candidates" })).not.toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: "Along a" })).toHaveValue(1);
  });
});
