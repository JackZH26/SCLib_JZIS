import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import Page, { metadata } from "@/app/materials/source-observations/nbsctizr-annealing/page";
import { MaterialAnnealingEvidence } from "@/components/MaterialAnnealingEvidence";
import { loadNbsctizrAnnealing, nbsctizrAnnealingDownloadPath, nbsctizrAnnealingSnapshotSha256 } from "@/lib/material-nbsctizr-annealing";

afterEach(() => { cleanup(); });

const fold = (name: string) => screen.getByText(name, { selector: "summary" }).closest("details")!;

describe("NbScTiZr source comparison reading", () => {
  it("provides an English reading page with material and Discovery navigation", () => {
    render(<Page />);
    expect(screen.getByRole("heading", { level: 1, name: "NbScTiZr annealing comparison" })).toBeInTheDocument();
    const nav = within(screen.getByRole("navigation", { name: "Materials source pages" }));
    expect(nav.getByRole("link", { name: "Materials catalogue" })).toHaveAttribute("href", "/materials");
    expect(nav.getByRole("link", { name: "Source observations" })).toHaveAttribute("href", "/materials/source-observations");
    expect(nav.getByRole("link", { name: "Discovery source comparisons" })).toHaveAttribute("href", "/discovery#discovery-source-comparisons");
    expect(metadata.title).toBe("NbScTiZr annealing and superconducting source reports");
    expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]/);
  });

  it("shows two distinct Tc reports with preparation labels and source-specific criterion context", () => {
    render(<MaterialAnnealingEvidence />);
    const oldTable = within(screen.getByRole("table", { name: "2023 Table 1 transition temperatures" }));
    expect(oldTable.getAllByRole("row")).toHaveLength(5);
    expect(oldTable.getByRole("row", { name: "as-cast 7.9" })).toBeInTheDocument();
    expect(oldTable.getByRole("row", { name: "400 °C 8.4" })).toBeInTheDocument();
    expect(oldTable.getByRole("row", { name: "800 °C 9.0" })).toBeInTheDocument();
    expect(oldTable.getByRole("row", { name: "1000 °C 8.7" })).toBeInTheDocument();
    expect(oldTable.queryByRole("row", { name: /^600 °C/ })).not.toBeInTheDocument();
    const recentTable = within(screen.getByRole("table", { name: "2024 Table 2 refined transition temperatures" }));
    expect(recentTable.getAllByRole("row")).toHaveLength(6);
    expect(recentTable.getByRole("row", { name: "as-cast 8.11" })).toBeInTheDocument();
    expect(recentTable.getByRole("row", { name: "600 °C 9.36" })).toBeInTheDocument();
    expect(recentTable.getByRole("row", { name: "800 °C 9.13" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "2023: ac-susceptibility onset" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "2024: refined Tc, Hc2 analysis" })).toBeInTheDocument();
    expect(screen.getByText(/5 Oe · 800 Hz · measurement range 3-20 K/)).toBeInTheDocument();
    expect(screen.getByText(/Its Tc values are not assigned the calorimetry midpoint criterion/)).toBeInTheDocument();
    expect(screen.getByText(/As-cast has no annealing temperature/)).toBeInTheDocument();
    expect(screen.getByText(/Measurement pressure is not supplied/)).toBeInTheDocument();
  });

  it("keeps default details closed while exposing the two separately fitted critical-field channels", () => {
    render(<MaterialAnnealingEvidence />);
    for (const name of ["All 15 parameters from 2024 Table 2", "Phase compositions, lattice parameters and phase fractions", "Electronic specific-heat fits", "Sources, methods and downloads"])
      expect(fold(name)).not.toHaveAttribute("open");
    const channels = within(screen.getByRole("table", { name: "2024 Table 2 WHH upper critical field channels" }));
    expect(channels.getAllByRole("row")).toHaveLength(6);
    expect(channels.getByRole("columnheader", { name: "μ0 Hc2ᴹ(0) (T)" })).toHaveAttribute("scope", "col");
    expect(channels.getByRole("columnheader", { name: "μ0 Hc2ρ(0) (T)" })).toHaveAttribute("scope", "col");
    expect(channels.getByRole("row", { name: "as-cast 13.1 12.8" })).toBeInTheDocument();
    expect(channels.getByRole("row", { name: "800 °C 13.9 15.0" })).toBeInTheDocument();
    expect(screen.getByText(/Hc2\(0\) is an extrapolated source fit/)).toHaveTextContent("rather than a measurement at 0 K");
  });

  it("renders all parameter roles and preserves the source units and printed uncertainty notation", () => {
    render(<MaterialAnnealingEvidence />);
    fireEvent.click(screen.getByText("All 15 parameters from 2024 Table 2", { selector: "summary" }));
    const table = within(screen.getByRole("table", { name: "2024 complete superconducting parameters and hardness" }));
    expect(table.getAllByRole("row")).toHaveLength(16);
    expect(table.getByRole("row", { name: "γel mJ/(mol·K²) 6.47 6.79 5.77 5.46 6.62" })).toBeInTheDocument();
    expect(table.getByRole("row", { name: "β mJ/(mol·K⁴) 0.150 0.127 0.127 0.129 0.145" })).toBeInTheDocument();
    expect(table.getByRole("row", { name: "μ0 Hc1(0) mT 29.1 32.9 22.9 22.2 4.46" })).toBeInTheDocument();
    expect(table.getByRole("row", { name: "λGLᴹ(0) nm 137 128 159 161 405" })).toBeInTheDocument();
    expect(table.getByRole("row", { name: "Vickers hardness HV 336(1) 345(4) 264(6) 239(2) 230(2)" })).toBeInTheDocument();
    expect(screen.getByText(/γel and β include both bcc and hcp contributions/)).toHaveTextContent("source-derived GL estimates");
    expect(screen.getByText(/Parentheses remain uninterpreted uncertainty notation/)).toBeInTheDocument();
  });

  it("keeps source phase rows distinct, including unlisted lattice cells and the missing 2023 600-degree group", () => {
    render(<MaterialAnnealingEvidence />);
    fireEvent.click(screen.getByText("Phase compositions, lattice parameters and phase fractions", { selector: "summary" }));
    const oldTable = within(screen.getByRole("table", { name: "2023 Table 1: phase compositions, volume fractions and VEC" }));
    const recentTable = within(screen.getByRole("table", { name: "2024 Table 1: phase compositions and lattice parameters" }));
    expect(oldTable.getAllByRole("row")).toHaveLength(9);
    expect(recentTable.getAllByRole("row")).toHaveLength(11);
    expect(oldTable.queryByRole("row", { name: /^600 °C/ })).not.toBeInTheDocument();
    expect(recentTable.getAllByRole("row", { name: /^600 °C/ })).toHaveLength(2);
    expect(recentTable.getAllByText("Not listed")).toHaveLength(5);
    expect(oldTable.getAllByText("Not listed")).toHaveLength(4);
    expect(recentTable.getByRole("row", { name: "as-cast hcp 21.3(4) 30(1) 23.0(7) 25.8(5) 3.262(3) 5.152(3)" })).toBeInTheDocument();
    expect(screen.getByText(/SEM phase volume fractions are separate from superconducting volume fractions/)).toBeInTheDocument();
    expect(screen.getByText(/600 °C is not listed in the captured 2023 v1 Table 1/)).toBeInTheDocument();
  });

  it("renders four calorimetric fits without adding an as-cast gap estimate or silently using tabulated Tc", () => {
    render(<MaterialAnnealingEvidence />);
    fireEvent.click(screen.getByText("Electronic specific-heat fits", { selector: "summary" }));
    const table = within(screen.getByRole("table", { name: "2024 electronic specific-heat fit parameters" }));
    expect(table.getAllByRole("columnheader")).toHaveLength(5);
    expect(table.queryByRole("columnheader", { name: "as-cast" })).not.toBeInTheDocument();
    expect(table.getByRole("row", { name: "Δ(0) meV 1.16 1.73 1.84 1.66" })).toBeInTheDocument();
    expect(table.getByRole("row", { name: "2Δ(0)/(kB Tc) 3.22 4.43 4.85 4.56" })).toBeInTheDocument();
    expect(screen.getByText(/The heat-jump normalization uses a calorimetry midpoint Tc/)).toHaveTextContent("as-cast transition is too broad");
    expect(screen.getByText(/does not establish a global pairing classification or electron–phonon λ/)).toBeInTheDocument();
  });

  it("provides focusable named table regions, source page links and real versioned metadata downloads", () => {
    render(<Page />);
    const region = screen.getByRole("region", { name: "2024 upper critical field probe channels, horizontally scrollable" });
    region.focus(); expect(region).toHaveFocus(); expect(region).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("link", { name: "Read the 2023 Tc table" })).toHaveAttribute("href", "https://arxiv.org/pdf/2311.00195v1#page=4");
    expect(screen.getByRole("link", { name: "Read the 2024 parameter table" })).toHaveAttribute("href", "https://arxiv.org/pdf/2406.19553v1#page=9");
    fireEvent.click(screen.getByText("Sources, methods and downloads", { selector: "summary" }));
    expect(screen.getByRole("link", { name: "Download all source values (JSON)" })).toHaveAttribute("href", nbsctizrAnnealingDownloadPath);
    expect(screen.getByRole("link", { name: "Download all source values (JSON)" })).toHaveAttribute("download");
    expect(screen.getByRole("link", { name: "Download file SHA-256" })).toHaveAttribute("href", nbsctizrAnnealingDownloadPath + ".sha256");
    expect(screen.getByRole("link", { name: "Read arXiv:2311.00195v1" })).toHaveAttribute("href", "https://arxiv.org/pdf/2311.00195v1");
    expect(screen.getByRole("link", { name: "Read arXiv:2406.19553v1" })).toHaveAttribute("href", "https://arxiv.org/pdf/2406.19553v1");
    expect(screen.getByText(nbsctizrAnnealingSnapshotSha256)).toBeInTheDocument();
    for (const link of screen.getAllByRole("link", { name: "Read source passage" })) {
      expect(link.getAttribute("href")).toMatch(/^https:\/\/arxiv\.org\/pdf\/(2311\.00195|2406\.19553)v1#page=\d+$/);
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
    }
    expect(document.body.textContent).not.toMatch(/\/Users\/|\/private\//);
  });

  it("withdraws tables when the finite source values or authority are altered", () => {
    const data = loadNbsctizrAnnealing()!;
    data.parameter_table.rows[0].cells.hc2_m_zero_t.raw_value = "19.1";
    render(<MaterialAnnealingEvidence data={data} />);
    expect(screen.getByRole("status")).toHaveTextContent("captured NbScTiZr annealing comparison is unavailable");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
