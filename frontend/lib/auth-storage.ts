/**
 * JWT storage. Phase 1 uses localStorage for simplicity — Phase 4 will
 * move this to an httpOnly cookie set by a Next.js route handler so the
 * token is not exposed to XSS.
 */
const KEY = "sclib_jwt";

export function saveToken(token: string) {
  if (typeof window !== "undefined") window.localStorage.setItem(KEY, token);
}

export function loadToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(KEY);
}

export function clearToken() {
  if (typeof window !== "undefined") window.localStorage.removeItem(KEY);
}
