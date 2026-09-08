/**
 * Thin client for the SCLib API.
 *
 * Server and client components both call through here so base URL and
 * credential handling live in one place. Browser sessions use a host-only
 * HttpOnly cookie; programmatic search/ask calls may still use `X-API-Key`.
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
export const PUBLIC_API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "https://api.jzis.org/sclib/v1";
const SERVER_BASE = process.env.API_BASE_SERVER ?? PUBLIC_API_BASE;

export const API_BASE =
  typeof window === "undefined" ? SERVER_BASE : PUBLIC_API_BASE;

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: unknown,
    msg: string,
    /** Seconds the server asked us to wait, parsed from Retry-After. */
    public retryAfterSec?: number,
    /** Correlation ID to include in support reports. */
    public requestId?: string,
  ) {
    super(msg);
  }
}

// Private read-only research workbench. Callers validate the closed wire before display.
export function scientificReviewCapabilities(signal?: AbortSignal): Promise<unknown> {
  return request("/ml/scientific-review/capabilities", { signal, cache: "no-store" });
}

export function scientificReviewQueue(after: string | null = null, signal?: AbortSignal): Promise<unknown> {
  const query = new URLSearchParams({ limit: "25" });
  if (after !== null) query.set("after", after);
  return request(`/ml/scientific-review/results?${query}`, { signal, cache: "no-store" });
}

export function scientificReviewDossier(propertyId: string, signal?: AbortSignal): Promise<unknown> {
  return request(`/ml/scientific-review/results/${encodeURIComponent(propertyId)}`, { signal, cache: "no-store" });
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
      const detail = (err.body as { detail?: { error?: string } } | null)?.detail;
      if (detail?.error === "auth_rate_limited") {
        return err.retryAfterSec
          ? `Too many attempts. Try again in about ${err.retryAfterSec} seconds.`
          : "Too many attempts. Please try again later.";
      }
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
  init: RequestInit & {
    apiKey?: string;
    next?: { revalidate?: number };
  } = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }
  if (init.apiKey) headers.set("x-api-key", init.apiKey);

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
      cache: init.cache ?? "no-store",
      credentials: init.credentials ?? "include",
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
    const requestId =
      res.headers.get("x-request-id") ??
      ((body as { request_id?: unknown }).request_id as string | undefined);
    throw new ApiError(
      res.status,
      body,
      sanitizeErrorMessage(rawMsg),
      retryAfterSec,
      requestId,
    );
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
  age: number | null;
  research_area: string | null;
  purpose: string | null;
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

export interface BackgroundCycle {
  status: "running" | "failed" | "succeeded";
  cycle_id: string;
  scheduled_for: string;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  attempts: number;
  recovered: boolean;
  result: Record<string, unknown>;
  error_code: string | null;
  next_retry_at: string | null;
  completion_scope: "database_effects_only";
}

export interface BackgroundJobStatus {
  job_name: "stats_refresh" | "timeline_projection" | "formula_audit" | "nightly_audit" | "ask_history_prune";
  active_owner_id: string | null;
  lock_observation: "current_query_only";
  last_success: BackgroundCycle | null;
  oldest_unfinished: BackgroundCycle | null;
  recent_cycles: BackgroundCycle[];
}

export interface BackgroundJobsResponse {
  version: string;
  jobs: BackgroundJobStatus[];
  scope: "database_cycles_not_external_cache_delivery";
}

export function adminBackgroundJobs(): Promise<BackgroundJobsResponse> {
  return request<BackgroundJobsResponse>("/admin/background-jobs");
}

/** PATCH /auth/me payload — only the fields the user may edit. */
export interface UpdateUserPayload {
  name?: string | null;
  institution?: string | null;
  country?: string | null;
  age?: number | null;
  research_area?: string | null;
  purpose?: string | null;
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
  age?: number;
  institution?: string;
  country?: string;
  research_area?: string;
  purpose?: string;
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
  return request<{ authenticated: boolean; expires_in: number }>(
    "/auth/session/login",
    { method: "POST", body: JSON.stringify({ email, password }) },
  );
}

export function logout() {
  return request<{ message: string }>("/auth/logout", { method: "POST" });
}

