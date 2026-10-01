import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import MaterialsSourceReferencesPage from "@/app/materials/source-references/page";
import pilot from "@/public/research-pilots/materials-source-references-2026-10-02.json";

describe("researcher source reference pilot", () => {
  it("keeps rounded and detailed Tc pressures separate and exposes derived dependencies", () => {
    render(<MaterialsSourceReferencesPage />);
    const summary = within(document.getElementById("crb2-summary-tc-pressure")!);
    const detailed = within(document.getElementById("crb2-detailed-tc-pressure")!);
    expect(summary.getByText("7 K at approximately 100 GPa")).toBeInTheDocument();
    expect(summary.queryByText(/110\.4 GPa/)).not.toBeInTheDocument();
    expect(detailed.getByText("Approximately 7.3 K at 110.4 GPa")).toBeInTheDocument();
    const field = within(document.getElementById("crb2-derived-hc2")!);
    expect(field.getByText(/Zero-temperature extrapolation/)).toBeInTheDocument();
    expect(field.getByRole("link", { name: "Related: Transition criterion" })).toHaveAttribute("href", "#crb2-tc-criterion");
    expect(within(document.getElementById("crb2-derived-coherence-length")!).getByRole("link", { name: /Related: Upper critical field/ })).toHaveAttribute("href", "#crb2-derived-hc2");
  });

  it("retains unknown CIF pressure, occupancy uncertainty and mutable-download limits without a catalogue association", () => {
    render(<MaterialsSourceReferencesPage />);
    const fe = within(screen.getByRole("article", { name: "FeSe" }));
    expect(fe.getByText("295 K · Pressure not supplied")).toBeInTheDocument();
    expect(fe.getByText(/0\.996\(3\) · standard uncertainty 0\.003/)).toBeInTheDocument();
    expect(fe.getByRole("link", { name: "Current CIF download" })).toHaveAttribute("href", "https://www.crystallography.net/cod/4002152.cif");
    expect(fe.queryByRole("link", { name: "CIF revision download" })).not.toBeInTheDocument();
    expect(fe.getByText(/future downloads may differ/)).toBeInTheDocument();
    expect(pilot.structure_references.every(item => item.pressure_gpa === null && item.selected_result_association === "unestablished")).toBe(true);
    expect(pilot.boundary.scientific_acceptance).toBe(false);
    expect(pilot.boundary.canonical_promotions).toBe(0);
    expect(screen.getByRole("link", { name: "Download reference metadata (JSON)" })).toHaveAttribute("href", `${process.env.NEXT_PUBLIC_BASE_PATH || ""}/research-pilots/materials-source-references-2026-10-02.json`);
  });
});
