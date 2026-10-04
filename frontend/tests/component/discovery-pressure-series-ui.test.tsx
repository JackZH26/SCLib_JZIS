import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { DiscoveryPressureSeries } from "@/components/DiscoveryPressureSeries";
import { loadDiscoveryPressureSeries } from "@/lib/discovery-pressure-series";

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const plot = () => screen.getByRole("img", { name: /La[HD]10:.*quantum pressure/ });
const points = () => plot().querySelectorAll("circle[data-source-row-id]");

describe("source pressure series display", () => {
  it("starts with four LaH10 anisotropic ME points and original table scalars", () => {
    render(<DiscoveryPressureSeries />);
    expect(screen.getByRole("combobox", { name: "Source composition" })).toHaveValue("LaH10");
    expect(screen.getByRole("combobox", { name: "Reported quantity / solver" })).toHaveValue("tc_anisotropic_me");
    const table = screen.getByRole("table", { name: /LaH10 source pressure rows/ });
    expect(within(table).getAllByRole("row")).toHaveLength(5);
    expect(within(table).getByRole("cell", { name: "255.3" })).toBeInTheDocument();
    expect(within(table).getByRole("cell", { name: "171.8" })).toBeInTheDocument();
    expect(within(table).getByRole("cell", { name: "76.4" })).toBeInTheDocument();
    expect(points()).toHaveLength(4);
    expect([...points()].map(p => p.getAttribute("data-pressure"))).toEqual(["129", "163", "214", "264"]);
    expect([...points()].map(p => p.getAttribute("data-source-value"))).toEqual(["255.3", "242.8", "237.9", "216.9"]);
    expect(screen.getByText(/k-averaged static screened Coulomb interaction/, { selector: "p" })).toBeInTheDocument();
    expect(plot().querySelectorAll("polyline,path")).toHaveLength(0);
  });

  it("switches isotope series without pairing pressure grids or carrying LaH10 values", () => {
    render(<DiscoveryPressureSeries />);
    fireEvent.change(screen.getByRole("combobox", { name: "Source composition" }), { target: { value: "LaD10" } });
    expect(points()).toHaveLength(3);
    expect([...points()].map(p => p.getAttribute("data-pressure"))).toEqual(["159", "210", "260"]);
    expect([...points()].map(p => p.getAttribute("data-source-value"))).toEqual(["180.4", "172.9", "157.9"]);
    const table = screen.getByRole("table", { name: /LaD10 source pressure rows/ });
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    expect(within(table).queryByRole("cell", { name: "255.3" })).not.toBeInTheDocument();
    expect(within(table).getByRole("cell", { name: "1.80" })).toBeInTheDocument();
  });

  it("shows separate physical units and solver Coulomb treatments", () => {
    render(<DiscoveryPressureSeries />);
    const select = screen.getByRole("combobox", { name: "Reported quantity / solver" });
    fireEvent.change(select, { target: { value: "omega_log" } });
    expect([...points()].map(p => p.getAttribute("data-source-value"))).toEqual(["76.4", "96.4", "115.5", "126.6"]);
    expect(plot().textContent).toContain("ωlog (meV)");
    fireEvent.change(select, { target: { value: "electron_phonon_lambda" } });
    expect([...points()].map(p => p.getAttribute("data-source-value"))).toEqual(["3.62", "2.67", "2.06", "1.73"]);
    expect(plot().textContent).toContain("EPC λ (dimensionless)");
    fireEvent.change(select, { target: { value: "tc_isotropic_sc_dft" } });
    expect([...points()].map(p => p.getAttribute("data-source-value"))).toEqual(["230", "225", "210", "201"]);
    expect(screen.getByText(/no empirical μ\* parameter\./, { selector: "p" })).toBeInTheDocument();
    fireEvent.change(select, { target: { value: "tc_allen_dynes" } });
    expect([...points()].map(p => p.getAttribute("data-source-value"))).toEqual(["252.6", "247.0", "235.9", "219.2"]);
    expect(screen.getByText(/Assumed scalar Coulomb pseudopotential μ\* = 0.1\./, { selector: "p" })).toBeInTheDocument();
  });

  it("places the source-defined pressure and chosen scalar on physical axes", () => {
    render(<DiscoveryPressureSeries />);
    const first = points()[0];
    expect(Number(first.getAttribute("cx"))).toBeCloseTo(91.3125);
    expect(Number(first.getAttribute("cy"))).toBeCloseTo(264 - (255.3 - 100) / 180 * 230);
    expect([...points()].every(p => Number(p.getAttribute("data-pressure")) > 100)).toBe(true);
    expect(plot().textContent).toContain("without an interpolated curve");
    expect(screen.getByText(/No values are interpolated or extrapolated to 1 atm\./)).toBeInTheDocument();
  });

  it("keeps reading regions focusable and source methods closed by default", () => {
    render(<DiscoveryPressureSeries />);
    for (const name of ["Source pressure plot, horizontally scrollable", "Selected compound pressure table, horizontally scrollable"]) {
      const region = screen.getByRole("region", { name });
      expect(region).toHaveAttribute("tabindex", "0");
      expect(region.className).toContain("overflow-x-auto");
      expect(region.className).toContain("max-w-full");
    }
    expect(screen.getByText("Methods and pressure-comparison scope").closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText("Pressure study source and downloads").closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText(/A row-specific structural calculation temperature/, { selector: "p" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Read the seven-row source table" })).toHaveAttribute("href", "https://arxiv.org/pdf/1907.11916v1#page=11");
    expect(screen.getByRole("link", { name: "Download all seven source rows (JSON)" })).toHaveAttribute("download", "discovery-lah10-pressure-series-2026-10-04.json");
  });

  it("rejects a rewritten source scalar or promoted authority instead of plotting it", () => {
    const edited = loadDiscoveryPressureSeries()!;
    edited.rows[0].tc_anisotropic_me.value = 300;
    render(<DiscoveryPressureSeries table={edited} />);
    expect(screen.getByRole("status")).toHaveTextContent("The captured pressure series is unavailable.");
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("retains static download access if the browser cannot start CSV", () => {
    render(<DiscoveryPressureSeries />);
    vi.stubGlobal("URL", class extends URL { static createObjectURL() { throw new Error("unavailable"); } });
    fireEvent.click(screen.getByRole("button", { name: "Export all seven pressure rows (CSV)" }));
    expect(screen.getByText("The browser could not start the CSV download. The static JSON resource remains available.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download all seven source rows (JSON)" })).toBeInTheDocument();
  });
});
