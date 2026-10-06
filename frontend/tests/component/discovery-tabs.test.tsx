import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DiscoveryTabs } from "@/components/DiscoveryTabs";
import { DiscoveryDisclosure } from "@/components/DiscoveryDisclosure";

afterEach(() => { window.history.replaceState(null, "", "/"); vi.restoreAllMocks(); });
function mount() {
  return render(<>
    <a href="#discovery-condition-design">Open plan directly</a>
    <a href="#discovery-pressure-response">Open pressure study</a>
    <DiscoveryTabs candidates={<><h2 id="candidate-results">Candidate list</h2><label>Candidate query<input /></label></>}
      research={<>
        <DiscoveryDisclosure id="discovery-source-studies" summary="Source studies">
          <section id="discovery-pressure-response"><h2>Pressure data</h2></section>
        </DiscoveryDisclosure>
        <DiscoveryDisclosure id="discovery-scientific-companions" summary="Scientific companions">
          <DiscoveryDisclosure id="discovery-condition-design" summary="Research plan">
            <label>Draft question<input /></label>
          </DiscoveryDisclosure>
        </DiscoveryDisclosure>
      </>} />
  </>);
}
const candidates = () => screen.getByRole("tab", { name: "Candidates", exact: true });
const research = () => screen.getByRole("tab", { name: "Research & tools", exact: true });

describe("Discovery candidate and research tabs", () => {
  it("defaults to only the candidate panel, with real fragment links and accessible tab relationships", () => {
    mount();
    expect(candidates()).toHaveAttribute("aria-selected", "true");
    expect(research()).toHaveAttribute("aria-selected", "false");
    expect(candidates()).toHaveAttribute("href", "#discovery-candidates");
    expect(research()).toHaveAttribute("href", "#discovery-research");
    expect(screen.getAllByRole("tabpanel")).toHaveLength(1);
    expect(screen.getByRole("tabpanel")).toHaveAttribute("id", candidates().getAttribute("aria-controls"));
    expect(screen.getByText("Candidate list")).toBeVisible();
    expect(screen.getByText("Source studies")).not.toBeVisible();
    expect(research()).toHaveAttribute("tabindex", "-1");
  });

  it("supports roving keyboard focus, activation, Home/End and preserves the current query in shareable links", () => {
    window.history.replaceState(null, "", "/discovery?context=kept"); mount();
    candidates().focus(); fireEvent.keyDown(candidates(), { key: "ArrowRight" });
    expect(research()).toHaveFocus(); expect(research()).toHaveAttribute("aria-selected", "true");
    expect(window.location.search).toBe("?context=kept"); expect(window.location.hash).toBe("#discovery-research");
    fireEvent.keyDown(research(), { key: "ArrowRight" }); expect(candidates()).toHaveFocus();
    fireEvent.keyDown(candidates(), { key: "End" }); expect(research()).toHaveFocus();
    fireEvent.keyDown(research(), { key: "Home" }); expect(candidates()).toHaveFocus();
    research().focus(); fireEvent.keyDown(research(), { key: " " });
    expect(research()).toHaveAttribute("aria-selected", "true");
    candidates().focus(); fireEvent.keyDown(candidates(), { key: "Enter" });
    expect(candidates()).toHaveAttribute("aria-selected", "true");
  });

  it("keeps drafts and candidate filters mounted when tabs change", () => {
    mount();
    fireEvent.change(screen.getByLabelText("Candidate query"), { target: { value: "MgB2" } });
    fireEvent.click(screen.getByRole("link", { name: "Open plan directly" }));
    expect(research()).toHaveAttribute("aria-selected", "true");
    expect(screen.getByLabelText("Draft question")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Draft question"), { target: { value: "Compare vacancy states" } });
    fireEvent.click(candidates());
    expect(screen.getByLabelText("Candidate query")).toHaveValue("MgB2");
    expect(screen.getByLabelText("Draft question")).not.toBeVisible();
    fireEvent.click(research());
    expect(screen.getByLabelText("Draft question")).toHaveValue("Compare vacancy states");
  });

  it.each(["discovery-research", "discovery-source-studies", "discovery-pressure-response", "discovery-condition-design"])("opens the correct panel for a direct #%s link", hash => {
    window.history.replaceState(null, "", `/discovery#${hash}`); mount();
    expect(research()).toHaveAttribute("aria-selected", "true");
    expect(document.getElementById("discovery-research")).toBeVisible();
    expect(screen.getByText("Candidate list")).not.toBeVisible();
    if (hash === "discovery-pressure-response") expect(screen.getByText("Pressure data")).toBeVisible();
    if (hash === "discovery-condition-design") {
      expect(document.getElementById("discovery-scientific-companions")).toHaveAttribute("open");
      expect(screen.getByLabelText("Draft question")).toBeVisible();
    }
  });

  it("reopens a manually closed same-fragment disclosure and moves back to its panel", () => {
    window.history.replaceState(null, "", "/discovery#discovery-pressure-response"); mount();
    (document.getElementById("discovery-source-studies") as HTMLDetailsElement).open = false;
    fireEvent.click(screen.getByRole("link", { name: "Open pressure study" }));
    expect(screen.getByText("Pressure data")).toBeVisible();
    fireEvent.click(candidates());
    fireEvent.click(screen.getByRole("link", { name: "Open pressure study" }));
    expect(research()).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Pressure data")).toBeVisible();
  });

  it("restores panels on back/forward fragment events and returns hidden-panel focus to a visible tab", () => {
    mount(); fireEvent.click(screen.getByRole("link", { name: "Open plan directly" }));
    const input = screen.getByLabelText("Draft question"); input.focus();
    fireEvent.change(input, { target: { value: "Retain this plan" } });
    act(() => { window.history.replaceState(null, "", "/discovery"); window.dispatchEvent(new PopStateEvent("popstate")); });
    expect(candidates()).toHaveAttribute("aria-selected", "true"); expect(candidates()).toHaveFocus();
    act(() => { window.history.replaceState(null, "", "/discovery#discovery-condition-design"); window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(input).toBeVisible(); expect(input).toHaveValue("Retain this plan");
  });

  it("does not intercept modified/new-window/external-query links or malformed fragments", () => {
    window.history.replaceState(null, "", "/discovery#%E0%A4%A"); mount();
    render(<><a href="#discovery-condition-design" target="_blank">New window</a><a href="/discovery?other=1#discovery-condition-design">Other query</a></>);
    fireEvent.click(research(), { ctrlKey: true });
    fireEvent.click(screen.getByRole("link", { name: "Open plan directly" }), { metaKey: true });
    fireEvent.click(screen.getByRole("link", { name: "New window" }));
    fireEvent.click(screen.getByRole("link", { name: "Other query" }));
    expect(candidates()).toHaveAttribute("aria-selected", "true");
    expect(document.getElementById("discovery-condition-design")).not.toHaveAttribute("open");
    act(() => { window.history.replaceState(null, "", "/discovery#unknown"); window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(candidates()).toHaveAttribute("aria-selected", "true");
  });
});
