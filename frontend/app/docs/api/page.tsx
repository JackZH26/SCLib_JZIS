/**
 * /docs/api — public API reference page.
 *
 * Static server component — no auth needed. Linked from the dashboard
 * API Keys tab so users know how to wire up their key.
 */
import type { Metadata } from "next";
import Link from "next/link";
import { absoluteUrl } from "@/lib/seo";

const API_BASE = "https://api.jzis.org/sclib/v1";

export const metadata: Metadata = {
  title: "API reference",
  description:
    "Use the SCLib API for superconductivity search, grounded Q&A, materials data, and paper metadata.",
  alternates: { canonical: absoluteUrl("/docs/api") },
  openGraph: { url: absoluteUrl("/docs/api") },
};

function Code({ children }: { children: React.ReactNode }) {
  return (
    <code className="rounded bg-slate-100 px-1.5 py-0.5 text-[13px] text-sage-ink">
      {children}
    </code>
  );
}

function Endpoint({
  method,
  path,
  badge,
  children,
}: {
  method: "GET" | "POST";
  path: string;
  badge: "free" | "quota";
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-sage-border bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={[
            "rounded px-2 py-0.5 text-xs font-bold uppercase tracking-wide",
            method === "POST"
              ? "bg-blue-100 text-blue-800"
              : "bg-emerald-100 text-emerald-800",
          ].join(" ")}
        >
          {method}
        </span>
        <code className="text-sm font-semibold text-sage-ink">{path}</code>
        <span
          className={[
            "ml-auto rounded-full px-2.5 py-0.5 text-[11px] font-medium",
            badge === "free"
              ? "bg-emerald-50 text-emerald-700"
              : "bg-amber-50 text-amber-800",
          ].join(" ")}
        >
          {badge === "free" ? "Free · no quota" : "Consumes quota"}
        </span>
      </div>
      <div className="mt-3 text-sm text-sage-muted">{children}</div>
    </div>
  );
}

