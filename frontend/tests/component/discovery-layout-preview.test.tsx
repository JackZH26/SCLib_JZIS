import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DiscoveryLayoutPreview } from "@/components/DiscoveryLayoutPreview";
import { DISCOVERY_DEMO_ROWS } from "@/lib/discovery-layout-demo";
import { FIELD_BY_KEY, FIELD_GROUPS, SCIENTIFIC_FIELDS } from "@/lib/discovery-field-registry";

describe("Discovery material-list layout preview", () => {
  it("shows sixteen single-line material records, each explicitly marked Demo", () => {
    const { container } = render(<DiscoveryLayoutPreview />);
    expect(screen.getByRole("note")).toHaveTextContent("All values and rankings are synthetic");
    expect(container.querySelectorAll("tbody tr")).toHaveLength(16);
    expect(screen.getAllByText("Demo")).toHaveLength(16);
    expect(screen.getByRole("columnheader", { name: /RPS/ })).toHaveAttribute("aria-sort", "descending");
  });

  it("searches chemical formulas with plain digits and filters material families", () => {
    render(<DiscoveryLayoutPreview />);
    fireEvent.change(screen.getByRole("textbox", { name: "Search example materials" }), { target: { value: "MgB2" } });
    expect(screen.getByText("1 materials")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "MgB₂" })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Search example materials" }), { target: { value: "" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Material family" }), { target: { value: "Hydride" } });
    expect(screen.getByText("2 materials")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "MgB₂" })).not.toBeInTheDocument();
  });

  it("switches raw-data columns to the six physical dimensions without adding rows", () => {
    const { container } = render(<DiscoveryLayoutPreview />);
    fireEvent.click(screen.getByRole("button", { name: "Physics scores" }));
    expect(screen.getByRole("columnheader", { name: "Pairing" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Space group" })).not.toBeInTheDocument();
    expect(container.querySelectorAll("tbody tr")).toHaveLength(16);
  });

  it("keeps unranked materials last and gives equal scores the same rank", () => {
    const { container } = render(<DiscoveryLayoutPreview />);
    fireEvent.click(screen.getByRole("button", { name: "RPS ↓" }));
    const rows = [...container.querySelectorAll("tbody tr")];
    expect(rows.at(-1)).toHaveTextContent("Sr₂RuO₄");
    expect(screen.getByRole("columnheader", { name: /RPS/ })).toHaveAttribute("aria-sort", "ascending");
    const fe = rows.find(row => row.textContent?.includes("FeSe₀.₅Te₀.₅"))!;
    const ca = rows.find(row => row.textContent?.includes("CaC₆"))!;
    expect(fe.querySelector("td")?.textContent).toBe(ca.querySelector("td")?.textContent);
  });

  it("opens synthetic context outside the table without requesting real evidence", () => {
    const { container } = render(<DiscoveryLayoutPreview />);
    fireEvent.click(screen.getByRole("button", { name: "MgB₂" }));
    const detail = screen.getByRole("complementary", { name: "Example material detail" });
    expect(detail).toHaveTextContent("No research evidence");
    expect(detail).toHaveFocus();
    expect(container.querySelectorAll("tbody tr")).toHaveLength(16);
    fireEvent.click(within(detail).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "MgB₂" })).toHaveFocus();
  });

  it("keeps demo score arithmetic consistent while retaining unknown values", () => {
    for (const row of DISCOVERY_DEMO_ROWS) {
      expect(row.previewOnly).toBe(true);
      expect(row.id).toMatch(/^DEMO-/);
      expect(row.score).toBe(row.gain > 0 ? Math.round((1000 + 45 * row.physical + 27 * row.gain + 18 * row.execution) / 50) * 50 : null);
    }
    expect(DISCOVERY_DEMO_ROWS.some(row => row.pressure === null)).toBe(true);
    expect(DISCOVERY_DEMO_ROWS.some(row => row.score === null)).toBe(true);
  });

  it.each(FIELD_GROUPS.map((group, index) => ({ group, previous: FIELD_GROUPS[index - 1] })))
  ("exposes all $group.id fields after the preceding group without changing rows or scores", ({ group, previous }) => {
    const { container } = render(<DiscoveryLayoutPreview />);
    const scores = () => [...container.querySelectorAll("tbody tr")].map(row => row.lastElementChild?.textContent);
    const original = scores();
    fireEvent.click(screen.getByRole("button", { name: /Columns/ }));
    // These controls stay mounted while the table changes. Query them once;
    // repeatedly scanning every scientific cell adds quadratic accessibility
    // work to this full-registry interaction test without testing more UI.
    const groupControl = screen.getByRole("combobox", { name: "Scientific fields" });
    const showAll = screen.getByRole("button", { name: "Show all in group" });
    // Preserve every consecutive transition from the original registry walk,
    // but give each independent group contract its own normal test deadline.
    // No field/score/row assertion or production/test timeout is relaxed.
    if (previous) {
      fireEvent.change(groupControl, { target: { value: previous.id } });
      fireEvent.click(showAll);
    }
    expect(groupControl).toBeInTheDocument();
    expect(showAll).toBeInTheDocument();
    fireEvent.change(groupControl, { target: { value: group.id } });
    fireEvent.click(showAll);
    const fields = SCIENTIFIC_FIELDS.filter(field => field.group === group.id);
    const headers = within(container.querySelector("thead")!).getAllByRole("button")
      .filter(button => button.getAttribute("aria-controls") === "scientific-detail");
    expect(headers).toHaveLength(fields.length);
    fields.forEach((field, index) => expect(headers[index]).toHaveAccessibleName(field.label));
    expect(container.querySelectorAll("tbody tr")).toHaveLength(16);
    expect(container.querySelectorAll("tbody tr")[0].children).toHaveLength(fields.length + 7);
    expect(scores()).toEqual(original);
  });

  it("shows state-bound cell provenance and explicit inapplicability reasons outside the table", () => {
    render(<DiscoveryLayoutPreview />);
    fireEvent.change(screen.getByRole("combobox", { name: "Scientific fields" }), { target: { value: "electronic" } });
    fireEvent.click(screen.getByRole("button", { name: /MgB₂ · DOS\(EF\)/ }));
    let detail = screen.getByRole("complementary");
    expect(detail).toHaveTextContent("per formula unit; spin summed");
    expect(detail).toHaveTextContent("DEMO-01:state-1");
    fireEvent.change(screen.getByRole("combobox", { name: "Scientific fields" }), { target: { value: "state" } });
    fireEvent.click(screen.getByRole("button", { name: /Columns/ }));
    fireEvent.click(screen.getByRole("button", { name: "Show all in group" }));
    fireEvent.click(screen.getByRole("button", { name: "MgB₂ · Substrate · Not applicable" }));
    detail = screen.getByRole("complementary");
    expect(detail).toHaveTextContent("free-standing bulk model");
  });

  it("marks outcome columns as posterior and separates unknown EPC from N/A", () => {
    render(<DiscoveryLayoutPreview />);
    fireEvent.change(screen.getByRole("combobox", { name: "Scientific fields" }), { target: { value: "outcomes" } });
    expect(screen.getByRole("columnheader", { name: /Tc onset.*post-outcome/ })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Scientific fields" }), { target: { value: "pairing" } });
    fireEvent.click(screen.getByRole("button", { name: "YBa₂Cu₃O₇−δ · λₑₚ · Not computed" }));
    expect(screen.getByRole("complementary")).toHaveTextContent("neither inapplicable");
  });

  it("filters overlapping profiles without re-ranking or relabeling chemical families", () => {
    render(<DiscoveryLayoutPreview />);
    fireEvent.change(screen.getByRole("combobox", { name: "Research profile" }), { target: { value: "multiband" } });
    expect(screen.getByRole("button", { name: "MgB₂" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "FeSe₀.₅Te₀.₅" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "LaH₁₀" })).not.toBeInTheDocument();
    expect(FIELD_BY_KEY.mechanism_profiles.definition).toContain("do not establish a mechanism");
  });

  it("searches the definition dictionary without filtering material rows", () => {
    const { container } = render(<DiscoveryLayoutPreview />);
    fireEvent.change(screen.getByRole("textbox", { name: "Find a field" }), { target: { value: "quantum_metric" } });
    expect(screen.getByText("quantum_metric")).toBeInTheDocument();
    expect(screen.queryByText("electron_phonon_lambda", { selector: "code" })).not.toBeInTheDocument();
    expect(container.querySelectorAll("tbody tr")).toHaveLength(16);
    expect(screen.getByRole("region", { name: "Scrollable scientific field dictionary" })).toHaveAttribute("tabindex", "0");
  });
});