export function requestPasswordReset(email: string) {
  return request<{ message: string }>("/auth/password-reset/request", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export function confirmPasswordReset(token: string, newPassword: string) {
  return request<{ message: string }>("/auth/password-reset/confirm", {
    method: "POST",
    body: JSON.stringify({ token, new_password: newPassword }),
  });
}

export function revokeAllSessions() {
  return request<{ message: string }>("/auth/sessions/revoke-all", {
    method: "POST",
  });
}

export function me() {
  return request<User>("/auth/me");
}

export function updateMe(payload: UpdateUserPayload) {
  return request<User>("/auth/me", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export interface AccountDataExport {
  schema_version: "1";
  generated_at: string;
  profile: Record<string, unknown>;
  api_keys: Array<Record<string, unknown>>;
  ask_history: Array<Record<string, unknown>>;
  bookmarks: Array<Record<string, unknown>>;
  email_verifications: Array<Record<string, unknown>>;
  password_resets: Array<Record<string, unknown>>;
  security_events: Array<Record<string, unknown>>;
}

export function exportAccountData() {
  return request<AccountDataExport>("/auth/me/export");
}

export function deleteAccount(data: {
  confirmation: "DELETE";
  email: string;
  current_password?: string;
}) {
  return request<{ message: string }>("/auth/me", {
    method: "DELETE",
    body: JSON.stringify(data),
  });
}

export function listKeys() {
  return request<ApiKey[]>("/auth/keys");
}

export function createKey(name: string) {
  return request<ApiKeyWithSecret>("/auth/keys", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function revokeKey(keyId: string) {
  return request<{ message: string }>(`/auth/keys/${keyId}`, {
    method: "DELETE",
  });
}

export function getUsage() {
  return request<UsageStats>("/auth/usage");
}

// --- Ask history ----------------------------------------------------------

export interface AskHistoryCurrentEvidence {
  scope: "current_paper_metadata_not_saved_excerpt";
  metadata_snapshot_at?: string;
  saved_answer_revalidated: false;
  sources: Array<{
    saved_source_position: number;
    paper_id: string | null;
    metadata_status: "checked" | "incomplete" | "unavailable";
    source_visibility: { source_status: string; reported_claim_filter_eligible: boolean };
    occurrence_visibility_summary: { total_occurrences: number; state_counts: Record<string, number>; omitted_occurrences: number } | null;
    warning_codes: string[];
  }>;
  warning_codes: string[];
}

export interface AskHistoryEntry {
  id: string;
  question: string;
  answer: string;
  sources: Array<{
    packing_info?: EvidencePackingSelection | null;
    evidence_provenance?: EvidenceProvenance;
    index?: number;
    paper_id?: string;
    arxiv_id?: string | null;
    title?: string;
    authors_short?: string;
    year?: number | null;
    section?: string | null;
    snippet?: string;
  }>;
  current_evidence?: AskHistoryCurrentEvidence;
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

export function listHistory(limit = 50, offset = 0) {
  const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return request<AskHistoryListResponse>(`/history?${qs}`);
}

export function deleteHistoryEntry(id: string) {
  return request<{ message: string }>(`/history/${id}`, {
    method: "DELETE",
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
  structure_evidence?: MaterialStructureEvidence;
  material_semantics?: MaterialSemantics;
  visibility?: MaterialVisibility;
  needs_review?: boolean;
  review_reason?: string | null;
  anomaly_review?: MaterialAnomalyReview;
  property_evidence?: MaterialPropertyEvidence;
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
  target_type: BookmarkTargetType,
  target_id: string,
) {
  return request<Bookmark>("/bookmarks", {
    method: "POST",
    body: JSON.stringify({ target_type, target_id }),
  });
}

export function deleteBookmark(id: string) {
  return request<{ message: string }>(`/bookmarks/${id}`, {
    method: "DELETE",
  });
}

export function listPaperBookmarks() {
  return request<BookmarkedPapersResponse>("/bookmarks/papers");
}

export function listMaterialBookmarks() {
  return request<BookmarkedMaterialsResponse>("/bookmarks/materials");
}

// --- Feedback -------------------------------------------------------------

export type FeedbackCategory = "bug" | "feature_request" | "data_issue" | "other";

export interface FeedbackPayload {
  category: FeedbackCategory;
  message: string;
  contact_email?: string | null;
}

export function submitFeedback(payload: FeedbackPayload) {
  return request<{ message: string }>("/feedback", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// --- Phase 3 public/search types ------------------------------------------

export interface SearchFilters {
  year_min?: number | null;
  year_max?: number | null;
  material_family?: string[] | null;
  tc_min?: number | null;
  pressure_max?: number | null;
  pressure_min?: number | null;
  ambient_only?: boolean;
  include_unknown_pressure?: boolean;
  knowledge_origin?: string[];
  source_role?: "primary" | "cited";
  experimental_only?: boolean;
  exclude_retracted?: boolean;
}

export interface SearchRequest {
  query: string;
  top_k?: number;
  filters?: SearchFilters;
  sort?: "relevance" | "date" | "tc";
}

export interface MaterialExtract {
  visibility?: SourceOccurrenceVisibility;
  formula?: string | null;
  tc_kelvin?: number | null;
  tc_type?: string | null;
  pressure_gpa?: number | null;
  pressure_semantics?: Record<string, unknown>;
  measurement?: string | null;
  confidence?: number | null;
}

export interface MatchingScientificResult {
  visibility?: MaterialVisibility | SourceOccurrenceVisibility;
  result_id: string;
  record_index: number;
  formula: string | null;
  family: string | null;
  tc_lower_bound_k: number | null;
  pressure_semantics: Record<string, unknown>;
  result_classification: Record<string, unknown>;
  filter_policy_version: string;
}

export interface SearchMatch {
  evidence_provenance?: EvidenceProvenance;
  source_visibility?: SourceVisibility;
  occurrence_visibility_summary?: Record<string, unknown>;
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
  matching_results?: MatchingScientificResult[];
  filter_policy_version?: string;
}

export interface SearchResponse {
  retrieval_generation?: RetrievalGeneration | null;
  scientific_query?: ScientificQueryInterpretation | null;
  scientific_results?: BoundScientificQueryResult[];
  scientific_lookup?: ScientificLookup;
  total: number;
  results: SearchMatch[];
  query_time_ms: number;
  guest_remaining: number | null;
  remaining: number | null;
}

export function search(req: SearchRequest, opts: { apiKey?: string; signal?: AbortSignal } = {}) {
  return request<SearchResponse>("/search", {
    method: "POST",
    body: JSON.stringify(req),
    apiKey: opts.apiKey,
    signal: opts.signal,
  });
}

// --- Ask ------------------------------------------------------------------

export interface AskRequest {
  question: string;
  max_sources?: number;
  language?: "auto" | "en" | "zh";
}

export interface AskSource {
  packing_info?: EvidencePackingSelection | null;
  evidence_provenance?: EvidenceProvenance;
  source_visibility?: SourceVisibility;
  index: number;
  paper_id: string;
  arxiv_id: string | null;
  title: string;
  authors_short: string;
  year: number | null;
  section: string | null;
  snippet: string;
}

export interface EvidenceProvenance {
  version: "rag-evidence/1.0.0";
  chunk_kind: "original_passage" | "abstract" | "derived_fact" | "legacy_unknown";
  evidence_revision_id: string | null;
  evidence_record_sha256: string | null;
  content_sha256: string;
  parent_result_revision_id: string | null;
  parent_result_sha256: string | null;
  extraction_version: string | null;
  rendering_version: string | null;
  source_capture_id: string | null;
  source_locator: Record<string, string | number>;
  root_status: "unresolved";
  permission_status: "unresolved" | "restricted";
  currentness: "current" | "stale" | "unresolved";
  warning_codes: string[];
  support_eligible: false;
  independent_evidence: false;
  scientific_acceptance: false;
}

export interface AskResponse {
  scientific_mixed?: ScientificMixedEvidence;
  evidence_packing?: EvidencePackingSummary;
  input_budget?: RagInputBudgetReport;
  retrieval_generation?: RetrievalGeneration | null;
  scientific_query?: ScientificQueryInterpretation | null;
  scientific_results?: BoundScientificQueryResult[];
  scientific_lookup?: ScientificLookup;
  answer: string;
  sources: AskSource[];
  tokens_used: number | null;
  query_time_ms: number;
  /** @deprecated Legacy mechanical citation check; never scientific approval. */
  citation_valid: boolean;
  citation_warnings: string[];
  guest_remaining: number | null;
  remaining: number | null;
  support_policy_version?: string;
  citation_indices_valid?: boolean;
  lexical_support_checked?: boolean;
  scientific_support_status?: AskScientificSupportStatus;
  claim_assessments?: AskClaimAssessment[];
  support_warnings?: string[];
  support_coverage?: AskSupportCoverage;
  answer_mode?: "synthesis" | "limited_synthesis" | "extractive_fallback" | "abstention";
  assessment_scope?: "generated_draft" | "none";
}

export type ScientificMixedReason = "numerical_explanation_not_established" | "reviewed_result_passage_bridge_missing"
  | "no_matching_extraction" | "no_original_context" | "combined_source_limit" | "mixed_lookup_unavailable"
  | "mixed_context_unavailable" | "mixed_currentness_unavailable" | "retrieval_generation_changed"
  | "retrieval_source_changed" | "retrieval_source_no_longer_eligible" | "retrieval_grouping_changed"
  | "retrieval_currentness_unavailable" | "retrieval_currentness_timeout" | "evidence_packing_unavailable";

export interface MixedEvidenceAssociation {
  parent_result_revision_id: string;
  result_source_snapshot_sha256: string;
  source_index: number;
  source_vector_id: string;
  source_evidence_revision_id: string;
  source_evidence_record_sha256: string;
  source_content_sha256: string;
  catalogue_relation: "same_snapshot" | "not_same_snapshot";
  status: "not_established";
  reason_code: "reviewed_result_passage_bridge_missing";
}

/** Separate retrieval inventories, never a numerical explanation or experiment link. */
export interface ScientificMixedEvidence {
  version: "scientific-mixed-evidence/1.0.0";
  status: "not_requested" | "completed" | "unavailable";
  result_count: number;
  source_count: number;
  max_selected_inputs: number;
  associations: MixedEvidenceAssociation[];
  reason_codes: ScientificMixedReason[];
  scientific_acceptance: false;
  independent_support_count: null;
}

export interface AskSupportCoverage {
  total_claims?: number;
  assessed_claims?: number;
  supported_claims?: number;
  contradicted_claims?: number;
  undetermined_claims?: number;
  truncated?: boolean;
  limits?: Record<string, unknown>;
}

/** Operational context selection, never independent evidence or source rights. */
export interface EvidencePackingSelection {
  version: "evidence-pack-item/1.0.0";
  position: number;
  chunk_id: string;
  source_group_id: string;
  source_snapshot_sha256: string | null;
  diversity_group_id: string;
  source_group_basis: "source_snapshot" | "legacy_paper";
  group_basis: "accepted_work_mapping" | "source_snapshot" | "legacy_paper";
  role_hint: "methods" | "results" | "table" | "other";
  selection_reason: "source_diversity" | "source_coverage" | "complementary_role";
  scientific_acceptance: false;
}

export interface RagInputBudgetReport {
  status: "not_requested" | "counted" | "rejected" | "unavailable";
  model: string | null;
  profile: "sclib-gemini-text-rag/1.0.0";
  request_sha256: string | null;
  payload_bytes: number | null;
  byte_limit: number;
  input_tokens: number | null;
  max_input_tokens: number | null;
  count_method: "provider_count_tokens";
  generation_started: boolean | null;
  scientific_acceptance: false;
}

export type PackingExclusionReason = "payload_budget" | "base_payload_budget" | "chunk_limit" | "source_limit" | "work_limit" | "duplicate_content" | "role_already_represented" | "not_complementary_original";
export type PackingSummaryReason = "packing_not_requested" | "no_admitted_candidates" | "base_payload_budget_exceeded" | "payload_budget_excluded" | "selection_limits_applied" | "duplicate_content_removed" | "complementarity_not_established" | "packing_unavailable" | "selected_context_withheld";
export interface EvidencePackingSummary {
  version: "evidence-packing/1.0.0";
  status: "not_requested" | "packed" | "empty" | "base_budget_exceeded" | "withheld" | "unavailable";
  candidate_count: number;
  selected_count: number;
  source_group_count: number;
  diversity_group_count: number;
  payload_bytes: number | null;
  byte_budget: number | null;
  byte_count_method: "utf8-full-payload/1";
  max_chunks: number;
  max_per_source: number;
  max_per_work: number;
  reason_counts: Partial<Record<PackingExclusionReason, number>>;
  reason_codes: PackingSummaryReason[];
  independent_support_count: null;
  independence_status: "independence_not_established";
  scientific_acceptance: false;
}

export type AskScientificSupportStatus = "supported" | "contradicted" | "undetermined" | "not_checked";

export interface AskClaimAssessment {
  claim_id: string;
  text: string;
  cited_indices: number[];
  status: AskScientificSupportStatus;
  reason_codes: string[];
  evidence: { source_index: number; paper_id: string | null; excerpt: string }[];
}

export function ask(req: AskRequest, opts: { apiKey?: string; signal?: AbortSignal } = {}) {
  return request<AskResponse>("/ask", {
    method: "POST",
    body: JSON.stringify(req),
    apiKey: opts.apiKey,
    signal: opts.signal,
  });
}

/** Query interpretation and machine extractions are not scientific acceptance. */
export interface RetrievalGeneration {
  version: "index-read/1.0.0";
  mode: "generation_snapshot" | "legacy_lexical_only";
  generation_id: string | null;
  activation_event_id: string | null;
  manifest_sha256: string | null;
}

export interface ScientificQuerySpan { raw_text: string; start: number; end: number }
export interface FormulaQueryNormalization {
  version: "formula-query/1.0.0";
  raw_formula: string;
  normalized_formula: string | null;
  status: "normalized" | "unresolved";
  reason_codes: string[];
}
export interface ScientificQuantityConstraint extends ScientificQuerySpan {
  field: "tc_kelvin" | "pressure_gpa";
  relation: "exact" | "lt" | "le" | "gt" | "ge" | "interval";
  value: number | null;
  lower: number | null;
  upper: number | null;
  unit: "K" | "GPa";
  unit_basis: "explicit" | "explicit_ambient_reference";
}
export interface ScientificEvidenceConstraint extends ScientificQuerySpan {
  field: "knowledge_origin" | "source_role" | "experimental_outcome";
  value: "Observed" | "Computed" | "Inferred" | "AI-Proposed" | "Unknown" | "primary" | "cited" | "positive_reported" | "not_detected";
}
export interface ScientificQueryInterpretation {
  version: "scientific-query/1.0.0";
  raw_query: string;
  normalized_query: string;
  language: "en" | "zh" | "mixed";
  intent: "numerical" | "mechanism" | "mixed" | "comparison" | "general";
  status: "resolved" | "clarification_required";
  requested_fields: ("tc_kelvin" | "pressure_gpa")[];
  formulas: (ScientificQuerySpan & { normalization: FormulaQueryNormalization })[];
  constraints: ScientificQuantityConstraint[];
  evidence_constraints: ScientificEvidenceConstraint[];
  unresolved_clauses: (ScientificQuerySpan & { reason_code: string })[];
  clarification_questions: string[];
  scientific_acceptance: false;
}

export interface ScientificReportQuantity {
  status: "parsed" | "unreported" | "invalid";
  relation: "exact" | "lt" | "le" | "gt" | "ge" | "interval" | "unreported";
  value: number | null;
  lower: number | null;
  upper: number | null;
  uncertainty: number | null;
  approximate: boolean;
  unit: "K" | "GPa";
  unit_basis: "explicit" | "field_schema_assumption" | "endpoint_units" | "unreported" | "explicit_ambient_reference";
  uncertainty_interpretation: "unspecified" | null;
}
export interface ScientificQueryResult {
  version: "scientific-query-result/1.0.0";
  result_id: string;
  record_index: number;
  formula: string;
  family: string | null;
  tc: ScientificReportQuantity;
  minimum_temperature: ScientificReportQuantity;
  pressure: ScientificReportQuantity & { pressure_state: "explicit_ambient" | "reported" | "not_reported" | "ambiguous" };
  result_classification: {
    knowledge_origin: "Observed" | "Computed" | "Inferred" | "AI-Proposed" | "Unknown";
    classification_status: "resolved" | "unknown" | "conflicted";
    source_role: "primary" | "cited" | "unknown" | "conflicted";
  };
  outcome_state: "positive_reported" | "not_detected" | "unspecified" | "unresolved" | "conflicted";
  reported_context: { tc_criterion: string | null; sample_label: string | null; sample_form: string | null; structure_phase: string | null; measurement_method: string | null };
  warning_codes: string[];
  scientific_acceptance: false;
  ml_training_eligible: false;
  detection_adequacy_verified: false;
}
export interface BoundScientificQueryResult {
  result: ScientificQueryResult;
  binding: {
    paper_id: string;
    vector_id: string;
    generation_id: string;
    activation_event_id: string;
    manifest_sha256: string;
    content_sha256: string;
    evidence_revision_id: string;
    evidence_record_sha256: string;
    parent_result_revision_id: string;
    parent_result_sha256: string;
    association_scope: "derived_extraction_not_original_support";
  };
}
export interface ScientificLookup {
  status: "not_requested" | "completed" | "unavailable" | "clarification_required";
  reason_codes: string[];
  returned_count: number;
  has_more: boolean;
  scope: "declared_generation_derived_extractions";
  scientific_acceptance: false;
}

// --- Materials ------------------------------------------------------------

/** Operational anomaly checks are not scientific acceptance or source corrections. */
export interface ScientificAnomalyFinding {
  finding_id: string;
  result_id: string;
  rule_id: string;
  rule_version: string;
  category: "format_invalid" | "metadata_conflict" | "unusual";
  field: string;
  affected_properties: string[];
  applicability: Record<string, unknown>;
  reason: string;
  description: string;
  severity: string;
  outcome: "pending";
  action: "retain_raw_and_review";
  quantity: Record<string, unknown> | null;
  default_view_disposition: "review_required";
}

export interface ScientificAnomalyAssessment {
  version: "anomaly-review/1.0.0";
  result_id: string;
  status: "no_findings" | "review_required" | "format_invalid";
  findings: ScientificAnomalyFinding[];
  total_findings: number;
  findings_truncated: boolean;
  review_required_properties: string[];
  raw_preserved: true;
  scientific_acceptance: false;
}

export interface MaterialAnomalyReview {
  version: "anomaly-review/1.0.0";
  needs_review: boolean;
  counts: { no_findings: number; review_required: number; format_invalid: number; total_records: number };
  rule_counts: Record<string, number>;
  records: ScientificAnomalyAssessment[];
  total_records: number;
  records_truncated: boolean;
  raw_preserved: true;
  scientific_acceptance: false;
  warnings: string[];
}

export interface MaterialRawArchive {
  visibility?: MaterialVisibility;
  version: "anomaly-review/1.0.0";
  scope: "material_retained_records";
  raw_field_policy: "scientific_allowlist_not_full_source";
  records: { result_id: string; record_index: number; raw: Record<string, unknown>; assessment: ScientificAnomalyAssessment }[];
  total: number;
  returned: number;
  truncated: boolean;
}

export interface PropertyEvidenceItem {
  anomaly_review?: ScientificAnomalyAssessment;
  result_id: string;
  property: string;
  value: unknown;
  quantity: Record<string, unknown> | null;
  conditions: Record<string, unknown>;
  state: Record<string, unknown>;
  source: Record<string, unknown>;
  origin: Record<string, unknown>;
  structure: Record<string, unknown>;
  warnings?: string[];
}

export interface PropertyEvidenceSelection {
  status: "supported" | "untraceable" | "not_reported" | "pending";
  selection: "legacy_exact_support" | "deterministic_result" | "none";
  selected: PropertyEvidenceItem | null;
  evidence: PropertyEvidenceItem[];
  warnings: string[];
  statistic?: "catalogue_median" | null;
  total_evidence_count?: number;
  truncated?: boolean;
}

export interface MaterialPropertyEvidence {
  version: "property-evidence/1.1.0";
  anomaly_policy_version: "anomaly-review/1.0.0";
  not_joint_observation: true;
  properties: Record<string, PropertyEvidenceSelection>;
  evidence_scope?: "selected_only" | "bounded_alternatives";
  joint_epc: {
    status: "eligible" | "pending" | "not_reported" | "not_evaluated";
    pairs: Record<string, unknown>[];
    selected?: Record<string, unknown> | null;
    warnings: string[];
    total_pair_count?: number | null;
    total_pair_count_exact?: boolean;
    total_pair_count_lower_bound?: number;
    truncated?: boolean;
  };
}

export interface MaterialVisibility {
  version: "material-visibility/1.0.0";
  state: "catalogue" | "pending" | "disputed" | "corrected" | "retracted" | "quarantined" | "unknown";
  public_catalogue_eligible: boolean;
  archive_available: boolean;
  scientific_acceptance: false;
  reason_codes: string[];
  warning_codes: string[];
  reason_messages?: string[];
  warning_messages?: string[];
  review_revision: string;
  source_status: "active" | "retracted" | "corrected" | "mixed" | "unknown";
  scope?: string;
}

export interface SourceVisibility {
  version: "material-visibility/1.0.0";
  source_status: "active" | "retracted" | "corrected" | "disputed" | "unknown";
  bibliography_available: boolean;
  reported_claim_filter_eligible: boolean;
  scientific_acceptance: false;
  warning_codes: string[];
}

export interface SourceOccurrenceVisibility extends Omit<MaterialVisibility, "review_revision" | "source_status"> {
  review_revision: string | null;
  source_status: SourceVisibility["source_status"] | "mixed";
  material_link_status: "resolved" | "unresolved" | "unlinked";
  reported_claim_filter_eligible: boolean;
}

export interface MaterialSummary {
  structure_evidence?: MaterialStructureEvidence;
  material_semantics?: MaterialSemantics;
  visibility?: MaterialVisibility;
  needs_review?: boolean;
  review_reason?: string | null;
  anomaly_review?: MaterialAnomalyReview;
  property_evidence?: MaterialPropertyEvidence;
  matching_results?: MatchingScientificResult[];
  filter_policy_version?: string;
  result_classification_version?: string;
  result_origin_counts?: Record<string, number>;
  classification_conflicts?: number;
  tc_max_origin?: string;
  id: string;
  formula: string;
  formula_latex: string | null;
  family: string | null;
  subfamily: string | null;
  tc_max: number | null;
  tc_max_conditions: string | null;
  tc_ambient: number | null;
  dominant_evidence: string | null;
  tc_max_experimental: number | null;
  tc_max_theoretical: number | null;
  arxiv_year: number | null;
  total_papers: number;
  status: string;
  // v2
  pairing_symmetry: string | null;
  structure_phase: string | null;
  ambient_sc: boolean | null;
  is_unconventional: boolean | null;
  has_competing_order: boolean | null;
  // Credibility
  best_credibility_tier: string | null;
  // P2
  parent_material_id: string | null;
  variant_count: number;
}

export interface MaterialDetail extends MaterialSummary {
  raw_archive?: MaterialRawArchive;
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
  // P2: Interface decomposition
  formula_substrate: string | null;
  formula_overlayer: string | null;
  layer_thickness_nm: number | null;
  // P2: Variants
  variants: VariantSummary[];
  // Phase B — Materials Project linkage. mp_id is null when the
  // formula has no MP entry. mp_alternate_ids is sorted by
  // energy_above_hull (lowest first); alternate_ids[0] === mp_id when
  // there's a match.
  mp_id: string | null;
  mp_alternate_ids: string[];
  mp_synced_at: string | null;
}

export interface VariantSummary {
  structure_evidence?: MaterialStructureEvidence;
  material_semantics?: MaterialSemantics;
  visibility?: MaterialVisibility;
  needs_review?: boolean;
  review_reason?: string | null;
  anomaly_review?: MaterialAnomalyReview;
  property_evidence?: MaterialPropertyEvidence;
  id: string;
  formula: string;
  tc_max: number | null;
  tc_ambient: number | null;
  total_papers: number;
  doping_level: number | null;
  pressure_type: string | null;
}

export interface MaterialStructureEvidence {
  version: string;
  scientific_acceptance: false;
  coordinate_status: string;
  properties: Record<string, { status: string; value: null; proposal_count: number }>;
  proposals: Record<string, unknown>[];
  unassigned_mentions: Record<string, unknown>[];
  coverage: Record<string, unknown>;
  warnings: string[];
}

export type MaterialSemanticField = "has_competing_order" | "is_unconventional" | "pairing_symmetry";
export type MaterialSemanticStatus = "reported" | "unknown" | "not_reported" | "not_extracted" | "not_computed" | "failed" | "conflicted" | "not_applicable";

export interface MaterialSemanticEvidence {
  result_id: string;
  result_revision?: string | number | null;
  paper_id?: string | null;
  bibliographic_identifiers?: { kind: string; value: string }[];
  source_status?: string;
  status: MaterialSemanticStatus;
  value: boolean | string | null;
  basis: string;
  eligible_for_summary: boolean;
  negative_qualified: boolean;
  knowledge_origin?: string;
  classification_status?: string;
  source_role?: string;
  state?: Record<string, unknown>;
  method?: string | null;
  detection_conditions?: Record<string, unknown>;
  source_locator?: Record<string, unknown>;
  reason_codes?: string[];
  source_value?: unknown;
  status_reason?: string | null;
  occurrence_id?: string;
  occurrence_count?: number;
}

export interface MaterialSemanticProperty {
  status: MaterialSemanticStatus;
  value: boolean | string | null;
  basis: string;
  reason_codes: string[];
  evidence: MaterialSemanticEvidence[];
  total_evidence: number;
  total_occurrences?: number;
  evidence_truncated: boolean;
}

export interface MaterialSemantics {
  version: string;
  scientific_acceptance?: false;
  properties: Partial<Record<MaterialSemanticField, MaterialSemanticProperty>>;
  priors: { property: string; value: unknown; knowledge_origin: string; basis: string; policy_version?: string; provenance?: unknown; applicability?: unknown; warning_codes?: string[] }[];
  conflicts: {
    state_variability?: { detected?: boolean; count?: number; properties?: string[]; evidence?: unknown[]; [key: string]: unknown };
    extraction_conflict?: { detected?: boolean; count?: number; properties?: string[]; evidence?: unknown[]; [key: string]: unknown };
    scientific_dispute?: { status?: string; count?: number; evidence?: unknown[]; [key: string]: unknown };
  };
  support: {
    occurrence_count?: number;
    bibliographic_identifier_count?: number;
    source_backed_occurrence_count?: number;
    independent_work_count?: number | null;
    independent_replication_count?: number | null;
    [key: string]: unknown;
  };
  warnings: string[];
}

export interface PhaseDiagramPoint {
  visibility?: MaterialVisibility;
  formula: string;
  tc_kelvin: number;
  doping_level: number | null;
  pressure_gpa: number | null;
  paper_id: string | null;
  year: number | null;
}

export interface HydrideTcParameterRecord {
  visibility?: MaterialVisibility;
  pressure_semantics?: Record<string, unknown>;
  id: number;
  material_id: string | null;
  formula: string;
  formula_normalized: string;
  paper_id: string;
  source: string;
  doi: string | null;
  arxiv_id: string | null;
  year: number | null;
  tc_kelvin: number | null;
  pressure_gpa: number | null;
  lambda_eph: number | null;
  mu_star: number | null;
  omega_log_k: number | null;
  omega_log_source_value: number | null;
  omega_log_source_unit: string | null;
  method: string | null;
  evidence_type: string | null;
  confidence: number | null;
  source_section: string | null;
  validation_flags: unknown[];
  provenance: Record<string, unknown>;
  model: string | null;
  prompt_version: string;
  created_at: string;
  updated_at: string;
}

export interface MaterialListResponse {
  total: number;
  results: MaterialSummary[];
  limit: number;
  offset: number;
  sort_basis?: "legacy_catalogue";
  scientific_display_policy?: "atomic_property_evidence";
  classification_filter_policy_version?: string;
  classification_filter_scope?: "material_reported_summary_not_joint_state";
}

export interface MaterialListParams {
  family?: string;
  tc_min?: number;
  ambient_sc?: boolean;
  pressure_min?: number;
  pressure_max?: number;
  include_unknown_pressure?: boolean;
  knowledge_origin?: string;
  source_role?: "primary" | "cited";
  experimental_only?: boolean;
  is_unconventional?: boolean;
  has_competing_order?: boolean;
  pairing_symmetry?: string;
  structure_phase?: string;
  min_tier?: "T1" | "T2" | "T3";
  min_papers?: number;
  parents_only?: boolean;
  sort?: "tc_max" | "tc_ambient" | "arxiv_year" | "total_papers";
  limit?: number;
  offset?: number;
  include_skeletons?: boolean;
  only_aps?: boolean;
}

export function listMaterials(params: MaterialListParams) {
  const qs = new URLSearchParams();
  if (params.family) qs.set("family", params.family);
  if (params.tc_min != null) qs.set("tc_min", String(params.tc_min));
  if (params.ambient_sc != null) qs.set("ambient_sc", String(params.ambient_sc));
  if (params.pressure_min != null) qs.set("pressure_min", String(params.pressure_min));
  if (params.pressure_max != null) qs.set("pressure_max", String(params.pressure_max));
  if (params.include_unknown_pressure) qs.set("include_unknown_pressure", "true");
  if (params.knowledge_origin) qs.set("knowledge_origin", params.knowledge_origin);
  if (params.source_role) qs.set("source_role", params.source_role);
  if (params.experimental_only) qs.set("experimental_only", "true");
  if (params.is_unconventional != null)
    qs.set("is_unconventional", String(params.is_unconventional));
  if (params.has_competing_order != null)
    qs.set("has_competing_order", String(params.has_competing_order));
  if (params.pairing_symmetry) qs.set("pairing_symmetry", params.pairing_symmetry);
  if (params.structure_phase) qs.set("structure_phase", params.structure_phase);
  if (params.min_tier) qs.set("min_tier", params.min_tier);
  if (params.min_papers != null) qs.set("min_papers", String(params.min_papers));
  if (params.sort) qs.set("sort", params.sort);
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.offset != null) qs.set("offset", String(params.offset));
  if (params.parents_only) qs.set("parents_only", "true");
  if (params.include_skeletons) qs.set("include_skeletons", "true");
  if (params.only_aps) qs.set("only_aps", "true");
  return request<MaterialListResponse>(
    `/materials${qs.toString() ? `?${qs}` : ""}`,
  );
}

export function getMaterial(id: string) {
  return request<MaterialDetail>(`/materials/${encodeURIComponent(id)}`);
}

export function getMaterialPhaseDiagram(id: string) {
  return request<PhaseDiagramPoint[]>(
    `/materials/${encodeURIComponent(id)}/phase_diagram`,
  );
}

export function getMaterialHydrideParameters(id: string) {
  return request<HydrideTcParameterRecord[]>(
    `/materials/${encodeURIComponent(id)}/hydride_parameters`,
  );
}

// --- Papers ---------------------------------------------------------------

export interface PaperDetail {
  source_visibility?: SourceVisibility;
  occurrence_visibility_summary?: Record<string, unknown>;
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
  credibility_tier: string | null;
  paper_type: string | null;
  journal: string | null;
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

// --- Search-engine discovery ---------------------------------------------

export type SitemapResourceKind = "paper" | "material";

export interface SitemapResource {
  kind: SitemapResourceKind;
  id: string;
  updated_at: string;
}

export interface SitemapResourcePage {
  total: number;
  limit: number;
  offset: number;
  results: SitemapResource[];
}

/**
 * Fetch a payload-minimal public inventory for XML sitemap generation.
 * The API caps pages at 10,000 URLs so each XML document stays well below
 * the search-engine protocol limit of 50,000 URLs.
 */
export function listSitemapResources(
  kind: SitemapResourceKind,
  limit = 10_000,
  offset = 0,
) {
  const qs = new URLSearchParams({
    kind,
    limit: String(limit),
    offset: String(offset),
  });
  return request<SitemapResourcePage>(`/sitemap/resources?${qs}`, {
    cache: "no-store",
  });
}

// --- Stats / timeline -----------------------------------------------------

export interface StatsResponse {
  total_papers: number;
  total_materials: number;
  total_chunks: number;
  papers_by_year: Record<string, number>;
  papers_by_year_arxiv: Record<string, number>;
  papers_by_year_aps: Record<string, number>;
  top_material_families: Array<{ family: string; count: number }>;
  last_ingest_at: string | null;
  stats_refreshed_at?: string | null;
  updated_at: string;
  dataset_version?: string | null;
  data_pipeline?: {
    status: "complete" | "partial" | "failed" | "unknown";
    last_run_at: string | null;
    stages: Record<
      string,
      { status: "complete" | "failed" | "unknown"; exit_code: number | null }
    >;
  };
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
  point_id?: string | null;
  material_id?: string | null;
  result_metadata?: TimelineResultMetadata;
  visibility?: MaterialVisibility;
  pressure_semantics?: Record<string, unknown>;
  material: string;
  formula_latex?: string | null;
  family: string | null;
  tc_kelvin: number;
  year: number;
  pressure_gpa: number | null;
  paper_id: string | null;
  /** Compatibility flag only: false does not establish an observation. */
  is_theoretical: boolean;
  knowledge_origin?: string;
  classification_status?: string;
  source_role?: string;
  classifier_version?: string;
}

export interface TimelineResultMetadata {
  version?: string;
  source_date_basis?: string | null;
  chronology_warnings?: string[];
  identity_warnings?: string[];
  identity_conflict?: boolean;
  result_id?: string | null;
  result_revision?: string | number | null;
  identity_basis?: string;
  year_basis?: string;
  source_date?: string | null;
  source_version?: string | number | null;
  state?: Record<string, unknown>;
  tc_criterion?: string;
  source_locator?: Record<string, unknown>;
  occurrence_count?: number;
  review_status?: string;
}

export interface TimelineSampling {
  policy_version: string;
  method: string;
  requested_max_points: number | null;
  total_points: number;
  selected_points: number;
  returned_points: number;
  is_sampled: boolean;
  strata_total: number;
  strata_represented: number;
  rare_groups_omitted: number;
  display_only: true;
  strata_by?: string[];
  selected_source_count?: number;
  source_count?: number;
}

export interface TimelineRecordSummary {
  scope: "full_filtered_unsampled";
  total_points: number;
  total_materials: number;
  source_count: number;
  max_tc_kelvin: number | null;
  min_tc_kelvin: number | null;
  by_family: Record<string, number>;
  by_origin: Record<string, number>;
  by_year_basis: Record<string, number>;
  by_pressure_state: Record<string, number>;
  record_candidates: TimelinePoint[];
  record_candidate_count?: number;
  record_candidates_truncated?: boolean;
  label?: string;
}

export interface TimelineCoverage {
  total_points: number;
  total_materials: number;
  year_min: number | null;
  year_max: number | null;
  returned_points: number;
  available_points: number | null;
}

export interface TimelineResponse {
  schema_version: "1";
  data_version: string;
  data_updated_at: string | null;
  family: string | null;
  points: TimelinePoint[];
  coverage: TimelineCoverage | null;
  offset: number;
  limit: number | null;
  has_more: boolean;
  timeline_policy_version?: string;
  visibility_policy_version?: string;
  sampling?: TimelineSampling;
  record_summary?: TimelineRecordSummary;
  review_mode?: string;
  reviewed_only_available?: boolean;
}

export function getTimeline(opts: {
  family?: string;
  experimentalOnly?: boolean;
  onlyAps?: boolean;
  maxPoints?: 5000 | 10000 | 20000 | 50000;
  compact?: boolean;
  offset?: number;
  limit?: number;
  schemaVersion?: "1";
} = {}) {
  const qs = new URLSearchParams({
    schema_version: opts.schemaVersion ?? "1",
  });
  if (opts.family) qs.set("family", opts.family);
  if (opts.experimentalOnly) qs.set("experimental_only", "true");
  if (opts.onlyAps) qs.set("only_aps", "true");
  if (opts.maxPoints) qs.set("max_points", String(opts.maxPoints));
  if (opts.compact) qs.set("compact", "true");
  if (opts.offset != null) qs.set("offset", String(opts.offset));
  if (opts.limit != null) qs.set("limit", String(opts.limit));
  const qstr = qs.toString();
  return request<TimelineResponse>(`/timeline${qstr ? `?${qstr}` : ""}`, {
    cache: "no-store",
    credentials: "omit",
  });
}

export interface DiscoveryFilterRule {
  key: string;
  label: string;
  value: string;
}

export interface DiscoveryCandidate {
  schema_version: "1";
  candidate_id: string;
  formula: string;
  normalized_formula: string | null;
  branch: string;
  lane_id: string | null;
  prototype_family: string | null;
  candidate_layer: string | null;
  candidate_quantity_score: number | null;
  candidate_quality_score: number | null;
  entry_block_reason: string | null;
  upgrade_requirements: string[];
  family_ruleset_id: string | null;
  validation_recipe_id: string | null;
  condition_class: string | null;
  required_condition_vector: string[];
  evidence_level: string;
  checker_status: string;
  public_confidence: string;
  evidence_schema_version: string | null;
  evidence_quality_score: number | null;
  literature_verifier_status: string | null;
  literature_verifier_flags: string[];
  failure_mode_taxonomy: string[];
  synthesis_feasibility_score: number | null;
  synthesis_feasibility_flags: string[];
  measurement_clarity_score: number | null;
  correlation_gate_status: string | null;
  correlation_gate_flags: string[];
  experiment_priority_score: number | null;
  experiment_readiness: string | null;
  record_role: string | null;
  claim_level: string | null;
  next_action: string | null;
  discovery_score: number | null;
  mechanism_hypothesis: string | null;
  risk_tags: string[];
  review_summary: string | null;
  provenance_summary: string | null;
  recommended_next_step: string | null;
  last_reviewed_at_utc: string | null;
  published_at_utc: string | null;
  base_discovery_score?: number | null;
  condition_badges?: string[];
  display_class?: string | null;
  family_gate_stage?: string | null;
  legacy_candidate_id?: string | null;
  taxonomy_bucket?: string | null;
}

export interface DiscoveryResponse {
  schema_version: "1";
  page_title: string;
  intro: string[];
  status: "planned" | "active";
  updated_at_utc: string | null;
  source: string | null;
  filter_rules: DiscoveryFilterRule[];
  candidates: DiscoveryCandidate[];
}

export function getDiscovery() {
  return request<DiscoveryResponse>("/discovery?schema_version=1", {
    cache: "force-cache",
    credentials: "omit",
    next: { revalidate: 60 },
  });
}

export type DiscoveryCandidateSummary = Pick<
  DiscoveryCandidate,
  | "candidate_id"
  | "formula"
  | "branch"
  | "lane_id"
  | "prototype_family"
  | "candidate_layer"
  | "condition_class"
  | "evidence_level"
  | "checker_status"
  | "public_confidence"
  | "evidence_quality_score"
  | "experiment_readiness"
  | "record_role"
  | "claim_level"
  | "next_action"
  | "discovery_score"
>;

export interface DiscoveryVersion {
  data_version: string;
  source_status: "ready" | "stale" | "missing" | "invalid";
  last_successful_at: string | null;
  source_error: "invalid_update" | "source_missing" | null;
}

export interface DiscoveryMetadata extends DiscoveryVersion {
  schema_version: "1";
  page_title: string;
  intro: string[];
  status: "planned" | "active";
  updated_at_utc: string | null;
  source: string | null;
  filter_rules: DiscoveryFilterRule[];
  total_candidates: number;
  role_counts: Record<string, number>;
}

export interface DiscoveryCandidatePage extends DiscoveryVersion {
  schema_version: "1";
  items: DiscoveryCandidateSummary[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
  record_role: string | null;
}

const DISCOVERY_PAGE_SIZE = 24;

export function getDiscoveryMetadata() {
  return request<DiscoveryMetadata>("/discovery/metadata?schema_version=1", {
    cache: "no-store",
    credentials: "omit",
  });
}

export function getDiscoveryCandidates(opts: {
  dataVersion: string;
  offset?: number;
  limit?: number;
  recordRole?: string | null;
}) {
  const qs = new URLSearchParams({
    offset: String(opts.offset ?? 0),
    limit: String(opts.limit ?? DISCOVERY_PAGE_SIZE),
    schema_version: "1",
    data_version: opts.dataVersion,
  });
  if (opts.recordRole) qs.set("record_role", opts.recordRole);
  return request<DiscoveryCandidatePage>(`/discovery/candidates?${qs}`, {
    cache: "no-store",
    credentials: "omit",
  });
}

export function getDiscoveryCandidate(candidateId: string, dataVersion: string) {
  const qs = new URLSearchParams({ schema_version: "1", data_version: dataVersion });
  return request<DiscoveryCandidate & DiscoveryVersion>(
    `/discovery/candidates/${encodeURIComponent(candidateId)}?${qs}`,
    {
      cache: "no-store",
      credentials: "omit",
    },
  );
}

export class DiscoveryVersionError extends Error {
  constructor() { super("The Discovery feed changed or could not be verified. Reload the latest feed."); }
}

export function isDiscoveryVersionConflict(error: unknown): boolean {
  return error instanceof DiscoveryVersionError || (error instanceof ApiError && [409, 428].includes(error.status));
}

export function verifyDiscoveryPage(
  page: DiscoveryCandidatePage, version: string, offset: number,
  previous: DiscoveryCandidateSummary[] = [], role: string | null = null, expectedTotal?: number,
): void {
  if (!/^discovery-v1-[a-f0-9]{16}$/.test(version) || page.data_version !== version ||
      page.schema_version !== "1" || !["ready", "stale"].includes(page.source_status) ||
      page.offset !== offset || page.record_role !== role || !Number.isInteger(page.total) || page.total < 0 ||
      !Number.isInteger(page.limit) || page.limit < 1 || page.limit > 100 ||
      (expectedTotal !== undefined && page.total !== expectedTotal) ||
      page.items.length > page.limit || offset + page.items.length > page.total ||
      page.has_more !== (offset + page.items.length < page.total) || (page.has_more && page.items.length === 0)) {
    throw new DiscoveryVersionError();
  }
  const ids = new Set(previous.map(item => item.candidate_id));
  for (const item of page.items) {
    if (!item.candidate_id?.trim() || ids.has(item.candidate_id) ||
        (role !== null && (item.record_role ?? "unclassified") !== role) ||
        [item.discovery_score, item.evidence_quality_score].some(value => value != null && !Number.isFinite(value))) {
      throw new DiscoveryVersionError();
    }
    ids.add(item.candidate_id);
  }
}

export function verifyDiscoveryDetail(detail: DiscoveryCandidate & DiscoveryVersion, version: string, candidateId: string): void {
  if (detail.data_version !== version || detail.candidate_id !== candidateId || !["ready", "stale"].includes(detail.source_status)) {
    throw new DiscoveryVersionError();
  }
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
  params: { q?: string; role?: "admin" | "active" | "inactive"; limit?: number; offset?: number } = {},
) {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.role) qs.set("role", params.role);
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.offset != null) qs.set("offset", String(params.offset));
  const suffix = qs.toString() ? `?${qs}` : "";
  return request<AdminUserListResponse>(`/admin/users${suffix}`);
}

export function adminBanUser(userId: string) {
  return request<{ message: string }>(`/admin/users/${userId}/ban`, {
    method: "POST",
  });
}

export function adminUnbanUser(userId: string) {
  return request<{ message: string }>(`/admin/users/${userId}/unban`, {
    method: "POST",
  });
}

export function adminDeleteUser(userId: string) {
  return request<{ message: string }>(`/admin/users/${userId}`, {
    method: "DELETE",
  });
}

export function adminSetReviewer(userId: string, value: boolean) {
  return request<{ message: string }>(
    `/admin/users/${userId}/set-reviewer?value=${value}`,
    { method: "POST" },
  );
}

export function adminListAuditReports(rule?: string) {
  const suffix = rule ? `?rule=${encodeURIComponent(rule)}` : "";
  return request<AuditReportSummary[]>(`/admin/audit/reports${suffix}`);
}

export function adminAuditQueue(
  params: { rule?: string; limit?: number; offset?: number } = {},
) {
  const qs = new URLSearchParams();
  if (params.rule) qs.set("rule", params.rule);
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.offset != null) qs.set("offset", String(params.offset));
  const suffix = qs.toString() ? `?${qs}` : "";
  return request<AuditQueueResponse>(`/admin/audit/queue${suffix}`);
}

export function adminOverrideFlag(materialId: string, note: string) {
  return request<{ message: string }>(
    `/admin/audit/queue/${encodeURIComponent(materialId)}/override`,
    { method: "POST", body: JSON.stringify({ note }) },
  );
}

export function adminConfirmFlag(materialId: string, note: string) {
  return request<{ message: string }>(
    `/admin/audit/queue/${encodeURIComponent(materialId)}/confirm`,
    { method: "POST", body: JSON.stringify({ note }) },
  );
}

export function adminOverview() {
  return request<AdminOverview>("/admin/overview");
}
