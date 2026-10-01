import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MaterialSourceObservations } from "@/components/MaterialSourceObservations";
import MaterialsSourceObservationsPage from "@/app/materials/source-observations/page";
import {
  loadSourceObservationBatch, sourceObservationDownloadPath, sourceObservationWindow,
  type SourceObservationWindow,
} from "@/lib/material-source-observations";

const batch = loadSourceObservationBatch()!;
function windowFor(group?: string): SourceObservationWindow {
  return sourceObservationWindow(group ? batch.entries.filter(entry => entry.source_group === group) : batch.entries,
    group === "pt" ? "mat:bafe1.906pt0.094as2" : group === "cs_nb" ? "mat:cs(v0.93nb0.07)3sb5" : null,
    "independent_captured_sources")!;
}
function observation(field: string) {
  const entry = batch.entries.find(item => item.field === field)!;
  return within(document.getElementById(entry.id.replace(/[^a-zA-Z0-9_-]/g, "-"))!);
}
function blobText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = reject;
    reader.readAsText(blob);
  });
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("researcher-facing source observations", () => {
  it("folds material details by default, while the independent page exposes four distinct source windows", () => {
    const detail = render(<MaterialSourceObservations window={windowFor("pt")} />);
    const disclosure = screen.getByText("Additional source observations (5)").closest("details")!;
    expect(disclosure).not.toHaveAttribute("open");
    fireEvent.click(disclosure.querySelector("summary")!);
    expect(disclosure).toHaveAttribute("open");
    expect(screen.getByRole("heading", { name: "dHc₂/dT" })).toBeInTheDocument();
    detail.unmount();
    render(<MaterialsSourceObservationsPage />);
    expect(screen.getByText("Additional source observations (15)").closest("details")).toHaveAttribute("open");
    expect(screen.getByRole("heading", { name: /Pt substituted/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /ambient prose fit/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /pressure-series table, 0 GPa/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /CrB₂ · captured COD/ })).toBeInTheDocument();
    expect(screen.getByText(/15 field projections across 4 source windows/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download captured observation metadata (JSON)" })).toHaveAttribute("href", sourceObservationDownloadPath);
    expect(screen.getByRole("link", { name: "Download SHA-256" })).toHaveAttribute("href", `${sourceObservationDownloadPath}.sha256`);
  });

  it("retains the signed Hc2 slope, its curve criterion and two different extrapolation models", () => {
    render(<MaterialSourceObservations window={windowFor("pt")} defaultExpanded />);
    const slope = observation("hc2_temperature_slope");
    const curve = within(screen.getByRole("region", { name: /Pt substituted/ }));
    expect(slope.getByText("-2.8 T/K")).toBeInTheDocument();
    expect(slope.getByText("Slope derived from a source curve")).toBeInTheDocument();
    expect(curve.getAllByText("50% resistive transition")).toHaveLength(1);
    expect(curve.getAllByText("T<20 K")).toHaveLength(1);
    expect(curve.getAllByText("parallel to the c-axis")).toHaveLength(1);
    expect(slope.getByText("Captured characters 559–567", { exact: false })).toBeInTheDocument();
    const whh = observation("hc2_whh_orbital_zero_temperature"), linear = observation("hc2_linear_zero_temperature");
    expect(whh.getByText("≈ 45 T")).toBeInTheDocument();
    expect(whh.getByText("WHH orbital estimate")).toBeInTheDocument();
    expect(linear.getByText("≈ 65 T")).toBeInTheDocument();
    expect(linear.getByText("linear extrapolation")).toBeInTheDocument();
    expect(whh.getByText("0 K · extrapolated")).toBeInTheDocument();
    expect(linear.getByText("0 K · extrapolated")).toBeInTheDocument();
    expect(curve.getAllByText("Not supplied in this source window")).toHaveLength(1);
    const source = screen.getByText("Source snapshot and association").closest("details")!;
    fireEvent.click(source.querySelector("summary")!);
    expect(within(source).getByRole("link", { name: "Open original source locator" })).toHaveAttribute("href", "https://arxiv.org/html/0912.2752v2#S3.SS2.p2.1");
  });

  it("keeps Cs ambient and zero-pressure fit values separate, with raw uncertainty and the T>0 penetration row", () => {
    render(<MaterialSourceObservations window={windowFor("cs_nb")} defaultExpanded />);
    const ambient = screen.getByRole("region", { name: /ambient prose fit/ });
    const table = screen.getByRole("region", { name: /pressure-series table/ });
    expect(within(ambient).getByText("4.70(3) K")).toBeInTheDocument();
    expect(within(ambient).getByText("316(5) nm")).toBeInTheDocument();
    expect(within(ambient).getByText("0.590(5) meV")).toBeInTheDocument();
    expect(within(ambient).getAllByText("ambient conditions; numeric pressure not supplied")).toHaveLength(1);
    expect(within(ambient).getAllByText("muon relaxation and superfluid-density fitting")).toHaveLength(1);
    expect(within(ambient).queryByText("3.000(6) K")).not.toBeInTheDocument();
    expect(within(table).getByText("3.000(6) K")).toBeInTheDocument();
    expect(within(table).getByText("381 nm")).toBeInTheDocument();
    expect(within(table).getByText("0.54(9) meV")).toBeInTheDocument();
    expect(within(table).queryByText("1.54(9) meV")).not.toBeInTheDocument();
    expect(within(table).getByText("λ(T>0) (nm)")).toBeInTheDocument();
    expect(within(table).getAllByText("Not supplied in this source window")).toHaveLength(1);
    expect(within(table).getAllByText("0 GPa")).toHaveLength(1);
    expect(within(table).queryByText("4.70(3) K")).not.toBeInTheDocument();
    expect(within(table).queryByText(/T\s*=\s*0/)).not.toBeInTheDocument();
    const tableSource = within(table).getByText("Source snapshot and association").closest("details")!;
    fireEvent.click(tableSource.querySelector("summary")!);
    expect(within(tableSource).getByRole("link", { name: "Open original source locator" })).toHaveAttribute("href", "https://arxiv.org/html/2411.18744v1#S3.T1.2");
  });

  it("makes listed CIF sites and all declared operations inspectable without inventing exact thirds or physical validation", () => {
    render(<MaterialSourceObservations window={windowFor("crb2_cif")} defaultExpanded />);
    const sites = screen.getByText("Inspect the 2 listed sites").closest("details")!;
    const operations = screen.getByText("Inspect the 24 declared operations").closest("details")!;
    expect(sites).not.toHaveAttribute("open");
    expect(operations).not.toHaveAttribute("open");
    fireEvent.click(sites.querySelector("summary")!);
    const table = within(sites).getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    const boron = within(table).getByRole("rowheader", { name: "B1" }).closest("tr")!;
    expect(within(boron).getByText("0.3333")).toBeInTheDocument();
    expect(within(boron).getByText("0.6667")).toBeInTheDocument();
    expect(within(boron).queryByText("1/3")).not.toBeInTheDocument();
    expect(within(sites).getByRole("region", { name: "Listed fractional sites" })).toHaveAttribute("tabindex", "0");
    fireEvent.click(operations.querySelector("summary")!);
    expect(within(operations).getAllByRole("listitem")).toHaveLength(24);
    expect(within(operations).getByText("x,y,z")).toBeInTheDocument();
    expect(within(operations).getByText(/no independent space-group inference/)).toBeInTheDocument();
    expect(screen.getByText(/Independent 1954 crystallographic reference\./)).toBeInTheDocument();
    expect(observation("reported_hall_symbol").getByText("-P 6 2")).toBeInTheDocument();
    expect(observation("listed_atomic_sites").getByText("CIF lines 82–83")).toBeInTheDocument();
  });

  it("downloads only the current material window and clears a failed attempt after a successful retry", async () => {
    const blobs: Blob[] = [];
    vi.stubGlobal("URL", class extends URL {
      static createObjectURL(blob: Blob) { blobs.push(blob); return "blob:observations"; }
      static revokeObjectURL() {}
    });
    const anchor = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementationOnce(() => { throw new Error("Download blocked"); }).mockImplementation(() => {});
    const view = render(<MaterialSourceObservations window={windowFor("pt")} defaultExpanded />);
    fireEvent.click(screen.getByRole("button", { name: "Download this observation window (JSON)" }));
    expect(screen.getByRole("status")).toHaveTextContent("unavailable");
    expect(document.querySelector('a[download^="source-observations-"]')).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Download this observation window (JSON)" }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    view.rerender(<MaterialSourceObservations window={null} defaultExpanded />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(document.getElementById("source-only-pt-hc2_temperature_slope")).toBeNull();
    view.rerender(<MaterialSourceObservations window={windowFor("cs_nb")} defaultExpanded />);
    fireEvent.click(screen.getByRole("button", { name: "Download this observation window (JSON)" }));
    expect(anchor).toHaveBeenCalledTimes(3);
    const downloaded = JSON.parse(await blobText(blobs.at(-1)!)) as SourceObservationWindow;
    expect(downloaded.view_context.material_id).toBe("mat:cs(v0.93nb0.07)3sb5");
    expect(downloaded.entries).toHaveLength(6);
    expect(downloaded.entries.map(entry => entry.id)).toEqual(batch.entries.filter(entry => entry.source_group === "cs_nb").map(entry => entry.id));
    expect(downloaded.entries.some(entry => entry.source_group === "pt")).toBe(false);
    expect(downloaded.scientific_acceptance).toBe(false);
    expect(downloaded.canonical_promotions).toBe(0);
    expect(downloaded.selected_result_association).toBe("unestablished");
    expect(JSON.stringify(downloaded)).not.toMatch(/evidence_text|private_notes|raw_record|source_excerpt|\/Users\//);
  });
});
