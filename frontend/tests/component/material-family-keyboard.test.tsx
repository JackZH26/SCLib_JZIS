import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MaterialsFilters } from "@/components/MaterialsFilters";

function setup() {
  render(<MaterialsFilters query={{}} pageSize={50} />);
  const trigger = within(screen.getByRole("group", { name: "Family", exact: true }))
    .getByRole("button", { name: "All families", exact: true });
  fireEvent.click(trigger);
  return trigger;
}

describe("Family checkbox disclosure keyboard behavior", () => {
  it("provides a named checkbox group and preserves multi-selection in GET submission", () => {
    const trigger = setup();
    const group = screen.getByRole("group", { name: "Material families" });
    expect(trigger).toHaveAttribute("aria-controls", group.id);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    fireEvent.click(within(group).getByRole("checkbox", { name: "Hydride", exact: true }));
    fireEvent.click(within(group).getByRole("checkbox", { name: "Cuprate", exact: true }));
    expect(trigger).toHaveTextContent("2 families");
    expect(new FormData(trigger.closest("form")!).get("family")).toBe("hydride,cuprate");
  });

  it("returns focus to Family when Escape removes the focused checkbox", () => {
    const trigger = setup();
    const checkbox = screen.getByRole("checkbox", { name: "Hydride", exact: true });
    act(() => checkbox.focus());
    fireEvent.keyDown(checkbox, { key: "Escape" });
    expect(screen.queryByRole("group", { name: "Material families" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("closes when keyboard focus leaves and does not steal Escape from another field", () => {
    const trigger = setup();
    act(() => screen.getByRole("checkbox", { name: "Hydride", exact: true }).focus());
    const next = screen.getByLabelText("Tc ≥ (K)", { exact: true });
    act(() => next.focus());
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    fireEvent.keyDown(next, { key: "Escape" });
    expect(next).toHaveFocus();
  });

  it("keeps focus usable after Clear removes its own button", () => {
    const trigger = setup();
    fireEvent.click(screen.getByRole("checkbox", { name: "Hydride", exact: true }));
    const clear = screen.getByRole("button", { name: "Clear (1)", exact: true });
    act(() => clear.focus());
    fireEvent.click(clear);
    expect(trigger).toHaveFocus();
    expect(trigger).toHaveTextContent("All families");
    expect(screen.getByRole("group", { name: "Material families" })).toBeInTheDocument();
    expect(new FormData(trigger.closest("form")!).get("family")).toBe("");
    for (const checkbox of screen.getAllByRole("checkbox")) expect(checkbox).not.toBeChecked();
  });
});
