import { createHash, webcrypto } from "node:crypto";
import { act } from "react";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DiscoverySiteCandidates } from "@/components/DiscoverySiteCandidates";
import { compositionOf, generateSiteCandidates, siteOperations, supercellModel } from "@/lib/discovery-site-candidates";
import { fractionalToCartesian, latticeBasis, structureReference, type Vector3 } from "@/lib/discovery-structures";

beforeEach(() => { vi.stubGlobal("crypto", webcrypto); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const sha256 = (text: string) => createHash("sha256").update(text).digest("hex");
const mgTarget = () => supercellModel("cod-1526507", [2, 2, 2]).atoms.find(atom => atom.element === "Mg")!;
const batch = () => generateSiteCandidates("cod-1526507", [2, 2, 2], mgTarget().id, "Al, Ca, Al", true);

describe("Ordered, source-linked site candidates", () => {
  it("preserves the hexagonal metric and translated Cartesian positions in an asymmetric supercell", () => {
    const model = supercellModel("cod-1526507", [2, 3, 1]);
    expect(model.atoms).toHaveLength(18);
    expect(compositionOf(model.atoms)).toEqual({ B: 12, Mg: 6 });
    expect(model.cell).toEqual({ a: 6.1646, b: 3.0823 * 3, c: 3.51461, alpha: 90, beta: 90, gamma: 120 });
    const basis = latticeBasis(model.reference);
    const expanded = basis.map((vector, index) => vector.map(value => value * model.repeats[index]) as Vector3);
    for (const atom of model.atoms) {
      const source = model.reference.display_unit_cell_sites[atom.source_expanded_index];
      const expected = fractionalToCartesian(source.fractional.map((value, i) => value + atom.cell_translation[i]), basis);
      fractionalToCartesian(atom.fractional, expanded).forEach((value, i) => expect(value).toBeCloseTo(expected[i], 11));
      expect(atom.fractional.every(value => value >= 0 && value < 1)).toBe(true);
    }
    expect(new Set(model.atoms.map(atom => atom.id)).size).toBe(18);
  });

  it("changes exactly one atom and reports both original-site concentration denominators", async () => {
    const result = await batch();
    expect(result.baseline.atoms).toHaveLength(24);
    expect(compositionOf(result.baseline.atoms)).toEqual({ B: 16, Mg: 8 });
    expect(result.candidates.map(item => item.composition)).toEqual([{ Al: 1, B: 16, Mg: 7 }, { B: 16, Ca: 1, Mg: 7 }, { B: 16, Mg: 7 }]);
    expect(result.candidates.map(item => item.atoms.length)).toEqual([24, 24, 23]);
    for (const candidate of result.candidates) {
      expect(candidate.nominal_change).toMatchObject({ changed_sites: 1, original_species_sites: 8, original_total_sites: 24, species_site_fraction: 0.125, original_total_site_fraction: 1 / 24 });
      expect(candidate.atoms.filter(atom => atom.id !== candidate.target_atom.id)).toEqual(result.baseline.atoms.filter(atom => atom.id !== candidate.target_atom.id));
      expect(candidate.atoms.find(atom => atom.id === candidate.target_atom.id)?.element).toBe(candidate.operation.element ?? undefined);
    }
    result.candidates[0].atoms[0].fractional[0] = 999;
    expect(result.baseline.atoms[0].fractional[0]).not.toBe(999);
    expect(structureReference("cod-1526507").display_unit_cell_sites[0].fractional[0]).not.toBe(999);
    const b = result.baseline.atoms.find(atom => atom.element === "B")!;
    expect((await generateSiteCandidates("cod-1526507", [2, 2, 2], b.id, "C", false)).candidates[0].nominal_change.species_site_fraction).toBe(1 / 16);
  });

  it("pins deterministic lineage and exports explicit P1 coordinates without source-state inheritance", async () => {
    const first = await batch();
    expect(await batch()).toEqual(first);
    for (const candidate of first.candidates) {
      expect(candidate.cif_sha256).toBe(sha256(candidate.cif));
      expect(candidate.cif).toContain("_symmetry_space_group_name_H-M 'P 1'");
      expect(candidate.cif).toContain(first.source_cif_sha256);
      expect(candidate.cif).not.toMatch(/_cell_measurement_temperature|_diffrn_ambient_temperature|_cell_measurement_pressure|P 6\/m m m/);
      expect(candidate.cif.split("\n").filter(line => /^S\d+ /.test(line))).toHaveLength(candidate.atoms.length);
      expect(candidate.cif.endsWith("\n")).toBe(true);
    }
    expect(new Set(first.candidates.map(item => item.id)).size).toBe(3);
    expect(first.boundary).toMatchObject({ charge_state: null, temperature_k: null, pressure_gpa: null, relaxed: false, energy_calculated: false, stability_validated: false, tc_calculated: false, catalogue_association: "unestablished", database_write: false, symmetry_unique_candidates: false });
    const otherMg = first.baseline.atoms.filter(atom => atom.element === "Mg")[1];
    const other = await generateSiteCandidates("cod-1526507", [2, 2, 2], otherMg.id, "Al", false);
    expect(other.parent_id).toBe(first.parent_id);
    expect(other.candidates[0].id).not.toBe(first.candidates[0].id);
  });

  it("rejects partial occupancy, invalid or excessive cells and foreign target IDs", async () => {
    expect(() => supercellModel("cod-4002152", [1, 1, 1])).toThrow(/disorder model/);
    expect(structureReference("cod-4002152").sites[0].occupancy.raw).toBe("0.996(3)");
    for (const repeats of [[0, 1, 1], [1.5, 1, 1], [NaN, 1, 1], [Infinity, 1, 1], [5, 1, 1], [1, 1], [4, 4, 4]]) expect(() => supercellModel("cod-1526507", repeats)).toThrow();
    expect(supercellModel("cod-1526507", [4, 4, 2]).atoms).toHaveLength(96);
    expect(() => supercellModel("not-a-source", [1, 1, 1])).toThrow();
    await expect(generateSiteCandidates("cod-1526507", [1, 1, 1], "foreign", "Al", false)).rejects.toThrow(/Choose an atom/);
  });

  it("accepts explicit unique symbols and vacancy alone, rejecting aliases, isotopes and no-ops", () => {
    expect(siteOperations(" Al, Ca, Al ", true, "Mg")).toEqual([{ kind: "substitution", element: "Al" }, { kind: "substitution", element: "Ca" }, { kind: "vacancy", element: null }]);
    expect(siteOperations("", true, "Mg")).toEqual([{ kind: "vacancy", element: null }]);
    for (const input of ["", "Mg", "Al,", "al", "Xx", "13C", "Ca2+", "<script>", "H,He,Li,Be,B,C,N,O,F"]) expect(() => siteOperations(input, false, "Mg")).toThrow();
    expect(() => siteOperations("H,He,Li,Be,B,C,N,O", true, "Mg")).toThrow(/limit/);
  });
});

describe("Site candidate workspace", () => {
  function chooseMg() {
    fireEvent.change(screen.getByRole("combobox", { name: "Source structure" }), { target: { value: "cod-1526507" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Atomic site to modify" }), { target: { value: mgTarget().id } });
    fireEvent.change(screen.getByRole("textbox", { name: "Replacement elements" }), { target: { value: "Al, Ca" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Vacancy candidate" }), { target: { value: "yes" } });
  }

  it("hydrates the initial form and generates inspectable, English proposals without network writes", async () => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    const container = document.createElement("div"); container.innerHTML = renderToString(<DiscoverySiteCandidates />); document.body.append(container);
    const recoverable = vi.fn(); let root: ReturnType<typeof hydrateRoot> | undefined;
    try {
      await act(async () => { root = hydrateRoot(container, <DiscoverySiteCandidates />, { onRecoverableError: recoverable }); });
      chooseMg(); fireEvent.click(screen.getByRole("button", { name: "Generate coordinate proposals" }));
      await screen.findByRole("heading", { name: "3 unrelaxed coordinate proposals" });
      expect(screen.getByText("1 / 8 = 12.5%")).toBeInTheDocument();
      expect(screen.getByText("1 / 24 = 4.1667%")).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Inspect vacancy candidate" }));
      expect(screen.getByRole("img", { name: /vacancy at/ })).toBeInTheDocument();
      expect(container.querySelectorAll("svg circle[data-atom-id]")).toHaveLength(23);
      expect(screen.getByRole("region", { name: "Scrollable proposed coordinates" })).toHaveAttribute("tabindex", "0");
      expect(container.textContent).not.toMatch(/[\u4e00-\u9fff]/);
      expect(recoverable).not.toHaveBeenCalled(); expect(fetch).not.toHaveBeenCalled();
    } finally { await act(async () => root?.unmount()); container.remove(); }
  });

  it("clears results on edits and blocks unresolved source occupancy and oversized cells", async () => {
    render(<DiscoverySiteCandidates />); chooseMg();
    fireEvent.click(screen.getByRole("button", { name: "Generate coordinate proposals" }));
    await screen.findByRole("heading", { name: "3 unrelaxed coordinate proposals" });
    fireEvent.change(screen.getByRole("spinbutton", { name: "Along a" }), { target: { value: "4" } });
    expect(screen.queryByRole("heading", { name: "3 unrelaxed coordinate proposals" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("spinbutton", { name: "Along b" }), { target: { value: "4" } });
    fireEvent.change(screen.getByRole("spinbutton", { name: "Along c" }), { target: { value: "4" } });
    expect(screen.getByRole("alert")).toHaveTextContent("192 sites");
    expect(screen.getByRole("button", { name: "Generate coordinate proposals" })).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox", { name: "Source structure" }), { target: { value: "cod-4002152" } });
    expect(screen.getByRole("alert")).toHaveTextContent("disorder model");
  });

  it("rejects injected source selections without retaining stale candidates or changing the source link", async () => {
    render(<DiscoverySiteCandidates />); chooseMg();
    fireEvent.click(screen.getByRole("button", { name: "Generate coordinate proposals" }));
    await screen.findByRole("heading", { name: "3 unrelaxed coordinate proposals" });
    const select = screen.getByRole("combobox", { name: "Source structure" });
    for (const value of ["cod-1526507&reference=other", '<img src=x onerror="alert(1)">']) {
      const option = document.createElement("option"); option.value = value; option.textContent = "Injected option"; select.append(option);
      fireEvent.change(select, { target: { value } });
      expect(screen.getByRole("alert")).toHaveTextContent("Choose a captured structure reference.");
      expect(select).toHaveValue("cod-1526507");
      expect(screen.getByRole("link", { name: "Inspect source and conditions" })).toHaveAttribute("href", "/discovery/structures?reference=cod-1526507");
      expect(screen.queryByRole("heading", { name: "3 unrelaxed coordinate proposals" })).not.toBeInTheDocument();
      option.remove();
    }
  });

  it("discards delayed preparation after a source edit and reports digest failures", async () => {
    let release: (value: ArrayBuffer) => void = () => {};
    const digest = vi.fn().mockImplementationOnce(() => new Promise<ArrayBuffer>(resolve => { release = resolve; }))
      .mockImplementation((algorithm, value) => webcrypto.subtle.digest(algorithm, value));
    vi.stubGlobal("crypto", { subtle: { digest } });
    render(<DiscoverySiteCandidates />); chooseMg();
    fireEvent.click(screen.getByRole("button", { name: "Generate coordinate proposals" }));
    expect(screen.getByRole("button", { name: "Preparing coordinates…" })).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox", { name: "Source structure" }), { target: { value: "cod-4002152" } });
    await act(async () => { release(new ArrayBuffer(32)); });
    await waitFor(() => expect(digest.mock.calls.length).toBeGreaterThan(3));
    expect(screen.queryByRole("heading", { name: /unrelaxed coordinate proposals/ })).not.toBeInTheDocument();
    chooseMg(); digest.mockRejectedValue(new Error("Digest unavailable"));
    fireEvent.click(screen.getByRole("button", { name: "Generate coordinate proposals" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Digest unavailable"));
  });

  it("keeps generated results available if a local download cannot start", async () => {
    render(<DiscoverySiteCandidates />); chooseMg();
    fireEvent.click(screen.getByRole("button", { name: "Generate coordinate proposals" }));
    await screen.findByRole("heading", { name: "3 unrelaxed coordinate proposals" });
    vi.stubGlobal("URL", { createObjectURL: vi.fn(() => { throw new Error("blocked"); }) });
    fireEvent.click(screen.getByRole("button", { name: "Download selected CIF" }));
    expect(screen.getByRole("status")).toHaveTextContent("could not start the download");
    expect(screen.getByRole("heading", { name: "3 unrelaxed coordinate proposals" })).toBeInTheDocument();
  });
});
