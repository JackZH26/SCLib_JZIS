import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DiscoveryDisclosure } from "@/components/DiscoveryDisclosure";

afterEach(() => { window.history.replaceState(null, "", "/"); vi.restoreAllMocks(); });

function mount() {
  return render(<DiscoveryDisclosure id="discovery-tools" summary="Research tools">
    <section id="discovery-pressure-response"><h2>Pressure study</h2></section>
    <label>Draft question<input /></label>
  </DiscoveryDisclosure>);
}

describe("Discovery progressive disclosure", () => {
  it("keeps nonessential tools collapsed and retains a draft when closed and reopened", () => {
    mount();
    const detail = document.querySelector("details")!;
    expect(detail.open).toBe(false);
    expect(screen.getByText("Pressure study")).not.toBeVisible();
    detail.open = true;
    fireEvent.change(screen.getByLabelText("Draft question"), { target: { value: "Check a matched pressure state" } });
    detail.open = false; detail.open = true;
    expect(screen.getByLabelText("Draft question")).toHaveValue("Check a matched pressure state");
  });
  it.each(["#discovery-tools", "#discovery-pressure-response"])("opens a direct link to %s", hash => {
    window.history.replaceState(null, "", `/${hash}`); mount();
    expect(document.querySelector("details")?.open).toBe(true);
    expect(screen.getByText("Pressure study")).toBeVisible();
  });
  it("opens an existing anchor after hash navigation or history restoration without opening unrelated groups", () => {
    mount();
    render(<DiscoveryDisclosure id="discovery-methodology" summary="Methodology"><p>Research framework</p></DiscoveryDisclosure>);
    act(() => {
      window.history.replaceState(null, "", "/#discovery-pressure-response");
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(document.getElementById("discovery-tools")).toHaveAttribute("open");
    expect(document.getElementById("discovery-methodology")).not.toHaveAttribute("open");
    document.querySelector("details")!.open = false;
    act(() => { window.dispatchEvent(new PopStateEvent("popstate")); });
    expect(document.getElementById("discovery-tools")).toHaveAttribute("open");
  });
  it("ignores malformed and unknown fragments", () => {
    window.history.replaceState(null, "", "/#%E0%A4%A"); mount();
    expect(document.querySelector("details")?.open).toBe(false);
    act(() => { window.history.replaceState(null, "", "/#unknown"); window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(document.querySelector("details")?.open).toBe(false);
  });
  it("reopens a manually closed group when its current fragment link is followed again", () => {
    window.history.replaceState(null, "", "/#discovery-pressure-response"); mount();
    render(<a href="#discovery-pressure-response">Open pressure study</a>);
    const detail = document.querySelector("details")!;
    detail.open = false;
    fireEvent.click(screen.getByRole("link", { name: "Open pressure study" }));
    expect(detail.open).toBe(true);
  });
  it("does not intercept modified clicks, new windows or other page queries", () => {
    mount();
    render(<><a href="#discovery-pressure-response">Modified link</a><a href="#discovery-pressure-response" target="_blank">New window</a><a href="/?other=1#discovery-pressure-response">Other query</a></>);
    fireEvent.click(screen.getByRole("link", { name: "Modified link" }), { ctrlKey: true });
    fireEvent.click(screen.getByRole("link", { name: "New window" }));
    fireEvent.click(screen.getByRole("link", { name: "Other query" }));
    expect(document.querySelector("details")?.open).toBe(false);
  });
});
