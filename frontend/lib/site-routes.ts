/** Preserve raw percent-encoded path segments; material and paper IDs are opaque. */
export function legacyDestination(pathname: string): string | null {
  const prefixed = pathname === "/sclib" || pathname.startsWith("/sclib/");
  let target = prefixed ? pathname.slice(6) || "/" : pathname;
  if (target === "/auth/verify" || target === "/auth/verify/") return "/verify";
  if (target === "/api-docs" || target === "/api-docs/") return "/docs/api";
  if (target === "/ask" || target === "/ask/") return "/search";
  if (!prefixed) {
    if (pathname === "/index.html") return "/";
    return pathname !== "/" && pathname.endsWith("/") ? pathname.replace(/\/+$/, "") : null;
  }
  if (target === "/") return target;
  if (!/^\/(search|materials|paper|timeline|discovery|stats|docs|dashboard|auth|login|register|forgot-password|reset-password|verify|privacy|terms|cookies|robots\.txt|sitemap\.xml|sitemaps)(\/|$)/.test(target)) return null;
  return target.replace(/\/+$/, "");
}

export function isPrivatePage(pathname: string): boolean {
  const path = pathname.replace(/^\/sclib(?=\/|$)/, "") || "/";
  return /^\/(auth|dashboard|login|register|forgot-password|reset-password|verify)(\/|$)/.test(path);
}
