/**
 * /docs/api — public API reference page.
 *
 * Static server component — no auth needed. Linked from the dashboard
 * API Keys tab so users know how to wire up their key.
 */
import Link from "next/link";

const API_BASE = "https://api.jzis.org/sclib/v1";

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
          Programmatic access to the JZIS Superconductivity Library — semantic
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
                  <Code>Authorization: Bearer &lt;JWT&gt;</Code>
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
            Semantic search across the arXiv cond-mat.supr-con corpus.
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
            <Code>tokens_used</Code>, <Code>query_time_ms</Code>.
          </p>
          <p className="mt-1">
            <Code>language</Code> accepts <Code>&quot;auto&quot;</Code>,{" "}
            <Code>&quot;en&quot;</Code>, or <Code>&quot;zh&quot;</Code>. Auto
            detects the question language and replies in kind.
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
            <Code>is_unconventional</Code>, <Code>is_topological</Code>,{" "}
            <Code>pairing_symmetry</Code>, <Code>structure_phase</Code>.
          </p>
          <p className="mt-1">
            <strong>Sort:</strong> <Code>tc_max</Code> |{" "}
            <Code>tc_ambient</Code> | <Code>discovery_year</Code> |{" "}
            <Code>total_papers</Code>. Pagination via <Code>limit</Code> &amp;{" "}
            <Code>offset</Code>.
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
            Tc discovery timeline data — every material plotted by discovery year
            and maximum Tc, grouped by family. Powers the Timeline chart.
          </p>
        </Endpoint>

        {/* Stats */}
        <Endpoint method="GET" path="/stats" badge="free">
          <p>
            Site-wide statistics: total papers, materials, families, chunks, and
            last-updated timestamp.
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
