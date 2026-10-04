import { createHash, webcrypto } from "node:crypto";
import { act } from "react";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DiscoveryCombinedCandidates } from "@/components/DiscoveryCombinedCandidates";
import { combinedPlan, generateCombinedCandidates, type CombinedInput } from "@/lib/discovery-combined-candidates";
import { generateSiteCandidates, supercellModel } from "@/lib/discovery-site-candidates";

beforeEach(() => { vi.stubGlobal("crypto", webcrypto); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const model = () => supercellModel("cod-1526507", [2, 2, 2]);
const mg = () => model().atoms.filter(atom => atom.element === "Mg");
const boron = () => model().atoms.find(atom => atom.element === "B")!;
const request = (): CombinedInput => ({ referenceId: "cod-1526507", repeats: [2, 2, 2], strain: "-2, 0, +2",
  sites: [{ targetId: mg()[0].id, replacements: "Al, Al", vacancy: false, unchanged: true },
    { targetId: boron().id, replacements: "C", vacancy: true, unchanged: true }] });
const sha = (text: string) => createHash("sha256").update(text).digest("hex");

describe("Combined ordered candidates", () => {
  it("enumerates the actual cross product with duplicate/no-change accounting", async () => {
    const input = request(), plan = combinedPlan(input);
    expect(plan.counts).toEqual({ raw_combinations: 27, distinct_combinations: 18, duplicate_choice_combinations: 9,
      generated_candidates: 17, unchanged_baselines: 1, empty_cells: 0 });
    const batch = await generateCombinedCandidates(input);
    expect(batch.candidates).toHaveLength(17);
    const co = batch.candidates.find(candidate => candidate.edits.length === 2 && candidate.edits.some(edit => edit.operation.element === "C") && candidate.strain_percent === 2)!;
    expect(co.composition).toEqual({ Al: 1, B: 15, C: 1, Mg: 7 });
    expect(co.nominal_change).toMatchObject({ changed_sites: 2, original_total_sites: 24, original_total_site_fraction: 2 / 24,
      by_original_species: [{ element: "B", changed_sites: 1, original_species_sites: 16, fraction: 1 / 16 }, { element: "Mg", changed_sites: 1, original_species_sites: 8, fraction: 1 / 8 }] });
    expect(co.volume_ratio).toBeCloseTo(1.061208, 12);
    expect(co.cell.a).toBeCloseTo(model().cell.a * 1.02, 12);
    expect(co.cell.gamma).toBe(120);
    for (const atom of co.atoms) expect(atom.fractional).toEqual(model().atoms.find(source => source.id === atom.id)!.fractional);
    const vacancy = batch.candidates.find(candidate => candidate.edits.length === 2 && candidate.edits.some(edit => edit.operation.kind === "vacancy"))!;
    expect(vacancy.atoms).toHaveLength(23); expect(vacancy.composition).toEqual({ Al: 1, B: 15, Mg: 7 });
    expect(batch.candidates.filter(candidate => !candidate.edits.length).map(candidate => candidate.strain_percent)).toEqual([-2, 2]);
    expect(batch.boundary).toMatchObject({ charge_state: null, magnetic_state: null, pressure_gpa: null, temperature_k: null, relaxed: false, energy_calculated: false, database_write: false });
  });

  it("counts two same-species changes against the original denominator and preserves untouched atoms", async () => {
    const input = request(); input.strain = "0"; input.sites = [mg()[0], mg()[1]].map(atom => ({ targetId: atom.id, replacements: "Al", vacancy: false, unchanged: false }));
    const batch = await generateCombinedCandidates(input), candidate = batch.candidates[0];
    expect(candidate.composition).toEqual({ Al: 2, B: 16, Mg: 6 });
    expect(candidate.nominal_change.by_original_species).toEqual([{ element: "Mg", changed_sites: 2, original_species_sites: 8, fraction: 0.25 }]);
    const changed = new Set(candidate.edits.map(edit => edit.target.id));
    expect(candidate.atoms.filter(atom => !changed.has(atom.id))).toEqual(batch.baseline.atoms.filter(atom => !changed.has(atom.id)));
    candidate.atoms[0].fractional[0] = 99;
    expect(batch.baseline.atoms[0].fractional[0]).not.toBe(99);
    expect(model().atoms[0].fractional[0]).not.toBe(99);
  });

  it("preserves the existing parent identity and makes candidate identity independent of input order", async () => {
    const input = request(), batch = await generateCombinedCandidates(input);
    const other = { ...input, strain: "2.000000,-2.0,+0,-0", sites: input.sites.slice().reverse().map(site => ({ ...site, replacements: site.replacements === "Al, Al" ? "Al" : site.replacements })) };
    const reordered = await generateCombinedCandidates(other);
    expect(reordered.candidates).toEqual(batch.candidates);
    expect(batch.parent_id).toBe((await generateSiteCandidates(input.referenceId, input.repeats, mg()[0].id, "Al", false)).parent_id);
    expect(new Set(batch.candidates.map(item => item.id)).size).toBe(17);
    for (const candidate of batch.candidates) {
      expect(candidate.cif_sha256).toBe(sha(candidate.cif));
      expect(candidate.cif).toContain("_symmetry_space_group_name_H-M 'P 1'");
      expect(candidate.cif).not.toMatch(/_cell_measurement_temperature|_cell_measurement_pressure|_diffrn_ambient_temperature/);
      expect(candidate.cif.split("\n").filter(line => /^S\d+ /.test(line))).toHaveLength(candidate.atoms.length);
    }
  });

  it("rejects ambiguous/conflicting input and oversized products before preparing candidates", () => {
    const input = request();
    expect(() => combinedPlan({ ...input, sites: [input.sites[0], input.sites[0]] })).toThrow(/only once/);
    expect(() => combinedPlan({ ...input, sites: [] })).toThrow(/1 to 3/);
    expect(() => combinedPlan({ ...input, sites: Array(4).fill(input.sites[0]) })).toThrow(/1 to 3/);
    expect(() => combinedPlan({ ...input, referenceId: "cod-4002152" })).toThrow(/disorder model/);
    expect(() => combinedPlan({ ...input, repeats: [4, 4, 4] })).toThrow(/192 sites/);
    expect(() => combinedPlan({ ...input, sites: [{ ...input.sites[0], targetId: "foreign" }] })).toThrow(/current supercell/);
    expect(() => combinedPlan({ ...input, sites: [{ ...input.sites[0], replacements: "Mg" }] })).toThrow(/itself/);
    for (const strain of ["", "1e-2", "NaN", "Infinity", "10.000001", "-10.1", "1.1234567", "0,", "1,2,3,4,5,6,7,8,9"]) expect(() => combinedPlan({ ...input, strain })).toThrow();
    const large = { ...input, strain: "-3,-2,-1,0,1,2,3,4", sites: input.sites.map(site => ({ ...site, replacements: "Al, Ca, Li", vacancy: false, unchanged: true })) };
    expect(() => combinedPlan(large)).toThrow(/128 distinct combinations/);
    expect(combinedPlan({ ...large, strain: "-2,-1,0,1" }).counts.distinct_combinations).toBe(64);
  });

  it("never emits an empty crystal or an unchanged zero-strain baseline", async () => {
    const atoms = supercellModel("cod-1526507", [1, 1, 1]).atoms;
    const input: CombinedInput = { referenceId: "cod-1526507", repeats: [1, 1, 1], strain: "0,1", sites: atoms.map(atom => ({ targetId: atom.id, replacements: "", vacancy: true, unchanged: false })) };
    expect(combinedPlan(input).counts.empty_cells).toBe(2);
    await expect(generateCombinedCandidates(input)).rejects.toThrow(/No changed, nonempty/);
    input.strain = "-0,+0,0.000000"; input.sites = [{ targetId: atoms[0].id, replacements: "", vacancy: false, unchanged: true }];
    expect(combinedPlan(input).counts).toMatchObject({ distinct_combinations: 1, unchanged_baselines: 1, generated_candidates: 0 });
  });

  it("freezes caller inputs before a delayed hash can change the proposal", async () => {
    let release: () => void = () => {};
    const digest = vi.fn().mockImplementationOnce(async (algorithm, bytes) => { await new Promise<void>(resolve => { release = resolve; }); return webcrypto.subtle.digest(algorithm, bytes); }).mockImplementation((algorithm, bytes) => webcrypto.subtle.digest(algorithm, bytes));
    vi.stubGlobal("crypto", { subtle: { digest } });
    const input = request(), pending = generateCombinedCandidates(input);
    input.strain = "10"; input.sites[0].replacements = "Ca"; input.repeats[0] = 4;
    release(); const batch = await pending;
    expect(batch.requested).toEqual(request()); expect(batch.candidates).toHaveLength(17);
  });
});

describe("Combined coordinate workspace", () => {
  function fill() {
    fireEvent.change(screen.getByRole("combobox", { name: "Source structure" }), { target: { value: "cod-1526507" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Modification 1 atomic site" }), { target: { value: mg()[0].id } });
    fireEvent.change(screen.getByRole("textbox", { name: "Modification 1 replacement elements" }), { target: { value: "Al" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Modification 1 unchanged option" }), { target: { value: "yes" } });
    fireEvent.click(screen.getByRole("button", { name: "Add another site" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Modification 2 atomic site" }), { target: { value: boron().id } });
    fireEvent.change(screen.getByRole("textbox", { name: "Modification 2 replacement elements" }), { target: { value: "C" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Modification 2 vacancy option" }), { target: { value: "yes" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Modification 2 unchanged option" }), { target: { value: "yes" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Uniform linear changes (%)" }), { target: { value: "-2, 0, 2" } });
  }
  it("hydrates, exposes 17 combinations across three pages, and keeps selection and export scope explicit", async () => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    const container = document.createElement("div"); container.innerHTML = renderToString(<DiscoveryCombinedCandidates />); document.body.append(container);
    const recoverable = vi.fn(); let root: ReturnType<typeof hydrateRoot> | undefined;
    try {
      await act(async () => { root = hydrateRoot(container, <DiscoveryCombinedCandidates />, { onRecoverableError: recoverable }); });
      fill(); fireEvent.click(screen.getByRole("button", { name: "Generate combined candidates" }));
      await screen.findByRole("heading", { name: "17 combined coordinate candidates" });
      fireEvent.click(screen.getByRole("button", { name: "Next combinations" }));
      fireEvent.click(screen.getByRole("button", { name: "Next combinations" }));
      expect(screen.getByText("Page 3 of 3")).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Inspect combination 17" }));
      expect(screen.getByRole("heading", { name: "Selected combination 17" })).toBeInTheDocument();
      expect(screen.getByRole("region", { name: "Scrollable combined candidate table" })).toHaveAttribute("tabindex", "0");
      vi.stubGlobal("URL", { createObjectURL: vi.fn(() => { throw new Error("blocked"); }) });
      fireEvent.click(screen.getByRole("button", { name: "Download all candidates JSON" }));
      expect(screen.getByRole("status")).toHaveTextContent("could not start the download");
      expect(screen.getByRole("heading", { name: "17 combined coordinate candidates" })).toBeInTheDocument();
      fireEvent.change(screen.getByRole("textbox", { name: "Uniform linear changes (%)" }), { target: { value: "1" } });
      expect(screen.queryByRole("heading", { name: "17 combined coordinate candidates" })).not.toBeInTheDocument();
      expect(container.textContent).not.toMatch(/[\u4e00-\u9fff]/); expect(recoverable).not.toHaveBeenCalled(); expect(fetch).not.toHaveBeenCalled();
    } finally { await act(async () => root?.unmount()); container.remove(); }
  });

  it("discards delayed generation on a source edit and blocks unresolved occupancy", async () => {
    let release: (value: ArrayBuffer) => void = () => {};
    const digest = vi.fn().mockImplementationOnce(() => new Promise<ArrayBuffer>(resolve => { release = resolve; })).mockImplementation((algorithm, bytes) => webcrypto.subtle.digest(algorithm, bytes));
    vi.stubGlobal("crypto", { subtle: { digest } });
    render(<DiscoveryCombinedCandidates />); fill(); fireEvent.click(screen.getByRole("button", { name: "Generate combined candidates" }));
    expect(screen.getByRole("button", { name: "Preparing combinations…" })).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox", { name: "Source structure" }), { target: { value: "cod-4002152" } });
    await act(async () => { release(new ArrayBuffer(32)); });
    await waitFor(() => expect(digest.mock.calls.length).toBeGreaterThan(4));
    expect(screen.queryByRole("heading", { name: /combined coordinate candidates/ })).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("disorder model");
    expect(screen.getByRole("button", { name: "Generate combined candidates" })).toBeDisabled();
  });
});
