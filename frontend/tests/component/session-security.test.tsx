import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { SessionSecurityCard } from "@/components/dashboard/SessionSecurityCard";

const { replace, revokeAllSessions, notifyAuthChange } = vi.hoisted(() => ({
  replace: vi.fn(),
  revokeAllSessions: vi.fn(),
  notifyAuthChange: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
}));
vi.mock("@/lib/auth-session", () => ({ notifyAuthChange }));
vi.mock("@/lib/api", () => ({
  revokeAllSessions,
  friendlyErrorMessage: (_error: unknown, fallback: string) => fallback,
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

it("revokes sessions, notifies the shell, and returns to login", async () => {
  revokeAllSessions.mockResolvedValue({ message: "revoked" });
  render(<SessionSecurityCard />);

  fireEvent.click(screen.getByRole("button", { name: "Revoke all sessions" }));

  await waitFor(() => expect(revokeAllSessions).toHaveBeenCalledOnce());
  expect(notifyAuthChange).toHaveBeenCalledOnce();
  expect(replace).toHaveBeenCalledWith("/login");
});

it("does not revoke when the confirmation is cancelled", () => {
  vi.mocked(window.confirm).mockReturnValue(false);
  render(<SessionSecurityCard />);

  fireEvent.click(screen.getByRole("button", { name: "Revoke all sessions" }));

  expect(revokeAllSessions).not.toHaveBeenCalled();
});
