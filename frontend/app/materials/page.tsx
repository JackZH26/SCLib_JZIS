/**
 * /materials — browse the materials DB. Server component; the
 * search params drive the API call so refresh / share preserves
 * the exact filter state.
 *
 * v2 adds filter controls for the boolean flags (ambient_sc,
 * is_unconventional, has_competing_order) plus pairing_symmetry / structure_phase
 * dropdowns. Everything round-trips via URL query params so the
 * page stays SSR-friendly and shareable.
 */
import type { Metadata } from "next";
import { listMaterials, type MaterialListParams } from "@/lib/api";
import { MaterialTable } from "@/components/MaterialTable";
import { Pagination } from "@/components/Pagination";
import { FamilyFilterField } from "@/components/FamilyFilterField";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Superconducting materials database",
  description:
    "Browse superconducting materials, critical temperatures, structures, pressure conditions, and supporting literature.",
  alternates: { canonical: absoluteUrl("/materials") },
  openGraph: { url: absoluteUrl("/materials") },
};

type Sp = {
  family?: string;
  tc_min?: string;
  pressure_max?: string;
  experimental_only?: string;
  sort?: string;
  page?: string;
  per_page?: string;
  ambient_sc?: string;
  is_unconventional?: string;
  has_competing_order?: string;
  pairing_symmetry?: string;
  structure_phase?: string;
  min_tier?: string;
  min_papers?: string;
  include_skeletons?: string;
  only_aps?: string;
};

const DEFAULT_PAGE_SIZE = 50;
const ALLOWED_PAGE_SIZES = new Set([25, 50, 100, 200]);

/** Clamp an arbitrary `per_page` URL value to a safe, allowed size. */
function resolvePageSize(raw: string | undefined): number {
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) return DEFAULT_PAGE_SIZE;
  return ALLOWED_PAGE_SIZES.has(n) ? n : DEFAULT_PAGE_SIZE;
}

/** URL "true"/"false"/"" → boolean | undefined. */
function parseTri(v: string | undefined): boolean | undefined {
  if (v === "true") return true;
  if (v === "false") return false;
  return undefined;
}