export default function ApiDocsPage() {
  return (
    <main className="mx-auto max-w-4xl space-y-10 px-6 py-12">
      {/* Header */}
      <div>
        <Link
          href="/dashboard/keys"
          className="text-sm text-sage-muted hover:text-accent-deep"
        >
          &larr; Back to API Keys
        </Link>
        <h1 className="mt-3 text-3xl font-bold text-sage-ink">
          SCLib API Reference
        </h1>
        <p className="mt-2 text-base text-sage-muted">
          Programmatic access to the JZIS Superconductivity Library — hybrid
          search, RAG Q&amp;A, materials database, paper metadata, and more.
        </p>
      </div>

      {/* ── Quick start ── */}
      <section className="space-y-4">
        <h2 className="text-xl font-semibold text-sage-ink">Quick start</h2>

        <div className="space-y-3 text-sm text-sage-muted">
          <p>
            <strong className="text-sage-ink">1. Get your API Key</strong> — go
            to{" "}
            <Link href="/dashboard/keys" className="text-accent-deep underline">
              Dashboard → API Keys
            </Link>{" "}
            and click <strong>+ New key</strong>. Copy the <Code>scl_…</Code>{" "}
            value.
          </p>
          <p>
            <strong className="text-sage-ink">2. Pass it in the header</strong>{" "}
            — every request that needs authentication should include:
          </p>
        </div>

        <pre className="overflow-x-auto rounded-lg border border-sage-border bg-slate-50 p-4 text-sm leading-relaxed">
          <span className="text-slate-500"># cURL</span>
          {"\n"}curl {API_BASE}/materials \{"\n"}
          {"  "}-H <span className="text-accent-deep">&quot;X-API-Key: scl_YOUR_KEY&quot;</span>
        </pre>

        <pre className="overflow-x-auto rounded-lg border border-sage-border bg-slate-50 p-4 text-sm leading-relaxed">
          <span className="text-slate-500"># Python</span>
          {"\n"}import requests{"\n"}{"\n"}
          API = <span className="text-accent-deep">&quot;{API_BASE}&quot;</span>{"\n"}
          headers = {"{"}<span className="text-accent-deep">&quot;X-API-Key&quot;</span>: <span className="text-accent-deep">&quot;scl_YOUR_KEY&quot;</span>{"}"}{"\n"}{"\n"}
          resp = requests.get(f<span className="text-accent-deep">&quot;{"{"}API{"}"}/materials&quot;</span>, headers=headers){"\n"}
          print(resp.json())
        </pre>
      </section>

      {/* ── Authentication & quotas ── */}
      <section className="space-y-4">
        <h2 className="text-xl font-semibold text-sage-ink">
          Authentication &amp; quotas
        </h2>
        <div className="overflow-x-auto rounded-lg border border-sage-border bg-white">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-sage-tertiary">
              <tr>
                <th className="px-4 py-2 text-left font-medium">Identity</th>
                <th className="px-4 py-2 text-left font-medium">Auth method</th>
                <th className="px-4 py-2 text-right font-medium">
                  Daily quota
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-sage-muted">
              <tr>
                <td className="px-4 py-2">Guest (no key)</td>
                <td className="px-4 py-2">None — rate-limited by IP</td>
                <td className="px-4 py-2 text-right font-semibold text-sage-ink">
                  3
                </td>
              </tr>
              <tr>
                <td className="px-4 py-2">Registered user</td>
                <td className="px-4 py-2">
                  <Code>X-API-Key: scl_…</Code>
                </td>
                <td className="px-4 py-2 text-right font-semibold text-sage-ink">
                  999
                </td>
              </tr>
              <tr>
                <td className="px-4 py-2">Browser session</td>
                <td className="px-4 py-2">
                  Secure HttpOnly session cookie
                </td>
                <td className="px-4 py-2 text-right font-semibold text-sage-ink">
                  999
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="text-sm text-sage-muted">
          API Key and JWT share the same daily quota per user. Quotas reset at{" "}
          <strong>00:00 UTC</strong>. When the quota is exceeded the API returns{" "}
          <Code>429 Too Many Requests</Code>.
        </p>
        <p className="text-sm text-sage-muted">
          Password resets and “revoke all sessions” invalidate browser and
          bearer JWT sessions. API keys remain separately revocable from the{" "}
          <Link href="/dashboard/keys" className="text-accent-deep underline">
            Keys dashboard
          </Link>.
        </p>
      </section>

      {/* ── Endpoints ── */}
      <section className="space-y-5">
        <h2 className="text-xl font-semibold text-sage-ink">Endpoints</h2>
        <p className="text-sm text-sage-muted">
          Base URL:{" "}
          <Code>{API_BASE}</Code>
        </p>

        {/* Search */}
        <Endpoint method="POST" path="/search" badge="quota">
          <p className="mb-2">
            Hybrid search across the arXiv cond-mat.supr-con corpus, combining
            Vertex semantic retrieval with PostgreSQL full-text search and
            deterministic reranking.
          </p>
          <pre className="mt-2 overflow-x-auto rounded border border-slate-200 bg-slate-50 p-3 text-xs leading-relaxed">{`POST /v1/search
Content-Type: application/json

{
  "query": "iron-based superconductor pairing symmetry",
  "top_k": 20,
  "filters": {
    "year_min": 2020,
    "material_family": ["iron_based"],
    "exclude_retracted": true
  }
}`}</pre>
          <p className="mt-2">
            <strong>Response:</strong> <Code>total</Code>, <Code>results[]</Code>{" "}
            (paper_id, title, authors, year, matched_chunk, relevance_score,
            material_family), <Code>query_time_ms</Code>.
          </p>
        </Endpoint>

        {/* Ask */}
        <Endpoint method="POST" path="/ask" badge="quota">
          <p className="mb-2">
            RAG question answering — the AI reads relevant papers and generates
            a cited answer.
          </p>
          <pre className="mt-2 overflow-x-auto rounded border border-slate-200 bg-slate-50 p-3 text-xs leading-relaxed">{`POST /v1/ask
Content-Type: application/json

{
  "question": "What is the highest Tc in nickelate superconductors?",
  "max_sources": 8,
  "language": "auto"
}`}</pre>
          <p className="mt-2">
            <strong>Response:</strong> <Code>answer</Code> (Markdown with [1][2]
            citations), <Code>sources[]</Code> (paper_id, title, year),{" "}
            <Code>citation_valid</Code>, <Code>citation_warnings</Code>,{" "}
            <Code>tokens_used</Code>, and <Code>query_time_ms</Code>.
          </p>
          <p className="mt-2">
            Scientific support metadata is additive: <Code>support_policy_version</Code>,{" "}
            <Code>citation_indices_valid</Code>, <Code>lexical_support_checked</Code>,{" "}
            <Code>scientific_support_status</Code>, <Code>claim_assessments[]</Code>,{" "}
            <Code>support_warnings</Code>, <Code>support_coverage</Code>,{" "}
            <Code>assessment_scope</Code>, and <Code>answer_mode</Code>.
            The legacy <Code>citation_valid</Code> flag is deprecated and mechanical
            only; valid citation indices do not demonstrate that a claim is supported.
          </p>
          <p className="mt-2">
            <Code>scientific_support_status</Code> is <Code>supported</Code>,{" "}
            <Code>contradicted</Code>, <Code>undetermined</Code>, or <Code>not_checked</Code>.
            “Supported” means narrow excerpt consistency checks passed, not scientific
            truth, experimental confirmation, or approval as an ML label. Claim assessments
            include draft text, cited indices, reason codes, and attributable evidence excerpts.
            Coverage counts and limits describe bounded checks, not exhaustive scientific validation.
          </p>
          <p className="mt-2">
            <Code>assessment_scope=generated_draft</Code> refers to an attempted generated
            draft, not to verification of a delivered fallback. <Code>answer_mode</Code>
            distinguishes <Code>synthesis</Code>, <Code>limited_synthesis</Code>,{" "}
            <Code>extractive_fallback</Code>, and <Code>abstention</Code>.
            Conflicted or unresolved draft assertions are withheld rather than shown
            as supported conclusions. A fallback supplies source excerpts, not verified
            findings. Missing or incompatible metadata is displayed as unchecked;
            historical saved answers do not contain this current audit envelope.
          </p>
          <p className="mt-1">
            <Code>language</Code> accepts <Code>&quot;auto&quot;</Code>,{" "}
            <Code>&quot;en&quot;</Code>, or <Code>&quot;zh&quot;</Code>. Auto
            detects the question language and replies in kind.
          </p>
          <p className="mt-2">
            Search results and Ask sources carry <Code>evidence_provenance</Code>
            with evidence kind, exact revision hashes, producer versions, source
            coordinates and currentness. Version <Code>rag-evidence/1.0.0</Code>
            leaves original roots and text permissions unreviewed; its scientific
            authority flags are always false. It cannot establish independent
            confirmation or an ML training label. Derived Facts are labeled as
            generated extraction text, not original quotations. Known restricted
            or stale excerpts are withheld.
          </p>
          <p className="mt-2">
            Ask rechecks its selected database inputs after generation. A changed
            or unavailable check withdraws the draft and returns an abstention.
            A matching snapshot is not scientific acceptance or a permanent
            currentness guarantee. Saved provenance is historical and does not
            revalidate a saved answer.
          </p>
        </Endpoint>

        {/* Materials list */}
        <Endpoint method="GET" path="/materials" badge="free">
          <p className="mb-2">
            Browse and filter the superconductor materials database.
          </p>
          <pre className="mt-2 overflow-x-auto rounded border border-slate-200 bg-slate-50 p-3 text-xs leading-relaxed">{`GET /v1/materials?family=cuprate,iron_based&tc_min=50&sort=tc_max&limit=100`}</pre>
          <p className="mt-2">
            <strong>Filters:</strong> <Code>family</Code> (comma-separated),{" "}
            <Code>tc_min</Code>, <Code>ambient_sc</Code>,{" "}
            <Code>pressure_min</Code>, <Code>pressure_max</Code>,{" "}
            <Code>experimental_only</Code>, <Code>knowledge_origin</Code>,{" "}
            <Code>source_role</Code>,{" "}
            <Code>is_unconventional</Code>, <Code>has_competing_order</Code>,{" "}
            <Code>pairing_symmetry</Code>, <Code>structure_phase</Code>.
          </p>
          <p className="mt-1">
            <strong>Sort:</strong> <Code>tc_max</Code> |{" "}
            <Code>tc_ambient</Code> | <Code>arxiv_year</Code> |{" "}
            <Code>total_papers</Code>. Pagination via <Code>limit</Code> &amp;{" "}
            <Code>offset</Code>.
          </p>
          <p className="mt-2">
            Family, Tc, pressure and evidence filters must match one extracted result;
            <Code>matching_results</Code> identifies the matching occurrences and their pressure semantics.
            Unknown pressure is excluded from pressure limits unless
            <Code>include_unknown_pressure=true</Code> is explicitly requested.
            <Code>ambient_sc=true</Code> requires an observed positive result with explicit ambient evidence;
            <Code>ambient_sc=false</Code> returns 422 because absence is not a negative experiment.
            These references are legacy occurrence identifiers, not reviewed ML labels.
          </p>
          <p className="mt-2">
            Classification filters <Code>pairing_symmetry</Code>, <Code>is_unconventional</Code> and{" "}
            <Code>has_competing_order</Code> use the current source-reported material summary under{" "}
            <Code>material-semantics/1.0.0</Code>, not a same-result Tc/state predicate.
            The response declares <Code>classification_filter_scope=material_reported_summary_not_joint_state</Code>.
            Unknown or missing values never mean false; reported false requires source-linked method and detection conditions.
            Family priors and stale aggregate classifications do not match these filters.
          </p>
          <p className="mt-2">
            The additive <Code>material_semantics</Code> envelope separates reported properties, inferred priors,
            state variability, extraction conflicts and unadjudicated dispute reports. Its support counts are
            occurrences and bibliographic identifiers, not independent works or replications.
            <Code>support.count_basis</Code> explains why identifier aliases and <Code>support.legacy_total_papers</Code>
            may differ, including parent rollups and other catalogue policies. Legacy responses without this envelope remain unchecked.
          </p>
          <p className="mt-2">
            <Code>structure_evidence</Code> contains pending text proposals and unassigned mentions under <Code>structure-evidence/1.0.0</Code>.
            Structure, phase and space-group summary aliases remain null until local material/state associations and source revisions can be reviewed.
            Nonempty <Code>structure_phase</Code> filters return 422 rather than matching unverified catalogue labels.
            A source-content hash and assembled-text span are provenance proposals, not a verified publication revision, coordinate artifact or scientific approval.
            Structure evidence excerpts are withheld pending source access and redistribution review; raw response records do not export the new extraction-only quotation containers.
          </p>
        </Endpoint>

        {/* Material detail */}
        <Endpoint method="GET" path="/materials/{id}" badge="free">
          <p>
            Full detail for a single material — Tc values, pressure, crystal
            structure, pairing symmetry, all source records with paper links.
          </p>
          <pre className="mt-2 overflow-x-auto rounded border border-slate-200 bg-slate-50 p-3 text-xs leading-relaxed">{`GET /v1/materials/mat%3AYBa2Cu3O7`}</pre>
        </Endpoint>

        {/* Paper detail */}
        <Endpoint method="GET" path="/paper/{id}" badge="free">
          <p>
            Paper metadata — title, authors, abstract, journal, DOI, arXiv ID,
            extracted materials list, retraction status.
          </p>
          <pre className="mt-2 overflow-x-auto rounded border border-slate-200 bg-slate-50 p-3 text-xs leading-relaxed">{`GET /v1/paper/arxiv%3A2301.12345`}</pre>
        </Endpoint>

        {/* Similar */}
        <Endpoint method="GET" path="/similar/{paper_id}" badge="free">
          <p>
            Find semantically similar papers via vector search. Returns up to 10
            neighbours.
          </p>
        </Endpoint>

        {/* Timeline */}
        <Endpoint method="GET" path="/timeline" badge="free">
          <p>
            Reported Tc Timeline results retain result identity, revision,
            year basis, state, criterion, and source provenance. Deterministic
            stratified display budgets (<code>max_points</code>) precede stable
            <code> offset</code>/<code>limit</code> pagination.
            <Code>sampling</Code> describes display selection; <Code>record_summary</Code>
            describes the full filtered, unsampled dataset. Neither is an
            approved training dataset or a world-record chronology.
          </p>
          <pre className="mt-2 overflow-x-auto rounded border border-slate-200 bg-slate-50 p-3 text-xs leading-relaxed">{`GET /v1/timeline?schema_version=1&max_points=10000&offset=0&limit=1000&compact=true`}</pre>
          <p className="mt-2">
            Timeline returns <Code>ETag</Code> and <Code>X-Data-Version</Code>
            after current governance checks, with <Code>Cache-Control: private, no-store</Code>.
            Compact mode retains result provenance. Legacy results are unreviewed;
            <Code>reviewed_only=true</Code> is unavailable and returns 422 until
            accepted result-level review data exists. The compatibility filter
            <Code>experimental_only=true</Code> means reported Observed origin,
            not independent experimental confirmation.
          </p>
        </Endpoint>

        {/* Discovery */}
        <Endpoint method="GET" path="/discovery/candidates" badge="free">
          <p>
            Versioned, paginated candidate summaries. Fetch full evidence only
            when needed from <Code>/discovery/candidates/{`{candidate_id}`}</Code>.
          </p>
          <pre className="mt-2 overflow-x-auto rounded border border-slate-200 bg-slate-50 p-3 text-xs leading-relaxed">{`GET /v1/discovery/candidates?schema_version=1&offset=0&limit=24`}</pre>
        </Endpoint>

        {/* Stats */}
        <Endpoint method="GET" path="/stats" badge="free">
          <p>
            Site-wide statistics with separate aggregate-refresh, data-snapshot,
            and ingestion-pipeline timestamps/status.
          </p>
        </Endpoint>

        {/* Health */}
        <Endpoint method="GET" path="/health/dependencies" badge="free">
          <p>
            Bounded PostgreSQL and Redis dependency probes. Returns{" "}
            <Code>503</Code> when a required dependency is unavailable. Process
            liveness and orchestrator readiness are also exposed upstream at{" "}
            <Code>/livez</Code> and <Code>/readyz</Code>.
          </p>
        </Endpoint>

        <Endpoint method="GET" path="/health/data" badge="free">
          <p>
            Non-gating data-health metadata for the stats cache, dataset
            snapshot, ingestion stages, timeline projection, and Discovery feed.
            Data age is reported without being treated as a readiness failure.
          </p>
        </Endpoint>
      </section>

      {/* ── Error codes ── */}
      <section className="space-y-4">
        <h2 className="text-xl font-semibold text-sage-ink">Error codes</h2>
        <div className="overflow-x-auto rounded-lg border border-sage-border bg-white">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-sage-tertiary">
              <tr>
                <th className="px-4 py-2 text-left font-medium">Code</th>
                <th className="px-4 py-2 text-left font-medium">Meaning</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-sage-muted">
              <tr>
                <td className="px-4 py-2 font-mono text-sage-ink">401</td>
                <td className="px-4 py-2">Invalid or revoked API key</td>
              </tr>
              <tr>
                <td className="px-4 py-2 font-mono text-sage-ink">403</td>
                <td className="px-4 py-2">
                  Account inactive or insufficient permissions
                </td>
              </tr>
              <tr>
                <td className="px-4 py-2 font-mono text-sage-ink">404</td>
                <td className="px-4 py-2">
                  Resource not found (material / paper ID)
                </td>
              </tr>
              <tr>
                <td className="px-4 py-2 font-mono text-sage-ink">422</td>
                <td className="px-4 py-2">
                  Validation error — check request body / query params
                </td>
              </tr>
              <tr>
                <td className="px-4 py-2 font-mono text-sage-ink">429</td>
                <td className="px-4 py-2">
                  Daily quota exceeded — resets at 00:00 UTC
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="text-sm text-sage-muted">
          Every response includes <Code>X-Request-ID</Code> and{" "}
          <Code>X-API-Version</Code>. Error JSON preserves <Code>detail</Code>
          and adds <Code>error_code</Code> plus <Code>request_id</Code>; include
          the request ID when reporting an API problem.
        </p>
      </section>

      {/* ── Full example ── */}
      <section className="space-y-4">
        <h2 className="text-xl font-semibold text-sage-ink">
          Full example: Python
        </h2>
        <pre className="overflow-x-auto rounded-lg border border-sage-border bg-slate-50 p-5 text-xs leading-relaxed">
{`import requests

API  = "${API_BASE}"
KEY  = "scl_YOUR_KEY"
HEAD = {"X-API-Key": KEY}

# 1. List cuprate materials with Tc > 100 K  (free, no quota)
mats = requests.get(
    f"{API}/materials",
    params={"family": "cuprate", "tc_min": 100, "limit": 50},
    headers=HEAD,
).json()

for m in mats["results"]:
    print(f"{m['formula']}  Tc={m['tc_max']} K  papers={m['total_papers']}")

# 2. Semantic search  (consumes 1 quota)
hits = requests.post(
    f"{API}/search",
    headers={**HEAD, "Content-Type": "application/json"},
    json={"query": "pressure-induced superconductivity in hydrides", "top_k": 10},
).json()

for h in hits["results"]:
    print(f"[{h['relevance_score']:.2f}] {h['title']}")

# 3. Ask a question  (consumes 1 quota)
ans = requests.post(
    f"{API}/ask",
    headers={**HEAD, "Content-Type": "application/json"},
    json={"question": "What is the mechanism of high-Tc in cuprates?", "max_sources": 5},
).json()

print(ans["answer"])
for s in ans["sources"]:
    print(f"  [{s['index']}] {s['title']} ({s['year']})")`}
        </pre>
      </section>

      {/* Footer */}
      <div className="border-t border-sage-border pt-6 text-center text-sm text-sage-muted">
        <Link
          href="/dashboard/keys"
          className="text-accent-deep hover:underline"
        >
          &larr; Back to API Keys
        </Link>
        {" · "}
        <Link href="/" className="text-accent-deep hover:underline">
          SCLib Home
        </Link>
      </div>
    </main>
  );
}
