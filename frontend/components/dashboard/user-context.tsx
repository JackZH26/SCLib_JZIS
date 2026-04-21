"use client";

/**
 * Shared user context for /dashboard/* pages.
 *
 * The shell layout fetches ``/auth/me`` once on mount; every child tab
 * reads from this context instead of re-fetching. The setter lets the
 * Profile edit flow push the updated user back into the shell header
 * too, so name / avatar change without a page reload.
 */
import { createContext, useContext } from "react";
import type { User } from "@/lib/api";

interface Ctx {
  user: User;
  setUser: (u: User) => void;
}

const DashboardUserContext = createContext<Ctx | null>(null);

export const DashboardUserProvider = DashboardUserContext.Provider;

export function useDashboardUser(): Ctx {
  const v = useContext(DashboardUserContext);
  if (!v) {
    throw new Error(
      "useDashboardUser must be used inside the /dashboard layout",
    );
  }
  return v;
}
