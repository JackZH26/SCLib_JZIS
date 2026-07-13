import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { DataPrivacyCard } from "@/components/dashboard/DataPrivacyCard";
import type { User } from "@/lib/api";

const { deleteAccount, exportAccountData, notifyAuthChange, replace } = vi.hoisted(() => ({
  deleteAccount: vi.fn(),
  exportAccountData: vi.fn(),
  notifyAuthChange: vi.fn(),
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
vi.mock("@/lib/auth-session", () => ({ notifyAuthChange }));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/api")>(),
  deleteAccount,
  exportAccountData,
}));

const user: User = {
  id: "45a355f1-5dd5-4fd3-a1a7-f447697303fd",
  email: "researcher@example.com",
  email_verified: true,
  name: "Researcher",
  institution: null,
  country: null,
  age: null,
  research_area: null,
  purpose: null,
  bio: null,
  orcid: null,
  created_at: "2026-07-13T00:00:00Z",
  is_active: true,
  auth_provider: "local",
  avatar_url: null,
  scopes: ["basic", "sclib"],
};

beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(window.URL, "createObjectURL", {
    configurable: true,
    value: vi.fn(() => "blob:account-export"),
  });
  Object.defineProperty(window.URL, "revokeObjectURL", {
    configurable: true,
    value: vi.fn(),
  });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});

it("downloads a portable account export", async () => {
  exportAccountData.mockResolvedValue({
    schema_version: "1",
    generated_at: "2026-07-13T00:00:00Z",
    profile: { email: user.email },
    api_keys: [],
    ask_history: [],
    bookmarks: [],
    email_verifications: [],
    password_resets: [],
    security_events: [],
  });
  render(<DataPrivacyCard user={user} />);

  fireEvent.click(screen.getByRole("button", { name: "Download my data" }));

  await waitFor(() => expect(exportAccountData).toHaveBeenCalledOnce());
  expect(window.URL.createObjectURL).toHaveBeenCalledOnce();
  expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledOnce();
  expect(await screen.findByText("Your account export is ready.")).toBeVisible();
});

it("requires explicit email and password confirmation before deletion", async () => {
  deleteAccount.mockResolvedValue({ message: "deleted" });
  render(<DataPrivacyCard user={user} />);

  fireEvent.click(screen.getByRole("button", { name: "Delete my account" }));
  fireEvent.change(screen.getByLabelText(`Type ${user.email} to confirm`), {
    target: { value: user.email },
  });
  fireEvent.change(screen.getByLabelText("Current password"), {
    target: { value: "correct horse battery staple" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Permanently delete account" }));

  await waitFor(() => expect(deleteAccount).toHaveBeenCalledWith({
    confirmation: "DELETE",
    email: user.email,
    current_password: "correct horse battery staple",
  }));
  expect(notifyAuthChange).toHaveBeenCalledOnce();
  expect(replace).toHaveBeenCalledWith("/login");
});
