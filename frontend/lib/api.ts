/**
 * Thin client for the SCLib API.
 *
 * Server and client components both call through here so base URL and auth
 * header handling live in one place. The API accepts either a bearer JWT
 * (for account management endpoints) or an `X-API-Key` (for search/ask) —
 * we expose both on `request` and let each call pick what it needs.
 */

/**
 * Two flavors:
 * - `NEXT_PUBLIC_API_BASE` is the URL browsers use (e.g. the public
 *   https://api.jzis.org/sclib/v1 once Nginx is in front).
 * - `API_BASE_SERVER` is the URL Next's server-side fetches use
 *   during SSR. Inside Docker Compose that's the internal service
 *   DNS `http://api:8000/v1`, which is reachable before Nginx is up
 *   and bypasses a TLS round-trip on every page render.
 *
 * If only the public URL is set (e.g. local dev), both fall back to
 * it so nothing breaks.
 */
const PUBLIC_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/v1";
const SERVER_BASE = process.env.API_BASE_SERVER ?? PUBLIC_BASE;

export const API_BASE =
  typeof window === "undefined" ? SERVER_BASE : PUBLIC_BASE;

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: unknown,
    msg: string,
    /** Seconds the server asked us to wait, parsed from Retry-After. */
    public retryAfterSec?: number,
  ) {
    super(msg);
  }
}

/**
 * Map any caught error into a user-facing string. The fetch API throws a
 * generic `TypeError: Failed to fetch` for every network-level failure
 * (DNS, CORS block, connection refused, offline), and surface detail
 * strings from the backend are often not fit for users either. Keep the
 * mapping centralized so every page gets the same language.
 *
 * - 401 / 403 → "please sign in"
 * - 429       → "daily free quota used up, sign in for unlimited" (+ retry hint if provided)
 * - 5xx       → generic "server error, try again"
 * - 0 / other → "network error"
 *
 * Pass a fallback for anything this helper doesn't know how to classify.
 */
export function friendlyErrorMessage(
  err: unknown,
  fallback = "Something went wrong. Please try again later.",
): string {
  if (err instanceof ApiError) {
    if (err.status === 429) {
      const base =
        "Daily free queries used up. Please register or sign in for more.";
      return err.retryAfterSec
        ? `${base} (retry in ~${Math.ceil(err.retryAfterSec / 60)} min)`
        : base;
    }
    if (err.status === 401 || err.status === 403) {
      return "Please sign in to use this feature.";
    }
    if (err.status >= 500) {
      return "Server temporarily unavailable. Please try again later.";
    }
    if (err.status === 0) {
      return "Network error. Please check your connection and try again.";
    }
    // Known 4xx other than the ones above — show server-provided detail
    // so validation errors ("query too short" etc.) still surface.
    return err.message || fallback;
  }
  return fallback;
}

/**
 * Parse a Retry-After header per RFC 7231: either delta-seconds or an
 * HTTP-date. Returns undefined when the header is missing or malformed
 * so the caller can fall back to its own default.
 */
function parseRetryAfter(raw: string | null): number | undefined {
  if (!raw) return undefined;
  const n = Number(raw);
  if (Number.isFinite(n) && n >= 0) return n;
  const t = Date.parse(raw);
  if (Number.isNaN(t)) return undefined;
  return Math.max(0, Math.round((t - Date.now()) / 1000));
}

/**
 * Scrub any internal URL (Docker service DNS, loopback) out of an
 * error string before surfacing it to the user. Error messages from
 * the API can contain the upstream URL when fetch itself fails
 * (DNS, connection refused) and we do not want to leak the internal
 * topology to the browser console.
 */
