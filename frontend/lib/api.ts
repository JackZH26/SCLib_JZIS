/**
 * Thin client for the SCLib API.
 *
 * Server and client components both call through here so base URL and auth
 * header handling live in one place. For Phase 1 we only need auth endpoints;
 * Phase 3 will add search/ask/materials/etc.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/v1";

export class ApiError extends Error {
  constructor(public status: number, public body: unknown, msg: string) {
    super(msg);
  }
}

async function request<T>(
  path: string,
  init: RequestInit & { auth?: string } = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }
  if (init.auth) headers.set("authorization", `Bearer ${init.auth}`);

  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg =
      (body as { detail?: string }).detail ?? `HTTP ${res.status}`;
    throw new ApiError(res.status, body, msg);
  }
  return body as T;
}

// --- types -----------------------------------------------------------------

export interface User {
  id: string;
  email: string;
  name: string;
  institution: string | null;
  country: string | null;
  research_area: string | null;
  created_at: string;
  is_active: boolean;
}

export interface ApiKey {
  id: string;
  key_prefix: string;
  name: string | null;
  created_at: string;
  last_used: string | null;
  revoked: boolean;
}

export interface ApiKeyWithSecret extends ApiKey {
  key: string;
}

// --- auth endpoints --------------------------------------------------------

export interface RegisterPayload {
  email: string;
  password: string;
  name: string;
  age: number;
  institution?: string;
  country?: string;
  research_area?: string;
  purpose: string;
}

export function register(data: RegisterPayload) {
  return request<{ user: User; message: string }>("/auth/register", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function verifyEmail(token: string) {
  return request<{ user: User; api_key: string }>(
    `/auth/verify?token=${encodeURIComponent(token)}`,
  );
}

export function login(email: string, password: string) {
  return request<{ access_token: string; token_type: string; expires_in: number }>(
    "/auth/login",
    { method: "POST", body: JSON.stringify({ email, password }) },
  );
}

export function me(jwt: string) {
  return request<User>("/auth/me", { auth: jwt });
}

export function createKey(jwt: string, name: string) {
  return request<ApiKeyWithSecret>("/auth/keys", {
    method: "POST",
    body: JSON.stringify({ name }),
    auth: jwt,
  });
}

export function revokeKey(jwt: string, keyId: string) {
  return request<{ message: string }>(`/auth/keys/${keyId}`, {
    method: "DELETE",
    auth: jwt,
  });
}
