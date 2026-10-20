import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DiscoveryNav } from "@/components/DiscoveryNav";
import DiscoveryPage from "@/app/discovery/page";
import { Brand } from "@/components/Brand";

vi.mock("next/navigation", () => ({ usePathname: () => "/timeline" }));

describe("SCLib research navigation", () => {
  it("groups all four research modules and marks the selected tool", () => {
    render(<DiscoveryNav />);
    expect(screen.getByRole("navigation", { name: "Discovery" })).toBeVisible();
    expect(screen.getByRole("link", { name: "TcTimeline" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Candidates" })).toHaveAttribute("href", "/discovery/candidates");
    expect(screen.getByRole("link", { name: "Data & methodology" })).toHaveAttribute("href", "/docs/data");
    expect(screen.getByRole("link", { name: "API reference" })).toHaveAttribute("href", "/docs/api");
  });
  it("provides a usable overview with explicit scientific limits", () => {
    render(<DiscoveryPage />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Discovery");
    expect(screen.getByRole("heading", { name: "Candidates" })).toBeVisible();
    expect(screen.getByText(/not probabilities of superconductivity or confirmed discoveries/)).toBeVisible();
  });
  it("gives the approved brand an accessible name", () => {
    render(<Brand />);
    expect(screen.getByRole("img", { name: "SCLib" })).toHaveAttribute("src", "/brand/logo.svg");
  });
});
