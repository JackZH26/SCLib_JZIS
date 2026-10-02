import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import MaterialsComputationalReferencesPage, { metadata } from "@/app/materials/source-observations/computational-references/page";
import MaterialsSourceObservationsPage from "@/app/materials/source-observations/page";
import { MaterialComputationalReference } from "@/components/MaterialComputationalReference";
import { computationalReferenceMetadataPath, loadComputationalReference } from "@/lib/material-computational-reference";

const data = loadComputationalReference()!;
describe("Computational reference scientific presentation", () => {
  it("presents one computed entry with readable method, grid and workflow metadata", () => {
    render(<MaterialsComputationalReferencesPage />);
    expect(screen.getByRole("heading", { level: 1, name: "Computational references" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "CrB₂: independent computed reference" })).toBeInTheDocument();
    expect(screen.getByText(/one independent computed entry, with no selected superconducting result/)).toBeInTheDocument();
    const method = screen.getByRole("heading", { name: "Reported archive method" }).closest("section")!;
    expect(within(method).getByText("VASP 5.3.2")).toBeInTheDocument();
    expect(within(method).getByText("DFT, PBE (GGA_C_PBE + GGA_X_PBE)")).toBeInTheDocument();
    expect(within(method).getByText("Gamma-centered, 14 × 14 × 11")).toBeInTheDocument();
    expect(within(method).getByText("2156")).toBeInTheDocument();
    expect(within(method).getByText("Cell-shape optimization (cell_shape), 3 reported steps")).toBeInTheDocument();
    expect(within(method).getByText(/Independent numerical convergence and a validated final geometry have not been established/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open NOMAD entry" })).toHaveAttribute("href", data.reference.entry_url);
    expect(metadata.alternates).toMatchObject({ canonical: expect.stringContaining("/materials/source-observations/computational-references") });
  });

  it("keeps all eight native inputs literal with distinct source/documentation cues", () => {
    render(<MaterialComputationalReference data={data} />);
    const region = screen.getByRole("region", { name: "Native VASP input settings, horizontally scrollable" });
    expect(region).toHaveAttribute("tabindex", "0");
    expect(region).toHaveClass("max-w-full", "overflow-x-auto");
    expect(within(region).getAllByRole("row")).toHaveLength(9);
    const ediff = within(region).getByRole("rowheader", { name: "EDIFF" }).closest("tr")!;
    expect(within(ediff).getByText("0.00010000")).toBeInTheDocument();
    expect(within(ediff).getByText("eV")).toBeInTheDocument();
    expect(within(ediff).getByText("Native input source").closest("details")).not.toHaveAttribute("open");
    expect(within(region).getAllByText("Integer code")).toHaveLength(2);
    expect(within(region).getAllByText("Logical flag")).toHaveLength(2);
    expect(within(region).queryByText("Unit unresolved")).not.toBeInTheDocument();
    const stress = within(region).getByRole("rowheader", { name: "PSTRESS" }).closest("tr")!;
    expect(within(stress).getByText("0.00000000")).toBeInTheDocument();
    expect(within(stress).getByText("Model input, not Tc pressure")).toBeInTheDocument();
    expect(within(stress).getByText(/not a Tc measurement pressure, applied experimental pressure or ambient-pressure classification/)).toBeInTheDocument();
    const sigma = within(region).getByRole("rowheader", { name: "SIGMA" }).closest("tr")!;
    expect(within(sigma).getByText("0.20000000")).toBeInTheDocument();
    expect(within(sigma).getByText(/no measured temperature is assigned/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Official EDIFF unit definition" })).toHaveAttribute("href", "https://vasp.at/wiki/index.php/EDIFF");
    expect(screen.getByText(/ENCUT:/).parentElement).toHaveTextContent("not found in the two complete checked blocks");
  });

  it("displays documented eV/kB and Methfessel-Paxton meaning while preserving the unmodified raw-row unit slots", () => {
    render(<MaterialComputationalReference data={data} />);
    const region = screen.getByRole("region", { name: "Native VASP input settings, horizontally scrollable" });
    for (const [tag, unit] of [["SIGMA", "eV"], ["ENAUG", "eV"], ["PSTRESS", "kB"]]) {
      const row = within(region).getByRole("rowheader", { name: tag }).closest("tr")!;
      expect(within(row).getByText(unit)).toBeInTheDocument();
      expect(within(row).getByText("Native-tag documentation")).toBeInTheDocument();
      expect(data.native_inputs.find(input => input.native_tag === tag)!.unit).toBeNull();
    }
    const smear = within(region).getByRole("rowheader", { name: "ISMEAR" }).closest("tr")!;
    expect(within(smear).getByText("Methfessel-Paxton order 1")).toBeInTheDocument();
    expect(within(smear).getByText("Native-tag documentation")).toBeInTheDocument();
    expect(screen.getAllByText(/Capture kind: rendered page text; original HTML response hash not established/)).toHaveLength(4);
    expect(screen.getByText(/four direct revision requests returned 403/)).toBeInTheDocument();
    expect(screen.getByText(/They do not establish legacy archive units or a historical VASP 5.3.2 documentation edition/)).toBeInTheDocument();
  });

  it("separates native ISPIN, normalized DOS spin, input/output systems and incomplete capture", () => {
    render(<MaterialComputationalReference data={data} />);
    expect(screen.getByText(/This is separate from native/)).toHaveTextContent("normalized archive DOS metadata reports true. This is separate from native ISPIN 2");
    expect(screen.getByText(/Workflow input system 0 and calculation-linked output system 2 differ/)).toBeInTheDocument();
    expect(screen.getByText(/Projection 2 compacts the selected original system 2 to response array index 0/)).toBeInTheDocument();
    expect(screen.getByText(/The whole XML is incomplete; the final calculation was not inspected/)).toBeInTheDocument();
    expect(screen.getByText(/Raw coordinate arrays remain unit-unresolved source metadata/)).toBeInTheDocument();
    expect(screen.getByText(/No new calculation, canonical promotion, scientific acceptance or ML training approval/)).toBeInTheDocument();
  });

  it("shows exact potential label strings without implying POTCAR identity or reproduction", () => {
    render(<MaterialComputationalReference data={data} />);
    const section = screen.getByRole("heading", { name: "Native potential labels" }).closest("section")!;
    expect(within(section).getAllByRole("row")).toHaveLength(3);
    expect(within(section).getByText("PAW_PBE B 06Sep2000")).toBeInTheDocument();
    expect(within(section).getByText("PAW_PBE Cr 06Sep2000")).toBeInTheDocument();
    expect(within(section).getByText(/POTCAR bytes, hashes, license and availability remain unestablished/)).toBeInTheDocument();
    expect(within(section).getByText(/These labels do not prove reproduction/)).toBeInTheDocument();
  });

  it("renders the actual finite metadata as escaped, closed, focusable and bounded JSON with an optional static link", () => {
    render(<MaterialComputationalReference data={data} />);
    const pre = screen.getByLabelText("Computational reference metadata JSON");
    expect(pre.closest("details")).not.toHaveAttribute("open");
    expect(pre).toHaveAttribute("tabindex", "0");
    expect(pre).toHaveClass("max-h-80", "max-w-full", "overflow-auto", "whitespace-pre-wrap", "break-all");
    const rendered = JSON.parse(pre.textContent!);
    expect(rendered).toEqual(data);
    expect(rendered.native_inputs[0].raw_scalar_lexeme).toBe("0.00010000");
    expect(rendered.archive_fields).toHaveLength(22);
    expect(rendered.native_inputs).toHaveLength(8);
    expect(rendered.native_potential_labels).toHaveLength(2);
    expect(rendered.authority.scientific_acceptance).toBe(false);
    expect(rendered.native_source.complete_file_established).toBe(false);
    const link = screen.getByRole("link", { name: "Static metadata JSON resource" });
    expect(link).toHaveAttribute("href", computationalReferenceMetadataPath);
    expect(link).not.toHaveAttribute("download");
    expect(link).not.toHaveAttribute("onclick");
    expect(document.querySelector('a[href^="blob:"]')).toBeNull();
  });

  it("keeps source-version and unit limits readable in folded disclosures", () => {
    render(<MaterialComputationalReference data={data} />);
    const disclosure = screen.getByText("Source identity, capture and remaining units").closest("details")!;
    expect(disclosure).not.toHaveAttribute("open");
    expect(within(disclosure).getByText(/does not establish an atomic snapshot across projections/)).toBeInTheDocument();
    expect(within(disclosure).getByText(/original raw archive, XML and documentation bodies are not redistributed/)).toBeInTheDocument();
    expect(within(disclosure).getAllByText(/unit unresolved/)).toHaveLength(3);
    expect(within(disclosure).getByText(/date\/time strings establish no timezone, publication time or successful completion/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]|\u2014/);
  });

  it("handles an unavailable snapshot without displaying a partial or invented reference", () => {
    render(<MaterialComputationalReference data={null} />);
    expect(screen.getByRole("status")).toHaveTextContent("Captured computational reference metadata is unavailable");
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("makes the new reference discoverable from the existing source index without replacing its source links", () => {
    render(<MaterialsSourceObservationsPage />);
    expect(screen.getByRole("link", { name: "Computational references" })).toHaveAttribute("href", "/materials/source-observations/computational-references");
    expect(screen.getByRole("link", { name: "Paper and CIF reference pilot" })).toHaveAttribute("href", "/materials/source-references");
    expect(screen.getByRole("link", { name: "Preparation, probes and additional sources" })).toHaveAttribute("href", "/materials/source-observations/followup");
  });
});