export default async function MaterialsPage({
  searchParams,
}: {
  searchParams: Promise<Sp>;
}) {
  const query = await searchParams;
  const page = Math.max(0, Number(query.page ?? "0"));
  const perPage = resolvePageSize(query.per_page);
  const sort =
    (query.sort as MaterialListParams["sort"]) ?? "tc_max";

  const includeSkeletons = query.include_skeletons === "true";
  const onlyAps = query.only_aps === "true";

  const minTier = (query.min_tier as MaterialListParams["min_tier"]) || undefined;
  const minPapers = query.min_papers ? Number(query.min_papers) : undefined;

  const params: MaterialListParams = {
    family: query.family || undefined,
    tc_min: query.tc_min ? Number(query.tc_min) : undefined,
    pressure_max: query.pressure_max ? Number(query.pressure_max) : undefined,
    experimental_only: query.experimental_only === "true",
    ambient_sc: parseTri(query.ambient_sc),
    is_unconventional: parseTri(query.is_unconventional),
    has_competing_order: parseTri(query.has_competing_order),
    pairing_symmetry: query.pairing_symmetry || undefined,
    structure_phase: query.structure_phase || undefined,
    min_tier: minTier,
    min_papers: minPapers,
    sort,
    limit: perPage,
    offset: page * perPage,
    include_skeletons: includeSkeletons,
    only_aps: onlyAps,
  };

  const data = query.structure_phase ? null : await listMaterials(params).catch(() => null);
  const withoutPhase = new URLSearchParams(Object.entries(query).filter(([key, value]) => key !== "structure_phase" && key !== "page" && typeof value === "string") as [string, string][]);
  // Recovery deliberately requests a fresh document, discarding stale client
  // route state. Plain anchors must include the deployment base path themselves.
  const phaseRecoveryHref = `${process.env.NEXT_PUBLIC_BASE_PATH || ""}/materials?${withoutPhase.toString()}`;

  // Small helper: render a tri-state select for boolean filters.
  const triOptions = (
    name: keyof Sp,
    label: string,
    current: string | undefined,
  ) => (
    <label key={name} className="flex flex-col gap-1">
      <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </span>
      <select
        name={name}
        defaultValue={current ?? ""}
        className="rounded border border-sage-border bg-white px-2 py-1"
      >
        <option value="">Any status</option>
        <option value="true">Reported true</option>
        <option value="false">Qualified reported false</option>
      </select>
    </label>
  );

  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Materials</h1>
        <p className="mt-1 text-sm text-slate-600">
          Catalogue selections for Tc, pairing, structure and competing orders,
          with per-property source records. A material row is not a joint
          observation. Tc, pressure and origin filters match one result.
          Pairing and classification filters use current declared reports, not
          family priors or legacy aggregate flags. A reported classification
          is not verified science or necessarily the same state as a selected Tc.
          Phase and structure labels remain pending proposals; reviewed phase
          filtering is unavailable until material/state associations are reviewed.
        </p>
      </div>

      <form className="flex flex-wrap items-end gap-3 rounded-lg border border-sage-border bg-white p-4 text-sm shadow-sage">
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Family
          </span>
          <FamilyFilterField initial={query.family ?? ""} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Tc ≥ (K)
          </span>
          <input
            type="number"
            name="tc_min"
            defaultValue={query.tc_min ?? ""}
            className="w-24 rounded border border-sage-border px-2 py-1"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Reported pairing
          </span>
          <select
            name="pairing_symmetry"
            defaultValue={query.pairing_symmetry ?? ""}
            className="rounded border border-sage-border bg-white px-2 py-1"
          >
            <option value="">any</option>
            <option value="s-wave">s-wave</option>
            <option value="s±">s±</option>
            <option value="d-wave">d-wave</option>
            <option value="p-wave">p-wave</option>
            <option value="chiral">chiral</option>
            <option value="nodal">nodal</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Reviewed phase · unavailable
          </span>
          <input
            name="structure_phase"
            disabled
            defaultValue={query.structure_phase ?? ""}
            className="rounded border border-sage-border px-2 py-1 w-32"
            placeholder="Pending source review"
          />
          <span className="max-w-48 text-[10px] text-slate-500">Text proposals are not reviewed material/state associations.</span>
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Result source tier
          </span>
          <select
            name="min_tier"
            defaultValue={query.min_tier ?? ""}
            className="rounded border border-sage-border bg-white px-2 py-1"
          >
            <option value="">any tier</option>
            <option value="T1">T1 only</option>
            <option value="T2">T1–T2</option>
            <option value="T3">T1–T3</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Legacy paper links ≥
          </span>
          <input
            type="number"
            name="min_papers"
            min="1"
            defaultValue={query.min_papers ?? ""}
            className="w-20 rounded border border-sage-border px-2 py-1"
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">Ambient result</span>
          <select name="ambient_sc" defaultValue={query.ambient_sc ?? ""}
            className="rounded border border-sage-border bg-white px-2 py-1">
            <option value="">Any</option>
            <option value="true">Explicit ambient + observed Tc</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">P ≤ (GPa)</span>
          <input type="number" name="pressure_max" min="0" step="any" defaultValue={query.pressure_max ?? ""}
            className="w-24 rounded border border-sage-border px-2 py-1" />
        </label>
        <label className="flex items-center gap-2 text-xs text-slate-600">
          <input type="checkbox" name="experimental_only" value="true" defaultChecked={query.experimental_only === "true"} />
          Observed results only
        </label>
        {triOptions(
          "is_unconventional",
          "Reported unconventional",
          query.is_unconventional,
        )}
        {triOptions(
          "has_competing_order",
          "Reported competing order",
          query.has_competing_order,
        )}

        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Sort
          </span>
          <select
            name="sort"
            defaultValue={sort}
            className="rounded border border-sage-border bg-white px-2 py-1"
          >
            <option value="tc_max">Catalogue Tc max</option>
            <option value="tc_ambient">Catalogue Tc ambient</option>
            <option value="arxiv_year">arXiv year</option>
            <option value="total_papers">Paper count</option>
          </select>
        </label>
        <label className="flex items-center gap-2 self-end pb-1">
          <input
            type="checkbox"
            name="only_aps"
            value="true"
            defaultChecked={onlyAps}
            className="h-4 w-4 rounded border-slate-300 accent-[color:var(--accent,#3A7D5C)]"
          />
          <span className="text-xs font-medium text-slate-600">
            Only APS Data
          </span>
        </label>
        {/*
          Library-only entries are NIMS SuperCon catalog rows that
          arrived with a reference DOI but no measured Tc / pressure /
          structure. Hiding them by default keeps the list feeling
          populated; toggling shows the full index for power users.
        */}
        <label className="flex items-center gap-2 self-end pb-1">
          <input
            type="checkbox"
            name="include_skeletons"
            value="true"
            defaultChecked={includeSkeletons}
            className="h-4 w-4 rounded border-slate-300 accent-[color:var(--accent,#3A7D5C)]"
          />
          <span className="text-xs font-medium text-slate-600">
            Include library-only entries
          </span>
        </label>
        <button type="submit" className="btn-primary">
          Apply
        </button>
      </form>

      {query.structure_phase && <p className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">Reviewed phase filtering is unavailable. Your saved phase filter was not silently ignored. <a className="underline" href={phaseRecoveryHref}>Remove the phase filter and reload</a>.</p>}

      <p className="text-xs text-slate-500">
        Family, Tc, pressure and result-evidence filters must match the same extracted result.
        Unknown pressure does not satisfy a pressure limit. Catalogue summary values may describe other results.
        Pairing and classification filters apply to the material reported-summary scope, not a joint Tc/state result.
        A false classification filter requires an explicit negative report with method and detection conditions; missing data does not match false.
      </p>

      {data == null ? (
        <p className="text-sm text-red-600">
          {query.structure_phase ? "Pending structure proposals cannot be used as reviewed material/state filters." : query.ambient_sc === "false"
            ? "The negative ambient filter is unsupported: missing ambient evidence is not a negative experiment. Choose Any or Explicit ambient + observed Tc."
            : "Failed to load materials."}
        </p>
      ) : (
        <>
          <div className="text-xs text-slate-500">
            {data.total.toLocaleString("en-US")} materials
          </div>
          <MaterialTable rows={data.results} />
          <Pagination
            total={data.total}
            limit={perPage}
            offset={page * perPage}
            basePath="/materials"
            searchParams={query}
          />
        </>
      )}
    </main>
  );
}
