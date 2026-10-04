import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import MaterialsComputationalReferencesPage from "@/app/materials/source-observations/computational-references/page";
import { MaterialComputationalNativeOutput } from "@/components/MaterialComputationalNativeOutput";
import { computationalInputContextMetadataPath, loadComputationalInputContext } from "@/lib/material-computational-input-context";
import { loadComputationalNativeOutput } from "@/lib/material-computational-native-output";

describe("Additional native input presentation", () => {
  it("shows all source occurrences without merging duplicate inputs or interpreting GGA", () => {
    render(<MaterialsComputationalReferencesPage />);
    const disclosure = screen.getByText("Full-source input settings (25 tags)").closest("details")!;
    expect(disclosure).not.toHaveAttribute("open");
    const region = screen.getByRole("region", { name: "Full native input contexts, horizontally scrollable" });
    expect(region).toHaveAttribute("tabindex", "0");
    expect(within(region).getAllByRole("row")).toHaveLength(37);
    const charges = within(region).getAllByRole("rowheader", { name: "ICHARG" }).map(header => header.closest("tr")!);
    expect(charges).toHaveLength(2);
    expect(charges[0]).toHaveTextContent("INCAR");
    expect(charges[1]).toHaveTextContent("Parameters · Electronic startup");
    expect(charges.every(row => within(row).getByText("1"))).toBe(true);
    const spins = within(region).getAllByRole("rowheader", { name: "MAGMOM" }).map(header => header.closest("tr")!);
    expect(spins).toHaveLength(2);
    for (const row of spins) {
      const cells = within(row).getAllByRole("cell");
      expect(cells[0].textContent).toBe("0.00000000      0.00000000      5.00000000");
      expect(cells[0]).toHaveClass("whitespace-pre-wrap");
      expect(cells[1]).toHaveTextContent("XML type: Not declared");
      expect(cells[1]).toHaveTextContent("Not final or ordered moments");
    }
    const gga = within(region).getByRole("rowheader", { name: "GGA" }).closest("tr")!;
    expect(within(gga).getAllByRole("cell")[0].textContent).toBe("--");
    expect(gga).toHaveTextContent("double dash remains uninterpreted");
    expect(screen.getByText(/The native GGA string/)).toHaveTextContent("PBE method label is a separate source report");
    expect(screen.getByText(/ICHARG is 1 in both INCAR/)).toHaveTextContent("does not establish original restart-file identities");
  });

  it("maps MAGMOM input to source atom order with no final moment or invented unit", () => {
    render(<MaterialsComputationalReferencesPage />);
    const region = screen.getByRole("region", { name: "Spin input atom order, horizontally scrollable" });
    expect(region).toHaveAttribute("tabindex", "0");
    expect(within(region).getAllByRole("row")).toHaveLength(4);
    const rows = within(region).getAllByRole("row").slice(1);
    expect(rows.map(row => within(row).getByRole("rowheader").textContent)).toEqual(["0", "1", "2"]);
    expect(rows.map(row => within(row).getAllByRole("cell")[1].textContent)).toEqual(["0.00000000", "0.00000000", "5.00000000"]);
    expect(rows.map(row => within(row).getAllByRole("cell")[0].textContent?.split("Atom label source")[0])).toEqual(["B", "B", "Cr"]);
    expect(screen.getByText(/These are input components/)).toHaveTextContent("no physical unit declared");
    expect(screen.getByText(/These are input components/)).toHaveTextContent("restart-dependent role remains unresolved");
  });

  it("keeps definitions, reproduction limits and finite metadata inside closed readable disclosures", () => {
    render(<MaterialsComputationalReferencesPage />);
    for (const title of ["Tag definitions in current VASP documentation", "Reproduction evidence still to recover", "Additional input-context metadata and downloads"]) {
      expect(screen.getByText(title).closest("details")).not.toHaveAttribute("open");
    }
    expect(screen.getByText(/Current definitions clarify input roles/)).toHaveTextContent("original VASP 5.3.2 edition");
    expect(screen.getByRole("link", { name: "Official MAGMOM definition" })).toHaveAttribute("href", "https://vasp.at/wiki/index.php/MAGMOM");
    expect(screen.getByRole("link", { name: "Observed revision 36612" })).toHaveAttribute("href", "https://vasp.at/wiki/index.php?title=MAGMOM&oldid=36612");
    expect(screen.getByText(/No claim that provider or original run lacks POTCAR/, { selector: "dd" })).toBeInTheDocument();
    const pre = screen.getByRole("region", { name: "Additional input-context metadata JSON" });
    expect(pre).toHaveAttribute("tabindex", "0");
    expect(pre).toHaveClass("max-h-80", "max-w-full", "overflow-auto", "whitespace-pre-wrap", "break-all");
    expect(JSON.parse(pre.textContent!)).toEqual(loadComputationalInputContext());
    expect(screen.getByRole("link", { name: "Download additional input-context JSON" })).toHaveAttribute("href", computationalInputContextMetadataPath);
    expect(screen.getByRole("link", { name: "Download additional input-context JSON" })).toHaveAttribute("download");
    expect(screen.getByRole("link", { name: "Additional input-context SHA-256" })).toHaveAttribute("href", `${computationalInputContextMetadataPath}.sha256`);
    expect(screen.getByRole("region", { name: "Complete native output metadata JSON" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("region", { name: "Computational reference metadata JSON" })).toHaveAttribute("tabindex", "0");
    expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]|\u2014/);
  });

  it("retains the earlier complete-source input settings when the additional projection is unavailable", () => {
    render(<MaterialComputationalNativeOutput data={loadComputationalNativeOutput()} additionalInputContext={null} />);
    expect(screen.getByText("Full-source input settings (17 tags)")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Additional input-context metadata is unavailable");
    const region = screen.getByRole("region", { name: "Full native input contexts, horizontally scrollable" });
    expect(within(region).getAllByRole("row")).toHaveLength(27);
    expect(within(region).queryByRole("rowheader", { name: "MAGMOM" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Download additional input-context JSON" })).toBeNull();
  });
});
