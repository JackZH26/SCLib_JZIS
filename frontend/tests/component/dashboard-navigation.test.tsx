import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { Sidebar } from "@/components/dashboard/Sidebar";

const route = vi.hoisted(() => ({ pathname: "/dashboard/research/discovery-designs" }));
vi.mock("next/navigation", () => ({ usePathname: () => route.pathname }));
beforeEach(() => { route.pathname = "/dashboard/research/discovery-designs"; });
const items = [
  { href: "/dashboard", label: "Overview" },
  { href: "/dashboard/research/discovery", label: "Discovery selection" },
  { href: "/dashboard/research/discovery-designs", label: "Discovery designs" },
  { href: "/dashboard/research/discovery-governance", label: "Discovery governance" },
];
it("identifies the designs page without activating the selection prefix or naming it in the mobile control", () => {
  render(<Sidebar items={items} />);
  expect(screen.getByRole("link", { name: "Discovery designs" })).toHaveAttribute("aria-current", "page");
  expect(screen.getByRole("link", { name: "Discovery selection" })).not.toHaveAttribute("aria-current");
  expect(screen.getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
  expect(screen.getByRole("button", { name: "Workspace navigation · Discovery designs" })).toBeInTheDocument();
});
it("keeps a nested designs history route within the same navigation item", () => {
  route.pathname = "/dashboard/research/discovery-designs/history";
  render(<Sidebar items={items} />);
  expect(screen.getByRole("link", { name: "Discovery designs" })).toHaveAttribute("aria-current", "page");
  expect(screen.getByRole("link", { name: "Discovery selection" })).not.toHaveAttribute("aria-current");
});
