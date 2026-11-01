import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { MaterialsDownloads } from "@/components/MaterialsDownloads";
import { ApiError, getMaterialsDataset, me } from "@/lib/api";
import { notifyAuthChange } from "@/lib/auth-session";
import type { MaterialsDataset } from "@/lib/materials-vnext";

vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(), me: vi.fn(), getMaterialsDataset: vi.fn() }));
const dataset: MaterialsDataset = { version: "a".repeat(64), created_at: "2026-10-31T00:00:00Z", paper_count: 1,
  files: Object.fromEntries(["results", "evidence", "training"].map(key => [key, {rows:1,columns:2,sha256:"b".repeat(64)}])) as MaterialsDataset["files"],
  source_scope: "Source-scoped results", training_policy: "Keep original quantities", grouping_policy: "Group by work" };
const member = () => ({id:"owned-member"} as Awaited<ReturnType<typeof me>>);
beforeEach(() => { vi.clearAllMocks(); vi.mocked(me).mockResolvedValue(member()); vi.mocked(getMaterialsDataset).mockResolvedValue(dataset); });

it("shows sign-in and registration guidance without requesting the dataset for a guest", async () => {
  vi.mocked(me).mockRejectedValue(new ApiError(401,"Missing session"));
  render(<MaterialsDownloads />);
  expect(await screen.findByText("Sign in to view dataset information and downloads.")).toBeVisible();
  expect(screen.getByRole("link",{name:"Sign in"})).toHaveAttribute("href","/login?next=%2Fmaterials%23materials-downloads");
  expect(screen.getByRole("link",{name:"Create an account"})).toHaveAttribute("href","/register?next=%2Fmaterials%23materials-downloads");
  expect(screen.getByText(/verify your email, then sign in/)).toBeVisible();
  expect(getMaterialsDataset).not.toHaveBeenCalled();
  expect(screen.queryByRole("link",{name:"Results CSV"})).not.toBeInTheDocument();
});

it("loads authenticated downloads only after the explicit button is clicked", async () => {
  render(<MaterialsDownloads />);
  const button = await screen.findByRole("button",{name:"Show dataset downloads"});
  expect(getMaterialsDataset).not.toHaveBeenCalled();
  fireEvent.click(button);
  expect(await screen.findByRole("link",{name:"Results CSV"})).toBeVisible();
  expect(getMaterialsDataset).toHaveBeenCalledOnce();
});

it("ignores an earlier pending download after the user signs out", async () => {
  let finish!: (value: MaterialsDataset) => void;
  vi.mocked(getMaterialsDataset).mockReturnValue(new Promise(resolve => {finish=resolve;}));
  render(<MaterialsDownloads />);
  fireEvent.click(await screen.findByRole("button",{name:"Show dataset downloads"}));
  vi.mocked(me).mockRejectedValue(new ApiError(401,"Signed out"));
  await act(async () => { notifyAuthChange(); });
  await act(async () => { finish(dataset); });
  expect(await screen.findByRole("link",{name:"Sign in"})).toBeVisible();
  expect(screen.queryByRole("link",{name:"Results CSV"})).not.toBeInTheDocument();
});

it("hides previously visible CSV links as soon as an auth change occurs", async () => {
  render(<MaterialsDownloads />);
  fireEvent.click(await screen.findByRole("button",{name:"Show dataset downloads"}));
  expect(await screen.findByRole("link",{name:"Results CSV"})).toBeVisible();
  let finish!: () => void;
  vi.mocked(me).mockReturnValue(new Promise(resolve => { finish=()=>resolve(member()); }));
  await act(async () => { notifyAuthChange(); });
  expect(screen.queryByRole("link",{name:"Results CSV"})).not.toBeInTheDocument();
  await act(async () => { finish(); });
  expect(await screen.findByRole("button",{name:"Show dataset downloads"})).toBeVisible();
});

it("returns to the sign-in prompt when a session expires before the dataset request", async () => {
  vi.mocked(getMaterialsDataset).mockRejectedValue(new ApiError(401,"Expired"));
  render(<MaterialsDownloads />);
  fireEvent.click(await screen.findByRole("button",{name:"Show dataset downloads"}));
  expect(await screen.findByRole("link",{name:"Sign in"})).toBeVisible();
  expect(screen.queryByText(/Version/)).not.toBeInTheDocument();
});
