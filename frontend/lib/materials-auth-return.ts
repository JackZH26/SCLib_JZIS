/** A non-secret return location for dataset sign-in, restricted to Materials. */
export const MATERIALS_DOWNLOAD_RETURN = "/materials#materials-downloads";
const KEY = "sclib:materials-auth-return";

function materialPath(value: unknown): string | null {
  if (typeof value !== "string" || /[\\\u0000-\u001f\u007f]/.test(value) || !/^\/materials(?:[/?#]|$)/.test(value)) return null;
  const url = new URL(value, "https://sclib.invalid");
  return url.origin === "https://sclib.invalid" && /^\/materials(?:\/|$)/.test(url.pathname) ? url.pathname + url.search + url.hash : null;
}
export function materialsAuthReturn(search: string): string | null {
  return materialPath(new URLSearchParams(search).get("next"));
}
export function rememberMaterialsAuthReturn(path: string | null) {
  try {
    const valid = materialPath(path);
    if (valid) sessionStorage.setItem(KEY, JSON.stringify({ path: valid, time: Date.now() }));
    else sessionStorage.removeItem(KEY);
  } catch { /* Sign-in remains usable when browser storage is unavailable. */ }
}
export function consumeMaterialsAuthReturn(): string | null {
  try {
    const raw = sessionStorage.getItem(KEY); sessionStorage.removeItem(KEY);
    if (!raw) return null;
    const saved = JSON.parse(raw), age = Date.now() - saved.time;
    return Number.isFinite(age) && age >= 0 && age <= 30 * 60 * 1000 ? materialPath(saved.path) : null;
  } catch { return null; }
}
