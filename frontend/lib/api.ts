/**
 * Thin client for the SCLib API.
 *
 * Server and client components both call through here so base URL and auth
 * header handling live in one place. The API accepts either a bearer JWT
 * (for account management endpoints) or an `X-API-Key` (for search/ask) —
 * we expose both on `request` and let each call pick what it needs.
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
  init: RequestInit & { auth?: string; apiKey?: string } = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }
  if (init.auth) headers.set("authorization", `Bearer ${init.auth}`);
  if (init.apiKey) headers.set("x-api-key", init.apiKey);

  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (body as { detail?: unknown }).detail;
    const msg =
      typeof detail === "string"
        ? detail
        : typeof detail === "object" && detail !== null && "message" in detail
          ? String((detail as { message: unknown }).message)
          : `HTTP ${res.status}`;
    throw new ApiError(res.status, body, msg);
  }
  return body as T;
}

// --- shared types ----------------------------------------------------------

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

// --- Phase 3 public/search types ------------------------------------------

export interface SearchFilters {
  year_min?: number | null;
  year_max?: number | null;
  material_family?: string[] | null;
  tc_min?: number | null;
  pressure_max?: number | null;
  exclude_retracted?: boolean;
}

export interface SearchRequest {
  query: string;
  top_k?: number;
  filters?: SearchFilters;
  sort?: "relevance" | "date" | "tc";
}

export interface MaterialExtract {
  formula?: string | null;
  tc_kelvin?: number | null;
  tc_type?: string | null;
  pressure_gpa?: number | null;
  measurement?: string | null;
  confidence?: number | null;
}

export interface SearchMatch {
  paper_id: string;
  arxiv_id: string | null;
  title: string;
  authors: string[];
  year: number | null;
  date_submitted: string | null;
  relevance_score: number;
  matched_chunk: string;
  matched_section: string | null;
  materials: MaterialExtract[];
  citation_count: number;
  material_family: string | null;
  has_equation: boolean;
  has_table: boolean;
}

export interface SearchResponse {
  total: number;
  results: SearchMatch[];
  query_time_ms: number;
  guest_remaining: number | null;
}

export function search(req: SearchRequest, opts: { apiKey?: string } = {}) {
  return request<SearchResponse>("/search", {
    method: "POST",
    body: JSON.stringify(req),
    apiKey: opts.apiKey,
  });
}

// --- Ask ------------------------------------------------------------------

export interface AskRequest {
  question: string;
  max_sources?: number;
  language?: "auto" | "en" | "zh";
}

export interface AskSource {
  index: number;
  paper_id: string;
  arxiv_id: string | null;
  title: string;
  authors_short: string;
  year: number | null;
  section: string | null;
  snippet: string;
}

export interface AskResponse {
  answer: string;
  sources: AskSource[];
  tokens_used: number | null;
  query_time_ms: number;
  guest_remaining: number | null;
}

export function ask(req: AskRequest, opts: { apiKey?: string } = {}) {
  return request<AskResponse>("/ask", {
    method: "POST",
    body: JSON.stringify(req),
    apiKey: opts.apiKey,
  });
}

// --- Materials ------------------------------------------------------------

export interface MaterialSummary {
  id: string;
  formula: string;
  formula_latex: string | null;
  family: string | null;
  subfamily: string | null;
  tc_max: number | null;
  tc_max_conditions: string | null;
  tc_ambient: number | null;
  discovery_year: number | null;
  total_papers: number;
  status: string;
}

export interface MaterialDetail extends MaterialSummary {
  crystal_structure: string | null;
  pairing_symmetry: string | null;
  records: Record<string, unknown>[];
}

export interface MaterialListResponse {
  total: number;
  results: MaterialSummary[];
  limit: number;
  offset: number;
}

export function listMaterials(params: {
  family?: string;
  tc_min?: number;
  sort?: "tc_max" | "discovery_year" | "total_papers";
  limit?: number;
  offset?: number;
}) {
  const qs = new URLSearchParams();
  if (params.family) qs.set("family", params.family);
  if (params.tc_min != null) qs.set("tc_min", String(params.tc_min));
  if (params.sort) qs.set("sort", params.sort);
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.offset != null) qs.set("offset", String(params.offset));
  return request<MaterialListResponse>(
    `/materials${qs.toString() ? `?${qs}` : ""}`,
  );
}

export function getMaterial(id: string) {
  return request<MaterialDetail>(`/materials/${encodeURIComponent(id)}`);
}

// --- Papers ---------------------------------------------------------------

export interface PaperDetail {
  id: string;
  arxiv_id: string | null;
  doi: string | null;
  title: string;
  authors: string[];
  date_submitted: string | null;
  material_family: string | null;
  status: string;
  citation_count: number;
  chunk_count: number;
  abstract: string;
  categories: string[] | null;
  materials_extracted: MaterialExtract[];
  quality_flags: unknown[];
  indexed_at: string;
}

export function getPaper(id: string) {
  return request<PaperDetail>(`/paper/${encodeURIComponent(id)}`);
}

export interface SimilarPaper {
  paper_id: string;
  arxiv_id: string | null;
  title: string;
  authors: string[];
  year: number | null;
  similarity: number;
}

export interface SimilarResponse {
  source_paper_id: string;
  results: SimilarPaper[];
}

export function getSimilar(id: string, top_k = 10) {
  return request<SimilarResponse>(
    `/similar/${encodeURIComponent(id)}?top_k=${top_k}`,
  );
}

// --- Stats / timeline -----------------------------------------------------

export interface StatsResponse {
  total_papers: number;
  total_materials: number;
  total_chunks: number;
  papers_by_year: Record<string, number>;
  top_material_families: Array<{ family: string; count: number }>;
  last_ingest_at: string | null;
  updated_at: string;
}

export function getStats() {
  return request<StatsResponse>("/stats");
}

export interface TimelinePoint {
  material: string;
  formula_latex: string | null;
  family: string | null;
  tc_kelvin: number;
  year: number;
  pressure_gpa: number | null;
  paper_id: string | null;
}

export interface TimelineResponse {
  family: string | null;
  points: TimelinePoint[];
}

export function getTimeline(family?: string) {
  const qs = family ? `?family=${encodeURIComponent(family)}` : "";
  return request<TimelineResponse>(`/timeline${qs}`);
}