function sanitizeErrorMessage(msg: string): string {
  return msg
    .replace(/https?:\/\/[^\s"']*api:\d+[^\s"']*/gi, "[api]")
    .replace(/https?:\/\/127\.0\.0\.1:\d+[^\s"']*/gi, "[api]")
    .replace(/https?:\/\/localhost:\d+[^\s"']*/gi, "[api]");
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

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
      cache: "no-store",
    });
  } catch (e) {
    // Network-level failure (DNS, refused, aborted). The message can
    // contain internal hostnames — scrub before rethrowing.
    const raw = e instanceof Error ? e.message : String(e);
    throw new ApiError(0, null, sanitizeErrorMessage(raw));
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (body as { detail?: unknown }).detail;
    const rawMsg =
      typeof detail === "string"
        ? detail
        : typeof detail === "object" && detail !== null && "message" in detail
          ? String((detail as { message: unknown }).message)
          : `HTTP ${res.status}`;
    const retryAfterSec =
      res.status === 429 ? parseRetryAfter(res.headers.get("retry-after")) : undefined;
    throw new ApiError(res.status, body, sanitizeErrorMessage(rawMsg), retryAfterSec);
  }
  return body as T;
}

// --- shared types ----------------------------------------------------------

export interface User {
  id: string;
  email: string;
  email_verified: boolean;
  name: string;
  institution: string | null;
  country: string | null;
  research_area: string | null;
  bio: string | null;
  orcid: string | null;
  created_at: string;
  is_active: boolean;
  is_admin?: boolean;
  is_reviewer?: boolean;
  auth_provider: string;
  avatar_url: string | null;
  scopes: string[];
}

/** PATCH /auth/me payload — only the fields the user may edit. */
export interface UpdateUserPayload {
  name?: string | null;
  institution?: string | null;
  country?: string | null;
  research_area?: string | null;
  bio?: string | null;
  orcid?: string | null;
}

export interface ApiKey {
  id: string;
  key_prefix: string;
  name: string | null;
  created_at: string;
  last_used: string | null;
  revoked: boolean;
  revoked_at: string | null;
  total_requests: number;
}

export interface ApiKeyWithSecret extends ApiKey {
  key: string;
}

export interface UsageStats {
  today_used: number;
  today_remaining: number;
  daily_limit: number;
  week_used: number;
  all_time_used: number;
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

export function updateMe(jwt: string, payload: UpdateUserPayload) {
  return request<User>("/auth/me", {
    method: "PATCH",
    body: JSON.stringify(payload),
    auth: jwt,
  });
}

export function listKeys(jwt: string) {
  return request<ApiKey[]>("/auth/keys", { auth: jwt });
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

export function getUsage(jwt: string) {
  return request<UsageStats>("/auth/usage", { auth: jwt });
}

// --- Ask history ----------------------------------------------------------

export interface AskHistoryEntry {
  id: string;
  question: string;
  answer: string;
  sources: Array<{
    index?: number;
    paper_id?: string;
    arxiv_id?: string | null;
    title?: string;
    authors_short?: string;
    year?: number | null;
    section?: string | null;
    snippet?: string;
  }>;
  tokens_used: number | null;
  latency_ms: number;
  language: string | null;
  created_at: string;
}

export interface AskHistoryListResponse {
  total: number;
  results: AskHistoryEntry[];
  limit: number;
  offset: number;
}

export function listHistory(jwt: string, limit = 50, offset = 0) {
  const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return request<AskHistoryListResponse>(`/history?${qs}`, { auth: jwt });
}

export function deleteHistoryEntry(jwt: string, id: string) {
  return request<{ message: string }>(`/history/${id}`, {
    method: "DELETE",
    auth: jwt,
  });
}

// --- Bookmarks ------------------------------------------------------------

export type BookmarkTargetType = "paper" | "material";

export interface Bookmark {
  id: string;
  target_type: BookmarkTargetType;
  target_id: string;
  created_at: string;
}

export interface BookmarkedPaper {
  id: string;
  target_id: string;
  created_at: string;
  title: string;
  authors: string[];
  date_submitted: string | null;
  material_family: string | null;
  status: string;
  citation_count: number;
}

export interface BookmarkedMaterial {
  id: string;
  target_id: string;
  created_at: string;
  formula: string;
  formula_latex: string | null;
  family: string | null;
  tc_max: number | null;
  tc_ambient: number | null;
  arxiv_year: number | null;
}

export interface BookmarkedPapersResponse {
  total: number;
  results: BookmarkedPaper[];
}

export interface BookmarkedMaterialsResponse {
  total: number;
  results: BookmarkedMaterial[];
}

export function createBookmark(
  jwt: string,
  target_type: BookmarkTargetType,
  target_id: string,
) {
  return request<Bookmark>("/bookmarks", {
    method: "POST",
    body: JSON.stringify({ target_type, target_id }),
    auth: jwt,
  });
}

export function deleteBookmark(jwt: string, id: string) {
  return request<{ message: string }>(`/bookmarks/${id}`, {
    method: "DELETE",
    auth: jwt,
  });
}

export function listPaperBookmarks(jwt: string) {
  return request<BookmarkedPapersResponse>("/bookmarks/papers", { auth: jwt });
}

export function listMaterialBookmarks(jwt: string) {
  return request<BookmarkedMaterialsResponse>("/bookmarks/materials", { auth: jwt });
}

// --- Feedback -------------------------------------------------------------

export type FeedbackCategory = "bug" | "feature_request" | "data_issue" | "other";

export interface FeedbackPayload {
  category: FeedbackCategory;
  message: string;
  contact_email?: string | null;
}

export function submitFeedback(jwt: string, payload: FeedbackPayload) {
  return request<{ message: string }>("/feedback", {
    method: "POST",
    body: JSON.stringify(payload),
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

export function search(req: SearchRequest, opts: { apiKey?: string; auth?: string } = {}) {
  return request<SearchResponse>("/search", {
    method: "POST",
    body: JSON.stringify(req),
    apiKey: opts.apiKey,
    auth: opts.auth,
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

export function ask(req: AskRequest, opts: { apiKey?: string; auth?: string } = {}) {
  return request<AskResponse>("/ask", {
    method: "POST",
    body: JSON.stringify(req),
    apiKey: opts.apiKey,
    auth: opts.auth,
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
  arxiv_year: number | null;
  total_papers: number;
  status: string;
  // v2
  pairing_symmetry: string | null;
  structure_phase: string | null;
  ambient_sc: boolean | null;
  is_unconventional: boolean | null;
  has_competing_order: boolean | null;
}

export interface MaterialDetail extends MaterialSummary {
  crystal_structure: string | null;
  records: Record<string, unknown>[];
  // v2 structural
  space_group: string | null;
  lattice_params: Record<string, number> | null;
  // v2 SC parameters
  gap_structure: string | null;
  hc2_tesla: number | null;
  hc2_conditions: string | null;
  lambda_eph: number | null;
  omega_log_k: number | null;
  rho_s_mev: number | null;
  // v2 competing orders
  t_cdw_k: number | null;
  t_sdw_k: number | null;
  t_afm_k: number | null;
  rho_exponent: number | null;
  competing_order: string | null;
  // v2 samples + pressure
  pressure_type: string | null;
  sample_form: string | null;
  substrate: string | null;
  doping_type: string | null;
  doping_level: number | null;
  // v2 misc
  disputed: boolean | null;
  retracted: boolean | null;
  // Phase B — Materials Project linkage. mp_id is null when the
  // formula has no MP entry. mp_alternate_ids is sorted by
  // energy_above_hull (lowest first); alternate_ids[0] === mp_id when
  // there's a match.
  mp_id: string | null;
  mp_alternate_ids: string[];
  mp_synced_at: string | null;
}

export interface MaterialListResponse {
  total: number;
  results: MaterialSummary[];
  limit: number;
  offset: number;
}

export interface MaterialListParams {
  family?: string;
  tc_min?: number;
  ambient_sc?: boolean;
  is_unconventional?: boolean;
  has_competing_order?: boolean;
  pairing_symmetry?: string;
  structure_phase?: string;
  sort?: "tc_max" | "tc_ambient" | "arxiv_year" | "total_papers";
  limit?: number;
  offset?: number;
  include_skeletons?: boolean;
}

export function listMaterials(params: MaterialListParams) {
  const qs = new URLSearchParams();
  if (params.family) qs.set("family", params.family);
  if (params.tc_min != null) qs.set("tc_min", String(params.tc_min));
  if (params.ambient_sc != null) qs.set("ambient_sc", String(params.ambient_sc));
  if (params.is_unconventional != null)
    qs.set("is_unconventional", String(params.is_unconventional));
  if (params.has_competing_order != null)
    qs.set("has_competing_order", String(params.has_competing_order));
  if (params.pairing_symmetry) qs.set("pairing_symmetry", params.pairing_symmetry);
  if (params.structure_phase) qs.set("structure_phase", params.structure_phase);
  if (params.sort) qs.set("sort", params.sort);
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.offset != null) qs.set("offset", String(params.offset));
  if (params.include_skeletons) qs.set("include_skeletons", "true");
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

export interface VersionResponse {
  site_version: string;
  dataset_version: string | null;
  api_version: string;
}

/**
 * Used by the site Footer on every page render. We deliberately bypass
 * `request()` (which forces `cache: "no-store"`) and let Next's data
 * cache deduplicate this. The default revalidate is 60s — short enough
 * that a deploy or daily-ingest update propagates to the footer within
 * a minute, long enough that a busy page is still served from cache.
 * Returns null on any failure so the footer can degrade gracefully.
 */
export async function getVersion(opts?: {
  revalidateSec?: number;
}): Promise<VersionResponse | null> {
  try {
    const res = await fetch(`${API_BASE}/version`, {
      next: { revalidate: opts?.revalidateSec ?? 60 },
    });
    if (!res.ok) return null;
    return (await res.json()) as VersionResponse;
  } catch {
    return null;
  }
}

export interface TimelinePoint {
  material: string;
  formula_latex: string | null;
  family: string | null;
  tc_kelvin: number;
  year: number;
  pressure_gpa: number | null;
  paper_id: string | null;
  /** True for DFT / first-principles records, false for experimental. */
  is_theoretical: boolean;
}

export interface TimelineCoverage {
  total_points: number;
  total_materials: number;
  year_min: number | null;
  year_max: number | null;
}

export interface TimelineResponse {
  family: string | null;
  points: TimelinePoint[];
  coverage: TimelineCoverage | null;
}

export function getTimeline(opts: {
  family?: string;
  experimentalOnly?: boolean;
} = {}) {
  const qs = new URLSearchParams();
  if (opts.family) qs.set("family", opts.family);
  if (opts.experimentalOnly) qs.set("experimental_only", "true");
  const qstr = qs.toString();
  return request<TimelineResponse>(`/timeline${qstr ? `?${qstr}` : ""}`);
}

// --- Admin --------------------------------------------------------------

export interface AdminUserSummary {
  id: string;
  email: string;
  name: string;
  institution: string | null;
  country: string | null;
  research_area: string | null;
  is_active: boolean;
  is_admin: boolean;
  is_reviewer: boolean;
  email_verified: boolean;
  auth_provider: string;
  created_at: string;
  last_login: string | null;
}

export interface AdminUserListResponse {
  total: number;
  results: AdminUserSummary[];
  limit: number;
  offset: number;
}

export interface AuditReportSummary {
  id: string;
  started_at: string;
  completed_at: string;
  rule_name: string;
  severity: string;
  rows_flagged: number;
  delta_vs_previous: number | null;
  sample_ids: string[];
}

export interface AuditQueueItem {
  id: string;
  formula: string;
  family: string | null;
  tc_max: number | null;
  review_reason: string | null;
  total_papers: number;
  has_admin_decision: boolean;
}

export interface AuditQueueResponse {
  total: number;
  results: AuditQueueItem[];
  limit: number;
  offset: number;
}

export interface AdminOverview {
  total_users: number;
  active_users: number;
  admins: number;
  total_materials: number;
  flagged_materials: number;
  flagged_by_reason: Record<string, number>;
  last_audit_started: string | null;
  last_audit_total_flagged: number | null;
}

export function adminListUsers(
  jwt: string,
  params: { q?: string; role?: "admin" | "active" | "inactive"; limit?: number; offset?: number } = {},
) {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.role) qs.set("role", params.role);
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.offset != null) qs.set("offset", String(params.offset));
  const suffix = qs.toString() ? `?${qs}` : "";
  return request<AdminUserListResponse>(`/admin/users${suffix}`, { auth: jwt });
}

export function adminBanUser(jwt: string, userId: string) {
  return request<{ message: string }>(`/admin/users/${userId}/ban`, {
    method: "POST", auth: jwt,
  });
}

export function adminUnbanUser(jwt: string, userId: string) {
  return request<{ message: string }>(`/admin/users/${userId}/unban`, {
    method: "POST", auth: jwt,
  });
}

export function adminDeleteUser(jwt: string, userId: string) {
  return request<{ message: string }>(`/admin/users/${userId}`, {
    method: "DELETE", auth: jwt,
  });
}

export function adminSetReviewer(jwt: string, userId: string, value: boolean) {
  return request<{ message: string }>(
    `/admin/users/${userId}/set-reviewer?value=${value}`,
    { method: "POST", auth: jwt },
  );
}

export function adminListAuditReports(jwt: string, rule?: string) {
  const suffix = rule ? `?rule=${encodeURIComponent(rule)}` : "";
  return request<AuditReportSummary[]>(`/admin/audit/reports${suffix}`, { auth: jwt });
}

export function adminAuditQueue(
  jwt: string,
  params: { rule?: string; limit?: number; offset?: number } = {},
) {
  const qs = new URLSearchParams();
  if (params.rule) qs.set("rule", params.rule);
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.offset != null) qs.set("offset", String(params.offset));
  const suffix = qs.toString() ? `?${qs}` : "";
  return request<AuditQueueResponse>(`/admin/audit/queue${suffix}`, { auth: jwt });
}

export function adminOverrideFlag(jwt: string, materialId: string, note: string) {
  return request<{ message: string }>(
    `/admin/audit/queue/${encodeURIComponent(materialId)}/override`,
    { method: "POST", body: JSON.stringify({ note }), auth: jwt },
  );
}

export function adminConfirmFlag(jwt: string, materialId: string, note: string) {
  return request<{ message: string }>(
    `/admin/audit/queue/${encodeURIComponent(materialId)}/confirm`,
    { method: "POST", body: JSON.stringify({ note }), auth: jwt },
  );
}

export function adminOverview(jwt: string) {
  return request<AdminOverview>("/admin/overview", { auth: jwt });
}
