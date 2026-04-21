/**
 * JWT storage. Phase 1 uses localStorage for simplicity — Phase 4 will
 * move this to an httpOnly cookie set by a Next.js route handler so the
 * token is not exposed to XSS.
 *
 * save / clear also dispatch a custom window event so long-lived
 * components (Header, dashboard shell) can re-fetch /auth/me without
 * waiting for a full page reload. The browser's built-in "storage"
 * event only fires across tabs, not within the same tab, so we need
 * our own channel here.
 */
const KEY = "sclib_jwt";
const AUTH_EVENT = "sclib:auth-change";

export function saveToken(token: string) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(KEY, token);
  window.dispatchEvent(new CustomEvent(AUTH_EVENT));
}

export function loadToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(KEY);
}

export function clearToken() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(KEY);
  window.dispatchEvent(new CustomEvent(AUTH_EVENT));
}

/**
 * Subscribe to same-tab auth changes. Returns an unsubscribe function
 * so it can be used directly as a useEffect cleanup.
 */
export function onAuthChange(handler: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(AUTH_EVENT, handler);
  return () => window.removeEventListener(AUTH_EVENT, handler);
}
