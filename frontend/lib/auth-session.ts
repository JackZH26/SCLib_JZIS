/**
 * Browser-session change notifications.
 *
 * The credential itself is a host-only HttpOnly cookie owned by the API and
 * is never readable by application JavaScript. This event only asks mounted
 * UI (notably the global header) to refresh `/auth/me` after login/logout.
 */
const AUTH_EVENT = "sclib:auth-change";

export function notifyAuthChange() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(AUTH_EVENT));
}

export function onAuthChange(handler: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(AUTH_EVENT, handler);
  return () => window.removeEventListener(AUTH_EVENT, handler);
}
