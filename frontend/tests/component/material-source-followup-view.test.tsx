import { fireEvent, render, screen, within, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MaterialSourceFollowup } from "@/components/MaterialSourceFollowup";
import Page from "@/app/materials/source-observations/followup/page";
import { loadSourceFollowupBatch } from "@/lib/material-source-followup";

const batch = loadSourceFollowupBatch()!;
function group(id: string) {
  const node = document.getElementById(`followup-${id}`)! as HTMLDetailsElement;
  fireEvent.click(node.querySelector("summary")!);
  return node;
}
function field(name: string) {
  const entry = batch.entries.find(item => item.field === name)!;
  return document.getElementById(entry.id.replace(/[^a-zA-Z0-9_-]/g, "-"))!;
}
function blobText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = reject; reader.readAsText(blob); });
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("Source follow-up researcher view", () => {
  it("keeps eight groups folded and distinguishes computation from inaccessible EPC values", () => {
    render(<Page />);
    const groups = document.querySelectorAll('details[id^="followup-"]');
    expect(groups).toHaveLength(8);
    expect([...groups].every(node => !(node as HTMLDetailsElement).open)).toBe(true);
    expect(screen.getByText(/31 source expressions/)).toHaveTextContent("3 unavailable settings · 8 source groups");
    expect(screen.getByRole("link", { name: "Download source-record metadata (JSON)" })).toHaveAttribute("href", "/research-pilots/materials-source-followup-2026-10-02.json");
    const node = group("ysc");
    expect(within(node).getByText("Computed")).toBeInTheDocument();
    expect(within(node).getByText("116 K at 140 GPa")).toBeInTheDocument();
    expect(within(node).getByText(/140–250 GPa; this is not a Tc measurement window/)).toBeInTheDocument();
    expect(within(node).getAllByText(/No numeric value recovered from accessible sources/)).toHaveLength(3);
    expect(within(node).getByText("Electron–phonon coupling λ")).toBeInTheDocument();
    expect(within(node).getByText("Coulomb pseudopotential μ*")).toBeInTheDocument();
  });

  it("keeps the Tm magnetic and superconducting transitions and member-specific probe limits separate", () => {
    render(<MaterialSourceFollowup batch={batch} />);
    const node = group("motm");
    const magnetic = within(field("reported_magnetic_order_and_temperature"));
    const transition = within(field("tm_member_transition_criterion"));
    expect(magnetic.getByText("17 K")).toBeInTheDocument();
    expect(magnetic.queryByText("24 K")).not.toBeInTheDocument();
    expect(transition.getByText("24 K")).toBeInTheDocument();
    expect(transition.getByText(/Deduced from χ′/)).toBeInTheDocument();
    expect(transition.getByRole("link", { name: "Open this field’s original source ↗" })).toHaveAttribute("href", expect.stringContaining("#page=6"));
    expect(within(node).getByText(/Source snapshots and locators/)).toBeInTheDocument();
    expect(within(node).queryByText(/Captured source files and versions/)).not.toBeInTheDocument();
    expect(within(field("magnetic_probe_method")).getByText(/Er figure's 30 Oe is not transferred/)).toBeInTheDocument();
    expect(within(node).getAllByRole("link", { name: "Open original source locator ↗" }).some(link => link.getAttribute("href")?.includes("#page=6"))).toBe(true);
  });

  it("preserves the Pt printed-unit conflict and the assumptions behind gamma", () => {
    render(<MaterialSourceFollowup batch={batch} />);
    group("pt_extra");
    const jump = within(field("specific_heat_jump_over_tc"));
    expect(jump.getByText("≈ 20 mJ/mol K · printed unit")).toBeInTheDocument();
    expect(jump.getByText(/no normalized unit is assigned/)).toBeInTheDocument();
    expect(jump.getByText("20 K · zero-field data; 10 T comparison")).toBeInTheDocument();
    const gamma = within(field("electronic_specific_heat_coefficient_model"));
    expect(gamma.getByText("≈ 14 mJ/(mol·K²)")).toBeInTheDocument();
    expect(gamma.getByText(/BCS ratio 1.43 and 100% superconducting volume/)).toHaveTextContent("not a direct normal-state measurement");
    expect(within(field("source_heating_program")).getByText("1150 °C")).toBeInTheDocument();
    expect(within(field("specific_heat_analysis_context")).getByText("100 % · assumed, not measured")).toBeInTheDocument();
  });

  it("preserves La–Sm preparation choices, separate database values and unresolved fraction/probe correspondence", () => {
    render(<MaterialSourceFollowup batch={batch} />);
    group("lasm");
    expect(within(field("source_anneal_temperature_options")).getByText("800 °C or 750 °C")).toBeInTheDocument();
    const probes = within(field("susceptibility_transition_definition"));
    expect(probes.getByText("ZFC/FC separation")).toBeInTheDocument();
    expect(probes.getByText("Imaginary susceptibility drops below zero")).toBeInTheDocument();
    expect(probes.getByText("4.95 K")).toBeInTheDocument();
    expect(probes.getByText("3.75 K")).toBeInTheDocument();
    expect(probes.getByText(/assignment of each database value remains unresolved/)).toBeInTheDocument();
    const fraction = within(field("meissner_measurement_method_and_conditions"));
    expect(fraction.getByText(/80 % · unit from the official data guide/)).toHaveTextContent("row supplies no unit literal");
    expect(fraction.getByText(/not assigned to a specific DC or AC curve/)).toHaveTextContent("shielding is not automatically Meissner fraction");
    expect(within(field("tc_applied_pressure_context")).getByText(/maximum study pressure is not assigned to a catalogue Tc/)).toBeInTheDocument();
  });

  it("renders the Hall exponent literally without transferring equipment or Hc2 conditions", () => {
    render(<MaterialSourceFollowup batch={batch} />);
    group("sn_in");
    const hall = within(field("hall_carrier_density_and_conditions"));
    expect(hall.getByText("8 × 10²⁰ cm⁻³")).toBeInTheDocument();
    expect(hall.getByText(/equipment's lower temperature limit is not substituted/)).toBeInTheDocument();
    expect(within(field("sample_measurement_context")).getByText("0.3 T at 0.37 K; Sharp resistivity onset")).toBeInTheDocument();
    expect(within(field("reported_gap_or_pairing_source_claim")).getByText("Explicitly beyond scope")).toBeInTheDocument();
  });

  it("retains FeSe site precision, occupancy, declared operations and both captured Hall labels", () => {
    render(<MaterialSourceFollowup batch={batch} />);
    const node = group("fese_cif");
    expect(within(node).getByText(/295 K. Pressure not supplied/)).toHaveTextContent("does not release the historical catalogue hold");
    const table = within(node).getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).getByText("0.996(3)")).toBeInTheDocument();
    expect(within(table).getByText("0.26526(14)")).toBeInTheDocument();
    expect(within(table).getByText("0.0182(4)")).toBeInTheDocument();
    expect(within(node).getByRole("region", { name: "Listed FeSe fractional sites" })).toHaveAttribute("tabindex", "0");
    const operations = field("declared_symmetry_operations");
    expect(within(operations).getByText(/16 operations declared/)).toBeInTheDocument();
    fireEvent.click(within(operations).getByText("Inspect all declared operations"));
    expect(operations.querySelectorAll("ol > li")).toHaveLength(16);
    expect(within(field("reported_hall_symbol")).getByText("P 4ab 2ab -1ab")).toBeInTheDocument();
    expect(within(field("reported_hall_symbol")).getByText("-P 4a;-2a")).toBeInTheDocument();
  });

  it("downloads only the chosen current source group and clears a failed attempt on retry", async () => {
    const exported: Blob[] = [];
    const NativeURL = URL;
    class DownloadURL extends NativeURL { static createObjectURL(blob: Blob) { exported.push(blob); return "blob:source-task-window"; } static revokeObjectURL() {} }
    vi.stubGlobal("URL", DownloadURL);
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementationOnce(() => { throw new Error("blocked"); }).mockImplementation(() => {});
    render(<MaterialSourceFollowup batch={batch} />);
    const node = group("motm");
    const download = within(node).getByRole("button", { name: "Download this source group (JSON)" });
    fireEvent.click(download);
    expect(within(node).getByRole("status")).toHaveTextContent("download is unavailable");
    expect(document.querySelector('a[download="source-followup-motm.json"]')).toBeNull();
    fireEvent.click(download);
    expect(within(node).queryByRole("status")).toBeNull();
    expect(click).toHaveBeenCalledTimes(2);
    const result = JSON.parse(await blobText(exported[1]));
    expect(result.task_records).toBe(4);
    expect(result.entries.map((entry: { id: string }) => entry.id)).toEqual(batch.entries.filter(entry => entry.source_group === "motm").map(entry => entry.id));
    expect(result).toMatchObject({ scientific_acceptance: false, canonical_promotions: 0, selected_result_association: "unestablished" });
    expect(result.entries.every((entry: { scientific_acceptance: boolean; field_locators: unknown[]; selected_result_association: string }) => entry.scientific_acceptance === false && entry.field_locators.length > 0 && entry.selected_result_association === "unestablished")).toBe(true);
    expect(JSON.stringify(result)).not.toMatch(/private_notes|evidence_text|source_excerpt|raw_record|\/Users\/|\/tmp\//);
  });
});
