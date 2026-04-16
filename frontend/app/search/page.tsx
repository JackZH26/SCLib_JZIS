"use client";

/**
 * /search — main semantic-search UI.
 *
 * Client component so we can bind the filters live without reloading.
 * The URL mirrors the query (`?q=...`) so users can share and bookmark
 * results; filters are kept in local state since they mutate often.
 *
 * useSearchParams() forces Next to bail out of static prerendering,
 * so the inner component is wrapped in <Suspense> to satisfy Next 14's
 * CSR-bailout rule during `next build`.
 */
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { search, type SearchResponse, friendlyErrorMessage } from "@/lib/api";
import { SearchBar } from "@/components/SearchBar";
import { PaperCard } from "@/components/PaperCard";
import { GuestBanner } from "@/components/GuestBanner";

export default function SearchPage() {
  return (
    <Suspense fallback={<p className="text-sm text-slate-500">Loading…</p>}>
      <SearchInner />
    </Suspense>
  );
}

function SearchInner() {
  const params = useSearchParams();
  const router = useRouter();
  const q = params.get("q") ?? "";

  const [data, setData] = useState<SearchResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [sort, setSort] = useState<"relevance" | "date" | "tc">("relevance");
  const [yearMin, setYearMin] = useState<string>("");
  const [yearMax, setYearMax] = useState<string>("");
  const [tcMin, setTcMin] = useState<string>("");

  useEffect(() => {
    if (q.length < 2) {
      setData(null);
      return;
    }
    setLoading(true);
    setErr(null);
    const apiKey =
      typeof window !== "undefined"
        ? localStorage.getItem("sclib_api_key") ?? undefined
        : undefined;
    search(
      {
        query: q,
        top_k: 20,
        sort,
        filters: {
          year_min: yearMin ? Number(yearMin) : undefined,
          year_max: yearMax ? Number(yearMax) : undefined,
          tc_min: tcMin ? Number(tcMin) : undefined,
          exclude_retracted: true,
        },
      },
      { apiKey },
    )
      .then(setData)
      .catch((e: unknown) => {
        setErr(friendlyErrorMessage(e));
      })
      .finally(() => setLoading(false));
  }, [q, sort, yearMin, yearMax, tcMin]);

  return (
    <main className="space-y-6">
      <SearchBar
        initial={q}
        placeholder="Search papers..."
      />

      <div className="flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-white p-4 text-sm">
        <Field label="Sort">
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as typeof sort)}
            className="rounded border border-slate-300 px-2 py-1"
          >
            <option value="relevance">Relevance</option>
            <option value="date">Date (newest)</option>
            <option value="tc">Highest Tc</option>
          </select>
        </Field>
        <Field label="Year ≥">
          <NumInput value={yearMin} set={setYearMin} />
        </Field>
        <Field label="Year ≤">
          <NumInput value={yearMax} set={setYearMax} />
        </Field>
        <Field label="Tc ≥ (K)">
          <NumInput value={tcMin} set={setTcMin} />
        </Field>
      </div>

      {data?.guest_remaining != null && (
        <GuestBanner remaining={data.guest_remaining} />
      )}

      {loading && <p className="text-sm text-slate-500">Searching…</p>}
      {err && (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {err}
        </div>
      )}

      {data && data.results.length > 0 && (
        <>
          <div className="text-xs text-slate-500">
            {data.results.length} result{data.results.length === 1 ? "" : "s"}{" "}
            · {data.query_time_ms} ms
          </div>
          <div className="space-y-3">
            {data.results.map((r, i) => (
              <PaperCard
                key={`${r.paper_id}-${i}`}
                paper_id={r.paper_id}
                arxiv_id={r.arxiv_id}
                title={r.title}
                authors={r.authors}
                year={r.year}
                snippet={r.matched_chunk.slice(0, 400)}
                section={r.matched_section}
                score={r.relevance_score}
                scoreLabel="relevance"
                badges={[
                  ...(r.material_family ? [r.material_family] : []),
                  ...(r.has_equation ? ["equations"] : []),
                  ...(r.has_table ? ["tables"] : []),
                ]}
              />
            ))}
          </div>
        </>
      )}
      {data && data.results.length === 0 && (
        <p className="text-sm text-slate-500">No results.</p>
      )}

      {!q && (
        <p className="text-sm text-slate-500">
          Enter a query above to start searching.
        </p>
      )}
    </main>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </span>
      {children}
    </label>
  );
}

function NumInput({ value, set }: { value: string; set: (s: string) => void }) {
  return (
    <input
      type="number"
      value={value}
      onChange={(e) => set(e.target.value)}
      className="w-24 rounded border border-slate-300 px-2 py-1"
    />
  );
}
