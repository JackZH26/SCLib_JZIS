import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Blob as NodeBlob } from "node:buffer";
import { ResearchProposalBoard } from "@/components/ResearchProposalBoard";
import { getResearchProposalCatalog } from "@/lib/discovery-proposals";

describe("retained research proposals", () => {
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it("shows exactly three compact, unranked material rows with evidence closed", () => {
    render(<ResearchProposalBoard catalog={getResearchProposalCatalog()} />);
    const table = screen.getByRole("table");
    expect(table.querySelectorAll("tbody > tr")).toHaveLength(3);
    expect(within(table).getAllByText("Unranked")).toHaveLength(3);
    expect(within(table).getAllByText("Unrelaxed")).toHaveLength(3);
    for (const formula of ["Mg7AlB16", "Mg7CaB16", "Mg7B16"]) {
      expect(screen.getByRole("button", { name: formula })).toHaveAttribute("aria-expanded", "false");
    }
    expect(screen.queryByRole("button", { name: "Download unrelaxed CIF" })).not.toBeInTheDocument();
    expect(screen.getByText("Status and evidence").closest("details")).not.toHaveAttribute("open");
    expect(screen.queryByRole("button", { name: "MgB2", exact: true })).not.toBeInTheDocument();
  });

  it("opens only the chosen state with unknown axes, exact source and full CIF, then restores focus", () => {
    const catalog = getResearchProposalCatalog();
    render(<ResearchProposalBoard catalog={catalog} />);
    const trigger = screen.getByRole("button", { name: "Mg7B16", exact: true });
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/23 atoms after modification/)).toBeVisible();
    expect(screen.getAllByText("Unknown")).toHaveLength(6);
    expect(screen.getByText(/No candidate Tc or inherited host results/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Parent CIF" })).toHaveAttribute("href", catalog.source.cif_url);
    const coordinates = screen.getByText("Full CIF coordinates").closest("details")!;
    expect(coordinates).not.toHaveAttribute("open");
    expect(coordinates.querySelector("pre")!.textContent).toBe(catalog.proposals[2].structure.cif_text);
    fireEvent.click(screen.getByRole("button", { name: "Close", exact: true }));
    expect(trigger).toHaveFocus();
    expect(screen.getByRole("table").querySelectorAll("tbody > tr")).toHaveLength(3);
  });

  it("filters subscript queries and modifications and shows a distinct empty result", () => {
    render(<ResearchProposalBoard catalog={getResearchProposalCatalog()} />);
    fireEvent.change(screen.getByRole("searchbox", { name: "Find a proposal" }), { target: { value: "Mg₇CaB₁₆" } });
    expect(screen.getByRole("table").querySelectorAll("tbody > tr")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Mg7CaB16", exact: true })).toBeVisible();
    fireEvent.change(screen.getByRole("combobox", { name: "Modification" }), { target: { value: "vacancy" } });
    expect(screen.getByText("No proposals match these filters.")).toBeVisible();
    fireEvent.change(screen.getByRole("searchbox", { name: "Find a proposal" }), { target: { value: "" } });
    expect(screen.getByRole("button", { name: "Mg7B16", exact: true })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Mg7CaB16", exact: true })).not.toBeInTheDocument();
  });

  it("exports the exact retained CIF and keeps null scores and scientific authority in JSON", async () => {
    const catalog = getResearchProposalCatalog(), blobs: Blob[] = [], names: string[] = [];
    vi.stubGlobal("Blob", NodeBlob);
    vi.stubGlobal("URL", class extends URL { static createObjectURL = vi.fn(); static revokeObjectURL = vi.fn(); });
    vi.spyOn(URL, "createObjectURL").mockImplementation(blob => { blobs.push(blob as Blob); return `blob:proposal-${blobs.length}`; });
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { names.push(this.download); });
    render(<ResearchProposalBoard catalog={catalog} />);
    fireEvent.click(screen.getByRole("button", { name: "Mg7AlB16", exact: true }));
    fireEvent.click(screen.getByRole("button", { name: "Download unrelaxed CIF" }));
    expect(await blobs[0].text()).toBe(catalog.proposals[0].structure.cif_text);
    expect(names[0]).toBe(`Mg7AlB16-unrelaxed-${catalog.proposals[0].structure.cif_sha256.slice(0, 12)}.cif`);
    fireEvent.click(screen.getByRole("button", { name: "Download proposal JSON" }));
    const data = JSON.parse(await blobs[1].text());
    expect(data).toMatchObject({ schema_version: "research-proposal-export/1.0.0", catalog_schema_version: catalog.schema_version,
      catalog_version: catalog.version, reference: catalog.reference, formal_scientific_release: false, rps_release: false, human_scientific_review: null,
      proposal: { score: null, rank: null, formal_approval: null, status: "unrelaxed" } });
    expect(data.proposal.structure.cif_text).toBe(catalog.proposals[0].structure.cif_text);
    expect(JSON.stringify(data)).not.toMatch(/\/Users\/|jack@|budget|approved.*true/);
    expect(screen.getByRole("status")).toHaveTextContent("unrelaxed structure proposal");
  });
});
