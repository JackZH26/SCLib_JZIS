import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DiscoveryNav } from "@/components/DiscoveryNav";
import DiscoveryPage from "@/app/discovery/page";
import { Brand } from "@/components/Brand";

const route = vi.hoisted(() => ({ pathname: "/timeline" }));
vi.mock("next/navigation", () => ({ usePathname: () => route.pathname }));
vi.mock("@/components/discovery/DiscoveryCandidatesContent", () => ({ DiscoveryCandidatesContent: () => <p>Source catalogue</p> }));
beforeEach(() => { route.pathname = "/timeline"; });

describe("SCLib research navigation", () => {
  it("keeps Discovery tools separate from the independent Timeline", () => {
    render(<DiscoveryNav />);
    expect(screen.getByRole("navigation", { name: "Discovery" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "TcTimeline" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Candidates" })).toHaveAttribute("href", "/discovery#candidates");
    expect(screen.getByRole("link", { name: "Data & methodology" })).toHaveAttribute("href", "/discovery#data-methodology");
    expect(screen.getByRole("link", { name: "API reference" })).toHaveAttribute("href", "/discovery#api-reference");
  });
  it("provides a usable overview with explicit scientific limits", () => {
    render(<DiscoveryPage />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Discovery");
    expect(screen.getByRole("heading", { name: "Candidates" })).toBeVisible();
    expect(screen.getByText(/not probabilities of superconductivity or confirmed discoveries/)).toBeVisible();
  });
  it("keeps all three sections in one page and opens documentation only on request", () => {
    route.pathname = "/discovery";
    render(<DiscoveryPage />);
    const sections = Array.from(document.querySelectorAll("main > section")).map(node => node.id);
    expect(sections).toEqual(["candidates", "data-methodology", "api-reference"]);
    expect(screen.queryByRole("link", { name: "TcTimeline" })).not.toBeInTheDocument();
    const data = screen.getByText("Read data and methodology").closest("details")!;
    const api = screen.getByText("Read API reference").closest("details")!;
    expect(data.open).toBe(false); expect(api.open).toBe(false);
    const nav = screen.getByRole("link", { name: "Data & methodology" });
    expect(nav).toHaveAttribute("href", "#data-methodology");
    fireEvent.click(nav);
    expect(nav).toHaveAttribute("aria-current", "location");
    expect(data.open).toBe(false);
    fireEvent.click(data.querySelector("summary")!);
    expect(screen.getByRole("heading", { name: "Coverage and updates" })).toBeVisible();
    fireEvent.click(api.querySelector("summary")!);
    expect(screen.getByRole("heading", { name: "Quick start" })).toBeVisible();
    expect(api.querySelectorAll("details").length).toBeGreaterThan(0);
    expect(Array.from(api.querySelectorAll("details")).every(item => !item.open)).toBe(true);
  });
  it("gives the approved brand an accessible name", () => {
    render(<Brand />);
    expect(screen.getByRole("img", { name: "SCLib" })).toHaveAttribute("src", "/brand/logo.svg");
  });
});
